import json
import os
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_key_value_file(path):
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_runtime_with_node(env_overrides=None):
    env = dict(os.environ)
    for key in ["AI_MODEL_HUB_KEYCLOAK_URL", "UI_DS_DOMAIN"]:
        env.pop(key, None)
    env.update(env_overrides or {})
    script = """
const { resolveAIModelHubRuntime } = require('./validation/components/ai_model_hub/ui/runtime');
console.log(JSON.stringify(resolveAIModelHubRuntime()));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def resolve_ui_trace_mode_with_node(env_overrides=None):
    env = dict(os.environ)
    env.pop("PLAYWRIGHT_TRACE", None)
    env.update(env_overrides or {})
    script = """
const config = require('./validation/components/ai_model_hub/ui/playwright.config');
console.log(JSON.stringify({ trace: config.use.trace }));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)["trace"]


class AIModelHubUiRuntimeTests(unittest.TestCase):
    def test_runtime_uses_shared_infrastructure_keycloak_and_domain_defaults(self):
        inesdata_config = {
            **parse_key_value_file(PROJECT_ROOT / "deployers" / "inesdata" / "deployer.config.example"),
            **parse_key_value_file(PROJECT_ROOT / "deployers" / "inesdata" / "deployer.config"),
        }
        infrastructure_config = parse_key_value_file(
            PROJECT_ROOT / "deployers" / "infrastructure" / "deployer.config"
        )

        runtime = resolve_runtime_with_node()

        expected_keycloak = (
            inesdata_config.get("KC_INTERNAL_URL")
            or infrastructure_config.get("KC_INTERNAL_URL")
            or inesdata_config.get("KC_URL")
            or infrastructure_config.get("KC_URL")
            or "http://keycloak.dev.ed.dataspaceunit.upm"
        )
        expected_domain = (
            inesdata_config.get("DS_DOMAIN_BASE")
            or infrastructure_config.get("DS_DOMAIN_BASE")
            or "dev.ds.dataspaceunit.upm"
        )
        self.assertEqual(runtime["keycloakBaseUrl"], expected_keycloak.rstrip("/"))
        self.assertEqual(runtime["dsDomain"], expected_domain)

    def test_runtime_allows_keycloak_env_override(self):
        runtime = resolve_runtime_with_node(
            {"AI_MODEL_HUB_KEYCLOAK_URL": "http://override.example.local/"}
        )

        self.assertEqual(runtime["keycloakBaseUrl"], "http://override.example.local")

    def test_runtime_exposes_model_server_base_url_from_components_namespace(self):
        runtime = resolve_runtime_with_node({"UI_COMPONENTS_NAMESPACE": "components-a52"})

        self.assertEqual(runtime["componentsNamespace"], "components-a52")
        self.assertEqual(
            runtime["modelServerBaseUrl"],
            "http://model-server.components-a52.svc.cluster.local:8080",
        )

    def test_runtime_uses_edc_connector_defaults_when_adapter_is_edc(self):
        runtime = resolve_runtime_with_node({"PIONERA_ADAPTER": "edc"})

        self.assertEqual(runtime["adapterName"], "edc")
        self.assertEqual(runtime["dataspace"], "pionera-edc")
        self.assertEqual(runtime["providerConnectorId"], "conn-citycounciledc-pionera-edc")
        self.assertEqual(runtime["consumerConnectorId"], "conn-companyedc-pionera-edc")
        self.assertIn("conn-citycounciledc-pionera-edc", runtime["providerManagementUrl"])

    def test_ui_playwright_trace_is_off_by_default(self):
        self.assertEqual(resolve_ui_trace_mode_with_node(), "off")

    def test_ui_playwright_trace_can_be_enabled_explicitly(self):
        self.assertEqual(resolve_ui_trace_mode_with_node({"PLAYWRIGHT_TRACE": "on"}), "on")


if __name__ == "__main__":
    unittest.main()
