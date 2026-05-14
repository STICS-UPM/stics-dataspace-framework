import unittest

from validation.orchestration.suite_taxonomy import (
    classify_playwright_spec,
    classify_suite_artifact,
    summarize_group_taxonomy,
)


class Level6SuiteTaxonomyTests(unittest.TestCase):
    def test_classifies_inesdata_component_integration_specs(self):
        self.assertEqual(
            classify_playwright_spec("core/08-ontology-hub-inesdata-readonly.spec.ts"),
            {"audit_suite": "INESData integration", "audit_group": "Ontology Hub"},
        )
        self.assertEqual(
            classify_playwright_spec("core/09-ai-model-hub-httpdata.spec.ts"),
            {"audit_suite": "INESData integration", "audit_group": "AI Model Hub"},
        )
        self.assertEqual(
            classify_playwright_spec("core/07-semantic-virtualization-httpdata.spec.ts"),
            {"audit_suite": "INESData integration", "audit_group": "Semantic Virtualization"},
        )

    def test_classifies_component_owned_specs(self):
        self.assertEqual(
            classify_playwright_spec(
                "validation/components/ontology_hub/functional/specs/oh_app_00_home.spec.js"
            ),
            {"audit_suite": "Ontology Hub", "audit_group": "Functional"},
        )
        self.assertEqual(
            classify_playwright_spec(
                "validation/components/ai_model_hub/ui/specs/pt5_mh_01_catalog_access.spec.js"
            ),
            {"audit_suite": "AI Model Hub", "audit_group": "Functional"},
        )
        self.assertEqual(
            classify_playwright_spec(
                "validation/components/semantic_virtualization/ui/specs/sv_ui_02_mapping_editor.spec.js"
            ),
            {"audit_suite": "Semantic Virtualization", "audit_group": "Functional"},
        )

    def test_classifies_cross_dataspace_component_specs_as_inesdata_integration(self):
        self.assertEqual(
            classify_playwright_spec(
                "validation/components/ai_model_hub/ui/specs/pt5_mh_08_contract_negotiation.spec.js"
            ),
            {"audit_suite": "INESData integration", "audit_group": "AI Model Hub"},
        )

    def test_classifies_level6_support_artifacts(self):
        self.assertEqual(
            classify_suite_artifact(kind="newman", title="Newman", artifacts=["newman_results.json"]),
            {"audit_suite": "INESData integration", "audit_group": "Core API"},
        )
        self.assertEqual(
            classify_suite_artifact(kind="kafka", title="Kafka transfer", artifacts=["kafka_transfer_results.json"]),
            {"audit_suite": "INESData integration", "audit_group": "Kafka / streaming transfer"},
        )
        self.assertEqual(
            classify_suite_artifact(kind="une-0087", title="UNE 0087 alignment", artifacts=["une_0087_alignment.json"]),
            {"audit_suite": "Audit assurance", "audit_group": "UNE-0087"},
        )

    def test_summarizes_multiple_groups_without_losing_audit_suite(self):
        summary = summarize_group_taxonomy(
            [
                {"audit_suite": "INESData integration", "audit_group": "Core"},
                {"audit_suite": "INESData integration", "audit_group": "Ontology Hub"},
            ]
        )

        self.assertEqual(summary, {"audit_suite": "INESData integration", "audit_group": "2 groups"})


if __name__ == "__main__":
    unittest.main()
