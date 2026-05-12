import json
import os
import tempfile
import unittest
from unittest import mock

from framework.experiment_runner import ExperimentRunner
from framework.experiment_storage import ExperimentStorage


class _FakeAdapter:
    def deploy_infrastructure(self):
        return None

    def deploy_dataspace(self):
        return None

    def deploy_connectors(self):
        return ["conn-a", "conn-b"]


class _FakeMetricsCollector:
    kafka_enabled = False

    def collect(self, connectors, experiment_dir=None, run_index=None):
        return {
            "connectors": list(connectors),
            "experiment_dir": experiment_dir,
            "run_index": run_index,
        }


class _FakeGraphBuilder:
    def build(self, experiment_dir):
        return {}


class _FakeSummaryBuilder:
    def build_summary(self, experiment_dir, adapter=None, iterations=1, kafka_enabled=False, timestamp=None):
        return {
            "experiment_dir": experiment_dir,
            "adapter": adapter,
            "iterations": iterations,
            "kafka_enabled": kafka_enabled,
            "timestamp": timestamp,
        }

    def build_markdown(self, summary):
        return f"# Experiment Report\n\nAdapter: {summary['adapter']}\n"


class ExperimentRunSmokeTests(unittest.TestCase):
    def test_run_creates_expected_experiment_scaffold(self):
        class FakeValidationEngine:
            def run(self, connectors, experiment_dir=None, run_index=None):
                return [{"pair": list(connectors), "report_dir": experiment_dir, "run_index": run_index}]

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=_FakeAdapter(),
                    validation_engine=FakeValidationEngine(),
                    metrics_collector=_FakeMetricsCollector(),
                    experiment_storage=ExperimentStorage,
                    graph_builder=_FakeGraphBuilder(),
                    summary_builder=_FakeSummaryBuilder(),
                )
                result = runner.run()

            metadata_path = os.path.join(tmpdir, "metadata.json")
            experiment_results_path = os.path.join(tmpdir, "experiment_results.json")
            newman_reports_dir = os.path.join(tmpdir, "newman_reports")

            self.assertEqual(result["status"], "completed")
            self.assertTrue(os.path.exists(metadata_path))
            self.assertTrue(os.path.exists(experiment_results_path))
            self.assertTrue(os.path.isdir(newman_reports_dir))

            with open(experiment_results_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(stored["status"], "completed")
            self.assertEqual(stored["connectors"], ["conn-a", "conn-b"])

    def test_run_persists_failed_state_when_validation_raises(self):
        class FailingValidationEngine:
            def run(self, connectors, experiment_dir=None, run_index=None):
                raise RuntimeError("validation boom")

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=_FakeAdapter(),
                    validation_engine=FailingValidationEngine(),
                    metrics_collector=_FakeMetricsCollector(),
                    experiment_storage=ExperimentStorage,
                    graph_builder=_FakeGraphBuilder(),
                    summary_builder=_FakeSummaryBuilder(),
                )

                with self.assertRaisesRegex(RuntimeError, "validation boom"):
                    runner.run()

            metadata_path = os.path.join(tmpdir, "metadata.json")
            experiment_results_path = os.path.join(tmpdir, "experiment_results.json")
            newman_reports_dir = os.path.join(tmpdir, "newman_reports")

            self.assertTrue(os.path.exists(metadata_path))
            self.assertTrue(os.path.exists(experiment_results_path))
            self.assertTrue(os.path.isdir(newman_reports_dir))

            with open(experiment_results_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(stored["status"], "failed")
            self.assertEqual(stored["error"]["type"], "RuntimeError")
            self.assertIn("validation boom", stored["error"]["message"])


if __name__ == "__main__":
    unittest.main()
