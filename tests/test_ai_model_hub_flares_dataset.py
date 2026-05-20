import tempfile
import unittest
import json

from tests.dataset_test_helpers import create_flares_source
from validation.components.ai_model_hub.model_execution_api import load_flares_dataset


class AIModelHubFlaresDatasetTests(unittest.TestCase):
    def test_flares_source_dataset_loads_expected_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_flares_source(tmpdir)
            dataset = load_flares_dataset(str(source_dir))

        self.assertEqual(dataset["metadata"]["datasetName"], "FLARES")
        self.assertEqual(dataset["metadata"]["domain"], "linguistic")
        self.assertEqual(dataset["metadata"]["assetPublication"]["assetId"], "dataset-flares-subtask2")
        self.assertEqual(dataset["expected_outputs"]["subtask2_trial_sample"]["recordCount"], 3)
        self.assertEqual(dataset["expected_outputs"]["subtask2_test_sample"]["recordCount"], 1)
        self.assertEqual(
            set(dataset["expected_outputs"]["subtask2_trial_sample"]["classDistribution"].keys()),
            {"confiable", "semiconfiable", "no confiable"},
        )
        self.assertTrue(any(row["5W1H_Label"] == "WHY" for row in dataset["trial_sample"]))
        self.assertTrue(all("Reliability_Label" not in row for row in dataset["test_sample"]))

    def test_flares_source_dataset_accepts_json_lines_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_flares_source(tmpdir)
            for name in ("5w1h_subtask_2_trial.json", "5w1h_subtarea_2_test.json"):
                file_path = source_dir / name
                records = json.loads(file_path.read_text(encoding="utf-8"))
                file_path.write_text(
                    "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
                    encoding="utf-8",
                )

            dataset = load_flares_dataset(str(source_dir))

        self.assertEqual(dataset["expected_outputs"]["subtask2_trial_sample"]["recordCount"], 3)
        self.assertEqual(dataset["expected_outputs"]["subtask2_test_sample"]["recordCount"], 1)
        self.assertTrue(any(row["Id"] == 463 for row in dataset["trial_sample"]))


if __name__ == "__main__":
    unittest.main()
