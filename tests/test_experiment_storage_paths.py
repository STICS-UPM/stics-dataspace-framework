import json
import os
import tempfile
import unittest
from unittest import mock

from framework.experiment_storage import ExperimentStorage
from framework.reporting.experiment_loader import ExperimentLoader


class ExperimentStoragePathTests(unittest.TestCase):
    def test_experiments_base_dir_points_to_repo_root(self):
        expected = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "experiments",
        )
        self.assertEqual(ExperimentStorage.experiments_base_dir(), expected)

    def test_create_experiment_directory_uses_repo_experiments_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "experiments_base_dir", return_value=tmpdir):
                experiment_dir = ExperimentStorage.create_experiment_directory()

        self.assertTrue(experiment_dir.startswith(tmpdir + os.sep))
        self.assertIn("experiment_", os.path.basename(experiment_dir))

    def test_experiment_loader_resolves_ids_under_repo_experiments_base(self):
        experiment_id = "experiment_2026-03-18_14-55-41"
        expected = os.path.join(ExperimentStorage.experiments_base_dir(), experiment_id)
        self.assertEqual(ExperimentLoader.experiment_dir(experiment_id), expected)

    def test_save_experiment_metadata_records_topology_and_cluster_runtime_separately(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ExperimentStorage.save_experiment_metadata(
                tmpdir,
                ["conn-a"],
                adapter="EdcAdapter",
                adapter_name="edc",
                topology="local",
                cluster_runtime="minikube",
            )
            metadata_path = os.path.join(tmpdir, "metadata.json")
            with open(metadata_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)

        self.assertEqual(metadata["adapter"], "EdcAdapter")
        self.assertEqual(metadata["adapter_name"], "edc")
        self.assertEqual(metadata["topology"], "local")
        self.assertEqual(metadata["cluster_runtime"], "minikube")
        self.assertEqual(metadata["cluster"], "minikube")


if __name__ == "__main__":
    unittest.main()
