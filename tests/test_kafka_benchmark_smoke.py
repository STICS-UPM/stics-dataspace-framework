import json
import os
import tempfile
import unittest
from unittest import mock

from framework.experiment_storage import ExperimentStorage
from framework.metrics_collector import MetricsCollector
from validation.orchestration.runner import Level6Runtime, run_level6


class KafkaBenchmarkSmokeTests(unittest.TestCase):
    def test_run_kafka_benchmark_experiment_persists_completed_payload(self):
        class FakeKafkaBenchmark:
            def run(self, experiment_id=None, run_index=1, runtime_overrides=None):
                return {
                    "kafka_benchmark": {
                        "status": "completed",
                        "experiment_id": experiment_id,
                        "run_index": run_index,
                        "average_latency_ms": 8.5,
                        "p50_latency_ms": 8.0,
                        "p95_latency_ms": 10.0,
                        "p99_latency_ms": 11.0,
                        "throughput_messages_per_second": 120.0,
                    }
                }

        class FakeKafkaManager:
            started_by_framework = False
            last_error = None

            def ensure_kafka_running(self):
                return "localhost:19092"

        collector = MetricsCollector(
            experiment_storage=ExperimentStorage,
            kafka_enabled=True,
            kafka_metrics_collector=FakeKafkaBenchmark(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            payload = collector.run_kafka_benchmark_experiment(
                tmpdir,
                iterations=2,
                kafka_manager=FakeKafkaManager(),
            )

            kafka_metrics_path = os.path.join(tmpdir, "kafka_metrics.json")
            self.assertTrue(os.path.exists(kafka_metrics_path))
            with open(kafka_metrics_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)

        self.assertEqual(payload["broker_source"], "external")
        self.assertEqual(payload["bootstrap_servers"], "localhost:19092")
        self.assertEqual(len(payload["runs"]), 2)
        self.assertEqual(stored["runs"][0]["kafka_benchmark"]["status"], "completed")

    def test_run_kafka_benchmark_experiment_persists_skipped_payload(self):
        class FakeKafkaManager:
            started_by_framework = True
            last_error = "docker unavailable"

            def ensure_kafka_running(self):
                return None

        collector = MetricsCollector(
            experiment_storage=ExperimentStorage,
            kafka_enabled=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            payload = collector.run_kafka_benchmark_experiment(
                tmpdir,
                iterations=1,
                kafka_manager=FakeKafkaManager(),
            )

            with open(os.path.join(tmpdir, "kafka_metrics.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

        self.assertEqual(payload["kafka_benchmark"]["status"], "skipped")
        self.assertEqual(payload["broker_source"], "auto-provisioned")
        self.assertIn("docker unavailable", stored["kafka_benchmark"]["reason"])

    def test_level6_persists_kafka_metrics_into_experiment_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kafka_payload = {
                "kafka_benchmark": {
                    "status": "completed",
                    "run_index": 1,
                    "average_latency_ms": 8.5,
                },
                "broker_source": "external",
                "bootstrap_servers": "localhost:19092",
            }
            mock_kafka = mock.Mock(return_value=kafka_payload)
            validation_engine = mock.Mock()
            validation_engine.last_storage_checks = []
            validation_engine.run_all_dataspace_tests.return_value = []
            metrics_collector = mock.Mock()
            metrics_collector.collect_experiment_newman_metrics.return_value = []

            def save_experiment_state(experiment_dir, connectors, **kwargs):
                payload = {
                    "status": kwargs.get("status"),
                    "connectors": list(connectors or []),
                    "kafka_metrics": kwargs.get("kafka_metrics"),
                    "newman_request_metrics": list(kwargs.get("newman_request_metrics") or []),
                    "storage_checks": list(kwargs.get("storage_checks") or []),
                    "ui_results": list(kwargs.get("ui_results") or []),
                    "component_results": list(kwargs.get("component_results") or []),
                }
                ExperimentStorage.save(payload, experiment_dir=experiment_dir)
                return payload

            class FakeExperimentStorage(ExperimentStorage):
                @classmethod
                def create_experiment_directory(cls):
                    return tmpdir

            runtime = Level6Runtime(
                newman_executor=mock.Mock(is_available=mock.Mock(return_value=True)),
                ensure_connectors_ready=mock.Mock(return_value=["conn-a", "conn-b"]),
                ensure_connector_hosts=mock.Mock(return_value=None),
                validate_connectors_deployment=mock.Mock(return_value=True),
                ensure_all_minio_policies=mock.Mock(return_value=None),
                wait_for_keycloak_readiness=mock.Mock(return_value=True),
                wait_for_validation_ready=mock.Mock(return_value={"status": "passed", "gates": []}),
                validation_engine=validation_engine,
                metrics_collector=metrics_collector,
                experiment_storage=FakeExperimentStorage,
                save_experiment_state=save_experiment_state,
                should_run_kafka_edc_validation=mock.Mock(return_value=False),
                run_kafka_edc_validation=mock.Mock(return_value=[]),
                run_kafka_benchmark=mock_kafka,
                should_run_ui_dataspace=mock.Mock(return_value=False),
                should_run_ui_ops=mock.Mock(return_value=False),
                should_run_component_validation=mock.Mock(return_value=False),
                run_component_validations=mock.Mock(return_value=[]),
                script_dir=mock.Mock(return_value=tmpdir),
                load_connector_credentials=mock.Mock(return_value=None),
                build_connector_url=mock.Mock(return_value=""),
                run_ui_smoke=mock.Mock(return_value={}),
                run_ui_dataspace=mock.Mock(return_value={}),
                run_ui_ops=mock.Mock(return_value={}),
            )

            run_level6(runtime)

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

        mock_kafka.assert_called_once()
        self.assertEqual(stored["kafka_metrics"]["kafka_benchmark"]["status"], "completed")
        self.assertEqual(stored["kafka_metrics"]["bootstrap_servers"], "localhost:19092")


if __name__ == "__main__":
    unittest.main()
