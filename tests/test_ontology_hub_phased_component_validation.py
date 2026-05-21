import os
import tempfile
import unittest
from unittest import mock

from validation.components.ontology_hub.component_runner import run_ontology_hub_component_validation


class OntologyHubPhasedComponentValidationTests(unittest.TestCase):
    def test_runs_functional_before_integration_and_persists_aggregate(self):
        calls = []

        def functional_runner(base_url, experiment_dir=None):
            calls.append("functional")
            return {
                "component": "ontology-hub",
                "status": "passed",
                "summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "OH-APP-01",
                        "case_group": "oh_app",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "pt5_case_results": [
                    {
                        "test_case_id": "PT5-OH-01",
                        "case_group": "pt5",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "support_checks": [],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(experiment_dir, "functional.json")},
            }

        def integration_runner(base_url, experiment_dir=None):
            calls.append("integration")
            return {
                "component": "ontology-hub",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "PT5-OH-15",
                        "case_group": "pt5",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "pt5_case_results": [
                    {
                        "test_case_id": "PT5-OH-15",
                        "case_group": "pt5",
                        "evaluation": {"status": "passed", "assertions": []},
                    }
                ],
                "support_checks": [],
                "evidence_index": [],
                "artifacts": {"report_json": os.path.join(experiment_dir, "integration.json")},
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch(
                    "validation.components.ontology_hub.component_runner.run_ontology_hub_functional_component_validation",
                    side_effect=functional_runner,
                ),
                mock.patch(
                    "validation.components.ontology_hub.component_runner.run_ontology_hub_integration_component_validation",
                    side_effect=integration_runner,
                ),
                mock.patch("builtins.print") as print_mock,
            ):
                result = run_ontology_hub_component_validation(
                    "http://ontology-hub.example.local",
                    experiment_dir=tmpdir,
                )

            printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
            self.assertIn("Component suite: Ontology Hub functional", printed)
            self.assertIn("Component suite: Ontology Hub API integration", printed)
            self.assertEqual(calls, ["functional", "integration"])
            self.assertEqual(result["phase_order"], ["functional", "integration"])
            self.assertEqual(result["phase_display_names"]["integration"], "Ontology Hub API integration")
            self.assertEqual(result["phases"]["integration"]["display_name"], "Ontology Hub API integration")
            self.assertEqual(result["summary"]["total"], 3)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(set(result["phases"]), {"functional", "integration"})
            self.assertEqual(len(result["pt5_case_results"]), 2)
            self.assertTrue(result["artifacts"]["report_json"].endswith("ontology_hub_component_validation.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))

    def test_runs_integration_even_when_functional_reports_failed_status(self):
        calls = []

        def functional_runner(base_url, experiment_dir=None):
            calls.append("functional")
            return {
                "component": "ontology-hub",
                "status": "failed",
                "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
                "executed_cases": [],
                "pt5_case_results": [],
                "support_checks": [],
                "evidence_index": [],
            }

        def integration_runner(base_url, experiment_dir=None):
            calls.append("integration")
            return {
                "component": "ontology-hub",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [],
                "pt5_case_results": [],
                "support_checks": [],
                "evidence_index": [],
            }

        with (
            mock.patch(
                "validation.components.ontology_hub.component_runner.run_ontology_hub_functional_component_validation",
                side_effect=functional_runner,
            ),
            mock.patch(
                "validation.components.ontology_hub.component_runner.run_ontology_hub_integration_component_validation",
                side_effect=integration_runner,
            ),
        ):
            result = run_ontology_hub_component_validation(
                "http://ontology-hub.example.local",
            )

        self.assertEqual(calls, ["functional", "integration"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["summary"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
