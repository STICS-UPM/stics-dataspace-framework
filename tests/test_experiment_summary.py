import json
import os
import tempfile
import unittest
from unittest import mock

from framework.experiment_runner import ExperimentRunner
from framework.experiment_storage import ExperimentStorage
from framework.experiment_summary import ExperimentSummaryBuilder
from framework.reporting.report_generator import ExperimentReportGenerator


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

    def test_compare_includes_level6_validation_layers_and_component_metrics(self):
        generator = ExperimentReportGenerator(storage=ExperimentStorage)

        def write_json(path, payload):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

        with tempfile.TemporaryDirectory() as tmpdir:
            experiment_a = os.path.join(tmpdir, "experiment_a")
            experiment_b = os.path.join(tmpdir, "experiment_b")
            comparison_dir = os.path.join(tmpdir, "comparison")
            for experiment, ui_passed, kafka_consumed in (
                (experiment_a, 2, 9),
                (experiment_b, 3, 10),
            ):
                os.makedirs(experiment, exist_ok=True)
                write_json(
                    os.path.join(experiment, "metadata.json"),
                    {
                        "experiment_id": os.path.basename(experiment),
                        "timestamp": "2026-05-25T10:00:00",
                        "adapter": "InesdataAdapter",
                        "topology": "local",
                        "cluster_runtime": "minikube",
                    },
                )
                write_json(
                    os.path.join(experiment, "aggregated_metrics.json"),
                    {"test_summary": {"total_tests": 4, "tests_passed": 4, "tests_failed": 0}},
                )
                write_json(os.path.join(experiment, "test_results.json"), [])
                write_json(
                    os.path.join(experiment, "ui", "inesdata", "playwright_validation.json"),
                    {
                        "adapter": "inesdata",
                        "status": "passed",
                        "summary": {
                            "total_specs": 3,
                            "status_counts": {"passed": ui_passed, "failed": 3 - ui_passed},
                        },
                    },
                )
                write_json(
                    os.path.join(experiment, "components", "ontology-hub", "ontology_hub_component_validation.json"),
                    {
                        "component": "ontology-hub",
                        "status": "passed",
                        "summary": {"total": 5, "passed": 5, "failed": 0, "skipped": 0},
                        "pt5_summary": {"total": 3, "passed": 3, "failed": 0, "skipped": 0},
                    },
                )
                write_json(
                    os.path.join(experiment, "kafka_transfer_results.json"),
                    [
                        {
                            "status": "passed" if kafka_consumed == 10 else "failed",
                            "metrics": {
                                "messages_produced": 10,
                                "messages_consumed": kafka_consumed,
                                "messages_missing": 10 - kafka_consumed,
                                "average_latency_ms": 20.0,
                                "throughput_messages_per_second": 1.0,
                            },
                        }
                    ],
                )
                write_json(
                    os.path.join(experiment, "local_stability_postflight.json"),
                    {
                        "blocking_issues": [],
                        "comparison": {"status": "passed", "warnings": [], "node_not_ready_delta": 0},
                        "snapshot": {"warnings": []},
                    },
                )

            result = generator.compare(experiment_a, experiment_b, output_dir=comparison_dir)

            with open(os.path.join(comparison_dir, "comparison_report.md"), "r", encoding="utf-8") as handle:
                markdown = handle.read()
            with open(os.path.join(comparison_dir, "comparison_report.html"), "r", encoding="utf-8") as handle:
                html_report = handle.read()

        self.assertIn("metrics", result)
        self.assertIn("A5.2 Validation Scope", markdown)
        self.assertIn("Component Coverage", markdown)
        self.assertIn("Kafka Transfer", markdown)
        self.assertIn("Kafka Transfer", html_report)
        self.assertIn("Local Stability", html_report)
        if result.get("graphs"):
            self.assertIn("data:image/png;base64,", html_report)
        self.assertEqual(result["metrics"]["kafka_transfer"]["missing_messages_delta"], -1)
        self.assertEqual(result["metrics"]["validation_layers"][0]["experiment_b"]["total"], 5)

    def test_report_generator_sums_kafka_missing_messages_per_transfer(self):
        generator = ExperimentReportGenerator(storage=ExperimentStorage)

        def write_json(path, payload):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

        with tempfile.TemporaryDirectory() as tmpdir:
            write_json(
                os.path.join(tmpdir, "metadata.json"),
                {
                    "experiment_id": os.path.basename(tmpdir),
                    "timestamp": "2026-05-25T10:00:00",
                    "adapter": "InesdataAdapter",
                    "topology": "vm-distributed",
                },
            )
            write_json(
                os.path.join(tmpdir, "kafka_transfer_results.json"),
                [
                    {
                        "status": "passed",
                        "metrics": {
                            "messages_produced": 10,
                            "messages_consumed": 8,
                            "messages_missing": 2,
                            "average_latency_ms": 20.0,
                            "throughput_messages_per_second": 1.0,
                        },
                    },
                    {
                        "status": "passed",
                        "metrics": {
                            "messages_produced": 5,
                            "messages_consumed": 4,
                            "messages_missing": 1,
                            "average_latency_ms": 30.0,
                            "throughput_messages_per_second": 2.0,
                        },
                    },
                ],
            )

            summary = generator.build_summary(
                tmpdir,
                adapter="InesdataAdapter",
                kafka_enabled=True,
                timestamp="2026-05-25T10:00:00",
            )

        kafka = summary["kafka_transfer"]
        self.assertEqual(kafka["summary"]["total"], 2)
        self.assertEqual(kafka["summary"]["passed"], 0)
        self.assertEqual(kafka["summary"]["failed"], 2)
        self.assertEqual(kafka["messages_produced"], 15)
        self.assertEqual(kafka["messages_consumed"], 12)
        self.assertEqual(kafka["messages_missing"], 3)
        self.assertEqual(kafka["incomplete_transfers"], 2)
        self.assertEqual(summary["validation_layers"]["Kafka transfer"]["failed"], 2)

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

