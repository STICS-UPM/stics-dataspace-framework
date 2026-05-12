import json
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from validation.components.ontology_hub.functional import runtime_preparation


class _FakeSession:
    def __init__(self, login_response, edition_response):
        self._login_response = login_response
        self._edition_response = edition_response
        self.post_calls = []
        self.closed = False

    def get(self, url, timeout=20, allow_redirects=True):
        if url.endswith("/edition/login"):
            return self._login_response
        if url.endswith("/edition"):
            return self._edition_response
        raise AssertionError(f"Unexpected GET URL: {url}")

    def post(self, url, data=None, timeout=20, allow_redirects=True):
        self.post_calls.append((url, data))
        return SimpleNamespace(status_code=200, text="", url=url)

    def close(self):
        self.closed = True


class OntologyHubCleanupGuardsTests(unittest.TestCase):
    def _run_node_json(self, script):
        validation_root = os.path.dirname(os.path.dirname(__file__))
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=validation_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_response_looks_broken_when_hidden_500_is_rendered_with_status_200(self):
        response = SimpleNamespace(
            status_code=200,
            text="<html><h1>500 - Oops! something went wrong - 500</h1></html>",
        )

        self.assertTrue(runtime_preparation.ontology_hub_response_looks_broken(response))

    def test_response_looks_broken_when_stacktrace_mentions_null_agent_name(self):
        response = SimpleNamespace(
            status_code=200,
            text="TypeError: /app/app/views/edition.jade:153 Cannot read properties of null (reading 'name')",
        )

        self.assertTrue(runtime_preparation.ontology_hub_response_looks_broken(response))

    def test_session_login_rejects_authenticated_broken_edition_page(self):
        runtime = {
            "baseUrl": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
            "adminEmail": "admin@gmail.com",
            "adminPassword": "admin1234",
        }
        login_response = SimpleNamespace(
            status_code=200,
            text="<input type='hidden' name='_csrf' value='token'>",
            url=f"{runtime['baseUrl']}/edition/login",
        )
        edition_response = SimpleNamespace(
            status_code=200,
            text="<h1>500 - Oops! something went wrong - 500</h1>",
            url=f"{runtime['baseUrl']}/edition",
        )
        session = _FakeSession(login_response, edition_response)

        with mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.requests.Session",
            return_value=session,
        ):
            authenticated = runtime_preparation._ontology_hub_session_login(runtime)

        self.assertIsNone(authenticated)

    def test_wait_for_preflight_requires_public_routes_and_authenticated_edition(self):
        runtime = {
            "baseUrl": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
            "adminEmail": "admin@gmail.com",
            "adminPassword": "admin1234",
        }
        http_calls = []
        fake_session = mock.Mock()

        def fake_get(url, timeout=10, allow_redirects=True):
            http_calls.append(url)
            return SimpleNamespace(status_code=200, text="<html>ok</html>", url=url)

        with mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.requests.get",
            side_effect=fake_get,
        ), mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation._ontology_hub_session_login",
            return_value=fake_session,
        ) as login_mock, mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.time.sleep",
        ):
            ready = runtime_preparation.wait_for_ontology_hub_preflight(
                runtime,
                timeout_seconds=5,
                stable_successes_required=2,
            )

        self.assertTrue(ready)
        self.assertEqual(login_mock.call_count, 2)
        self.assertEqual(fake_session.close.call_count, 2)
        self.assertIn("http://ontology-hub-demo.dev.ds.dataspaceunit.upm", http_calls)
        self.assertIn("http://ontology-hub-demo.dev.ds.dataspaceunit.upm/dataset", http_calls)
        self.assertIn("http://ontology-hub-demo.dev.ds.dataspaceunit.upm/edition", http_calls)

    def test_prepare_functional_runtime_uses_runtime_preflight_timeout(self):
        runtime = {
            "baseUrl": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
            "preflightTimeout": 240,
        }

        with mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.ontology_hub_functional_reset_mode",
            return_value="hard",
        ), mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.reset_ontology_hub_for_functional",
            return_value=True,
        ), mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.wait_for_ontology_hub_preflight",
            return_value=True,
        ) as preflight_mock:
            ready = runtime_preparation.prepare_ontology_hub_for_functional(runtime)

        self.assertTrue(ready)
        preflight_mock.assert_called_once_with(runtime, timeout_seconds=240)

    def test_reset_mode_defaults_to_soft(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime_preparation.ontology_hub_functional_reset_mode(), "soft")

    def test_prepare_functional_runtime_soft_cleanup_falls_back_to_hard_reset_when_cleanup_fails(self):
        runtime = {
            "baseUrl": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
            "preflightTimeout": 240,
        }

        with mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.ontology_hub_functional_reset_mode",
            return_value="soft",
        ), mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.soft_cleanup_ontology_hub_for_functional",
            return_value=False,
        ) as soft_cleanup_mock, mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.reset_ontology_hub_for_functional",
            return_value=True,
        ) as reset_mock, mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation.wait_for_ontology_hub_preflight",
            return_value=True,
        ) as preflight_mock:
            ready = runtime_preparation.prepare_ontology_hub_for_functional(runtime)

        self.assertTrue(ready)
        soft_cleanup_mock.assert_called_once_with(runtime)
        reset_mock.assert_called_once_with(runtime)
        preflight_mock.assert_called_once_with(runtime, timeout_seconds=240)

    def test_transient_availability_detection_matches_502_503_but_not_application_500(self):
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "validation",
            "components",
            "ontology_hub",
            "ui",
            "support",
            "bootstrap.js",
        )
        script = f"""
const {{ textShowsTransientAvailabilityFailure }} = require({json.dumps(module_path)});
console.log(JSON.stringify({{
  transient503: textShowsTransientAvailabilityFailure("503 Service Temporarily Unavailable\\nnginx"),
  transient502: textShowsTransientAvailabilityFailure("502 Bad Gateway"),
  application500: textShowsTransientAvailabilityFailure("500 - Oops! something went wrong - 500"),
  invalidCredentials: textShowsTransientAvailabilityFailure("Invalid email or password.")
}}));
"""

        result = self._run_node_json(script)

        self.assertTrue(result["transient503"])
        self.assertTrue(result["transient502"])
        self.assertFalse(result["application500"])
        self.assertFalse(result["invalidCredentials"])

    def test_home_page_bubble_click_prefers_circle_click_and_falls_back_to_forced_circle_click(self):
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "validation",
            "components",
            "ontology_hub",
            "ui",
            "pages",
            "home.page.js",
        )
        script = f"""
const {{ OntologyHubHomePage }} = require({json.dumps(module_path)});

const circleClicks = [];
const bubbleClicks = [];

const circle = {{
  first() {{
    return this;
  }},
  async count() {{
    return 1;
  }},
  async click(options) {{
    circleClicks.push(options || null);
    if (!options || options.force !== true) {{
      throw new Error("locator.click: <text> intercepts pointer events");
    }}
  }},
}};

const bubble = {{
  async waitFor() {{}},
  locator(selector) {{
    if (selector !== "circle") {{
      throw new Error(`Unexpected selector: ${{selector}}`);
    }}
    return circle;
  }},
  async click(options) {{
    bubbleClicks.push(options || null);
  }},
}};

const homePage = new OntologyHubHomePage({{}});
homePage.vocabularyBubble = () => bubble;

(async () => {{
  await homePage.openVocabularyBubble("demo");
  console.log(JSON.stringify({{
    circleClicks,
    bubbleClicks,
  }}));
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}});
"""

        result = self._run_node_json(script)

        self.assertEqual(len(result["circleClicks"]), 2)
        self.assertEqual(result["circleClicks"][1], {"force": True})
        self.assertEqual(result["bubbleClicks"], [])

    def test_themis_panel_uses_visible_entrypoints_when_legacy_user_options_is_hidden(self):
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "validation",
            "components",
            "ontology_hub",
            "functional",
            "support",
            "excel-flows.js",
        )
        script = f"""
const {{ openThemisPanel }} = require({json.dumps(module_path)});

const actions = [];

function makeLocator(name, options = {{}}) {{
  const present = options.present !== false;
  return {{
    first() {{
      return this;
    }},
    async count() {{
      return present ? 1 : 0;
    }},
    async isVisible() {{
      if (typeof options.visible === "function") {{
        return present && options.visible();
      }}
      return present && Boolean(options.visible);
    }},
    async scrollIntoViewIfNeeded() {{}},
    async click(clickOptions) {{
      actions.push({{
        name,
        options: clickOptions || null,
      }});
      if (options.onClick) {{
        options.onClick();
      }}
    }},
    async waitFor() {{
      const visible = typeof options.visible === "function" ? options.visible() : Boolean(options.visible);
      if (!present || !visible) {{
        throw new Error(`${{name}} is not visible`);
      }}
    }},
  }};
}}

const page = {{
  _themisVisible: false,
  locator(selector) {{
    if (selector === "#normal-button") {{
      return makeLocator("normal-button", {{ visible: true }});
    }}
    if (selector === "#user-options img[src='/img/themis.png']") {{
      return makeLocator("legacy-user-options", {{ visible: false }});
    }}
    if (selector === ".tool-item.gradient img[src='/img/themis.png']") {{
      return makeLocator("visible-tool-item", {{
        visible: true,
        onClick() {{
          page._themisVisible = true;
        }},
      }});
    }}
    if (selector === ".ontology-tab[data-onto-target='themis']") {{
      return makeLocator("themis-tab", {{
        visible: true,
        onClick() {{
          page._themisVisible = true;
        }},
      }});
    }}
    if (selector === "#themisVocabContainer") {{
      return makeLocator("themis-container", {{
        visible: false,
      }});
    }}
    if (selector === "#executeThemisButton") {{
      return makeLocator("execute-themis", {{
        visible: () => page._themisVisible,
      }});
    }}
    if (selector === "#themisModeManual") {{
      return makeLocator("themis-mode-manual", {{
        visible: () => page._themisVisible,
      }});
    }}
    throw new Error(`Unexpected selector: ${{selector}}`);
  }},
  async waitForFunction() {{
    if (!page._themisVisible) {{
      throw new Error("Themis panel not visible");
    }}
  }},
  async evaluate() {{
    throw new Error("Script fallback should not be needed when the visible Themis tool is present.");
  }},
}};

(async () => {{
  const activation = await openThemisPanel(page);
  console.log(JSON.stringify({{
    activation,
    actions,
  }}));
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}});
"""

        result = self._run_node_json(script)

        self.assertEqual(result["activation"]["entrypoint"], "visible-tool-item")
        self.assertFalse(result["activation"]["fallback"])
        self.assertEqual(
            [action["name"] for action in result["actions"]],
            ["normal-button", "visible-tool-item"],
        )

    def test_expect_healthy_page_rejects_embedded_500_heading(self):
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "validation",
            "components",
            "ontology_hub",
            "functional",
            "support",
            "excel-flows.js",
        )
        script = f"""
const {{ expectHealthyPage }} = require({json.dumps(module_path)});

const page = {{
  locator(selector) {{
    if (selector !== "h1") {{
      throw new Error(`Unexpected selector: ${{selector}}`);
    }}
    return {{
      first() {{
        return this;
      }},
      async count() {{
        return 1;
      }},
      async textContent() {{
        return "500 - Oops! something went wrong - 500";
      }},
    }};
  }},
}};

(async () => {{
  try {{
    await expectHealthyPage(page, "Users administration");
    console.log(JSON.stringify({{ passed: true }}));
  }} catch (error) {{
    console.log(JSON.stringify({{
      passed: false,
      message: String(error && error.message ? error.message : error),
    }}));
  }}
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}});
"""

        result = self._run_node_json(script)

        self.assertFalse(result["passed"])
        self.assertIn("Users administration page failed to load", result["message"])

    def test_version_edit_recovery_waits_for_transient_502_503_and_verifies_updated_row(self):
        module_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "validation",
            "components",
            "ontology_hub",
            "functional",
            "support",
            "excel-flows.js",
        )
        script = f"""
const {{ waitForRecoveredVersionRow }} = require({json.dumps(module_path)});

function makeWaitLocator(check) {{
  return {{
    first() {{
      return this;
    }},
    filter() {{
      return this;
    }},
    async waitFor() {{
      if (!check()) {{
        throw new Error("not ready");
      }}
    }},
    async count() {{
      return check() ? 1 : 0;
    }},
    async textContent() {{
      return check() ? "versions" : "";
    }},
  }};
}}

const page = {{
  _attempt: 0,
  _recovered: false,
  _currentUrl: "http://ontology-hub-demo.dev.ds.dataspaceunit.upm/edition/vocabs/demo/versions/edit",
  async waitForTimeout() {{}},
  async goto(url) {{
    this._attempt += 1;
    this._currentUrl = url;
    if (this._attempt >= 3) {{
      this._recovered = true;
    }}
  }},
  url() {{
    return this._currentUrl;
  }},
  async title() {{
    return this._recovered ? "Ontology Hub" : "503 Service Temporarily Unavailable";
  }},
  locator(selector) {{
    if (selector === "h1") {{
      return {{
        first: () => ({{
          async count() {{
            return 1;
          }},
          async textContent() {{
            return page._recovered
              ? "Ontology-Development-Repository-Example"
              : "503 Service Temporarily Unavailable";
          }},
        }}),
        filter() {{
          return this.first();
        }},
      }};
    }}
    if (selector === ".editionIndexBoxHeader .title") {{
      return makeWaitLocator(() => page._recovered);
    }}
    if (selector === ".editionBoxSugg") {{
      return {{
        filter() {{
          return makeWaitLocator(() => page._recovered);
        }},
      }};
    }}
    throw new Error(`Unexpected selector: ${{selector}}`);
  }},
}};

(async () => {{
  const result = await waitForRecoveredVersionRow(
    page,
    {{ baseUrl: "http://ontology-hub-demo.dev.ds.dataspaceunit.upm" }},
    "ontology-development-repository-example",
    {{ name: "v2026-01-01", issued: "2026-01-01" }},
  );
  console.log(JSON.stringify({{
    result,
    attempts: page._attempt,
    finalUrl: page.url(),
  }}));
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}});
"""

        result = self._run_node_json(script)

        self.assertTrue(result["result"]["recovered"])
        self.assertGreaterEqual(result["attempts"], 3)
        self.assertTrue(result["finalUrl"].endswith("/edition/vocabs/ontology-development-repository-example/versions"))


if __name__ == "__main__":
    unittest.main()
