import os
import tempfile
import unittest

from validation.components.ai_model_hub.model_benchmarking_api import (
    CASE_IDS,
    DEFAULT_MODELS,
    build_flares_benchmark_rows,
    run_ai_model_hub_model_benchmarking_validation,
)
from validation.components.ai_model_hub.model_execution_api import load_flares_mini_fixture


class AIModelHubModelBenchmarkingApiTests(unittest.TestCase):
    def test_run_generates_four_benchmarking_cases_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_ai_model_hub_model_benchmarking_validation(experiment_dir=tmpdir)
            report_path = result["artifacts"]["report_json"]
            self.assertTrue(os.path.exists(report_path))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-mh-12-model-selection.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-mh-13-benchmark-executions.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-mh-14-benchmark-metrics.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-mh-15-benchmark-visualization-data.json"]))
            with open(report_path, encoding="utf-8") as handle:
                report_text = handle.read()

        self.assertEqual(result["component"], "ai-model-hub")
        self.assertEqual(result["suite"], "model-benchmarking-api")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"], {"total": 4, "passed": 4, "failed": 0, "skipped": 0})
        self.assertEqual([case["test_case_id"] for case in result["executed_cases"]], CASE_IDS)
        self.assertEqual(result["visualization_data"]["best_model"], "FLARES Reliability Baseline A")
        self.assertEqual(len(result["visualization_data"]["table_rows"]), 2)
        self.assertNotIn("access_token", report_text)
        self.assertNotIn("Bearer ", report_text)

    def test_benchmark_rows_use_flares_expected_outputs(self):
        fixture = load_flares_mini_fixture()
        rows = build_flares_benchmark_rows(fixture)
        rows_by_id = {row["record_id"]: row for row in rows}

        self.assertEqual(len(rows), 9)
        self.assertEqual(rows_by_id[463]["expected_label"], "confiable")
        self.assertEqual(rows_by_id[106]["expected_label"], "no confiable")
        self.assertEqual(rows_by_id[113]["expected_label"], "semiconfiable")
        self.assertIn("text", rows_by_id[463]["input"])
        self.assertIn("tag_text", rows_by_id[463]["input"])

    def test_selection_case_fails_when_less_than_two_models_are_selected(self):
        result = run_ai_model_hub_model_benchmarking_validation(models=[DEFAULT_MODELS[0]])
        selection_case = result["executed_cases"][0]

        self.assertEqual(result["status"], "failed")
        self.assertEqual(selection_case["test_case_id"], "PT5-MH-12")
        self.assertEqual(selection_case["evaluation"]["status"], "failed")
        self.assertIn("At least two models", selection_case["evaluation"]["assertions"][0])


if __name__ == "__main__":
    unittest.main()
