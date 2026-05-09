import unittest

from validation.components.semantic_virtualization.gtfs_bench_official import (
    DEFAULT_SOURCE_DIR,
    GTFS_BENCH_REPOSITORY,
    validate_gtfs_bench_official_source,
)


@unittest.skipUnless(
    DEFAULT_SOURCE_DIR.is_dir(),
    "Official gtfs-bench source clone is not available in adapters/inesdata/sources/gtfs-bench",
)
class SemanticVirtualizationGtfsBenchOfficialTests(unittest.TestCase):
    def test_official_gtfs_bench_source_resources_are_ready(self):
        result = validate_gtfs_bench_official_source()

        self.assertEqual(result["status"], "passed", result.get("assertions"))
        self.assertEqual(result["repository"], GTFS_BENCH_REPOSITORY)
        self.assertIn("gtfs-bench", result["source_dir"])
        self.assertGreater(result["ontology"]["triple_count"], 0)
        self.assertGreater(result["csv_mapping"]["triples_map_count"], 0)
        self.assertGreaterEqual(result["queries"]["simple_query_count"], 11)
        self.assertGreaterEqual(result["queries"]["full_query_count"], 18)
        self.assertIn("/data/STOPS.csv", result["csv_mapping"]["detected_sources"])
        self.assertIn("/data/STOP_TIMES.csv", result["csv_mapping"]["detected_sources"])


if __name__ == "__main__":
    unittest.main()
