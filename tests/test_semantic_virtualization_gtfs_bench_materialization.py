import tempfile
import unittest
from pathlib import Path

from rdflib import Graph

from validation.components.semantic_virtualization.gtfs_bench_materialization import (
    adapt_official_csv_mapping,
    materialize_gtfs_bench_official_mini_graph,
    run_gtfs_bench_official_materialization_validation,
    validate_gtfs_bench_official_materialization,
)


class SemanticVirtualizationGtfsBenchMaterializationTests(unittest.TestCase):
    def test_official_csv_mapping_can_be_adapted_to_mini_fixture(self):
        result = adapt_official_csv_mapping()

        self.assertEqual(result["status"], "passed", result.get("assertions"))
        self.assertEqual(result["triples_map_count"], 13)
        self.assertEqual(len(result["source_rewrites"]), 10)
        self.assertEqual(result["source_rewrites"]["/data/SHAPES.csv"], "csv/SHAPES.csv")
        self.assertTrue(result["adapted_mapping_sha256"])

    def test_mini_fixture_materializes_queryable_gtfs_graph(self):
        graph, summary = materialize_gtfs_bench_official_mini_graph()

        self.assertGreater(summary["triple_count"], 300)
        self.assertEqual(summary["shape_count"], 2)
        self.assertEqual(summary["shape_point_count"], 16)
        self.assertEqual(summary["trip_count"], 2)
        self.assertEqual(summary["stop_time_count"], 12)
        self.assertGreater(len(graph), summary["shape_point_count"])

    def test_materialization_validation_runs_official_q1_queries(self):
        result = validate_gtfs_bench_official_materialization()

        self.assertEqual(result["status"], "passed", result.get("assertions"))
        self.assertEqual(result["queries"]["simple_q1"]["row_count"], 16)
        self.assertEqual(result["queries"]["full_q1"]["row_count"], 16)
        self.assertEqual(result["queries"]["route_trip_stop_join_probe"]["row_count"], 12)
        self.assertEqual(result["materialization"]["shape_point_count"], 16)

    def test_runner_persists_report_graph_and_adapted_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_gtfs_bench_official_materialization_validation(experiment_dir=tmpdir)

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["summary"], {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
            self.assertEqual(report["test_cases"][0]["test_case_id"], "SV-GTFS-BENCH-03")

            report_path = Path(report["artifacts"]["report_json"])
            graph_path = Path(report["artifacts"]["materialized_graph"])
            adapted_mapping_path = Path(report["artifacts"]["adapted_mapping"])
            self.assertTrue(report_path.is_file())
            self.assertTrue(graph_path.is_file())
            self.assertTrue(adapted_mapping_path.is_file())

            graph = Graph()
            graph.parse(graph_path, format="turtle")
            self.assertGreater(len(graph), 300)


if __name__ == "__main__":
    unittest.main()
