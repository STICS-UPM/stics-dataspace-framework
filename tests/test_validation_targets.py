import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from validation.orchestration.targets import (
    build_validation_target_plan,
    discover_validation_targets,
    format_validation_target_plan,
    load_validation_target,
    run_validation_target_read_only,
)


TARGET_YAML = """
name: inesdata-production
project: inesdata
mode: validation-only
environment: production

safety:
  default_profile: read-only
  allow_write_tests: false

auth:
  username_env: INESDATA_PROD_VALIDATION_USER
  password_env: INESDATA_PROD_VALIDATION_PASSWORD

dataspaces:
  - name: linguistic
    public_portal_url: https://linguistic.example.org
    connectors:
      - name: provider-linguistic
        role: provider
        management_api_url: https://provider-api.example.org
        protocol_url: https://provider-protocol.example.org

suites:
  newman_core:
    enabled: true
    profile: read-only
  kafka_edc:
    enabled: false

components: {}

project_suites:
  inesdata:
    linguistic:
      enabled: true
      profile: read-only
"""


class ValidationTargetTests(unittest.TestCase):
    def _write_target(self, root, filename="inesdata-production.example.yaml", content=TARGET_YAML):
        target_dir = Path(root) / "validation" / "targets"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        target_path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
        return target_path

    def _write_target_playwright_config(self, root):
        config_path = Path(root) / "validation" / "projects" / "inesdata" / "playwright.target.config.js"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("module.exports = {};\n", encoding="utf-8")
        return config_path

    def _write_project_spec(self, root, suite="linguistic", filename="catalog.spec.ts"):
        spec_path = Path(root) / "validation" / "projects" / "inesdata" / suite / "specs" / filename
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(
            "import { test } from '@playwright/test';\n"
            "test('read-only smoke', async () => {});\n",
            encoding="utf-8",
        )
        return spec_path

    def test_discover_validation_targets_lists_examples_without_requiring_real_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_target(tmpdir)

            targets = discover_validation_targets(root=tmpdir)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["name"], "inesdata-production")
        self.assertEqual(targets[0]["path"], str(path))
        self.assertTrue(targets[0]["example"])
        self.assertEqual(targets[0]["status"], "available")
        self.assertEqual(targets[0]["mode"], "validation-only")

    def test_load_validation_target_accepts_configured_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_target(tmpdir)

            payload, path = load_validation_target("inesdata-production", root=tmpdir)

        self.assertEqual(payload["name"], "inesdata-production")
        self.assertEqual(path.name, "inesdata-production.example.yaml")

    def test_build_validation_target_plan_is_safe_and_does_not_expose_secret_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_target(tmpdir)
            payload, target_path = load_validation_target(path, root=tmpdir)

            plan = build_validation_target_plan(
                payload,
                target_path=target_path,
                environ={
                    "INESDATA_PROD_VALIDATION_USER": "validation-user",
                    "INESDATA_PROD_VALIDATION_PASSWORD": "credential-value-not-printed",
                },
            )
            output = "\n".join(format_validation_target_plan(plan))

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["execution"], "read-only-runner")
        self.assertEqual(plan["levels_1_5"], "disabled")
        self.assertEqual(plan["level_6"], "read-only-playwright")
        self.assertEqual(plan["cleanup"], "disabled")
        self.assertEqual(plan["writes"], "disabled")
        self.assertEqual(plan["destructive_actions"], "disabled")
        self.assertIn("Levels 1-5: disabled", output)
        self.assertIn("Level 6: read-only-playwright", output)
        self.assertIn("Cleanup: disabled", output)
        self.assertIn("Writes: disabled", output)
        self.assertIn("Destructive actions: disabled", output)
        self.assertIn("INESDATA_PROD_VALIDATION_PASSWORD: available", output)
        self.assertNotIn("credential-value-not-printed", output)

    def test_non_validation_only_target_fails_before_execution(self):
        unsafe_yaml = TARGET_YAML.replace("mode: validation-only", "mode: deploy")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_target(tmpdir, content=unsafe_yaml)
            payload, target_path = load_validation_target(path, root=tmpdir)

            plan = build_validation_target_plan(payload, target_path=target_path)

        self.assertEqual(plan["status"], "failed")
        self.assertIn("Target mode must be validation-only.", plan["errors"])

    def test_read_only_runner_skips_when_only_example_specs_exist(self):
        subprocess_module = mock.Mock()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_target(tmpdir)
            self._write_project_spec(tmpdir, filename="catalog.example.ts")
            payload, target_path = load_validation_target(path, root=tmpdir)

            result = run_validation_target_read_only(
                payload,
                target_path=target_path,
                root=tmpdir,
                subprocess_module=subprocess_module,
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no-read-only-specs")
        subprocess_module.run.assert_not_called()

    def test_read_only_runner_executes_only_enabled_read_only_playwright_specs(self):
        subprocess_module = mock.Mock()
        subprocess_module.run.return_value = mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_target(tmpdir)
            self._write_target_playwright_config(tmpdir)
            spec_path = self._write_project_spec(tmpdir)
            payload, target_path = load_validation_target(path, root=tmpdir)

            result = run_validation_target_read_only(
                payload,
                target_path=target_path,
                root=tmpdir,
                environ={
                    "INESDATA_PROD_VALIDATION_USER": "validation-user",
                    "INESDATA_PROD_VALIDATION_PASSWORD": "credential-value-not-printed",
                },
                subprocess_module=subprocess_module,
            )

        self.assertEqual(result["status"], "passed")
        subprocess_module.run.assert_called_once()
        command = subprocess_module.run.call_args.args[0]
        env = subprocess_module.run.call_args.kwargs["env"]
        self.assertEqual(command[:3], ["npx", "playwright", "test"])
        self.assertIn("--workers=1", command)
        self.assertIn(str(spec_path.resolve()), command)
        self.assertEqual(env["INESDATA_LINGUISTIC_PORTAL_URL"], "https://linguistic.example.org")
        self.assertEqual(env["INESDATA_VALIDATION_MODE"], "validation-only")
        self.assertEqual(env["INESDATA_VALIDATION_PROFILE"], "read-only")
        self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
        self.assertNotIn("credential-value-not-printed", str(result))

    def test_read_only_runner_fails_before_execution_when_secrets_are_missing(self):
        subprocess_module = mock.Mock()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_target(tmpdir)
            self._write_target_playwright_config(tmpdir)
            self._write_project_spec(tmpdir)
            payload, target_path = load_validation_target(path, root=tmpdir)

            result = run_validation_target_read_only(
                payload,
                target_path=target_path,
                root=tmpdir,
                environ={},
                subprocess_module=subprocess_module,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "missing-secrets")
        self.assertEqual(
            [item["env"] for item in result["missing_secrets"]],
            ["INESDATA_PROD_VALIDATION_USER", "INESDATA_PROD_VALIDATION_PASSWORD"],
        )
        subprocess_module.run.assert_not_called()

    def test_read_only_runner_fails_before_execution_when_enabled_suite_is_not_read_only(self):
        unsafe_yaml = TARGET_YAML.replace("profile: read-only", "profile: write-safe")
        subprocess_module = mock.Mock()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_target(tmpdir, content=unsafe_yaml)
            self._write_project_spec(tmpdir)
            payload, target_path = load_validation_target(path, root=tmpdir)

            result = run_validation_target_read_only(
                payload,
                target_path=target_path,
                root=tmpdir,
                subprocess_module=subprocess_module,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "non-read-only-suite")
        subprocess_module.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
