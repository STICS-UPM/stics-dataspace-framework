import json
import os
import tempfile
import unittest
from unittest import mock

from validation.components.ai_model_hub.component_runner import run_ai_model_hub_component_validation
from validation.components.ai_model_hub.runner import (
    evaluate_html_shell_response,
    evaluate_runtime_config_response,
    run_ai_model_hub_validation,
)
from validation.components.ai_model_hub.ui_runner import run_ai_model_hub_ui_validation


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

    def test_run_ai_model_hub_validation_persists_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_http_get(url, timeout=20):
                if url == "http://ai-model-hub.example.local":
                    return 200, "text/html", "<!doctype html><html><body><app-root></app-root></body></html>"
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

    def test_run_ai_model_hub_component_validation_builds_catalog_alignment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_http_get(url, timeout=20):
                if url == "http://ai-model-hub.example.local":
                    return 200, "text/html", "<!doctype html><html><body><app-root></app-root></body></html>"
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

            with (
                mock.patch("validation.components.ai_model_hub.runner._http_get", side_effect=fake_http_get),
                mock.patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_MODEL_HUB_ENABLE_UI_VALIDATION", None)
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(result["suites"]["bootstrap"]["status"], "passed")
            self.assertEqual(result["suites"]["ui"]["status"], "skipped")
            self.assertEqual(result["support_summary"]["total"], 2)
            self.assertEqual(result["support_summary"]["passed"], 2)
            self.assertEqual(result["pt5_summary"]["total"], 0)
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_pt5_cases"], 18)
            self.assertEqual(result["catalog_alignment"]["summary"]["uncovered_pt5_cases"], 18)
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_support_checks"], 2)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_support_checks"], 2)
            self.assertEqual(result["catalog_alignment"]["summary"]["missing_support_checks"], 0)
            self.assertEqual(len(result["findings"]), 0)
            self.assertTrue(result["artifacts"]["report_json"].endswith("ai_model_hub_component_validation.json"))
            self.assertTrue(result["artifacts"]["ui_report_json"].endswith("ai_model_hub_ui_validation.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["support_checks_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["catalog_alignment_json"]))

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
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 6)
            self.assertEqual(result["summary"]["passed"], 6)
            self.assertEqual(result["pt5_summary"]["total"], 1)
            self.assertEqual(result["pt5_summary"]["passed"], 1)
            self.assertEqual(result["support_summary"]["total"], 1)
            self.assertEqual(result["support_summary"]["passed"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_pt5_cases"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_support_checks"], 1)
            self.assertEqual(result["pt5_case_results"][0]["traceability"], ["MH-01"])
            self.assertTrue(result["artifacts"]["ui_report_json"].endswith("ui.json"))

    def test_run_ai_model_hub_component_validation_can_include_connector_governance_opt_in(self):
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
                        "coverage_status": "automated_opt_in",
                        "execution_mode": "api_opt_in",
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
                mock.patch.dict(os.environ, {"AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE": "1"}),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["summary"]["total"], 6)
            self.assertEqual(result["summary"]["passed"], 6)
            self.assertIn("connector_governance", result["suites"])
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_pt5_cases"], 1)
            self.assertEqual(result["pt5_case_results"][0]["traceability"], ["MH-45"])

    def test_run_ai_model_hub_component_validation_can_include_model_benchmarking_opt_in(self):
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
                        "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE": "",
                        "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING": "1",
                    },
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["summary"]["passed"], 5)
            self.assertIn("model_benchmarking", result["suites"])
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_pt5_cases"], 1)
            self.assertEqual(result["pt5_case_results"][0]["traceability"], ["MH-37"])

    def test_run_ai_model_hub_component_validation_can_include_mobility_benchmarking_opt_in(self):
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
                        "execution_mode": "api_fixture_opt_in",
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
                        "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE": "",
                        "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING": "",
                        "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING": "1",
                    },
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(result["summary"]["passed"], 2)
            self.assertIn("mobility_benchmarking", result["suites"])
            self.assertEqual(result["functional_use_case_summary"]["total"], 1)
            self.assertEqual(result["functional_use_case_summary"]["passed"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_functional_use_cases"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["uncovered_functional_use_cases"], 1)
            self.assertEqual(
                result["functional_use_case_results"][0]["traceability"],
                ["MH-MOB-01", "GTFS-Madrid-Bench"],
            )
            self.assertTrue(os.path.exists(result["artifacts"]["functional_use_case_results_json"]))

    def test_run_ai_model_hub_component_validation_can_include_model_observer_opt_in(self):
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
                        "coverage_status": "automated_opt_in",
                        "execution_mode": "api_opt_in",
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
                ),
                mock.patch.dict(
                    os.environ,
                    {
                        "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE": "",
                        "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING": "",
                        "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING": "",
                        "AI_MODEL_HUB_ENABLE_MODEL_OBSERVER": "1",
                    },
                ),
            ):
                result = run_ai_model_hub_component_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(result["summary"]["passed"], 2)
            self.assertIn("model_observer", result["suites"])
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


if __name__ == "__main__":
    unittest.main()
