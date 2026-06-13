import json
import os
import tempfile
import unittest
from unittest import mock

from validation.components.ai_model_hub import component_runner
from validation.components.ai_model_hub.component_runner import run_ai_model_hub_component_validation
from validation.components.ai_model_hub.model_server_use_cases_api import (
    model_server_use_case_validation_enabled,
    resolve_model_server_validation_url,
    run_ai_model_hub_model_server_use_cases_validation,
)
from validation.components.ai_model_hub.runner import (
    evaluate_html_shell_response,
    evaluate_runtime_config_response,
    run_ai_model_hub_validation,
)
from validation.components.ai_model_hub.ui_runner import run_ai_model_hub_ui_validation

AI_MODEL_HUB_A52_SUITES_DISABLED = {
    "AI_MODEL_HUB_ENABLE_UI_VALIDATION": "",
    "AI_MODEL_HUB_ENABLE_FUNCTIONAL_VALIDATION": "",
    "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE": "",
    "AI_MODEL_HUB_ENABLE_MODEL_EXECUTION": "",
    "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING": "",
    "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING": "",
    "AI_MODEL_HUB_ENABLE_MODEL_OBSERVER": "",
    "AI_MODEL_HUB_ENABLE_MODEL_SERVER_USE_CASES": "",
}


