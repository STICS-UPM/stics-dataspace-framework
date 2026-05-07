import json
import unittest
from datetime import datetime
from pathlib import Path


class AIModelHubGtfsFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture_dir = (
            Path(__file__).resolve().parents[1]
            / "validation"
            / "components"
            / "ai_model_hub"
            / "fixtures"
            / "datasets"
            / "mobility"
            / "gtfs-madrid-bench-mini"
        )

    def _read_json(self, name):
        return json.loads((self.fixture_dir / name).read_text(encoding="utf-8"))

    def test_gtfs_madrid_bench_mini_fixture_contains_expected_files(self):
        expected = {
            "README.md",
            "metadata.json",
            "schema.json",
            "benchmark_sample.json",
            "expected_outputs.json",
        }
        actual = {path.name for path in self.fixture_dir.iterdir()}
        self.assertTrue(expected.issubset(actual))

    def test_metadata_and_expected_outputs_are_consistent(self):
        metadata = self._read_json("metadata.json")
        sample = self._read_json("benchmark_sample.json")
        expected_outputs = self._read_json("expected_outputs.json")

        self.assertEqual(metadata["datasetName"], "GTFS-Madrid-Bench-mini")
        self.assertEqual(metadata["domain"], "mobility")
        self.assertEqual(metadata["assetPublication"]["assetId"], "dataset-gtfs-madrid-bench-mini")

        expected_counts = expected_outputs["benchmark_sample"]["recordCounts"]
        for entity, expected_count in expected_counts.items():
            self.assertEqual(expected_count, len(sample[entity]))
            self.assertEqual(metadata["selection"]["recordCounts"][entity], expected_count)

        self.assertTrue(expected_outputs["integrationExpectations"]["semanticVirtualizationReady"])
        self.assertFalse(expected_outputs["integrationExpectations"]["mobilityModelReady"])

    def test_gtfs_references_are_resolvable(self):
        sample = self._read_json("benchmark_sample.json")

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

    def test_expected_route_sequences_and_durations_match_sample(self):
        sample = self._read_json("benchmark_sample.json")
        expected_outputs = self._read_json("expected_outputs.json")

        stop_times_by_trip = {}
        for stop_time in sample["stop_times"]:
            stop_times_by_trip.setdefault(stop_time["trip_id"], []).append(stop_time)
        for rows in stop_times_by_trip.values():
            rows.sort(key=lambda row: row["stop_sequence"])

        expected_sequences = expected_outputs["benchmark_sample"]["routeStopSequences"]
        for expected_sequence in expected_sequences:
            actual_stop_ids = [
                row["stop_id"] for row in stop_times_by_trip[expected_sequence["trip_id"]]
            ]
            self.assertEqual(actual_stop_ids, expected_sequence["stop_ids"])

        expected_cases = {
            row["case_id"]: row for row in expected_outputs["benchmark_sample"]["transferCases"]
        }
        sample_cases = {row["case_id"]: row for row in sample["transfer_benchmark_cases"]}
        self.assertEqual(set(expected_cases), set(sample_cases))

        for case_id, expected_case in expected_cases.items():
            sample_case = sample_cases[case_id]
            self.assertEqual(sample_case["expected_route_id"], expected_case["expected_route_id"])
            self.assertEqual(sample_case["expected_trip_id"], expected_case["expected_trip_id"])
            self.assertEqual(
                self._duration_minutes(
                    stop_times_by_trip[sample_case["expected_trip_id"]],
                    sample_case["origin_stop_id"],
                    sample_case["destination_stop_id"],
                ),
                expected_case["expected_duration_minutes"],
            )

    @staticmethod
    def _duration_minutes(stop_times, origin_stop_id, destination_stop_id):
        origin = next(row for row in stop_times if row["stop_id"] == origin_stop_id)
        destination = next(row for row in stop_times if row["stop_id"] == destination_stop_id)
        start = datetime.strptime(origin["departure_time"], "%H:%M:%S")
        end = datetime.strptime(destination["arrival_time"], "%H:%M:%S")
        return int((end - start).total_seconds() / 60)


if __name__ == "__main__":
    unittest.main()
