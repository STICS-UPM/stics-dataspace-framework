import os
import tempfile
import unittest
import uuid
from unittest import mock

from validation.components.ontology_hub.functional import runtime_preparation
from validation.components.ontology_hub.functional.component_runner import (
    run_ontology_hub_component_validation,
)
from validation.components.ontology_hub.functional.pt5_traceability import (
    build_oh_app_traceability,
    build_pt5_case_results_from_oh_app,
    summarize_pt5_case_results,
)
from validation.components.ontology_hub.functional.ui_runner import (
    PROJECT_ROOT,
    PLAYWRIGHT_WORKDIR,
    _build_artifact_paths,
    _prepare_functional_runtime,
    run_ontology_hub_functional_validation,
)


class OntologyHubFunctionalComponentValidationTests(unittest.TestCase):
    def test_functional_ui_runner_uses_validation_ui_as_workdir(self):
        self.assertTrue(str(PLAYWRIGHT_WORKDIR).endswith("Validation-Environment/validation/ui"))

    def test_build_artifact_paths_resolves_relative_experiment_dir_under_project_root(self):
        experiment_dir = f"experiments/relative-ontology-hub-test-{uuid.uuid4().hex}"
        paths = _build_artifact_paths(experiment_dir, create=False)

        self.assertTrue(
            paths["json_report_file"].startswith(str(PROJECT_ROOT / "experiments")),
        )
        self.assertFalse(os.path.exists(paths["base_dir"]))

    def test_functional_ui_runner_prunes_empty_playwright_dirs(self):
        experiments_root = PROJECT_ROOT / "experiments"
        with tempfile.TemporaryDirectory(dir=str(experiments_root)) as tmpdir, mock.patch(
            "validation.components.ontology_hub.functional.ui_runner._prepare_functional_runtime",
            return_value=(True, None),
        ), mock.patch(
            "validation.components.ontology_hub.functional.ui_runner.subprocess.run",
            side_effect=FileNotFoundError("playwright missing"),
        ):
            result = run_ontology_hub_functional_validation(
                "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                experiment_dir=tmpdir,
            )

            self.assertEqual(result["status"], "failed")
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertFalse(os.path.exists(result["artifacts"]["test_results_dir"]))
            self.assertFalse(os.path.exists(result["artifacts"]["html_report_dir"]))
            self.assertFalse(os.path.exists(result["artifacts"]["blob_report_dir"]))

    def test_functional_ui_runner_uses_framework_preparation_hook(self):
        with mock.patch(
            "validation.components.ontology_hub.functional.ui_runner._prepare_functional_runtime",
            return_value=(True, None),
        ) as prepare_mock, mock.patch(
            "validation.components.ontology_hub.functional.ui_runner.subprocess.run",
            side_effect=FileNotFoundError("playwright missing"),
        ):
            run_ontology_hub_functional_validation(
                "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                experiment_dir=tempfile.mkdtemp(),
            )

        prepare_mock.assert_called_once()

    def test_prepare_functional_runtime_reports_preparation_failure(self):
        with mock.patch(
            "validation.components.ontology_hub.functional.ui_runner.prepare_ontology_hub_for_functional",
            return_value=False,
        ):
            prepared, error = _prepare_functional_runtime({"baseUrl": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm"})

        self.assertFalse(prepared)
        self.assertEqual(error["type"], "RuntimePreparationError")

    def test_reset_runtime_uses_component_namespace_from_runtime(self):
        commands = []

        def fake_run(command, check=False):
            commands.append(command)
            return object()

        with mock.patch(
            "validation.components.ontology_hub.functional.runtime_preparation._run",
            side_effect=fake_run,
        ):
            result = runtime_preparation.reset_ontology_hub_for_functional(
                {
                    "dataspace": "demo",
                    "componentsNamespace": "components",
                }
            )

        self.assertTrue(result)
        self.assertTrue(commands)
        self.assertIn("deployment/demo-ontology-hub-mongodb -n components", commands[0])
        self.assertTrue(all(" -n components" in command for command in commands))

    def test_functional_ui_runner_reports_reason_when_playwright_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "validation.components.ontology_hub.functional.ui_runner._prepare_functional_runtime",
            return_value=(True, None),
        ), mock.patch(
            "validation.components.ontology_hub.functional.ui_runner.subprocess.run",
            side_effect=FileNotFoundError("playwright missing"),
        ):
            result = run_ontology_hub_functional_validation(
                "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                experiment_dir=tmpdir,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "playwright_runtime_unavailable")
        self.assertEqual(result["error"]["type"], "FileNotFoundError")

    def test_functional_ui_runner_fails_fast_when_preparation_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "validation.components.ontology_hub.functional.ui_runner._prepare_functional_runtime",
            return_value=(False, {"type": "RuntimePreparationError", "message": "prep failed"}),
        ), mock.patch(
            "validation.components.ontology_hub.functional.ui_runner.subprocess.run",
        ) as subprocess_mock:
            result = run_ontology_hub_functional_validation(
                "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                experiment_dir=tmpdir,
            )

        subprocess_mock.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "functional_preparation_failed")
        self.assertEqual(result["error"]["message"], "prep failed")

    def test_component_runner_wraps_functional_suite_for_level6(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            functional_result = {
                "component": "ontology-hub",
                "suite": "functional",
                "status": "passed",
                "reason": None,
                "error": None,
                "summary": {"total": 27, "passed": 27, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "OH-APP-01",
                        "description": "home is available",
                        "case_group": "pt5",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                    {
                        "test_case_id": "OH-APP-02",
                        "description": "admin login works",
                        "case_group": "pt5",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                ],
                "pt5_summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0},
                "evidence_index": [
                    {
                        "scope": "suite",
                        "suite": "functional",
                        "artifact_name": "report_json",
                        "path": os.path.join(tmpdir, "functional.json"),
                    }
                ],
                "artifacts": {
                    "report_json": os.path.join(tmpdir, "functional.json"),
                    "test_results_dir": os.path.join(tmpdir, "functional", "test-results"),
                    "html_report_dir": os.path.join(tmpdir, "functional", "playwright-report"),
                    "blob_report_dir": os.path.join(tmpdir, "functional", "blob-report"),
                    "json_report_file": os.path.join(tmpdir, "functional", "results.json"),
                },
            }

            with mock.patch(
                "validation.components.ontology_hub.functional.component_runner.run_ontology_hub_functional_validation",
                return_value=functional_result,
            ):
                result = run_ontology_hub_component_validation(
                    "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ontology-hub")
            self.assertEqual(result["status"], "passed")
            self.assertIsNone(result["reason"])
            self.assertEqual(result["suites"]["functional"]["status"], "passed")
            self.assertEqual(len(result["executed_cases"]), 2)
            self.assertEqual(result["pt5_summary"]["total"], 2)
            self.assertEqual(result["support_summary"]["total"], 0)
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5_case_results_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["support_checks_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["evidence_index_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["findings_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["catalog_alignment_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["oh_app_pt5_traceability_json"]))
            self.assertTrue(
                result["artifacts"]["functional_report_json"].endswith("functional.json")
            )

    def test_oh_app_results_are_aggregated_into_official_pt5_traceability(self):
        executed_cases = [
            {
                "test_case_id": "OH-APP-03",
                "description": "register ontology by URI",
                "request": {"spec": "oh_app_03_vocab_management.spec.js"},
                "response": {"attachments": []},
                "evaluation": {"status": "passed", "assertions": []},
            },
            {
                "test_case_id": "OH-APP-10",
                "description": "edit ontology metadata and tags",
                "request": {"spec": "oh_app_10_vocab_management.spec.js"},
                "response": {"attachments": []},
                "evaluation": {"status": "failed", "assertions": []},
            },
            {
                "test_case_id": "OH-APP-17",
                "description": "promote user to admin and verify + USER appears",
                "request": {"spec": "oh_app_15_agents_users.spec.js"},
                "response": {"attachments": []},
                "evaluation": {"status": "failed", "assertions": []},
            },
        ]

        pt5_case_results = build_pt5_case_results_from_oh_app(executed_cases)
        summary = summarize_pt5_case_results(pt5_case_results)
        by_id = {case["test_case_id"]: case for case in pt5_case_results}

        self.assertEqual(summary["total"], 16)
        self.assertEqual(by_id["PT5-OH-01"]["evaluation"]["status"], "passed")
        self.assertEqual(by_id["PT5-OH-02"]["evaluation"]["status"], "failed")
        self.assertEqual(by_id["PT5-OH-05"]["evaluation"]["status"], "failed")
        self.assertEqual(by_id["PT5-OH-13"]["evaluation"]["status"], "skipped")
        self.assertEqual(by_id["PT5-OH-16"]["evaluation"]["status"], "skipped")
        self.assertEqual(by_id["PT5-OH-02"]["known_component_issue_cases"], ["OH-APP-10"])
        self.assertIn("OH-APP-03", by_id["PT5-OH-01"]["executed_oh_app_cases"])

    def test_oh_app_traceability_keeps_raw_app_cases_and_mapped_pt5_ids(self):
        traceability = build_oh_app_traceability(
            [
                {
                    "test_case_id": "OH-APP-22",
                    "description": "patterns page generates a zip",
                    "request": {"spec": "oh_app_22_services.spec.js"},
                    "evaluation": {"status": "failed"},
                }
            ]
        )

        self.assertEqual(traceability[0]["test_case_id"], "OH-APP-22")
        self.assertEqual(traceability[0]["mapped_pt5_cases"], ["PT5-OH-06", "PT5-OH-14"])
        self.assertTrue(traceability[0]["known_component_issue"])

    def test_component_runner_prefers_functional_pt5_results_over_raw_oh_app_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            functional_result = {
                "component": "ontology-hub",
                "suite": "functional",
                "status": "passed",
                "reason": None,
                "error": None,
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "OH-APP-03",
                        "description": "register ontology by URI",
                        "case_group": "oh_app",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "oh_app_traceability": [
                    {
                        "test_case_id": "OH-APP-03",
                        "mapped_pt5_cases": ["PT5-OH-01", "PT5-OH-07"],
                    }
                ],
                "pt5_case_results": [
                    {
                        "test_case_id": "PT5-OH-01",
                        "description": "Registrar una ontologia mediante URI o repositorio",
                        "case_group": "pt5",
                        "evaluation": {"status": "passed", "assertions": ["OH-APP-03: passed"]},
                    }
                ],
                "pt5_summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "catalog_alignment": {
                    "source_file": "context/A5.2_Casos_Prueba_Framework_Reproducibles.xlsx",
                    "summary": {
                        "declared_pt5_cases": 16,
                        "executed_pt5_cases": 1,
                        "uncovered_pt5_cases": 15,
                    },
                },
                "evidence_index": [],
                "artifacts": {
                    "report_json": os.path.join(tmpdir, "functional.json"),
                    "test_results_dir": os.path.join(tmpdir, "functional", "test-results"),
                    "html_report_dir": os.path.join(tmpdir, "functional", "playwright-report"),
                    "blob_report_dir": os.path.join(tmpdir, "functional", "blob-report"),
                    "json_report_file": os.path.join(tmpdir, "functional", "results.json"),
                },
            }

            with mock.patch(
                "validation.components.ontology_hub.functional.component_runner.run_ontology_hub_functional_validation",
                return_value=functional_result,
            ):
                result = run_ontology_hub_component_validation(
                    "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["executed_cases"][0]["test_case_id"], "OH-APP-03")
            self.assertEqual(result["pt5_case_results"][0]["test_case_id"], "PT5-OH-01")
            self.assertEqual(result["oh_app_traceability"][0]["mapped_pt5_cases"], ["PT5-OH-01", "PT5-OH-07"])
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_pt5_cases"], 16)


if __name__ == "__main__":
    unittest.main()
