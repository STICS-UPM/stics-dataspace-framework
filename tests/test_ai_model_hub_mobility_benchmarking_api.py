import os
import tempfile
import unittest

from validation.components.ai_model_hub.mobility_benchmarking_api import (
    CASE_ID,
    DEFAULT_MODELS,
    load_gtfs_mobility_fixture,
    run_ai_model_hub_mobility_benchmarking_validation,
)


class AIModelHubMobilityBenchmarkingApiTests(unittest.TestCase):
    def test_run_generates_mobility_use_case_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_ai_model_hub_mobility_benchmarking_validation(experiment_dir=tmpdir)
            report_path = result["artifacts"]["report_json"]
            fixture_path = result["artifacts"]["mh-mob-01-mobility-fixture-validation.json"]
            benchmark_path = result["artifacts"]["mh-mob-01-mobility-benchmark-results.json"]

            self.assertTrue(os.path.exists(report_path))
            self.assertTrue(os.path.exists(fixture_path))
            self.assertTrue(os.path.exists(benchmark_path))
            with open(report_path, encoding="utf-8") as handle:
                report_text = handle.read()

        self.assertEqual(result["component"], "ai-model-hub")
        self.assertEqual(result["suite"], "mobility-benchmarking-api")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"], {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
        self.assertEqual(result["dataset"]["name"], "GTFS-Madrid-Bench-mini")
        self.assertEqual(result["dataset"]["domain"], "mobility")
        self.assertEqual(result["dataset"]["join_keys"], ["route_id", "trip_id", "stop_id"])
        self.assertEqual(result["executed_cases"][0]["test_case_id"], CASE_ID)
        self.assertEqual(result["executed_cases"][0]["case_group"], "functional_use_case")
        self.assertEqual(len(result["metrics"]), 2)
        self.assertEqual(result["visualization_data"]["best_model"], "GTFS Mobility Route Baseline A")
        self.assertEqual(len(result["visualization_data"]["table_rows"]), 2)
        self.assertEqual(len(result["evidence_index"]), 3)
        self.assertNotIn("access_token", report_text)
        self.assertNotIn("Bearer ", report_text)

    def test_fixture_loader_uses_gtfs_madrid_bench_mini_context(self):
        fixture = load_gtfs_mobility_fixture()

        self.assertEqual(fixture["metadata"]["datasetName"], "GTFS-Madrid-Bench-mini")
        self.assertEqual(fixture["context"]["fixture_name"], "GTFS-Madrid-Bench-mini")
        self.assertEqual(fixture["context"]["join_keys"], ["route_id", "trip_id", "stop_id"])
        self.assertIn("transfer_benchmark_cases", fixture["sample"])
        self.assertIn("transferCases", fixture["expected_outputs"]["benchmark_sample"])

    def test_mobility_case_fails_when_less_than_two_models_are_selected(self):
        result = run_ai_model_hub_mobility_benchmarking_validation(models=[DEFAULT_MODELS[0]])
        mobility_case = result["executed_cases"][0]

        self.assertEqual(result["status"], "failed")
        self.assertEqual(mobility_case["test_case_id"], CASE_ID)
        self.assertEqual(mobility_case["evaluation"]["status"], "failed")
        self.assertIn("At least two controlled mobility models", mobility_case["evaluation"]["assertions"][0])


if __name__ == "__main__":
    unittest.main()
