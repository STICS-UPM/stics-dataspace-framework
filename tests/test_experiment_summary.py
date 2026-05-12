import json
import os
import tempfile
import unittest
from unittest import mock

from framework.experiment_runner import ExperimentRunner
from framework.experiment_storage import ExperimentStorage
from framework.experiment_summary import ExperimentSummaryBuilder


class ExperimentSummaryTests(unittest.TestCase):
    def test_summary_builder_creates_normalized_summary_and_markdown(self):
        builder = ExperimentSummaryBuilder()

        with tempfile.TemporaryDirectory() as tmpdir:
            ExperimentStorage.save_experiment_metadata(tmpdir, ["conn-a", "conn-b"])
            ExperimentStorage.save_aggregated_metrics({
                "Create Asset": {
                    "count": 2,
                    "average_latency_ms": 42.0,
                    "min_latency_ms": 38.0,
                    "max_latency_ms": 46.0,
                    "p50_latency_ms": 42.0,
                    "p95_latency_ms": 45.8,
                    "p99_latency_ms": 45.96,
                }
            }, tmpdir)
            ExperimentStorage.save_raw_request_metrics_jsonl([
                {"collection": "03_provider_setup", "request_name": "Create Asset", "latency_ms": 40},
                {"collection": "03_provider_setup", "request_name": "Create Asset", "latency_ms": 44},
                {"collection": "02_connector_management_api", "request_name": "List Assets", "latency_ms": 18},
                {"collection": "02_connector_management_api", "request_name": "List Assets", "latency_ms": 22},
            ], tmpdir)
            ExperimentStorage.save_kafka_metrics_json({
                "broker_source": "external",
                "kafka_benchmark": {
                    "status": "completed",
                    "average_latency_ms": 8.5,
                    "p50_latency_ms": 8.0,
                    "p95_latency_ms": 10.0,
                    "p99_latency_ms": 11.0,
                    "throughput_messages_per_second": 120.0,
                }
            }, tmpdir)
            ExperimentStorage.save(
                {
                    "status": "passed",
                    "summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0, "not_run": 0},
                    "support_summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                    "dataspace_summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                    "ops_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
                    "operations_involved": ["create_asset", "upload_asset_file"],
                    "operation_summary": {
                        "create_asset": {
                            "total": 1,
                            "passed": 1,
                            "failed": 0,
                            "skipped": 0,
                            "test_case_ids": ["DS-UI-03"],
                        },
                        "upload_asset_file": {
                            "total": 1,
                            "passed": 1,
                            "failed": 0,
                            "skipped": 0,
                            "test_case_ids": ["DS-UI-03"],
                        },
                    },
                },
                experiment_dir=tmpdir,
                file_name="ui_validation_summary.json",
            )
            graphs_dir = os.path.join(tmpdir, "graphs")
            os.makedirs(graphs_dir, exist_ok=True)
            for file_name in ("request_latency_avg.png", "kafka_throughput.png"):
                with open(os.path.join(graphs_dir, file_name), "wb") as f:
                    f.write(b"png")

            summary = builder.build_summary(
                tmpdir,
                adapter="FakeAdapter",
                iterations=3,
                kafka_enabled=True,
                timestamp="2026-03-08T12:00:00",
            )
            markdown = builder.build_markdown(summary)

        self.assertEqual(summary["adapter"], "FakeAdapter")
        self.assertEqual(summary["iterations"], 3)
        self.assertTrue(summary["kafka_enabled"])
        self.assertTrue(summary["baseline"] is False)
        self.assertIn("Create Asset", summary["endpoint_latency_table"])
        self.assertEqual(summary["kafka_metrics"]["throughput_messages_per_sec"], 120.0)
        self.assertEqual(summary["ui_validation"]["status"], "passed")
        self.assertEqual(summary["ui_validation"]["summary"]["total"], 2)
        self.assertEqual(summary["ui_validation"]["operations_involved"], ["create_asset", "upload_asset_file"])
        self.assertEqual(summary["generated_graphs"], ["kafka_throughput.png", "request_latency_avg.png"])
        self.assertEqual(summary["raw_request_count"], 4)
        self.assertIn("# Experiment Report:", markdown)
        self.assertIn("## Endpoint Latency", markdown)
        self.assertIn("## UI Validation", markdown)
        self.assertIn("Operations involved", markdown)
        self.assertIn("create_asset, upload_asset_file", markdown)
        self.assertIn("## Kafka Benchmark", markdown)
        self.assertIn("| Endpoint | Count | p50 | p95 | p99 | Error Rate |", markdown)
        self.assertIn("`kafka_throughput.png`", markdown)

    def test_summary_builder_handles_missing_optional_kafka(self):
        builder = ExperimentSummaryBuilder()

        with tempfile.TemporaryDirectory() as tmpdir:
            ExperimentStorage.save_aggregated_metrics({
                "Health": {
                    "count": 1,
                    "average_latency_ms": 11.0,
                    "min_latency_ms": 11.0,
                    "max_latency_ms": 11.0,
                    "p50_latency_ms": 11.0,
                    "p95_latency_ms": 11.0,
                    "p99_latency_ms": 11.0,
                }
            }, tmpdir)
            summary = builder.build_summary(
                tmpdir,
                adapter="FakeAdapter",
                iterations=1,
                kafka_enabled=False,
                timestamp="2026-03-08T12:00:00",
            )
            markdown = builder.build_markdown(summary)

        self.assertFalse(summary["kafka_enabled"])
        self.assertIsNone(summary["kafka_metrics"])
        self.assertEqual(summary["generated_graphs"], [])
        self.assertIn("## Endpoint Latency", markdown)
        self.assertIn("Health", markdown)

    def test_experiment_runner_generates_summary_files(self):
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
                ExperimentStorage.save_aggregated_metrics({
                    "Health": {
                        "count": 1,
                        "average_latency_ms": 11.0,
                        "min_latency_ms": 11.0,
                        "max_latency_ms": 11.0,
                        "p50_latency_ms": 11.0,
                        "p95_latency_ms": 11.0,
                        "p99_latency_ms": 11.0,
                    }
                }, experiment_dir)
                return []
            def collect_kafka_benchmark(self, experiment_dir, run_index=1, kafka_runtime_overrides=None):
                return {
                    "kafka_benchmark": {
                        "status": "completed",
                        "run_index": run_index,
                        "average_latency_ms": 8.5,
                        "p50_latency_ms": 8.0,
                        "p95_latency_ms": 10.0,
                        "p99_latency_ms": 11.0,
                        "throughput_messages_per_second": 120.0,
                    }
                }

        class FakeGraphBuilder:
            def build(self, experiment_dir):
                graphs_dir = os.path.join(experiment_dir, "graphs")
                os.makedirs(graphs_dir, exist_ok=True)
                output = os.path.join(graphs_dir, "request_latency_avg.png")
                with open(output, "wb") as f:
                    f.write(b"png")
                return {"request_latency_avg": output}

        class FakeKafkaManager:
            started_by_framework = True
            last_error = None
            def ensure_kafka_running(self):
                return "localhost:19092"
            def stop_kafka(self):
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=FakeAdapter(),
                    validation_engine=FakeValidationEngine(),
                    metrics_collector=FakeMetricsCollector(),
                    experiment_storage=ExperimentStorage,
                    graph_builder=FakeGraphBuilder(),
                    kafka_manager=FakeKafkaManager(),
                )
                result = runner.run()

            summary_json_path = os.path.join(tmpdir, "summary.json")
            summary_md_path = os.path.join(tmpdir, "summary.md")
            self.assertTrue(os.path.exists(summary_json_path))
            self.assertTrue(os.path.exists(summary_md_path))
            with open(summary_json_path, "r", encoding="utf-8") as f:
                summary_json = json.load(f)
            with open(summary_md_path, "r", encoding="utf-8") as f:
                summary_md = f.read()

            self.assertEqual(summary_json["broker_source"], "auto-provisioned")
            self.assertTrue(summary_json["kafka_enabled"])
            self.assertIn("summary_json", result["summary_files"])
            self.assertIn("## Generated Graphs", summary_md)
            self.assertIn("`request_latency_avg.png`", summary_md)

    def test_experiment_runner_continues_when_summary_generation_fails(self):
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
            kafka_enabled = False
            def collect(self, connectors, experiment_dir=None, run_index=None):
                return []
            def collect_newman_request_metrics(self, report_dir, experiment_dir=None):
                ExperimentStorage.save_aggregated_metrics({
                    "Health": {
                        "count": 1,
                        "average_latency_ms": 11.0,
                        "min_latency_ms": 11.0,
                        "max_latency_ms": 11.0,
                        "p50_latency_ms": 11.0,
                        "p95_latency_ms": 11.0,
                        "p99_latency_ms": 11.0,
                    }
                }, experiment_dir)
                return []

        class FakeGraphBuilder:
            def build(self, experiment_dir):
                return {}

        class FailingSummaryBuilder:
            def build_summary(self, experiment_dir, adapter=None, iterations=1, kafka_enabled=False, timestamp=None):
                raise RuntimeError("summary boom")

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=FakeAdapter(),
                    validation_engine=FakeValidationEngine(),
                    metrics_collector=FakeMetricsCollector(),
                    experiment_storage=ExperimentStorage,
                    graph_builder=FakeGraphBuilder(),
                    summary_builder=FailingSummaryBuilder(),
                )
                result = runner.run()

        self.assertEqual(result["summary_files"], {})


if __name__ == "__main__":
    unittest.main()

