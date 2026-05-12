import itertools
import json
import os
import tempfile
import unittest
from unittest import mock

from framework.experiment_runner import ExperimentRunner
from framework.experiment_storage import ExperimentStorage
from framework.kafka_metrics import KafkaMetricsCollector
from framework.metrics_collector import MetricsCollector


class _FakeTopic:
    def __init__(self, name, num_partitions=1, replication_factor=1):
        self.name = name
        self.num_partitions = num_partitions
        self.replication_factor = replication_factor


class _FakeMessage:
    def __init__(self, value):
        self.value = value


class _FakeBrokerState:
    topics = {}

    @classmethod
    def reset(cls):
        cls.topics = {}


class _FakeAdminClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def list_topics(self):
        return list(_FakeBrokerState.topics.keys())

    def create_topics(self, topics):
        for topic in topics:
            _FakeBrokerState.topics.setdefault(topic.name, [])

    def close(self):
        return None


class _FakeProducer:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def send(self, topic, value):
        _FakeBrokerState.topics.setdefault(topic, []).append(value)

    def flush(self):
        return None

    def close(self):
        return None


class _FakeConsumer:
    def __init__(self, topic, **kwargs):
        self.topic = topic
        self.offset = 0
        self.kwargs = kwargs

    def poll(self, timeout_ms=0):
        messages = _FakeBrokerState.topics.get(self.topic, [])
        if self.offset >= len(messages):
            return {}
        batch = [_FakeMessage(value) for value in messages[self.offset:]]
        self.offset = len(messages)
        return {self.topic: batch}

    def close(self):
        return None


