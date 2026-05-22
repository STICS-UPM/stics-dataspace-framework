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


if __name__ == "__main__":
    unittest.main()
