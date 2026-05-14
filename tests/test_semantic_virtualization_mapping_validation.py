import os
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph

from validation.components.semantic_virtualization.mapping_validation import (
    DEFAULT_FIXTURE_DIR,
    execute_sparql_fixture_query,
    evaluate_mapping_generation_methods,
    run_semantic_virtualization_mapping_validation,
    validate_mapping_artifact,
)


class SemanticVirtualizationMappingValidationTests(unittest.TestCase):
    def test_valid_fixture_mapping_references_sources_and_ontology_terms(self):
        mapping_path = DEFAULT_FIXTURE_DIR / "mappings" / "mobility_stops_csv.rml.ttl"

        result = validate_mapping_artifact(mapping_path)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["source_formats"], ["csv"])
        self.assertTrue(result["source_references"][0]["exists"])
        self.assertTrue(any(term.endswith("#Stop") for term in result["ontology_terms"]))
        self.assertTrue(any(term.endswith("#hasStopName") for term in result["ontology_terms"]))

    def test_invalid_fixture_mapping_is_rejected_with_actionable_diagnostics(self):
        mapping_path = DEFAULT_FIXTURE_DIR / "mappings" / "invalid_missing_source.rml.ttl"

        result = validate_mapping_artifact(mapping_path)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("missing source file" in item for item in result["assertions"]))
        self.assertTrue(any("ontology term not loaded" in item for item in result["assertions"]))

    def test_sparql_fixture_query_joins_routes_and_stops(self):
        query_path = DEFAULT_FIXTURE_DIR / "queries" / "multisource_routes_stops.rq"

        result = execute_sparql_fixture_query(query_path)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["row_count"], 2)
        self.assertIn({"routeName": "C4", "stopName": "Atocha"}, result["rows"])
        self.assertIn({"routeName": "ML4", "stopName": "Parla Centro"}, result["rows"])

    def test_mapping_generation_methods_are_compared_with_scores(self):
        result = evaluate_mapping_generation_methods()

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["method_count"], 3)
        self.assertEqual(result["approach_count"], 2)
        self.assertEqual(result["passed_method_count"], 3)
        self.assertEqual(
            {method["expected_source_format"] for method in result["methods"]},
            {"csv", "json", "relational"},
        )
        self.assertTrue(all(method["score"] >= method["expected_min_score"] for method in result["methods"]))

    def test_run_mapping_validation_persists_report_and_standard_exports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_semantic_virtualization_mapping_validation(experiment_dir=tmpdir)

            self.assertEqual(result["component"], "semantic-virtualization")
            self.assertEqual(result["suite"], "mapping-fixtures")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"], {"total": 7, "passed": 7, "failed": 0, "skipped": 0})
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))

            exported_paths = [
                path for name, path in result["artifacts"].items()
                if name.startswith("exported-")
            ]
            self.assertEqual(len(exported_paths), 4)
            for exported_path in exported_paths:
                self.assertTrue(Path(exported_path).name.endswith(".ttl"))
                graph = Graph()
                graph.parse(exported_path, format="turtle")
                self.assertGreater(len(graph), 0)

            case_ids = {case["test_case_id"] for case in result["test_cases"]}
            self.assertEqual(
                case_ids,
                {
                    "PT5-VS-01",
                    "PT5-VS-03",
                    "PT5-VS-04",
                    "PT5-VS-05",
                    "PT5-VS-06",
                    "PT5-VS-09",
                    "PT5-VS-10",
                },
            )


if __name__ == "__main__":
    unittest.main()
