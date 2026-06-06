import unittest
from unittest import mock
import tempfile
import os

from validation.components.ai_model_hub.component_runner import (
    run_ai_model_hub_component_validation,
)
from validation.components.ontology_hub.component_runner import (
    run_ontology_hub_component_validation,
)
from validation.components.execution_mode import (
    component_adapter_name,
    component_api_only_enabled,
)
from validation.components.registry import COMPONENT_REGISTRY, get_component_registration
from validation.components.runner import (
    COMPONENT_RUNNERS,
    run_component_validations,
    summarize_component_results,
)

AI_MODEL_HUB_A52_SUITES_DISABLED = {
    "AI_MODEL_HUB_ENABLE_UI_VALIDATION": "",
    "AI_MODEL_HUB_ENABLE_FUNCTIONAL_VALIDATION": "",
    "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE": "",
    "AI_MODEL_HUB_ENABLE_MODEL_EXECUTION": "",
    "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING": "",
    "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING": "",
    "AI_MODEL_HUB_ENABLE_MODEL_OBSERVER": "",
}


class ComponentValidationRunnerTests(unittest.TestCase):
    def test_ontology_hub_uses_phased_runner_by_default(self):
        self.assertIs(
            COMPONENT_RUNNERS["ontology-hub"],
            run_ontology_hub_component_validation,
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
        self.assertEqual(ontology_registration.deployable_adapters, ("inesdata", "edc"))
        self.assertEqual(ai_model_registration.supported_adapters, ("inesdata", "edc"))
        self.assertEqual(ai_model_registration.deployable_adapters, ("inesdata", "edc"))
        self.assertEqual(COMPONENT_REGISTRY["ai-model-hub"].validation_groups, ("ai-model-hub",))

    def test_component_execution_mode_defaults_to_mixed_for_edc(self):
        self.assertEqual(component_adapter_name({"PIONERA_ADAPTER": "edc"}), "edc")
        self.assertFalse(component_api_only_enabled({"PIONERA_ADAPTER": "edc"}))
        self.assertFalse(component_api_only_enabled({"PIONERA_ADAPTER": "inesdata"}))

    def test_component_execution_mode_honors_explicit_override(self):
        self.assertTrue(
            component_api_only_enabled(
                {
                    "PIONERA_ADAPTER": "inesdata",
                    "PIONERA_COMPONENT_VALIDATION_MODE": "api-only",
                }
            )
        )
        self.assertFalse(
            component_api_only_enabled(
                {
                    "PIONERA_ADAPTER": "edc",
                    "PIONERA_COMPONENT_VALIDATION_MODE": "mixed",
                }
            )
        )

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
        with mock.patch.dict("os.environ", AI_MODEL_HUB_A52_SUITES_DISABLED, clear=False):
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

    def test_ontology_hub_component_runner_writes_common_artifact_manifest(self):
        phase_result = {
            "component": "ontology-hub",
            "suite": "phase",
            "status": "passed",
            "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
            "executed_cases": [
                {
                    "test_case_id": "PT5-OH-01",
                    "case_group": "pt5",
                    "evaluation": {"status": "passed", "assertions": []},
                }
            ],
            "pt5_case_results": [],
            "pt5_cases": [],
            "support_checks": [],
            "evidence_index": [],
            "findings": [],
            "artifacts": {},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch(
                    "validation.components.ontology_hub.component_runner.run_ontology_hub_functional_component_validation",
                    return_value={**phase_result, "suite": "functional"},
                ),
                mock.patch(
                    "validation.components.ontology_hub.component_runner.run_ontology_hub_integration_component_validation",
                    return_value={**phase_result, "suite": "integration"},
                ),
            ):
                result = run_ontology_hub_component_validation(
                    "http://ontology.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertTrue(os.path.exists(result["artifacts"]["artifact_manifest_json"]))

    def test_registered_components_follow_auditor_execution_order(self):
        calls = []

        def fake_runner(component):
            def _run(base_url, experiment_dir=None):
                calls.append(component)
                return {
                    "component": component,
                    "base_url": base_url,
                    "status": "passed",
                    "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                }

            return _run

        with mock.patch.dict(
            "validation.components.runner.COMPONENT_RUNNERS",
            {
                "ai-model-hub": fake_runner("ai-model-hub"),
                "ontology-hub": fake_runner("ontology-hub"),
                "semantic-virtualization": fake_runner("semantic-virtualization"),
            },
            clear=False,
        ):
            results = run_component_validations(
                {
                    "semantic-virtualization": "http://semantic.example.local",
                    "ai-model-hub": "http://ai.example.local",
                    "ontology-hub": "http://ontology.example.local",
                },
                experiment_dir="/tmp/fake-experiment",
            )

        self.assertEqual(calls, ["ontology-hub", "ai-model-hub", "semantic-virtualization"])
        self.assertEqual(
            [result["component"] for result in results],
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
        )

    def test_registered_components_stop_after_first_failure_when_fail_fast_enabled(self):
        calls = []

        def fake_runner(component, status):
            def _run(base_url, experiment_dir=None):
                calls.append(component)
                return {
                    "component": component,
                    "base_url": base_url,
                    "status": status,
                    "summary": {"total": 1, "passed": int(status == "passed"), "failed": int(status == "failed"), "skipped": 0},
                }

            return _run

        with mock.patch.dict(
            "validation.components.runner.COMPONENT_RUNNERS",
            {
                "ai-model-hub": fake_runner("ai-model-hub", "passed"),
                "ontology-hub": fake_runner("ontology-hub", "failed"),
                "semantic-virtualization": fake_runner("semantic-virtualization", "passed"),
            },
            clear=False,
        ), mock.patch.dict(os.environ, {"PIONERA_LEVEL6_STOP_ON_PLAYWRIGHT_FAILURE": "1"}, clear=False):
            results = run_component_validations(
                {
                    "semantic-virtualization": "http://semantic.example.local",
                    "ai-model-hub": "http://ai.example.local",
                    "ontology-hub": "http://ontology.example.local",
                },
                experiment_dir="/tmp/fake-experiment",
            )

        self.assertEqual(calls, ["ontology-hub"])
        self.assertEqual([result["component"] for result in results], ["ontology-hub"])
        self.assertEqual(results[0]["status"], "failed")

    def test_playwright_max_failures_does_not_stop_component_sequence(self):
        calls = []

        def fake_runner(component, status):
            def _run(base_url, experiment_dir=None):
                calls.append(component)
                return {
                    "component": component,
                    "base_url": base_url,
                    "status": status,
                    "summary": {"total": 1, "passed": int(status == "passed"), "failed": int(status == "failed"), "skipped": 0},
                }

            return _run

        with mock.patch.dict(
            "validation.components.runner.COMPONENT_RUNNERS",
            {
                "ai-model-hub": fake_runner("ai-model-hub", "passed"),
                "ontology-hub": fake_runner("ontology-hub", "failed"),
                "semantic-virtualization": fake_runner("semantic-virtualization", "passed"),
            },
            clear=False,
        ), mock.patch.dict(os.environ, {"PLAYWRIGHT_MAX_FAILURES": "1"}, clear=False):
            results = run_component_validations(
                {
                    "semantic-virtualization": "http://semantic.example.local",
                    "ai-model-hub": "http://ai.example.local",
                    "ontology-hub": "http://ontology.example.local",
                },
                experiment_dir="/tmp/fake-experiment",
            )

        self.assertEqual(calls, ["ontology-hub", "ai-model-hub", "semantic-virtualization"])
        self.assertEqual(
            [result["component"] for result in results],
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
        )
        self.assertEqual(results[0]["status"], "failed")

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
