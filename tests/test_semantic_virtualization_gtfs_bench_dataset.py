import tempfile
import unittest
from pathlib import Path

from tests.dataset_test_helpers import create_gtfs_source
from validation.components.semantic_virtualization.gtfs_bench_dataset import (
    EXPECTED_CSV_FILES,
    GTFS_HEADERS,
    PRIMARY_TRIP_ID,
    RELATED_TRIP_ID,
    build_gtfs_bench_official_sample,
    parse_insert_rows,
    run_gtfs_bench_official_dataset_validation,
    validate_gtfs_bench_official_dataset_sample,
    write_gtfs_bench_runtime_sample_csvs,
)


class SemanticVirtualizationGtfsBenchDatasetTests(unittest.TestCase):
    def test_source_derived_runtime_sample_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            result = validate_gtfs_bench_official_dataset_sample(source_dir)

        self.assertEqual(result["status"], "passed", result.get("assertions"))
        self.assertEqual(result["dataset_name"], "GTFS-Madrid-Bench")
        selection = result["selection"]
        self.assertEqual(selection["primaryTripId"], PRIMARY_TRIP_ID)
        self.assertEqual(selection["relatedTripId"], RELATED_TRIP_ID)
        self.assertGreaterEqual(selection["recordCounts"]["STOPS"], 10)
        self.assertGreaterEqual(selection["recordCounts"]["STOP_TIMES"], 12)
        self.assertGreaterEqual(selection["recordCounts"]["SHAPES"], 16)

    def test_report_runner_records_sv_gtfs_bench_02(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            report = run_gtfs_bench_official_dataset_validation(source_dir=source_dir)

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["test_cases"][0]["test_case_id"], "SV-GTFS-BENCH-02")
        self.assertEqual(report["test_cases"][0]["coverage_status"], "automated")

    def test_parser_reads_multiple_insert_statements_for_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            dump_path = source_dir / "generation" / "mysql_data" / "dump-gtfs-new.sql"
            shape_rows = parse_insert_rows(dump_path, "SHAPES")
            shape_ids = {row["shape_id"] for row in shape_rows}

        self.assertIn("4__1____1__IT_1", shape_ids)
        self.assertIn("4__1____2__IT_1", shape_ids)

    def test_can_write_runtime_sample_csvs_to_experiment_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            sample = build_gtfs_bench_official_sample(source_dir)
            output_dir = Path(tmpdir) / "runtime-sample-csv"
            written = write_gtfs_bench_runtime_sample_csvs(sample, output_dir)

            self.assertEqual(set(written), set(GTFS_HEADERS))
            for csv_file in EXPECTED_CSV_FILES:
                self.assertTrue((output_dir / csv_file).is_file(), csv_file)


if __name__ == "__main__":
    unittest.main()
