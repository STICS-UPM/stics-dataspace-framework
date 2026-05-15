import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.dataset_test_helpers import create_gtfs_source
from validation.components.ai_model_hub.virtualization_traceability import (
    build_vs_ai_model_hub_traceability,
)
from validation.components.semantic_virtualization.dataspace_integration import (
    load_gtfs_madrid_bench_context,
)


class VSAIModelHubTraceabilityTests(unittest.TestCase):
    def _semantic_report(self, source_dir, digest=None, status="passed"):
        context = load_gtfs_madrid_bench_context(str(source_dir))
        expected_digest = digest or context["asset_summary"]["expected_outputs_digest"]
        return {
            "component": "semantic-virtualization",
            "suite": "dataspace-integration",
            "test_case_id": "INT-VS-DS-01",
            "status": status,
            "summary": {"total": 11, "passed": 11, "failed": 0, "skipped": 0},
            "integration_context": context,
            "created_entities": {
                "asset_id": "asset-e2e-sv-test",
                "agreement_id": "agreement-test",
                "transfer_id": "transfer-test",
            },
            "asset_payload": {
                "properties": {
                    "assetType": "semantic-virtualization-mobility-output",
                    "dcat:keyword": [
                        "validation",
                        "semantic-virtualization",
                        "HttpData",
                        "A5.2",
                        "GTFS-Madrid-Bench",
                        "mobility",
                        "gtfs",
                        "MH-MOB-01",
                    ],
                    "daimo:sourceDataset": "GTFS-Madrid-Bench",
                    "daimo:expectedOutputsDigest": expected_digest,
                }
            },
        }

    def test_traceability_passes_when_semantic_report_matches_ai_model_hub_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            semantic_report_path = Path(tmpdir) / "semantic_report.json"
            semantic_report_path.write_text(json.dumps(self._semantic_report(source_dir)), encoding="utf-8")

            result = build_vs_ai_model_hub_traceability(
                semantic_report_path=semantic_report_path,
                experiment_dir=tmpdir,
                source_dir=str(source_dir),
            )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["test_case_id"], "INT-VS-AMH-01")
            self.assertIn("MH-MOB-01", result["linked_cases"])
            self.assertEqual(result["summary"]["failed"], 0)
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertEqual(result["dataset"]["name"], "GTFS-Madrid-Bench")
            self.assertEqual(
                result["semantic_virtualization_evidence"]["asset_properties"]["daimo:sourceDataset"],
                "GTFS-Madrid-Bench",
            )

    def test_traceability_fails_when_expected_outputs_digest_differs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            semantic_report_path = Path(tmpdir) / "semantic_report.json"
            semantic_report_path.write_text(
                json.dumps(self._semantic_report(source_dir, digest="0" * 64)),
                encoding="utf-8",
            )

            result = build_vs_ai_model_hub_traceability(
                semantic_report_path=semantic_report_path,
                experiment_dir=tmpdir,
                source_dir=str(source_dir),
            )

            self.assertEqual(result["status"], "failed")
            failed_checks = [check["name"] for check in result["checks"] if check["status"] == "failed"]
            self.assertIn("expected_outputs_digest_matches_ai_model_hub_dataset", failed_checks)


if __name__ == "__main__":
    unittest.main()
