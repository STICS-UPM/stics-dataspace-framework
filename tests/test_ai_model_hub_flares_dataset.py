import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