class AIModelHubComponentValidationTests(unittest.TestCase):
    def test_evaluate_html_shell_response_passes_on_expected_markers(self):
        body = "<!doctype html><html><body><app-root></app-root></body></html>"

        result = evaluate_html_shell_response(
            200,
            "text/html; charset=utf-8",
            body,
            required_markers=["<html", "app-root"],
        )

        self.assertEqual(result["status"], "passed")

    def test_evaluate_runtime_config_response_passes_on_valid_config(self):
        body = json.dumps(
            {
                "menuItems": [],
                "healthCheckIntervalSeconds": 30,
                "enableUserConfig": False,
            }
        )

        result = evaluate_runtime_config_response(
            200,
            "application/json",
            body,
            required_keys=["menuItems"],
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["menu_items_count"], 0)
        self.assertIsNone(result["app_title"])
        self.assertEqual(result["health_check_interval_seconds"], 30)
        self.assertFalse(result["enable_user_config"])

    def test_evaluate_runtime_config_response_passes_on_inesdata_connector_config(self):
        body = json.dumps(
            {
                "managementApiUrl": "http://connector.example.local/management",
                "catalogUrl": "http://connector.example.local/management/federatedcatalog",
                "sharedUrl": "http://connector.example.local/shared",
                "participantId": "connector-c1",
                "service": {"asset": {"baseUrl": "/v3/assets"}},
                "oauth2": {"issuer": "http://auth.example.local/realms/pionera"},
            }
        )

        result = evaluate_runtime_config_response(
            200,
            "application/json",
            body,
            required_keys=[],
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["config_shape"], "inesdata-connector-interface")
        self.assertEqual(result["management_api_url"], "http://connector.example.local/management")
        self.assertEqual(result["participant_id"], "connector-c1")
        self.assertEqual(result["oauth2_issuer"], "http://auth.example.local/realms/pionera")

    def test_run_ai_model_hub_validation_persists_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_http_get(url, timeout=20):
                if url == "http://ai-model-hub.example.local":
                    return 200, "text/html", "<!doctype html><html><body><app-root></app-root></body></html>"
                if (
                    url
                    == "http://ai-model-hub.example.local/inesdata-connector-interface/assets/config/app.config.json"
                ):
                    payload = {
                        "managementApiUrl": "http://connector.example.local/management",
                        "catalogUrl": "http://connector.example.local/management/federatedcatalog",
                        "sharedUrl": "http://connector.example.local/shared",
                        "participantId": "connector-c1",
                        "service": {"asset": {"baseUrl": "/v3/assets"}},
                        "oauth2": {"issuer": "http://auth.example.local/realms/pionera"},
                    }
                    return 200, "application/json", json.dumps(payload)
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch("validation.components.ai_model_hub.runner._http_get", side_effect=fake_http_get):
                result = run_ai_model_hub_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["suite"], "bootstrap")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(result["summary"]["passed"], 2)
            self.assertEqual(result["pt5_summary"]["total"], 0)
            self.assertEqual(result["support_summary"]["total"], 2)
            self.assertEqual(len(result["executed_cases"]), 2)
            self.assertEqual(len(result["evidence_index"]), 3)
            self.assertTrue(result["artifacts"]["report_json"].endswith("ai_model_hub_validation.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["mh-bootstrap-01-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["mh-bootstrap-02-response.json"]))

    def test_run_ai_model_hub_validation_falls_back_to_legacy_config_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requested_urls = []

            def fake_http_get(url, timeout=20):
                requested_urls.append(url)
                if url == "http://ai-model-hub.example.local":
                    return 200, "text/html", "<!doctype html><html><body><app-root></app-root></body></html>"
                if url.endswith("/inesdata-connector-interface/assets/config/app.config.json"):
                    return 404, "text/html", "not found"
                if url.endswith("/assets/config/app.config.json"):
                    return 404, "text/html", "not found"
                if url == "http://ai-model-hub.example.local/config/app-config.json":
                    payload = {
                        "menuItems": [
                            {"label": "Catalog", "path": "/catalog"},
                        ],
                        "healthCheckIntervalSeconds": 30,
                        "enableUserConfig": False,
                    }
                    return 200, "application/json", json.dumps(payload)
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch("validation.components.ai_model_hub.runner._http_get", side_effect=fake_http_get):
                result = run_ai_model_hub_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["status"], "passed")
            config_case = result["executed_cases"][1]
            self.assertEqual(
                config_case["request"]["url"],
                "http://ai-model-hub.example.local/config/app-config.json",
            )
            self.assertEqual(len(config_case["response"]["attempts"]), 3)
            self.assertEqual(
                requested_urls,
                [
                    "http://ai-model-hub.example.local",
                    "http://ai-model-hub.example.local/inesdata-connector-interface/assets/config/app.config.json",
                    "http://ai-model-hub.example.local/assets/config/app.config.json",
                    "http://ai-model-hub.example.local/config/app-config.json",
                ],
            )

    def test_run_ai_model_hub_validation_falls_back_to_edc_dashboard_config_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requested_urls = []

            def fake_http_get(url, timeout=20):
                requested_urls.append(url)
                if url == "http://ai-model-hub.example.local":
                    return 200, "text/html", "<!doctype html><html><body><app-root></app-root></body></html>"
                if url.endswith("/edc-dashboard/config/app-config.json"):
                    payload = {
                        "menuItems": [
                            {"label": "ML Assets", "path": "/assets/ml"},
                        ],
                        "healthCheckIntervalSeconds": 30,
                        "enableUserConfig": False,
                    }
                    return 200, "application/json", json.dumps(payload)
                if url.endswith("/inesdata-connector-interface/assets/config/app.config.json"):
                    return 404, "text/html", "not found"
                if url.endswith("/assets/config/app.config.json"):
                    return 404, "text/html", "not found"
                if url.endswith("/config/app-config.json"):
                    return 404, "text/html", "not found"
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch("validation.components.ai_model_hub.runner._http_get", side_effect=fake_http_get):
                result = run_ai_model_hub_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["status"], "passed")
            config_case = result["executed_cases"][1]
            self.assertEqual(
                config_case["request"]["url"],
                "http://ai-model-hub.example.local/edc-dashboard/config/app-config.json",
            )
            self.assertEqual(config_case["response"]["config_shape"], "data-dashboard")
            self.assertEqual(len(config_case["response"]["attempts"]), 4)
            self.assertEqual(
                requested_urls,
                [
                    "http://ai-model-hub.example.local",
                    "http://ai-model-hub.example.local/inesdata-connector-interface/assets/config/app.config.json",
                    "http://ai-model-hub.example.local/assets/config/app.config.json",
                    "http://ai-model-hub.example.local/config/app-config.json",
                    "http://ai-model-hub.example.local/edc-dashboard/config/app-config.json",
                ],
            )

    def test_run_ai_model_hub_component_validation_builds_catalog_alignment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_http_get(url, timeout=20):
                if url == "http://ai-model-hub.example.local":
                    return 200, "text/html", "<!doctype html><html><body><app-root></app-root></body></html>"
                if (
                    url
                    == "http://ai-model-hub.example.local/inesdata-connector-interface/assets/config/app.config.json"
                ):
                    payload = {
                        "managementApiUrl": "http://connector.example.local/management",
                        "catalogUrl": "http://connector.example.local/management/federatedcatalog",
                        "sharedUrl": "http://connector.example.local/shared",
                        "participantId": "connector-c1",
                        "service": {"asset": {"baseUrl": "/v3/assets"}},
                        "oauth2": {"issuer": "http://auth.example.local/realms/pionera"},
                    }
                    return 200, "application/json", json.dumps(payload)
                raise AssertionError(f"Unexpected URL: {url}")

            with (
                mock.patch("validation.components.ai_model_hub.runner._http_get", side_effect=fake_http_get),
                mock.patch.dict(os.environ, AI_MODEL_HUB_A52_SUITES_DISABLED, clear=False),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["summary"]["passed"], 2)
            self.assertEqual(result["summary"]["skipped"], 3)
            self.assertEqual(result["suites"]["bootstrap"]["status"], "passed")
            self.assertEqual(result["suites"]["ui"]["status"], "skipped")
            self.assertEqual(result["suites"]["model_server_use_cases"]["status"], "skipped")
            self.assertEqual(result["support_summary"]["total"], 5)
            self.assertEqual(result["support_summary"]["passed"], 2)
            self.assertEqual(result["support_summary"]["skipped"], 3)
            self.assertEqual(result["pt5_summary"]["total"], 0)
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_pt5_cases"], 18)
            self.assertEqual(result["catalog_alignment"]["summary"]["uncovered_pt5_cases"], 18)
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_support_checks"], 5)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_support_checks"], 5)
            self.assertEqual(result["catalog_alignment"]["summary"]["missing_support_checks"], 0)
            self.assertEqual(len(result["findings"]), 0)
            self.assertTrue(result["artifacts"]["report_json"].endswith("ai_model_hub_component_validation.json"))
            self.assertTrue(result["artifacts"]["ui_report_json"].endswith("ai_model_hub_ui_validation.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["support_checks_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["catalog_alignment_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["artifact_manifest_json"]))

    def test_run_ai_model_hub_component_validation_combines_bootstrap_and_ui_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_result = {
                "component": "ai-model-hub",
                "suite": "bootstrap",
                "status": "passed",
                "summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-BOOTSTRAP-01",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [{"scope": "suite", "suite": "bootstrap", "artifact_name": "report_json", "path": "bootstrap.json"}],
                "artifacts": {"report_json": os.path.join(tmpdir, "bootstrap.json")},
            }
            ui_result = {
                "component": "ai-model-hub",
                "suite": "ui",
                "status": "passed",
                "summary": {"total": 4, "passed": 4, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "PT5-MH-01",
                        "type": "ui",
                        "case_group": "pt5",
                        "validation_type": "functional",
                        "dataspace_dimension": "access",
                        "mapping_status": "partial",
                        "coverage_status": "partial",
                        "execution_mode": "ui",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [{"scope": "suite", "suite": "ui", "artifact_name": "report_json", "path": "ui.json"}],
                "artifacts": {
                    "report_json": os.path.join(tmpdir, "ui.json"),
                    "test_results_dir": os.path.join(tmpdir, "ui", "test-results"),
                    "html_report_dir": os.path.join(tmpdir, "ui", "playwright-report"),
                    "blob_report_dir": os.path.join(tmpdir, "ui", "blob-report"),
                    "json_report_file": os.path.join(tmpdir, "ui", "results.json"),
                },
            }

            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=bootstrap_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation",
                    return_value=ui_result,
                ),
                mock.patch.dict(os.environ, AI_MODEL_HUB_A52_SUITES_DISABLED, clear=False),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 9)
            self.assertEqual(result["summary"]["passed"], 6)
            self.assertEqual(result["summary"]["skipped"], 3)
            self.assertEqual(result["phase_order"], ["preflight", "functional", "integration"])
            self.assertIn("bootstrap", result["phases"]["preflight"]["suites"])
            self.assertIn("ui", result["phases"]["functional"]["suites"])
            self.assertIn("model_server_use_cases", result["phases"]["functional"]["suites"])
            self.assertEqual(result["pt5_summary"]["total"], 1)
            self.assertEqual(result["pt5_summary"]["passed"], 1)
            self.assertEqual(result["support_summary"]["total"], 4)
            self.assertEqual(result["support_summary"]["passed"], 1)
            self.assertEqual(result["support_summary"]["skipped"], 3)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_pt5_cases"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_support_checks"], 4)
            self.assertEqual(result["pt5_case_results"][0]["traceability"], ["MH-01"])
            self.assertTrue(result["artifacts"]["ui_report_json"].endswith("ui.json"))

    def test_run_ai_model_hub_component_validation_skips_legacy_playwright_for_inesdata_connector_interface(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_result = {
                "component": "ai-model-hub",
                "suite": "bootstrap",
                "status": "passed",
                "summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-BOOTSTRAP-01",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                    {
                        "test_case_id": "MH-BOOTSTRAP-02",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "response": {"config_shape": "inesdata-connector-interface"},
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                ],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "bootstrap.json")},
            }
            skipped_api_result = {
                "component": "ai-model-hub",
                "suite": "model-server-use-cases-api",
                "status": "skipped",
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "executed_cases": [],
                "evidence_index": [],
                "artifacts": {},
            }

            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=bootstrap_result,
                ),
                mock.patch("validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation") as ui,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_functional_validation"
                ) as functional,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_server_use_cases_validation",
                    return_value=skipped_api_result,
                ),
                mock.patch.dict(os.environ, AI_MODEL_HUB_A52_SUITES_DISABLED, clear=False),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

        ui.assert_not_called()
        functional.assert_not_called()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["suites"]["ui"]["status"], "skipped")
        self.assertIn("INESData connector interface", result["suites"]["ui"]["skip_reason"])
        self.assertEqual(result["suites"]["linguistic_functional"]["status"], "skipped")

    def test_run_ai_model_hub_component_validation_skips_legacy_playwright_for_edc_dashboard(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_result = {
                "component": "ai-model-hub",
                "suite": "bootstrap",
                "status": "passed",
                "summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-BOOTSTRAP-01",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                    {
                        "test_case_id": "MH-BOOTSTRAP-02",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "response": {"config_shape": "data-dashboard"},
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                ],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "bootstrap.json")},
            }
            skipped_api_result = {
                "component": "ai-model-hub",
                "suite": "model-server-use-cases-api",
                "status": "skipped",
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "executed_cases": [],
                "evidence_index": [],
                "artifacts": {},
            }

            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=bootstrap_result,
                ),
                mock.patch("validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation") as ui,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_functional_validation"
                ) as functional,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_server_use_cases_validation",
                    return_value=skipped_api_result,
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        **AI_MODEL_HUB_A52_SUITES_DISABLED,
                        "PIONERA_ADAPTER": "edc",
                    },
                    clear=False,
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

        ui.assert_not_called()
        functional.assert_not_called()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["suites"]["ui"]["status"], "skipped")
        self.assertIn("EDC dashboard layout", result["suites"]["ui"]["skip_reason"])
        self.assertIn("EDC integration Playwright suite", result["suites"]["ui"]["skip_reason"])
        self.assertEqual(result["suites"]["linguistic_functional"]["status"], "skipped")

    def test_run_ai_model_hub_component_validation_runs_a52_suites_by_default(self):
        def suite_result(suite, case_id, case_group="pt5", validation_type="functional"):
            return {
                "component": "ai-model-hub",
                "suite": suite,
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": case_id,
                        "type": "api",
                        "case_group": case_group,
                        "validation_type": validation_type,
                        "dataspace_dimension": "test",
                        "mapping_status": "phase_3",
                        "coverage_status": "automated",
                        "execution_mode": "api",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [],
                "artifacts": {},
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            patches = [
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=suite_result("bootstrap", "MH-BOOTSTRAP-01", "support", "support"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation",
                    return_value=suite_result("ui", "PT5-MH-01"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_functional_validation",
                    return_value=suite_result("linguistic-functional", "MH-LING-01", "functional_use_case"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_connector_governance_validation",
                    return_value=suite_result("connector-governance-api", "PT5-MH-16", "pt5", "integration"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_execution_validation",
                    return_value=suite_result("model-execution-api", "PT5-MH-10", "pt5", "integration"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_benchmarking_validation",
                    return_value=suite_result("model-benchmarking-api", "PT5-MH-12"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_mobility_benchmarking_validation",
                    return_value=suite_result("mobility-benchmarking-api", "MH-MOB-01", "functional_use_case"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_observer_validation",
                    return_value=suite_result("model-observer-api", "MH-OBS-02", "observer", "non_functional"),
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_server_use_cases_validation",
                    return_value=suite_result("model-server-use-cases-api", "MH-MODEL-SERVER-01", "support", "support"),
                ),
            ]
            with mock.patch.dict(os.environ, {}, clear=True):
                with patches[0] as bootstrap, patches[1] as ui, patches[2] as functional, patches[3] as governance:
                    with patches[4] as execution, patches[5] as benchmarking, patches[6] as mobility, patches[7] as observer:
                        with patches[8] as model_server_use_cases:
                            result = run_ai_model_hub_component_validation(
                                "http://ai-model-hub.example.local",
                                experiment_dir=tmpdir,
                            )

            for patched_runner in [
                bootstrap,
                ui,
                functional,
                governance,
                execution,
                benchmarking,
                mobility,
                observer,
                model_server_use_cases,
            ]:
                patched_runner.assert_called_once()

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 9)
            self.assertIn("model_execution", result["suites"])
            self.assertIn("model_server_use_cases", result["suites"])
            self.assertIn("connector_governance", result["phases"]["integration"]["suites"])
            self.assertIn("model_execution", result["phases"]["integration"]["suites"])
            self.assertIn("model_benchmarking", result["phases"]["functional"]["suites"])
            self.assertIn("mobility_benchmarking", result["phases"]["functional"]["suites"])
            self.assertIn("model_observer", result["phases"]["integration"]["suites"])
            self.assertTrue(os.path.exists(result["artifacts"]["artifact_manifest_json"]))

    def test_model_execution_validation_skips_local_when_model_server_is_disabled(self):
        class Adapter:
            @staticmethod
            def get_cluster_connectors():
                return ["conn-provider"]

            @staticmethod
            def load_deployer_config():
                return {
                    "AI_MODEL_HUB_MODEL_SERVER_ENABLED": "false",
                    "AI_MODEL_HUB_MODEL_SERVER_MODE": "disabled",
                }

        suite = mock.Mock()
        with mock.patch(
            "validation.components.ai_model_hub.model_execution_api.build_ai_model_hub_model_execution_suite",
            return_value=(suite, Adapter()),
        ), mock.patch.dict(os.environ, {"PIONERA_TOPOLOGY": "local"}, clear=True):
            result = component_runner.run_ai_model_hub_model_execution_validation()

        suite.run.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["summary"]["skipped"], 1)
        self.assertEqual(result["executed_cases"][0]["test_case_id"], "PT5-MH-10")
        self.assertEqual(result["executed_cases"][0]["coverage_status"], "skipped_model_server_not_deployed")

    def test_model_execution_validation_runs_local_mock_when_enabled(self):
        class Adapter:
            @staticmethod
            def get_cluster_connectors():
                return ["conn-provider"]

            @staticmethod
            def load_deployer_config():
                return {
                    "AI_MODEL_HUB_MODEL_SERVER_ENABLED": "true",
                    "AI_MODEL_HUB_MODEL_SERVER_MODE": "mock",
                    "COMPONENTS_NAMESPACE": "components",
                }

        suite = mock.Mock()
        suite.run.return_value = {
            "component": "ai-model-hub",
            "suite": "model-execution-api",
            "status": "passed",
            "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
            "executed_cases": [],
            "evidence_index": [],
            "artifacts": {},
        }
        with mock.patch(
            "validation.components.ai_model_hub.model_execution_api.build_ai_model_hub_model_execution_suite",
            return_value=(suite, Adapter()),
        ), mock.patch.dict(os.environ, {"PIONERA_TOPOLOGY": "local"}, clear=True):
            result = component_runner.run_ai_model_hub_model_execution_validation()

        self.assertEqual(result["status"], "passed")
        suite.run.assert_called_once()
        kwargs = suite.run.call_args.kwargs
        self.assertEqual(kwargs["model_server_mode"], "mock")
        self.assertEqual(kwargs["provider"], "conn-provider")
        self.assertIn("http://model-server.components.svc.cluster.local:8080", kwargs["model_url"])

    def test_model_server_use_cases_validation_is_enabled_by_real_modes(self):
        self.assertFalse(model_server_use_case_validation_enabled({}))
        self.assertFalse(model_server_use_case_validation_enabled({"AI_MODEL_HUB_MODEL_SERVER_MODE": "mock"}))
        self.assertTrue(model_server_use_case_validation_enabled({"AI_MODEL_HUB_MODEL_SERVER_MODE": "use-cases"}))
        self.assertTrue(model_server_use_case_validation_enabled({"AI_MODEL_HUB_MODEL_SERVER_MODE": "combined"}))
        self.assertFalse(
            model_server_use_case_validation_enabled(
                {
                    "AI_MODEL_HUB_MODEL_SERVER_MODE": "combined",
                    "AI_MODEL_HUB_ENABLE_MODEL_SERVER_USE_CASES": "0",
                }
            )
        )

    def test_model_server_use_cases_validation_uses_public_validation_url(self):
        self.assertEqual(
            resolve_model_server_validation_url(
                {
                    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://model-server.internal",
                    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL": "https://org.example.test/model-server",
                }
            ),
            "https://org.example.test/model-server",
        )
        self.assertEqual(
            resolve_model_server_validation_url(
                {
                    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL": "http://127.0.0.1:18080",
                    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL": "https://org.example.test/model-server",
                }
            ),
            "http://127.0.0.1:18080",
        )
        self.assertEqual(
            resolve_model_server_validation_url(
                {
                    "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
                    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH": "/model-server",
                }
            ),
            "https://org1.example.test/model-server",
        )

    def test_model_server_use_cases_validation_records_discovery_evidence(self):
        def fake_http_request(method, url, payload=None, timeout=30):
            self.assertEqual(method, "GET")
            if url == "https://org.example.test/model-server/models":
                return 200, "application/json", json.dumps({"flares": [{"name": "flares-reliability"}]})
            if url == "https://org.example.test/model-server/datasets":
                return 200, "application/json", json.dumps({"datasets": [{"name": "segments_test.csv"}]})
            self.fail(f"unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "validation.components.ai_model_hub.model_server_use_cases_api._http_request",
                side_effect=fake_http_request,
            ):
                result = run_ai_model_hub_model_server_use_cases_validation(
                    experiment_dir=tmpdir,
                    environ={
                        "AI_MODEL_HUB_MODEL_SERVER_MODE": "combined",
                        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL": "https://org.example.test/model-server",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY": "https://example.test/use-cases.git",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF": "abc123",
                    },
                )
                self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
                self.assertTrue(os.path.exists(result["artifacts"]["mh-model-server-01-response.json"]))
                self.assertTrue(os.path.exists(result["artifacts"]["mh-model-server-02-response.json"]))

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["suite_display_name"], "AI Model Hub use cases")
        self.assertEqual(result["summary"], {"total": 2, "passed": 2, "failed": 0, "skipped": 0})
        self.assertEqual(result["executed_cases"][0]["test_case_id"], "MH-MODEL-SERVER-01")
        self.assertEqual(result["executed_cases"][1]["test_case_id"], "MH-MODEL-SERVER-02")
        self.assertEqual(result["model_server"]["source_ref"], "abc123")

    def test_model_server_use_cases_validation_can_probe_configured_endpoints(self):
        calls = []

        def fake_http_request(method, url, payload=None, timeout=30):
            calls.append((method, url, payload))
            if method == "GET":
                if url.endswith("/models"):
                    return 200, "application/json", json.dumps({"models": [{"endpoint": "/api/v1/flares"}]})
                return 200, "application/json", json.dumps({"datasets": [{"name": "segments_test.csv"}]})
            return 200, "application/json", json.dumps({"result": {"label": "confiable"}})

        with mock.patch(
            "validation.components.ai_model_hub.model_server_use_cases_api._http_request",
            side_effect=fake_http_request,
        ):
            result = run_ai_model_hub_model_server_use_cases_validation(
                environ={
                    "AI_MODEL_HUB_MODEL_SERVER_MODE": "use-cases",
                    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL": "http://model-server.example.test",
                    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS": "/api/v1/flares,/api/v1/gtfs",
                    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD": '{"text":"sample"}',
                },
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"]["total"], 3)
        self.assertEqual(result["executed_cases"][2]["test_case_id"], "MH-MODEL-SERVER-03")
        self.assertEqual(
            calls,
            [
                ("GET", "http://model-server.example.test/models", None),
                ("GET", "http://model-server.example.test/datasets", None),
                ("POST", "http://model-server.example.test/api/v1/flares", {"text": "sample"}),
                ("POST", "http://model-server.example.test/api/v1/gtfs", {"text": "sample"}),
            ],
        )

    def test_run_ai_model_hub_component_validation_uses_api_only_mode_when_explicitly_enabled(self):
        def suite_result(suite, case_id, case_group="pt5", validation_type="functional"):
            return {
                "component": "ai-model-hub",
                "suite": suite,
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": case_id,
                        "type": "api",
                        "case_group": case_group,
                        "validation_type": validation_type,
                        "dataspace_dimension": "test",
                        "mapping_status": "phase_3",
                        "coverage_status": "automated",
                        "execution_mode": "api",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [],
                "artifacts": {},
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=suite_result("bootstrap", "MH-BOOTSTRAP-01", "support", "support"),
                ) as bootstrap,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation"
                ) as ui,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_functional_validation"
                ) as playwright_functional,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_connector_governance_validation",
                    return_value=suite_result("connector-governance-api", "PT5-MH-16", "pt5", "integration"),
                ) as governance,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_execution_validation",
                    return_value=suite_result("model-execution-api", "PT5-MH-10", "pt5", "integration"),
                ) as execution,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_benchmarking_validation",
                    return_value=suite_result("model-benchmarking-api", "PT5-MH-12"),
                ) as benchmarking,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_mobility_benchmarking_validation",
                    return_value=suite_result("mobility-benchmarking-api", "MH-MOB-01", "functional_use_case"),
                ) as mobility,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_observer_validation",
                    return_value=suite_result("model-observer-api", "MH-OBS-02", "observer", "non_functional"),
                ) as observer,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_server_use_cases_validation",
                    return_value=suite_result("model-server-use-cases-api", "MH-MODEL-SERVER-01", "support", "support"),
                ) as model_server_use_cases,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner._resolve_model_observer_base_url",
                    return_value="http://observer.example.local",
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        "PIONERA_ADAPTER": "edc",
                        "PIONERA_COMPONENT_VALIDATION_MODE": "api-only",
                    },
                    clear=True,
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

        bootstrap.assert_called_once()
        ui.assert_not_called()
        playwright_functional.assert_not_called()
        for api_runner in [model_server_use_cases, governance, execution, benchmarking, mobility, observer]:
            api_runner.assert_called_once()

        self.assertEqual(result["validation_mode"], "api")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"]["total"], 7)
        self.assertNotIn("ui", result["suites"])
        self.assertNotIn("linguistic_functional", result["suites"])
        self.assertEqual(result["phase_execution_channels"]["preflight"], ["api"])
        self.assertEqual(result["phase_execution_channels"]["functional"], ["api"])
        self.assertEqual(result["phase_execution_channels"]["integration"], ["api"])
        self.assertIn("model_benchmarking", result["phases"]["functional"]["suites"])
        self.assertIn("model_execution", result["phases"]["integration"]["suites"])

    def test_run_ai_model_hub_component_validation_can_include_connector_governance_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_result = {
                "component": "ai-model-hub",
                "suite": "bootstrap",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-BOOTSTRAP-01",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "bootstrap.json")},
            }
            ui_result = {
                "component": "ai-model-hub",
                "suite": "ui",
                "status": "skipped",
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "executed_cases": [],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "ui.json")},
            }
            governance_result = {
                "component": "ai-model-hub",
                "suite": "connector-governance-api",
                "status": "passed",
                "summary": {"total": 5, "passed": 5, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "PT5-MH-16",
                        "type": "api",
                        "case_group": "pt5",
                        "validation_type": "integration",
                        "dataspace_dimension": "identity",
                        "mapping_status": "phase_3",
                        "coverage_status": "automated",
                        "execution_mode": "api",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [
                    {
                        "scope": "suite",
                        "suite": "connector-governance-api",
                        "artifact_name": "report_json",
                        "path": os.path.join(tmpdir, "governance.json"),
                    }
                ],
                "artifacts": {"report_json": os.path.join(tmpdir, "governance.json")},
            }

            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=bootstrap_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation",
                    return_value=ui_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_connector_governance_validation",
                    return_value=governance_result,
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        **AI_MODEL_HUB_A52_SUITES_DISABLED,
                        "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE": "1",
                    },
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["summary"]["total"], 9)
            self.assertEqual(result["summary"]["passed"], 6)
            self.assertEqual(result["summary"]["skipped"], 3)
            self.assertIn("connector_governance", result["suites"])
            self.assertIn("model_server_use_cases", result["suites"])
            self.assertIn("connector_governance", result["phases"]["integration"]["suites"])
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_pt5_cases"], 1)
            self.assertEqual(result["pt5_case_results"][0]["traceability"], ["MH-45"])

    def test_run_ai_model_hub_component_validation_can_include_model_benchmarking_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_result = {
                "component": "ai-model-hub",
                "suite": "bootstrap",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-BOOTSTRAP-01",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "bootstrap.json")},
            }
            ui_result = {
                "component": "ai-model-hub",
                "suite": "ui",
                "status": "skipped",
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "executed_cases": [],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "ui.json")},
            }
            benchmarking_result = {
                "component": "ai-model-hub",
                "suite": "model-benchmarking-api",
                "status": "passed",
                "summary": {"total": 4, "passed": 4, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "PT5-MH-12",
                        "type": "api",
                        "case_group": "pt5",
                        "validation_type": "functional",
                        "dataspace_dimension": "comparison",
                        "mapping_status": "phase_3",
                        "coverage_status": "automated",
                        "execution_mode": "api_fixture",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [
                    {
                        "scope": "suite",
                        "suite": "model-benchmarking-api",
                        "artifact_name": "report_json",
                        "path": os.path.join(tmpdir, "benchmarking.json"),
                    }
                ],
                "artifacts": {"report_json": os.path.join(tmpdir, "benchmarking.json")},
            }

            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=bootstrap_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation",
                    return_value=ui_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_benchmarking_validation",
                    return_value=benchmarking_result,
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        **AI_MODEL_HUB_A52_SUITES_DISABLED,
                        "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING": "1",
                    },
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["summary"]["total"], 8)
            self.assertEqual(result["summary"]["passed"], 5)
            self.assertEqual(result["summary"]["skipped"], 3)
            self.assertIn("model_benchmarking", result["suites"])
            self.assertIn("model_server_use_cases", result["suites"])
            self.assertIn("model_benchmarking", result["phases"]["functional"]["suites"])
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_pt5_cases"], 1)
            self.assertEqual(result["pt5_case_results"][0]["traceability"], ["MH-37"])

    def test_run_ai_model_hub_component_validation_can_include_mobility_benchmarking_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_result = {
                "component": "ai-model-hub",
                "suite": "bootstrap",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-BOOTSTRAP-01",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "bootstrap.json")},
            }
            ui_result = {
                "component": "ai-model-hub",
                "suite": "ui",
                "status": "skipped",
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "executed_cases": [],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "ui.json")},
            }
            mobility_result = {
                "component": "ai-model-hub",
                "suite": "mobility-benchmarking-api",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-MOB-01",
                        "type": "api",
                        "case_group": "functional_use_case",
                        "validation_type": "functional",
                        "dataspace_dimension": "mobility",
                        "mapping_status": "phase_3",
                        "coverage_status": "automated_fixture",
                        "execution_mode": "api_fixture",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [
                    {
                        "scope": "suite",
                        "suite": "mobility-benchmarking-api",
                        "artifact_name": "report_json",
                        "path": os.path.join(tmpdir, "mobility.json"),
                    }
                ],
                "artifacts": {"report_json": os.path.join(tmpdir, "mobility.json")},
            }

            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=bootstrap_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation",
                    return_value=ui_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_mobility_benchmarking_validation",
                    return_value=mobility_result,
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        **AI_MODEL_HUB_A52_SUITES_DISABLED,
                        "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING": "1",
                    },
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["summary"]["passed"], 2)
            self.assertEqual(result["summary"]["skipped"], 3)
            self.assertIn("mobility_benchmarking", result["suites"])
            self.assertIn("model_server_use_cases", result["suites"])
            self.assertEqual(result["functional_use_case_summary"]["total"], 1)
            self.assertEqual(result["functional_use_case_summary"]["passed"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_functional_use_cases"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["uncovered_functional_use_cases"], 3)
            self.assertEqual(
                result["functional_use_case_results"][0]["traceability"],
                ["MH-MOB-01", "GTFS-Madrid-Bench"],
            )
            self.assertTrue(os.path.exists(result["artifacts"]["functional_use_case_results_json"]))

    def test_run_ai_model_hub_component_validation_can_include_model_observer_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_result = {
                "component": "ai-model-hub",
                "suite": "bootstrap",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-BOOTSTRAP-01",
                        "type": "api",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "api_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "bootstrap.json")},
            }
            ui_result = {
                "component": "ai-model-hub",
                "suite": "ui",
                "status": "skipped",
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                "executed_cases": [],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(tmpdir, "ui.json")},
            }
            observer_result = {
                "component": "ai-model-hub",
                "suite": "model-observer-api",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "MH-OBS-02",
                        "type": "api",
                        "case_group": "observer",
                        "validation_type": "non_functional",
                        "dataspace_dimension": "governance",
                        "mapping_status": "planned_observer",
                        "coverage_status": "automated",
                        "execution_mode": "api",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "evidence_index": [
                    {
                        "scope": "suite",
                        "suite": "model-observer-api",
                        "artifact_name": "report_json",
                        "path": os.path.join(tmpdir, "observer.json"),
                    }
                ],
                "artifacts": {"report_json": os.path.join(tmpdir, "observer.json")},
            }

            with (
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_validation",
                    return_value=bootstrap_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_ui_validation",
                    return_value=ui_result,
                ),
                mock.patch(
                    "validation.components.ai_model_hub.component_runner.run_ai_model_hub_model_observer_validation",
                    return_value=observer_result,
                ) as observer,
                mock.patch(
                    "validation.components.ai_model_hub.component_runner._resolve_model_observer_base_url",
                    return_value="http://backend-demo.dev.ds.dataspaceunit.upm",
                ) as resolve_observer_base_url,
                mock.patch.dict(
                    os.environ,
                    {
                        **AI_MODEL_HUB_A52_SUITES_DISABLED,
                        "AI_MODEL_HUB_ENABLE_MODEL_OBSERVER": "1",
                    },
                ),
                mock.patch("builtins.print") as print_mock,
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
            self.assertIn("Component API suite: AI Model Hub preflight", printed)
            self.assertIn("Component Playwright suite: AI Model Hub functional", printed)
            self.assertIn("Component API suite: AI Model Hub integration", printed)
            self.assertIn("✓ MH-OBS-02", printed)
            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["summary"]["passed"], 2)
            self.assertEqual(result["summary"]["skipped"], 3)
            self.assertIn("model_observer", result["suites"])
            self.assertIn("model_server_use_cases", result["suites"])
            self.assertEqual(result["phase_execution_channels"]["preflight"], ["api"])
            self.assertEqual(result["phase_execution_channels"]["integration"], ["api"])
            self.assertEqual(result["suite_execution_channels"]["model_observer"], "api")
            resolve_observer_base_url.assert_called_once_with("http://ai-model-hub.example.local")
            observer.assert_called_once()
            self.assertEqual(
                observer.call_args.kwargs["base_url"],
                "http://backend-demo.dev.ds.dataspaceunit.upm",
            )
            self.assertEqual(result["observer_case_summary"]["total"], 1)
            self.assertEqual(result["observer_case_summary"]["passed"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_observer_cases"], 6)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_observer_cases"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["uncovered_observer_cases"], 5)
            self.assertEqual(
                result["observer_case_results"][0]["traceability"],
                ["PT5-MH-17", "MH-46", "Model Clearing House"],
            )
            self.assertTrue(os.path.exists(result["artifacts"]["observer_case_results_json"]))

    def test_resolve_model_observer_base_url_prefers_configured_backend_over_dashboard_url(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                component_runner,
                "_derive_model_observer_base_url_from_adapter",
                return_value="http://backend-demo.dev.ds.dataspaceunit.upm",
            ) as derive_backend,
        ):
            result = component_runner._resolve_model_observer_base_url("http://ai-model-hub.example.local")

        self.assertEqual(result, "http://backend-demo.dev.ds.dataspaceunit.upm")
        derive_backend.assert_called_once()

    def test_resolve_model_observer_base_url_prefers_explicit_environment(self):
        with (
            mock.patch.dict(
                os.environ,
                {"AI_MODEL_HUB_OBSERVER_API_BASE_URL": "http://observer.example.local/api/model-observer"},
                clear=True,
            ),
            mock.patch.object(
                component_runner,
                "_derive_model_observer_base_url_from_adapter",
                return_value="http://backend-demo.dev.ds.dataspaceunit.upm",
            ) as derive_backend,
        ):
            result = component_runner._resolve_model_observer_base_url("http://ai-model-hub.example.local")

        self.assertEqual(result, "http://observer.example.local")
        derive_backend.assert_not_called()

    def test_resolve_model_observer_base_url_prefers_edc_connector_default_api(self):
        class FakeConfig:
            @staticmethod
            def ds_domain_base():
                return "dev.ds.dataspaceunit.upm"

        class FakeAdapter:
            config = FakeConfig()

            @staticmethod
            def load_deployer_config():
                return {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"}

            @staticmethod
            def get_cluster_connectors():
                return ["conn-provider-edc", "conn-consumer-edc"]

            @staticmethod
            def load_connector_credentials(connector):
                if connector != "conn-provider-edc":
                    return None
                return {
                    "public_access_urls": {
                        "edc_dashboard_login": "http://dashboard.example.local/edc-dashboard/",
                        "connector_ingress": "http://conn-provider-edc.example.local",
                        "connector_default_api": "http://conn-provider-edc.example.local/api",
                    }
                }

        with (
            mock.patch.dict(
                os.environ,
                {"PIONERA_ADAPTER": "edc"},
                clear=True,
            ),
            mock.patch(
                "validation.components.ai_model_hub.connector_governance_api._build_adapter",
                return_value=FakeAdapter(),
            ),
            mock.patch(
                "validation.components.ai_model_hub.connector_governance_api._dataspace_name_loader",
                return_value=lambda: "pionera-edc",
            ),
        ):
            result = component_runner._resolve_model_observer_base_url("http://ai-model-hub.example.local")

        self.assertEqual(
            result,
            "http://conn-provider-edc.example.local/api",
        )

    def test_resolve_model_observer_base_url_uses_edc_dashboard_proxy_when_ingress_is_missing(self):
        class FakeConfig:
            @staticmethod
            def ds_domain_base():
                return "dev.ds.dataspaceunit.upm"

        class FakeAdapter:
            config = FakeConfig()

            @staticmethod
            def load_deployer_config():
                return {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"}

            @staticmethod
            def get_cluster_connectors():
                return ["conn-provider-edc"]

            @staticmethod
            def load_connector_credentials(connector):
                if connector != "conn-provider-edc":
                    return None
                return {
                    "public_access_urls": {
                        "edc_dashboard_login": "http://dashboard.example.local/edc-dashboard/",
                    }
                }

        with (
            mock.patch.dict(
                os.environ,
                {"PIONERA_ADAPTER": "edc"},
                clear=True,
            ),
            mock.patch(
                "validation.components.ai_model_hub.connector_governance_api._build_adapter",
                return_value=FakeAdapter(),
            ),
            mock.patch(
                "validation.components.ai_model_hub.connector_governance_api._dataspace_name_loader",
                return_value=lambda: "pionera-edc",
            ),
        ):
            result = component_runner._resolve_model_observer_base_url("http://ai-model-hub.example.local")

        self.assertEqual(
            result,
            "http://dashboard.example.local/edc-dashboard-api/connectors/conn-provider-edc/api",
        )

    def test_edc_model_observer_auth_headers_are_derived_from_connector_credentials(self):
        class FakeConfig:
            @staticmethod
            def ds_domain_base():
                return "dev.ds.dataspaceunit.upm"

        class FakeAdapter:
            config = FakeConfig()

            @staticmethod
            def load_deployer_config():
                return {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"}

            @staticmethod
            def get_cluster_connectors():
                return ["conn-provider-edc"]

            @staticmethod
            def load_connector_credentials(connector):
                if connector != "conn-provider-edc":
                    return None
                return {
                    "connector_user": {
                        "user": "user-conn-provider-edc",
                        "passwd": "demo-password",
                    },
                    "public_access_urls": {
                        "keycloak_realm": "http://auth.example.local/realms/pionera-edc",
                    },
                }

        token_response = mock.Mock()
        token_response.status_code = 200
        token_response.json.return_value = {"access_token": "observer-token"}

        with (
            mock.patch.dict(
                os.environ,
                {"PIONERA_ADAPTER": "edc"},
                clear=True,
            ),
            mock.patch(
                "validation.components.ai_model_hub.connector_governance_api._build_adapter",
                return_value=FakeAdapter(),
            ),
            mock.patch(
                "validation.components.ai_model_hub.connector_governance_api._dataspace_name_loader",
                return_value=lambda: "pionera-edc",
            ),
            mock.patch(
                "validation.components.ai_model_hub.component_runner.requests.post",
                return_value=token_response,
            ) as post,
        ):
            headers = component_runner._derive_edc_model_observer_auth_headers_from_adapter()

        self.assertEqual(headers, {"Authorization": "Bearer observer-token"})
        post.assert_called_once()
        self.assertEqual(
            post.call_args.args[0],
            "http://auth.example.local/realms/pionera-edc/protocol/openid-connect/token",
        )


if __name__ == "__main__":
    unittest.main()
