import tempfile
import unittest
from pathlib import Path

from validation.components.semantic_virtualization.gtfs_bench_mini import (
    DEFAULT_FIXTURE_DIR,
    DEFAULT_SOURCE_DIR,
    EXPECTED_CSV_FILES,
    GTFS_HEADERS,
    PRIMARY_TRIP_ID,
    RELATED_TRIP_ID,
    generate_gtfs_bench_official_mini_fixture,
    parse_insert_rows,
    run_gtfs_bench_official_mini_validation,
    validate_gtfs_bench_official_mini_fixture,
)


class SemanticVirtualizationGtfsBenchMiniFixtureTests(unittest.TestCase):
    def test_committed_official_mini_fixture_is_valid(self):
        result = validate_gtfs_bench_official_mini_fixture()

        self.assertEqual(result["status"], "passed", result.get("assertions"))
        self.assertEqual(result["dataset_name"], "GTFS-Bench-official-mini")
        self.assertEqual(set(result["csv_summaries"]), set(GTFS_HEADERS))
        for csv_file in EXPECTED_CSV_FILES:
            self.assertTrue((DEFAULT_FIXTURE_DIR / "csv" / csv_file).is_file(), csv_file)

        selection = result["selection"]
        self.assertEqual(selection["primaryTripId"], PRIMARY_TRIP_ID)
        self.assertEqual(selection["relatedTripId"], RELATED_TRIP_ID)
        self.assertGreaterEqual(selection["recordCounts"]["STOPS"], 10)
        self.assertGreaterEqual(selection["recordCounts"]["STOP_TIMES"], 12)
        self.assertGreaterEqual(selection["recordCounts"]["SHAPES"], 16)

    def test_report_runner_records_sv_gtfs_bench_02(self):
        report = run_gtfs_bench_official_mini_validation()

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["test_cases"][0]["test_case_id"], "SV-GTFS-BENCH-02")
        self.assertEqual(report["test_cases"][0]["coverage_status"], "automated")


@unittest.skipUnless(
    DEFAULT_SOURCE_DIR.is_dir(),
    "Official gtfs-bench source clone is not available in adapters/inesdata/sources/gtfs-bench",
)
class SemanticVirtualizationGtfsBenchMiniRegenerationTests(unittest.TestCase):
    def test_parser_reads_multiple_insert_statements_for_shapes(self):
        dump_path = DEFAULT_SOURCE_DIR / "generation" / "mysql_data" / "dump-gtfs-new.sql"
        shape_rows = parse_insert_rows(dump_path, "SHAPES")
        shape_ids = {row["shape_id"] for row in shape_rows}

        self.assertIn("4__1____1__IT_1", shape_ids)
        self.assertIn("4__1____2__IT_1", shape_ids)

    def test_can_regenerate_mini_fixture_to_temp_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir) / "gtfs-bench-official-mini"
            result = generate_gtfs_bench_official_mini_fixture(fixture_dir=fixture_dir)

            self.assertEqual(result["status"], "passed", result.get("assertions"))
            self.assertTrue((fixture_dir / "manifest.json").is_file())
            self.assertTrue((fixture_dir / "references" / "simple-q1.rq").is_file())
            self.assertTrue((fixture_dir / "references" / "full-q1.rq").is_file())
            self.assertGreaterEqual(result["selection"]["recordCounts"]["SHAPES"], 16)


if __name__ == "__main__":
    unittest.main()
