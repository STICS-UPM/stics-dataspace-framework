import unittest
from unittest import mock

from validation.orchestration import components


class Level6ComponentsTests(unittest.TestCase):
    def test_configured_optional_components_normalizes_names(self):
        configured = components.configured_optional_components(
            {"COMPONENTS": "ontology_hub, ai-model-hub, semantic_virtualization"}
        )

        self.assertEqual(
            configured,
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
        )

    def test_should_run_component_validation_defaults_true_when_components_exist(self):
        self.assertTrue(
            components.should_run_component_validation(
                ["ontology-hub"],
                env={},
                env_flag_enabled=mock.Mock(return_value=False),
            )
        )

    def test_should_run_component_validation_honors_env_override(self):
        flag_enabled = mock.Mock(return_value=False)

        enabled = components.should_run_component_validation(
            ["ontology-hub"],
            env={"LEVEL6_RUN_COMPONENT_VALIDATION": "false"},
            env_flag_enabled=flag_enabled,
        )

        self.assertFalse(enabled)
        flag_enabled.assert_called_once_with("LEVEL6_RUN_COMPONENT_VALIDATION", True)

    def test_run_component_validations_marks_missing_component_as_skipped(self):
        results = components.run_component_validations(
            ["ontology-hub", "ai-model-hub"],
            infer_component_urls=mock.Mock(return_value={"ontology-hub": "http://ontology"}),
            run_component_validations_fn=mock.Mock(
                return_value=[
                    {
                        "component": "ontology-hub",
                        "status": "passed",
                    }
                ]
            ),
            experiment_dir="/tmp/experiment",
        )

        self.assertEqual(results[0]["component"], "ontology-hub")
        self.assertEqual(results[1]["component"], "ai-model-hub")
        self.assertEqual(results[1]["status"], "skipped")
        self.assertEqual(results[1]["reason"], "component_url_not_inferred")


if __name__ == "__main__":
    unittest.main()
