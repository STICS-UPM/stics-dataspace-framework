import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import main
from framework.experiment_storage import ExperimentStorage
from framework.metrics_collector import MetricsCollector


FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "newman",
    "minimal_run",
)


def _materialize_fixture_reports(experiment_dir):
    report_dir = ExperimentStorage.newman_reports_dir(experiment_dir)
    pair_dir = os.path.join(report_dir, "run_001", "conn-a__conn-b")
    os.makedirs(pair_dir, exist_ok=True)

    exported = []
    for file_name in (
        "01_environment_health.json",
        "05_consumer_negotiation.json",
        "06_consumer_transfer.json",
    ):
        source = os.path.join(FIXTURE_DIR, file_name)
        target = os.path.join(pair_dir, file_name)
        shutil.copyfile(source, target)
        exported.append(target)

    return exported


class _FakeConfig:
    DS_NAME = "demo"

    @staticmethod
    def ds_domain_base():
        return "example.local"


class _FakeConfigAdapter:
    def load_deployer_config(self):
        return {"KC_URL": "http://keycloak.local"}


class _FakeConnectors:
    @staticmethod
    def build_connector_url(connector):
        return f"http://{connector}.example.local/interface"

    @staticmethod
    def load_connector_credentials(connector):
        return {
            "connector_user": {
                "user": f"{connector}-user",
                "passwd": "secret",
            }
        }

    @staticmethod
    def cleanup_test_entities(connector):
        return None

    @staticmethod
    def validation_test_entities_absent(connector):
        return True, []


class _FakeAdapter:
    def __init__(self):
        self.config = _FakeConfig
        self.config_adapter = _FakeConfigAdapter()
        self.connectors = _FakeConnectors()

    def get_cluster_connectors(self):
        return ["conn-a", "conn-b"]

    def deploy_connectors(self):
        return ["conn-a", "conn-b"]


class MetricsPipelineSmokeTests(unittest.TestCase):
    def test_collect_newman_request_metrics_writes_all_phase2_artifacts(self):
        collector = MetricsCollector(experiment_storage=ExperimentStorage)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = ExperimentStorage.newman_reports_dir(tmpdir)
            _materialize_fixture_reports(tmpdir)

            metrics = collector.collect_newman_request_metrics(report_dir, experiment_dir=tmpdir)

            newman_results_path = os.path.join(tmpdir, "newman_results.json")
            raw_requests_path = os.path.join(tmpdir, "raw_requests.jsonl")
            test_results_path = os.path.join(tmpdir, "test_results.json")
            negotiation_metrics_path = os.path.join(tmpdir, "negotiation_metrics.json")
            aggregated_metrics_path = os.path.join(tmpdir, "aggregated_metrics.json")

            self.assertEqual(len(metrics), 5)
            self.assertTrue(os.path.exists(newman_results_path))
            self.assertTrue(os.path.exists(raw_requests_path))
            self.assertTrue(os.path.exists(test_results_path))
            self.assertTrue(os.path.exists(negotiation_metrics_path))
            self.assertTrue(os.path.exists(aggregated_metrics_path))

            with open(test_results_path, "r", encoding="utf-8") as handle:
                test_results = json.load(handle)
            with open(negotiation_metrics_path, "r", encoding="utf-8") as handle:
                negotiation_metrics = json.load(handle)
            with open(aggregated_metrics_path, "r", encoding="utf-8") as handle:
                aggregated_metrics = json.load(handle)

        self.assertEqual(len(test_results), 5)
        self.assertEqual(
            aggregated_metrics["test_summary"],
            {
                "total_tests": 5,
                "tests_passed": 4,
                "tests_failed": 1,
                "failure_details": [
                    {
                        "test_name": "Transfer process reaches completed state",
                        "endpoint": "Transfer Process Status",
                        "status": "fail",
                        "error_message": "expected COMPLETED but got IN_PROGRESS",
                        "iteration": 1,
                    }
                ],
            },
        )
        self.assertEqual(
            negotiation_metrics,
            [
                {
                    "iteration": 1,
                    "catalog_latency_ms": 33.0,
                    "negotiation_latency_ms": 120.0,
                    "transfer_latency_ms": 116.0,
                }
            ],
        )
        self.assertIn(
            "http://conn-b.example/management/v3/catalog/request",
            aggregated_metrics["request_metrics"],
        )

    def test_run_validate_collects_metrics_even_when_validation_fails_after_exporting_reports(self):
        class FailingValidationEngine:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def run(self, connectors, experiment_dir=None):
                _materialize_fixture_reports(experiment_dir)
                raise RuntimeError("validation boom")

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                with self.assertRaisesRegex(RuntimeError, "validation boom"):
                    main.run_validate(
                        _FakeAdapter(),
                        validation_engine_cls=FailingValidationEngine,
                        experiment_storage=ExperimentStorage,
                    )

            for file_name in (
                "newman_results.json",
                "raw_requests.jsonl",
                "test_results.json",
                "negotiation_metrics.json",
                "aggregated_metrics.json",
            ):
                self.assertTrue(os.path.exists(os.path.join(tmpdir, file_name)))


if __name__ == "__main__":
    unittest.main()
