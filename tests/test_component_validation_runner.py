import unittest
from unittest import mock

from validation.components.ai_model_hub.component_runner import (
    run_ai_model_hub_component_validation,
)
from validation.components.ontology_hub.functional.component_runner import (
    run_ontology_hub_component_validation as run_ontology_hub_functional_component_validation,
)
from validation.components.registry import COMPONENT_REGISTRY, get_component_registration
from validation.components.runner import (
    COMPONENT_RUNNERS,
    run_component_validations,
    summarize_component_results,
)


class ComponentValidationRunnerTests(unittest.TestCase):
    def test_ontology_hub_uses_functional_runner_by_default(self):
        self.assertIs(
            COMPONENT_RUNNERS["ontology-hub"],
            run_ontology_hub_functional_component_validation,
        )

    def test_ai_model_hub_uses_component_runner_by_default(self):
        self.assertIs(
            COMPONENT_RUNNERS["ai-model-hub"],
            run_ai_model_hub_component_validation,
        )

    def test_component_registry_declares_supported_adapters(self):
        ontology_registration = get_component_registration("ontology-hub")
        ai_model_registration = get_component_registration("ai-model-hub")

        self.assertEqual(ontology_registration.supported_adapters, ("inesdata", "edc"))
        self.assertEqual(ontology_registration.deployable_adapters, ("inesdata",))
        self.assertEqual(ai_model_registration.supported_adapters, ("inesdata", "edc"))
        self.assertEqual(ai_model_registration.deployable_adapters, ("inesdata",))
        self.assertEqual(COMPONENT_REGISTRY["ai-model-hub"].validation_groups, ("ai-model-hub",))

    def test_unregistered_component_is_reported_as_skipped(self):
        results = run_component_validations(
            {
                "unknown-component": "http://unknown.example.local",
            }
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "skipped")
        self.assertEqual(results[0]["reason"], "no_validator_registered")
        self.assertEqual(results[0]["supported_adapters"], [])

    def test_ai_model_hub_runs_when_registered_in_common_runner(self):
        results = run_component_validations(
            {
                "ai-model-hub": "http://ai-model-hub.example.local",
            }
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["component"], "ai-model-hub")
        self.assertNotEqual(results[0]["status"], "skipped")

    def test_registered_component_uses_configured_runner(self):
        fake_runner = mock.Mock(
            return_value={
                "component": "ontology-hub",
                "status": "passed",
                "summary": {"total": 10, "passed": 10, "failed": 0, "skipped": 0},
                "suites": {
                    "api": {"status": "passed"},
                    "ui": {"status": "passed"},
                },
            }
        )

        with mock.patch.dict(
            "validation.components.runner.COMPONENT_RUNNERS",
            {"ontology-hub": fake_runner},
            clear=False,
        ):
            results = run_component_validations(
                {"ontology-hub": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm"},
                experiment_dir="/tmp/fake-experiment",
            )

        fake_runner.assert_called_once_with(
            "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
            experiment_dir="/tmp/fake-experiment",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["component"], "ontology-hub")
        self.assertEqual(results[0]["status"], "passed")
        self.assertIn("suites", results[0])

    def test_summary_counts_statuses(self):
        summary = summarize_component_results(
            [
                {"status": "passed"},
                {"status": "failed"},
                {"status": "skipped"},
            ]
        )

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
