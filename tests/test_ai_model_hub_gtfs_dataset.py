import tempfile
import unittest

from tests.dataset_test_helpers import create_gtfs_source
from validation.components.ai_model_hub.mobility_benchmarking_api import load_gtfs_mobility_fixture


class AIModelHubGtfsDatasetTests(unittest.TestCase):
    def test_gtfs_source_dataset_builds_mobility_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            fixture = load_gtfs_mobility_fixture(str(source_dir))

        self.assertEqual(fixture["metadata"]["datasetName"], "GTFS-Madrid-Bench")
        self.assertEqual(fixture["metadata"]["domain"], "mobility")
        self.assertEqual(fixture["context"]["dataset_name"], "GTFS-Madrid-Bench")
        self.assertEqual(fixture["context"]["join_keys"], ["route_id", "trip_id", "stop_id"])
        self.assertIn("transfer_benchmark_cases", fixture["sample"])
        self.assertIn("transferCases", fixture["expected_outputs"]["benchmark_sample"])

    def test_gtfs_references_are_resolvable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            sample = load_gtfs_mobility_fixture(str(source_dir))["sample"]

        stop_ids = {row["stop_id"] for row in sample["stops"]}
        route_ids = {row["route_id"] for row in sample["routes"]}
        trip_ids = {row["trip_id"] for row in sample["trips"]}
        trip_route_ids = {row["trip_id"]: row["route_id"] for row in sample["trips"]}

        self.assertTrue({row["route_id"] for row in sample["trips"]}.issubset(route_ids))
        self.assertTrue({row["trip_id"] for row in sample["stop_times"]}.issubset(trip_ids))
        self.assertTrue({row["stop_id"] for row in sample["stop_times"]}.issubset(stop_ids))

        for case in sample["transfer_benchmark_cases"]:
            self.assertIn(case["origin_stop_id"], stop_ids)
            self.assertIn(case["destination_stop_id"], stop_ids)
            self.assertIn(case["expected_route_id"], route_ids)
            self.assertIn(case["expected_trip_id"], trip_ids)
            self.assertEqual(trip_route_ids[case["expected_trip_id"]], case["expected_route_id"])


if __name__ == "__main__":
    unittest.main()
