import os
import tempfile
import unittest
from unittest import mock

from validation.components.ontology_hub.integration.component_runner import run_ontology_hub_component_validation
from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime


class OntologyHubComponentIntegrationValidationTests(unittest.TestCase):
    def test_resolve_ontology_hub_runtime_reads_admin_credentials_from_chart_values(self):
        with mock.patch(
            "validation.components.ontology_hub.runtime_config._parse_key_value_file",
            return_value={
                "DS_1_NAME": "demo",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            },
        ), mock.patch(
            "validation.components.ontology_hub.runtime_config._load_chart_values",
            return_value={
                "validation": {
                    "ui": {
                        "adminEmail": "qa-admin@example.org",
                        "adminPassword": "super-secret-password",
                        "creationRepositoryUri": "https://github.com/example/repo.git",
                        "creationPrimaryLanguage": "en",
                        "creationSecondaryLanguage": "es",
                    }
                }
            },
        ):
            runtime = resolve_ontology_hub_runtime(environ={})

        self.assertEqual(runtime["adminEmail"], "qa-admin@example.org")
        self.assertEqual(runtime["adminPassword"], "super-secret-password")
        self.assertEqual(runtime["componentsNamespace"], "components")
        self.assertEqual(runtime["creationRepositoryUri"], "https://github.com/example/repo")
        self.assertEqual(runtime["creationPrimaryLanguage"], "en")
        self.assertEqual(runtime["creationSecondaryLanguage"], "es")
        self.assertEqual(runtime["uiExpectTimeoutMs"], 15000)
        self.assertEqual(runtime["uiActionTimeoutMs"], 15000)
        self.assertEqual(runtime["uiNavigationTimeoutMs"], 30000)
        self.assertEqual(runtime["uiReadyTimeoutMs"], 30000)
        self.assertEqual(runtime["preflightTimeout"], 180)

    def test_resolve_ontology_hub_runtime_reads_admin_credentials_from_secret_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            email_path = os.path.join(tmpdir, "ontology-hub-admin-email.txt")
            password_path = os.path.join(tmpdir, "ontology-hub-admin-password.txt")
            with open(email_path, "w", encoding="utf-8") as handle:
                handle.write("file-admin@example.org\n")
            with open(password_path, "w", encoding="utf-8") as handle:
                handle.write("file-secret-password\n")

            with mock.patch(
                "validation.components.ontology_hub.runtime_config._parse_key_value_file",
                return_value={},
            ):
                runtime = resolve_ontology_hub_runtime(
                    environ={
                        "ONTOLOGY_HUB_ADMIN_EMAIL_FILE": email_path,
                        "ONTOLOGY_HUB_ADMIN_PASSWORD_FILE": password_path,
                    }
                )

        self.assertEqual(runtime["adminEmail"], "file-admin@example.org")
        self.assertEqual(runtime["adminPassword"], "file-secret-password")

    def test_resolve_ontology_hub_runtime_honors_component_namespace_and_timeout_overrides(self):
        with mock.patch(
            "validation.components.ontology_hub.runtime_config._parse_key_value_file",
            return_value={
                "DS_1_NAME": "demo",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "COMPONENTS_NAMESPACE": "components",
            },
        ):
            runtime = resolve_ontology_hub_runtime(
                environ={
                    "ONTOLOGY_HUB_COMPONENTS_NAMESPACE": "custom-components",
                    "ONTOLOGY_HUB_UI_EXPECT_TIMEOUT_MS": "21000",
                    "ONTOLOGY_HUB_UI_ACTION_TIMEOUT_MS": "22000",
                    "ONTOLOGY_HUB_UI_NAVIGATION_TIMEOUT_MS": "23000",
                    "ONTOLOGY_HUB_UI_READY_TIMEOUT_MS": "24000",
                }
            )

        self.assertEqual(runtime["componentsNamespace"], "custom-components")
        self.assertEqual(runtime["uiExpectTimeoutMs"], 21000)
        self.assertEqual(runtime["uiActionTimeoutMs"], 22000)
        self.assertEqual(runtime["uiNavigationTimeoutMs"], 23000)
        self.assertEqual(runtime["uiReadyTimeoutMs"], 24000)

    def test_resolve_ontology_hub_runtime_reads_admin_credentials_from_explicit_values_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_path = os.path.join(tmpdir, "custom-values.yaml")
            with open(values_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            "validation:",
                            "  ui:",
                            "    adminEmail: chart-admin@example.org",
                            "    adminPassword: chart-secret-password",
                            "",
                        ]
                    )
                )

            with mock.patch(
                "validation.components.ontology_hub.runtime_config._parse_key_value_file",
                return_value={
                    "DS_1_NAME": "demo",
                    "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                },
            ):
                runtime = resolve_ontology_hub_runtime(
                    environ={"ONTOLOGY_HUB_VALUES_FILE": values_path}
                )

        self.assertEqual(runtime["adminEmail"], "chart-admin@example.org")
        self.assertEqual(runtime["adminPassword"], "chart-secret-password")

    def test_run_ontology_hub_component_validation_is_api_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            api_cases = [
                {
                    "test_case_id": "PT5-OH-08",
                    "type": "api",
                    "case_group": "pt5",
                    "evaluation": {"status": "passed", "assertions": []},
                },
                {
                    "test_case_id": "PT5-OH-09",
                    "type": "api",
                    "case_group": "pt5",
                    "evaluation": {"status": "passed", "assertions": []},
                },
                {
                    "test_case_id": "PT5-OH-13",
                    "type": "api",
                    "case_group": "pt5",
                    "evaluation": {"status": "failed", "assertions": ["Expected HTTP 200, got HTTP 502"]},
                },
                {
                    "test_case_id": "PT5-OH-14",
                    "type": "api",
                    "case_group": "pt5",
                    "evaluation": {"status": "passed", "assertions": []},
                },
                {
                    "test_case_id": "PT5-OH-15",
                    "type": "api",
                    "case_group": "pt5",
                    "evaluation": {"status": "passed", "assertions": []},
                },
            ]
            api_result = {
                "component": "ontology-hub",
                "suite": "api",
                "status": "failed",
                "summary": {"total": 5, "passed": 4, "failed": 1, "skipped": 0},
                "executed_cases": api_cases,
                "evidence_index": [{"scope": "suite", "suite": "api", "artifact_name": "report_json", "path": "api.json"}],
                "artifacts": {"report_json": os.path.join(tmpdir, "api.json")},
            }

            with mock.patch(
                "validation.components.ontology_hub.integration.component_runner.run_ontology_hub_validation",
                return_value=api_result,
            ):
                result = run_ontology_hub_component_validation(
                    "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ontology-hub")
            self.assertEqual(result["suite"], "api-integration")
            self.assertEqual(result["display_name"], "Ontology Hub API integration")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["summary"], {"total": 5, "passed": 4, "failed": 1, "skipped": 0})
            self.assertEqual(set(result["suites"]), {"api"})
            self.assertNotIn("ui", result["suites"])
            self.assertEqual(len(result["executed_cases"]), 5)
            self.assertEqual(result["pt5_summary"], {"total": 5, "passed": 4, "failed": 1, "skipped": 0})
            self.assertEqual(result["support_summary"], {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_pt5_cases"], 5)
            self.assertEqual(result["catalog_alignment"]["summary"]["uncovered_pt5_cases"], 0)
            self.assertNotIn("ui_report_json", result["artifacts"])
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))


if __name__ == "__main__":
    unittest.main()