class KafkaMetricsTests(unittest.TestCase):
    def setUp(self):
        _FakeBrokerState.reset()

    def _time_provider(self):
        counter = itertools.count(1_000, 10)
        return lambda: next(counter)

    def test_kafka_metrics_collector_benchmarks_broker_successfully(self):
        collector = KafkaMetricsCollector(
            runtime_config={
                "bootstrap_servers": "localhost:9092",
                "topic_strategy": KafkaMetricsCollector.STATIC_TOPIC,
                "topic_name": "benchmark-topic",
                "message_count": 3,
                "poll_timeout_seconds": 5,
            },
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeTopic,
            time_provider=self._time_provider(),
            uuid_factory=itertools.count(1).__next__,
        )

        result = collector.run(experiment_id="experiment_001", run_index=2)
        benchmark = result["kafka_benchmark"]

        self.assertEqual(benchmark["status"], "completed")
        self.assertEqual(benchmark["messages_produced"], 3)
        self.assertEqual(benchmark["messages_consumed"], 3)
        self.assertEqual(benchmark["run_index"], 2)
        self.assertEqual(benchmark["topic"], "benchmark-topic")
        self.assertGreaterEqual(benchmark["average_latency_ms"], 0)
        self.assertGreater(benchmark["throughput_messages_per_second"], 0)

    def test_kafka_metrics_collector_supports_experiment_topic_strategy(self):
        collector = KafkaMetricsCollector(
            runtime_config={
                "bootstrap_servers": "localhost:9092",
                "topic_strategy": KafkaMetricsCollector.EXPERIMENT_TOPIC,
                "message_count": 1,
            },
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeTopic,
            time_provider=self._time_provider(),
            uuid_factory=itertools.count(1).__next__,
        )

        result = collector.run(experiment_id="experiment_2026-03-07_12-00-10", run_index=1)
        topic_name = result["kafka_benchmark"]["topic"]

        self.assertTrue(topic_name.startswith("experiment-kafka-experiment-2026-03-07-12-00-10"))

    def test_kafka_metrics_collector_uses_environment_variables_as_fallback(self):
        with mock.patch.dict(os.environ, {
            "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            "KAFKA_TOPIC_NAME": "env-topic",
            "KAFKA_MESSAGE_COUNT": "2",
        }, clear=False):
            collector = KafkaMetricsCollector(
                producer_class=_FakeProducer,
                consumer_class=_FakeConsumer,
                admin_client_class=_FakeAdminClient,
                new_topic_class=_FakeTopic,
                time_provider=self._time_provider(),
                uuid_factory=itertools.count(1).__next__,
            )
            config = collector.load_config()

        self.assertEqual(config["bootstrap_servers"], "localhost:9092")
        self.assertEqual(config["topic_name"], "env-topic")
        self.assertEqual(config["message_count"], 2)

    def test_kafka_metrics_collector_skips_when_missing_configuration(self):
        collector = KafkaMetricsCollector(runtime_config={})

        result = collector.run(experiment_id="exp", run_index=1)

        self.assertEqual(result["kafka_benchmark"]["status"], "skipped")
        self.assertIn("bootstrap_servers", result["kafka_benchmark"]["reason"])

    def test_kafka_metrics_collector_skips_invalid_negative_latency_samples(self):
        counter = iter([1000, 1001, 1002, 1003, 900, 2003, 2004])
        collector = KafkaMetricsCollector(
            runtime_config={
                "bootstrap_servers": "localhost:9092",
                "topic_strategy": KafkaMetricsCollector.STATIC_TOPIC,
                "topic_name": "benchmark-topic",
                "message_count": 1,
                "poll_timeout_seconds": 1,
            },
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeTopic,
            time_provider=lambda: next(counter),
            uuid_factory=itertools.count(1).__next__,
        )

        result = collector.run(experiment_id="experiment_001", run_index=1)

        self.assertEqual(result["kafka_benchmark"]["status"], "skipped")
        self.assertIn("invalid Kafka latency", result["kafka_benchmark"]["reason"])

    def test_metrics_collector_measure_connector_latency_never_returns_negative_values(self):
        collector = MetricsCollector(build_connector_url=lambda connector: f"http://{connector}.test")

        with mock.patch("framework.metrics_collector.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            with mock.patch("framework.metrics_collector.time.perf_counter", side_effect=[10.0, 9.5, 20.0, 20.2]):
                with mock.patch("framework.metrics_collector.time.sleep"):
                    result = collector.measure_connector_latency("conn-a", "conn-b", repetitions=2)

        self.assertGreaterEqual(result["avg_latency_sec"], 0)
        self.assertGreaterEqual(result["min_latency_sec"], 0)
        self.assertGreaterEqual(result["max_latency_sec"], 0)

    def test_metrics_collector_delegates_optional_kafka_benchmark(self):
        class FakeKafkaBenchmark:
            def run(self, experiment_id=None, run_index=1):
                return {"kafka_benchmark": {"status": "completed", "experiment_id": experiment_id, "run_index": run_index}}

        collector = MetricsCollector(
            kafka_enabled=True,
            kafka_metrics_collector=FakeKafkaBenchmark(),
        )

        result = collector.collect_kafka_benchmark("experiments/experiment_001", run_index=4)

        self.assertEqual(result["kafka_benchmark"]["run_index"], 4)
        self.assertEqual(result["kafka_benchmark"]["experiment_id"], "experiment_001")

    def test_metrics_collector_run_kafka_benchmark_experiment_persists_skipped_status(self):
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
        self.assertEqual(stored["broker_source"], "auto-provisioned")
        self.assertIn("docker unavailable", stored["kafka_benchmark"]["reason"])

    def test_experiment_runner_persists_kafka_metrics_json(self):
        class FakeAdapter:
            def deploy_infrastructure(self):
                return None
            def deploy_dataspace(self):
                return None
            def deploy_connectors(self):
                return ["conn-a", "conn-b"]

        class FakeValidationEngine:
            def run(self, connectors, experiment_dir=None, run_index=None):
                return []

        class FakeMetricsCollector:
            kafka_enabled = True
            def collect(self, connectors, experiment_dir=None, run_index=None):
                return []
            def collect_newman_request_metrics(self, report_dir, experiment_dir=None):
                return []
            def collect_kafka_benchmark(self, experiment_dir, run_index=1, kafka_runtime_overrides=None):
                return {"kafka_benchmark": {"status": "completed", "run_index": run_index, "bootstrap_servers": kafka_runtime_overrides.get("bootstrap_servers") if kafka_runtime_overrides else None}}

        class FakeGraphBuilder:
            def build(self, experiment_dir):
                return {}

        class FakeKafkaManager:
            def __init__(self):
                self.last_error = None
                self.stopped = False
            def ensure_kafka_running(self):
                return "localhost:19092"
            def stop_kafka(self):
                self.stopped = True

        kafka_manager = FakeKafkaManager()
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=FakeAdapter(),
                    validation_engine=FakeValidationEngine(),
                    metrics_collector=FakeMetricsCollector(),
                    experiment_storage=ExperimentStorage,
                    iterations=2,
                    graph_builder=FakeGraphBuilder(),
                    kafka_manager=kafka_manager,
                )
                result = runner.run()
                kafka_metrics_path = os.path.join(tmpdir, "kafka_metrics.json")
                with open(kafka_metrics_path, "r", encoding="utf-8") as f:
                    kafka_metrics = json.load(f)

        self.assertIn("runs", kafka_metrics)
        self.assertEqual(len(kafka_metrics["runs"]), 2)
        self.assertEqual(kafka_metrics["broker_source"], "external")
        self.assertEqual(result["kafka_metrics"]["runs"][0]["kafka_benchmark"]["run_index"], 1)
        self.assertEqual(result["kafka_metrics"]["runs"][1]["kafka_benchmark"]["run_index"], 2)
        self.assertEqual(result["kafka_metrics"]["runs"][0]["kafka_benchmark"]["bootstrap_servers"], "localhost:19092")
        self.assertTrue(kafka_manager.stopped)


if __name__ == "__main__":
    unittest.main()

