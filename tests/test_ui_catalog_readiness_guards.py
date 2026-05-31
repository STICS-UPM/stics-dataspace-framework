import os
import unittest


VALIDATION_ROOT = os.path.dirname(os.path.dirname(__file__))
UI_ROOT = os.path.join(VALIDATION_ROOT, "validation", "ui")


def _read_ui_file(*parts):
    with open(os.path.join(UI_ROOT, *parts), "r", encoding="utf-8") as handle:
        return handle.read()


class ConsumerCatalogReadinessGuardsTests(unittest.TestCase):
    def test_provider_bootstrap_exposes_non_blocking_catalog_probe(self):
        source = _read_ui_file("shared", "utils", "provider-bootstrap.ts")

        self.assertIn("type CatalogDatasetReadinessProbe", source)
        self.assertIn("export async function probeConsumerCatalogDatasetReadiness(", source)
        self.assertIn('status: "ready"', source)
        self.assertIn('status: "timeout"', source)
        self.assertIn("error instanceof Error ? error.message : String(error)", source)

    def test_core_ui_specs_use_catalog_probe_instead_of_failing_before_ui_retries(self):
        expected_specs = [
            ("adapters", "inesdata", "specs", "04-consumer-catalog.spec.ts"),
            ("adapters", "inesdata", "specs", "05-consumer-negotiation.spec.ts"),
            ("adapters", "inesdata", "specs", "05-e2e-transfer-flow.spec.ts"),
            ("adapters", "inesdata", "specs", "06-consumer-transfer.spec.ts"),
            ("adapters", "inesdata", "specs", "07-semantic-virtualization-httpdata.spec.ts"),
            ("adapters", "inesdata", "specs", "09-ai-model-hub-httpdata.spec.ts"),
            ("adapters", "inesdata", "specs", "15-ai-model-external-execution.spec.ts"),
        ]

        for parts in expected_specs:
            source = _read_ui_file(*parts)
            self.assertIn("probeConsumerCatalogDatasetReadiness", source, "/".join(parts))
            self.assertNotIn("await waitForConsumerCatalogDatasetReadiness(", source, "/".join(parts))

    def test_dataspace_runtime_uses_shared_infrastructure_config_as_fallback(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn('"deployers", "infrastructure", "deployer.config"', source)
        self.assertIn("infrastructureConfig.KC_INTERNAL_URL", source)
        self.assertIn("infrastructureConfig.KC_URL", source)
        self.assertIn("infrastructureConfig.DS_DOMAIN_BASE", source)

    def test_dataspace_runtime_prefers_generated_public_access_urls(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn("public_access_urls", source)
        self.assertIn("access_urls", source)
        self.assertIn("connector_interface_login", source)
        self.assertIn("connector_management_api", source)
        self.assertIn("connector_protocol_api", source)
        self.assertIn("keycloak_realm", source)
        self.assertIn("keycloak_account", source)
        self.assertIn("publicKeycloakUrlFromConnectorCredentials", source)
        self.assertIn("DS_1_CONNECTORS", source)
        self.assertIn("DS_1_VALIDATION_PAIRS", source)
        self.assertIn("UI_CONNECTOR_PROTOCOL_ADDRESS_MODE", source)

    def test_vm_distributed_ui_runtime_uses_public_protocol_addresses_only_as_default(self):
        source = _read_ui_file("shared", "utils", "dataspace-runtime.ts")

        self.assertIn('topology === "vm-distributed"', source)
        self.assertIn('return "public"', source)
        self.assertIn("deployerConfig.UI_CONNECTOR_PROTOCOL_ADDRESS_MODE", source)
        self.assertIn("deployerConfig.CONNECTOR_PROTOCOL_ADDRESS_MODE", source)

    def test_ai_model_specs_build_model_urls_from_public_model_server_base(self):
        helper = _read_ui_file("shared", "utils", "model-server-url.ts")
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL", helper)
        self.assertIn("AI_MODEL_HUB_MODEL_SERVER_BASE_URL", helper)
        self.assertIn("UI_AI_MODEL_HUB_MODEL_SERVER_BASE_URL", helper)
        self.assertIn("VM_COMMON_HTTP_URL", helper)
        self.assertIn("UI_TOPOLOGY", helper)
        self.assertIn("vm-distributed", helper)
        self.assertIn("UI_DS_DOMAIN", helper)
        self.assertIn("org1.${domain}", helper)
        self.assertIn("model-server.${namespace}.svc.cluster.local", helper)

        expected_specs = [
            ("adapters", "inesdata", "specs", "09-ai-model-hub-httpdata.spec.ts"),
            ("adapters", "inesdata", "specs", "11-ai-model-browser.spec.ts"),
            ("adapters", "inesdata", "specs", "12-ai-model-execution.spec.ts"),
            ("adapters", "inesdata", "specs", "13-ai-model-benchmarking.spec.ts"),
            ("adapters", "inesdata", "specs", "15-ai-model-external-execution.spec.ts"),
        ]
        for parts in expected_specs:
            source = _read_ui_file(*parts)
            self.assertIn("modelServerUrlForPath", source, "/".join(parts))

    def test_inesdata_playwright_suite_includes_minio_ops_by_default(self):
        source = _read_ui_file("playwright.inesdata.config.ts")

        self.assertIn("UI_MINIO_OPS_DEMO", source)
        self.assertIn("adapters/inesdata/specs/06b-minio-bucket-visibility.spec.ts", source)

    def test_provider_bootstrap_publishes_storage_type_metadata(self):
        source = _read_ui_file("shared", "utils", "provider-bootstrap.ts")

        self.assertIn("const dataAddress =", source)
        self.assertIn("const dataAddressType =", source)
        self.assertIn("const storageMetadata =", source)
        self.assertIn('edc: "https://w3id.org/edc/v0.0.1/ns/"', source)
        self.assertIn("storageType: dataAddressType", source)
        self.assertIn('"edc:dataAddressType": dataAddressType', source)
        self.assertIn('"https://w3id.org/edc/v0.0.1/ns/dataAddressType": dataAddressType', source)
        self.assertIn("...storageMetadata", source)
        self.assertIn("...(options.properties || {})", source)


if __name__ == "__main__":
    unittest.main()
