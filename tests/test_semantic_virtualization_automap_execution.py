import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from validation.components.semantic_virtualization.automap_execution import (
    TEST_CASE_ID,
    run_automap_deterministic_execution_validation,
    validate_automap_deterministic_execution,
)


class SemanticVirtualizationAutomapExecutionTests(unittest.TestCase):
    def _create_minimal_automap_source(self, root: Path) -> None:
        (root / "tools").mkdir(parents=True)
        (root / "evaluation").mkdir(parents=True)
        (root / "tools" / "rml_tools.py").write_text(
            textwrap.dedent(
                """
                import csv

                def get_csv_schema(path):
                    with open(path, newline="", encoding="utf-8") as handle:
                        reader = csv.DictReader(handle)
                        sample = []
                        for row in reader:
                            sample.append(row)
                            if len(sample) == 3:
                                break
                    return {"columns": reader.fieldnames or [], "sample": sample}

                def get_ontology_subgraph(path, keywords):
                    return (
                        "Class: <https://pionera.example/ontology/mobility#Stop>\\n"
                        "DatatypeProperty: stopName\\n"
                        "DatatypeProperty: latitude\\n"
                        "DatatypeProperty: longitude\\n"
                        "Class: <https://w3id.org/pionera/validation/mobility#Stop>\\n"
                        "DatatypeProperty: hasStopName\\n"
                        "DatatypeProperty: hasLatitude\\n"
                        "DatatypeProperty: hasLongitude"
                    )
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (root / "evaluation" / "metrics.py").write_text(
            textwrap.dedent(
                """
                def evaluate(levels, pipeline_result, gold_kg_path=None):
                    return {
                        "L2_skipped": False,
                        "L2_norm_triple_precision": 1.0,
                        "L2_norm_triple_recall": 1.0,
                        "L2_norm_triple_f1": 1.0,
                        "L2_predicate_f1": 1.0,
                        "L2_class_f1": 1.0,
                        "L3_skipped": False,
                        "L3_columns_mapped_yarrrml": 4,
                        "L3_columns_missing_yarrrml": [],
                    }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

    def test_validate_automap_deterministic_execution_passes_with_expected_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "automap"
            source_dir.mkdir()
            self._create_minimal_automap_source(source_dir)
            output_dir = Path(tmpdir) / "output"

            result = validate_automap_deterministic_execution(
                source_dir,
                output_dir=output_dir,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["assertions"], [])
        self.assertEqual(result["schema"]["columns"], ["stop_id", "stop_name", "lat", "lon"])
        self.assertEqual(result["materialization"]["triples"], 12)
        self.assertTrue(result["sparql"]["passed"])
        self.assertEqual(result["ontology_hub_reuse"]["status"], "passed")
        self.assertTrue(result["ontology_hub_reuse"]["sparql"]["passed"])
        self.assertIn("PT5-OH-07", result["ontology_hub_reuse"]["linked_cases"])
        self.assertEqual(
            result["secret_policy"],
            "No environment files, API keys or remote LLM endpoints are read by this validation.",
        )

    def test_validate_automap_deterministic_execution_fails_when_source_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_automap_deterministic_execution(
                Path(tmpdir) / "missing-automap",
                output_dir=Path(tmpdir) / "output",
            )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("not available locally" in item for item in result["assertions"]))

    def test_run_automap_deterministic_execution_validation_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "automap"
            source_dir.mkdir()
            self._create_minimal_automap_source(source_dir)
            experiment_dir = Path(tmpdir) / "experiment"

            report = run_automap_deterministic_execution_validation(
                experiment_dir=experiment_dir,
                source_dir=source_dir,
            )

            report_path = report["artifacts"]["report_json"]
            metrics_path = report["artifacts"]["metrics_json"]
            generated_kg = report["artifacts"]["generated_kg"]
            self.assertTrue(os.path.exists(report_path))
            self.assertTrue(os.path.exists(metrics_path))
            self.assertTrue(os.path.exists(generated_kg))
            self.assertEqual(report["summary"], {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
            self.assertEqual(report["pt5_case_results"][0]["test_case_id"], TEST_CASE_ID)
            self.assertIn("INT-VS-OH-01", report["pt5_case_results"][0]["linked_cases"])


if __name__ == "__main__":
    unittest.main()
