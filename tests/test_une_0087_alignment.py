import json
import tempfile
import unittest
from pathlib import Path

from framework.reporting.une_0087_alignment import (
    build_une_0087_alignment,
    write_une_0087_alignment,
)


class Une0087AlignmentTests(unittest.TestCase):
    def _write_json(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_builds_non_certifying_alignment_from_experiment_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment = root / "experiments" / "experiment_2026-05-04_15-44-46"
            self._write_json(
                experiment / "metadata.json",
                {
                    "topology": "vm-single",
                    "cluster": "k3s",
                    "architecture": "INESData dataspace connectors",
                },
            )
            self._write_json(
                experiment / "newman_results.json",
                [
                    {
                        "checks": [
                            {"name": "consumer catalog returns DCAT assets", "ok": True},
                            {"name": "contract negotiation finalized before transfer", "ok": True},
                        ]
                    }
                ],
            )
            self._write_json(
                experiment / "kafka_transfer_results.json",
                [
                    {
                        "status": "passed",
                        "metrics": {"average_latency_ms": 12.0},
                        "traceability": "transfer between provider and consumer connector",
                    }
                ],
            )
            self._write_json(
                experiment / "components" / "ai-model-hub" / "ai_model_hub_component_validation.json",
                {
                    "component": "ai-model-hub",
                    "summary": {"passed": 4},
                    "details": "model catalog publication and discovery via API",
                },
            )
            traceability = root / "extra" / "vs_ai_model_hub_mobility_traceability.json"
            self._write_json(
                traceability,
                {
                    "case_id": "INT-VS-AMH-01",
                    "status": "passed",
                    "gtfs": "semantic virtualization RDF SPARQL API infer no_jwt_or_bearer finalized",
                },
            )

            alignment = build_une_0087_alignment(
                experiment,
                additional_evidence_paths=[traceability],
                include_project_context=False,
                project_root=root,
            )

        criteria = {item["id"]: item for item in alignment["criteria"]}
        self.assertEqual(alignment["assessment_type"], "non_certifying_alignment")
        self.assertFalse(alignment["certification_claim"])
        self.assertEqual(alignment["summary"]["total_criteria"], 23)
        self.assertEqual(criteria["Int.1"]["status"], "covered")
        self.assertEqual(criteria["Int.4"]["status"], "covered")
        self.assertEqual(criteria["Fun.4"]["status"], "covered")
        self.assertEqual(criteria["Neg.3"]["status"], "not_covered")
        self.assertGreater(criteria["Tec.5"]["evidence_count"], 0)

    def test_writes_json_and_markdown_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment = root / "experiments" / "experiment_1"
            self._write_json(experiment / "metadata.json", {"topology": "vm-single"})

            alignment = write_une_0087_alignment(
                experiment,
                include_project_context=False,
                project_root=root,
            )

            json_path = experiment / "une_0087_alignment.json"
            md_path = experiment / "une_0087_alignment.md"
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["schema_version"], "1.0")
            self.assertIn("UNE 0087 Alignment", md_path.read_text(encoding="utf-8"))
            self.assertEqual(alignment["summary"]["total_criteria"], 23)

    def test_regeneration_does_not_use_previous_alignment_as_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment = root / "experiments" / "experiment_1"
            self._write_json(experiment / "metadata.json", {"topology": "vm-single"})

            write_une_0087_alignment(
                experiment,
                include_project_context=False,
                project_root=root,
            )
            alignment = write_une_0087_alignment(
                experiment,
                include_project_context=False,
                project_root=root,
            )

        criteria = {item["id"]: item for item in alignment["criteria"]}
        self.assertEqual(criteria["Neg.3"]["status"], "not_covered")
        self.assertEqual(criteria["Gob.1"]["status"], "not_covered")


if __name__ == "__main__":
    unittest.main()
