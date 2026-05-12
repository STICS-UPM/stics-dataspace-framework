import json
import unittest
from pathlib import Path


class AIModelHubFlaresFixtureTests(unittest.TestCase):
    def setUp(self):
        self.fixture_dir = Path(__file__).resolve().parents[1] / "validation" / "components" / "ai_model_hub" / "fixtures" / "datasets" / "linguistic" / "flares-mini"

    def test_flares_mini_fixture_contains_expected_files(self):
        expected = {
            "README.md",
            "metadata.json",
            "schema.json",
            "subtask2_trial_sample.json",
            "subtask2_test_sample.json",
            "expected_outputs.json",
        }
        actual = {path.name for path in self.fixture_dir.iterdir()}
        self.assertTrue(expected.issubset(actual))

    def test_flares_mini_metadata_and_expected_outputs_are_consistent(self):
        metadata = json.loads((self.fixture_dir / "metadata.json").read_text(encoding="utf-8"))
        expected_outputs = json.loads((self.fixture_dir / "expected_outputs.json").read_text(encoding="utf-8"))
        trial_sample = json.loads((self.fixture_dir / "subtask2_trial_sample.json").read_text(encoding="utf-8"))
        test_sample = json.loads((self.fixture_dir / "subtask2_test_sample.json").read_text(encoding="utf-8"))

        self.assertEqual(metadata["datasetName"], "FLARES-mini")
        self.assertEqual(metadata["domain"], "linguistic")
        self.assertEqual(metadata["assetPublication"]["assetId"], "dataset-flares-mini-subtask2")
        self.assertEqual(expected_outputs["subtask2_trial_sample"]["recordCount"], len(trial_sample))
        self.assertEqual(expected_outputs["subtask2_test_sample"]["recordCount"], len(test_sample))
        self.assertEqual(
            set(expected_outputs["subtask2_trial_sample"]["classDistribution"].keys()),
            {"confiable", "semiconfiable", "no confiable"},
        )
        self.assertTrue(any(row["5W1H_Label"] == "WHY" for row in trial_sample))
        self.assertTrue(all("Reliability_Label" not in row for row in test_sample))


if __name__ == "__main__":
    unittest.main()
