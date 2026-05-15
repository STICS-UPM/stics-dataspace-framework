import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.components import (
    COMPONENT_CONTRACTS,
    build_component_preview,
    component_validation_groups,
    component_values_file_candidates,
    components_for_adapter,
    configured_component_host,
    configured_optional_components,
    get_component_contract,
    infer_component_hostname,
    required_connector_extensions_for_adapter,
    resolve_component_release_name,
    summarize_components_for_adapter,
)


class SharedComponentsContractTests(unittest.TestCase):
    def test_configured_optional_components_normalizes_and_deduplicates(self):
        configured = configured_optional_components(
            {
                "COMPONENTS": "ontology_hub, ai-model-hub, semantic_virtualization, ontology-hub",
            }
        )

        self.assertEqual(
            configured,
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
        )

    def test_component_contract_tracks_supported_and_deployable_adapters(self):
        ontology = get_component_contract("ontology-hub")
        ai_model_hub = get_component_contract("ai_model_hub")

        self.assertEqual(ontology.supported_adapters, ("inesdata", "edc"))
        self.assertEqual(ontology.deployable_adapters, ("inesdata", "edc"))
        self.assertEqual(ai_model_hub.supported_adapters, ("inesdata", "edc"))
        self.assertEqual(ai_model_hub.deployable_adapters, ("inesdata", "edc"))
        semantic_virtualization = get_component_contract("semantic_virtualization")
        self.assertEqual(semantic_virtualization.supported_adapters, ("inesdata", "edc"))
        self.assertEqual(semantic_virtualization.deployable_adapters, ("inesdata", "edc"))
        self.assertIn("semantic-virtualization", COMPONENT_CONTRACTS)

    def test_components_for_adapter_filters_by_current_deployable_runtime(self):
        config = {
            "COMPONENTS": "ontology-hub,ai-model-hub,semantic-virtualization",
        }

        self.assertEqual(
            components_for_adapter(config, "inesdata", deployable_only=True),
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
        )
        self.assertEqual(
            components_for_adapter(config, "edc", deployable_only=True),
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
        )
        self.assertEqual(
            components_for_adapter(config, "edc", deployable_only=False),
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
        )

    def test_component_validation_groups_follow_registered_contract(self):
        groups = component_validation_groups(
            ["ontology-hub", "ai-model-hub", "semantic-virtualization", "ontology-hub"]
        )

        self.assertEqual(groups, ["ontology-hub", "ai-model-hub", "semantic-virtualization"])

    def test_summarize_components_for_adapter_separates_pending_support(self):
        summary = summarize_components_for_adapter(
            {"COMPONENTS": "ontology-hub,ai-model-hub,semantic-virtualization"},
            "edc",
        )

        self.assertEqual(summary["configured"], ["ontology-hub", "ai-model-hub", "semantic-virtualization"])
        self.assertEqual(summary["deployable"], ["ontology-hub", "ai-model-hub", "semantic-virtualization"])
        self.assertEqual(summary["pending_support"], [])
        self.assertEqual(summary["unsupported"], [])
        self.assertEqual(summary["unknown"], [])

    def test_required_connector_extensions_for_edc_are_component_specific(self):
        required = required_connector_extensions_for_adapter(
            ["ontology-hub", "ai-model-hub", "semantic-virtualization"],
            "edc",
        )

        self.assertEqual(
            required,
            [
                "com.pionera.assetfilter.filter.AssetFilterExtension",
                "com.pionera.assetfilter.observability.ObservabilityExtension",
                "com.pionera.assetfilter.infer.InferenceExtension",
                "com.pionera.assetfilter.contracts.ContractSequenceExtension",
                "com.pionera.assetfilter.proxy.CustomProxyDataPlaneExtension",
            ],
        )
        self.assertEqual(
            required_connector_extensions_for_adapter(["ai-model-hub"], "inesdata"),
            [],
        )

    def test_component_values_file_candidates_follow_expected_precedence(self):
        candidates = component_values_file_candidates("/tmp/chart", "demo", "demo-provider")

        self.assertEqual(
            candidates,
            [
                "/tmp/chart/values-demo.yaml",
                "/tmp/chart/values-demo-provider.yaml",
                "/tmp/chart/values.yaml",
            ],
        )

    def test_configured_component_host_derives_ontology_hub_host_from_dataspace_domain(self):
        host = configured_component_host(
            "ontology-hub",
            {"DS_DOMAIN_BASE": "custom.ds.example.org"},
            dataspace_name="demo",
        )

        self.assertEqual(host, "ontology-hub-demo.custom.ds.example.org")

    def test_configured_component_host_derives_ai_model_hub_host_from_dataspace_domain(self):
        host = configured_component_host(
            "ai-model-hub",
            {"DS_DOMAIN_BASE": "custom.ds.example.org"},
            dataspace_name="demo",
        )

        self.assertEqual(host, "ai-model-hub-demo.custom.ds.example.org")

    def test_configured_component_host_derives_semantic_virtualization_host_from_dataspace_domain(self):
        host = configured_component_host(
            "semantic-virtualization",
            {"DS_DOMAIN_BASE": "custom.ds.example.org"},
            dataspace_name="demo",
        )

        self.assertEqual(host, "semantic-virtualization-demo.custom.ds.example.org")

    def test_infer_component_hostname_prefers_configured_host_over_chart_values(self):
        host = infer_component_hostname(
            "ontology-hub",
            {
                "ingress": {
                    "enabled": True,
                    "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                }
            },
            {"DS_DOMAIN_BASE": "custom.ds.example.org"},
            dataspace_name="demo",
        )

        self.assertEqual(host, "ontology-hub-demo.custom.ds.example.org")

    def test_infer_component_hostname_falls_back_to_enabled_ingress_host(self):
        host = infer_component_hostname(
            "ai-model-hub",
            {
                "ingress": {
                    "enabled": True,
                    "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                }
            },
            {},
            dataspace_name="demo",
        )

        self.assertEqual(host, "ai-model-hub-demo.dev.ds.dataspaceunit.upm")

    def test_resolve_component_release_name_follows_dataspace_convention(self):
        self.assertEqual(
            resolve_component_release_name("ontology-hub", dataspace_name="demo"),
            "demo-ontology-hub",
        )
        self.assertEqual(
            resolve_component_release_name(
                "registration-service",
                dataspace_name="demo",
                registration_service_release_name="demo-dataspace-rs",
            ),
            "demo-dataspace-rs",
        )
        self.assertEqual(
            resolve_component_release_name("public-portal", dataspace_name="demo"),
            "demo-dataspace-pp",
        )

    def test_build_component_preview_marks_deployable_and_pending_components(self):
        preview = build_component_preview(
            configured=["ontology-hub", "ai-model-hub"],
            deployable=["ontology-hub"],
            pending_support=["ai-model-hub"],
            unsupported=[],
            unknown=[],
            inferred_urls={"ontology-hub": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm"},
        )

        self.assertEqual(preview["status"], "planned")
        self.assertEqual(preview["action"], "deploy_components")
        self.assertEqual(
            preview["components"],
            [
                {
                    "name": "ontology-hub",
                    "url": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    "status": "planned",
                },
                {
                    "name": "ai-model-hub",
                    "url": None,
                    "status": "pending-support",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
