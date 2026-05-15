import subprocess
import tempfile
import unittest
from pathlib import Path

from validation.datasets.manager import (
    DATASET_SOURCES,
    required_datasets_for_components,
    sync_dataset_source,
)


class ValidationDatasetsManagerTests(unittest.TestCase):
    def test_required_datasets_are_resolved_from_components(self):
        datasets = required_datasets_for_components(["ai-model-hub", "semantic_virtualization"])
        keys = [dataset.key for dataset in datasets]

        self.assertEqual(keys, ["flares-dataset", "gtfs-bench"])

    def test_sync_clones_missing_required_datasets_into_neutral_source_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            calls = []

            def fake_runner(command, cwd=None):
                calls.append(list(command))
                if command[:3] == ["git", "clone", "--depth"]:
                    target = Path(command[-1])
                    target.mkdir(parents=True, exist_ok=True)
                    for relative_path in DATASET_SOURCES["flares-dataset"].required_paths:
                        path = target / relative_path
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("fixture", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command[:2] == ["git", "-C"] and command[-2:] == ["rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(command, 0, "abc123\n", "")
                if command[:2] == ["git", "-C"] and command[-3:] == ["config", "--get", "remote.origin.url"]:
                    return subprocess.CompletedProcess(command, 0, "https://github.com/oeg-upm/gtfs-bench\n", "")
                return subprocess.CompletedProcess(command, 0, "", "")

            dataset = sync_dataset_source(
                DATASET_SOURCES["flares-dataset"],
                source_root=tmpdir,
                runner=fake_runner,
            )

        self.assertEqual(dataset["status"], "passed")
        self.assertEqual(dataset["key"], "flares-dataset")
        self.assertTrue(dataset["cloned"])
        self.assertEqual(dataset["source_mode"], "canonical")
        self.assertEqual(dataset["missing_required_paths"], [])
        self.assertTrue(any(call[:3] == ["git", "clone", "--depth"] for call in calls))

    def test_sync_reports_warning_when_clone_fails_in_non_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:

            def fake_runner(command, cwd=None):
                return subprocess.CompletedProcess(command, 128, "", "network unavailable")

            dataset = sync_dataset_source(
                DATASET_SOURCES["flares-dataset"],
                source_root=tmpdir,
                runner=fake_runner,
            )

        self.assertEqual(dataset["status"], "warning")
        self.assertIn("network unavailable", dataset["error"])


if __name__ == "__main__":
    unittest.main()
