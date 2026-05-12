import json
import os

from ..experiment_storage import ExperimentStorage
from ..metrics.aggregator import MetricsAggregator
from .experiment_loader import ExperimentLoader


class ExperimentReportGenerator:
    """Generate experiment summaries and comparison reports."""

    def __init__(self, storage=None):
        self.storage = storage or ExperimentStorage

    @staticmethod
    def _graph_files(experiment_dir):
        graphs_dir = os.path.join(experiment_dir, "graphs")
        if not os.path.isdir(graphs_dir):
            return []
        return sorted(file_name for file_name in os.listdir(graphs_dir) if file_name.endswith(".png"))

    @staticmethod
    def _completed_kafka_runs(kafka_payload):
        if not isinstance(kafka_payload, dict):
            return []
        if isinstance(kafka_payload.get("kafka_benchmark"), dict):
            benchmark = kafka_payload["kafka_benchmark"]
            return [benchmark] if benchmark.get("status") == "completed" else []
        runs = []
        for item in kafka_payload.get("runs") or []:
            benchmark = item.get("kafka_benchmark") if isinstance(item, dict) else None
            if isinstance(benchmark, dict) and benchmark.get("status") == "completed":
                runs.append(benchmark)
        return runs

    @staticmethod
    def _average(values):
        numeric = [float(value) for value in values if value is not None]
        if not numeric:
            return None
        return round(sum(numeric) / len(numeric), 2)

    @classmethod
    def _normalize_kafka_metrics(cls, kafka_payload):
        completed_runs = cls._completed_kafka_runs(kafka_payload)
        if not completed_runs:
            return None
        return {
            "total_messages": cls._average([run.get("messages_produced") for run in completed_runs]),
            "message_latency_ms": cls._average([run.get("average_latency_ms") for run in completed_runs]),
            "throughput_messages_per_sec": cls._average(
                [run.get("throughput_messages_per_second") for run in completed_runs]
            ),
            "p50_latency_ms": cls._average([run.get("p50_latency_ms") for run in completed_runs]),
            "p95_latency_ms": cls._average([run.get("p95_latency_ms") for run in completed_runs]),
            "p99_latency_ms": cls._average([run.get("p99_latency_ms") for run in completed_runs]),
            "runs": completed_runs,
        }

    @staticmethod
    def _request_metrics_from_aggregated(aggregated_metrics):
        if not isinstance(aggregated_metrics, dict):
            return {}
        if "request_metrics" in aggregated_metrics:
            return aggregated_metrics.get("request_metrics") or {}
        return aggregated_metrics

    @staticmethod
    def _negotiation_metrics_from_aggregated(aggregated_metrics, explicit_negotiation_metrics):
        if explicit_negotiation_metrics:
            return explicit_negotiation_metrics
        if isinstance(aggregated_metrics, dict):
            return aggregated_metrics.get("negotiation_metrics") or {}
        return {}

    @staticmethod
    def _test_summary(aggregated_metrics, test_results):
        if isinstance(aggregated_metrics, dict) and aggregated_metrics.get("test_summary"):
            return aggregated_metrics["test_summary"]
        return MetricsAggregator.summarize_test_results(test_results)

    def build_summary(self, experiment_dir, adapter=None, iterations=None, kafka_enabled=None, timestamp=None):
        data = ExperimentLoader.load(experiment_dir)
        metadata = data.get("metadata.json") or {}
        raw_requests = data.get("raw_requests.jsonl") or []
        aggregated_payload = data.get("aggregated_metrics.json") or {}
        negotiation_metrics = data.get("negotiation_metrics.json") or []
        test_results = data.get("test_results.json") or []
        kafka_payload = data.get("kafka_metrics.json") or {}
        ui_validation = data.get("ui_validation_summary.json") or {}
        request_metrics = self._request_metrics_from_aggregated(aggregated_payload)
        negotiation_summary = self._negotiation_metrics_from_aggregated(aggregated_payload, negotiation_metrics)
        test_summary = self._test_summary(aggregated_payload, test_results)
        broker_source = kafka_payload.get("broker_source") if isinstance(kafka_payload, dict) else None

        summary = {
            "experiment_id": metadata.get("experiment_id") or os.path.basename(os.path.normpath(data["experiment_dir"])),
            "timestamp": timestamp or metadata.get("timestamp"),
            "metadata": metadata,
            "adapter": adapter or metadata.get("adapter"),
            "iterations": metadata.get("iterations") if iterations is None else iterations,
            "baseline": bool(metadata.get("baseline")),
            "cluster": metadata.get("cluster"),
            "connectors": metadata.get("connectors") or [],
            "environment": metadata.get("environment"),
            "kafka_enabled": bool(kafka_enabled) if kafka_enabled is not None else bool(kafka_payload),
            "broker_source": broker_source,
            "raw_request_count": len(raw_requests),
            "endpoint_latency_table": request_metrics,
            "negotiation_metrics": negotiation_summary,
            "test_results": test_results,
            "test_summary": test_summary,
            "kafka_metrics": self._normalize_kafka_metrics(kafka_payload),
            "ui_validation": ui_validation,
            "generated_graphs": self._graph_files(data["experiment_dir"]),
        }
        return summary

    @staticmethod
    def build_markdown(summary):
        lines = [
            f"# Experiment Report: {summary.get('experiment_id')}",
            "",
            "## Metadata",
            f"- **timestamp**: `{summary.get('timestamp')}`",
            f"- **adapter**: `{summary.get('adapter')}`",
            f"- **iterations**: `{summary.get('iterations')}`",
            f"- **baseline**: `{summary.get('baseline')}`",
            f"- **cluster**: `{summary.get('cluster')}`",
            f"- **connectors**: `{summary.get('connectors')}`",
            f"- **environment**: `{summary.get('environment')}`",
            "",
            "## Test Results",
        ]
        test_summary = summary.get("test_summary") or {}
        lines.extend([
            f"- Total tests: `{test_summary.get('total_tests', 0)}`",
            f"- Passed: `{test_summary.get('tests_passed', 0)}`",
            f"- Failed: `{test_summary.get('tests_failed', 0)}`",
        ])
        failures = test_summary.get("failure_details") or []
        if failures:
            lines.extend(["", "### Failure Details"])
            for item in failures:
                lines.append(
                    f"- `{item.get('endpoint')}` :: `{item.get('test_name')}` :: {item.get('error_message')}"
                )

        lines.extend([
            "",
            "## Endpoint Latency",
            "",
            "| Endpoint | Count | p50 | p95 | p99 | Error Rate |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for endpoint, stats in sorted((summary.get("endpoint_latency_table") or {}).items()):
            lines.append(
                f"| {endpoint} | {stats.get('request_count') or stats.get('count')} | "
                f"{stats.get('p50_latency_ms') or stats.get('p50')}ms | "
                f"{stats.get('p95_latency_ms') or stats.get('p95')}ms | "
                f"{stats.get('p99_latency_ms') or stats.get('p99')}ms | "
                f"{stats.get('error_rate', 0)} |"
            )

        if summary.get("negotiation_metrics"):
            lines.extend(["", "## Negotiation Latency", "", "```json", json.dumps(summary["negotiation_metrics"], indent=2), "```"])

        ui_validation = summary.get("ui_validation") or {}
        ui_summary = ui_validation.get("summary") or {}
        if ui_validation:
            operations = list(ui_validation.get("operations_involved") or [])
            lines.extend([
                "",
                "## UI Validation",
                f"- Suite runs: `{ui_summary.get('total', 0)}`",
                f"- Passed: `{ui_summary.get('passed', 0)}`",
                f"- Failed: `{ui_summary.get('failed', 0)}`",
                f"- Skipped: `{ui_summary.get('skipped', 0)}`",
            ])
            if operations:
                lines.append(f"- Operations involved: `{', '.join(operations)}`")

        kafka_metrics = summary.get("kafka_metrics")
        if kafka_metrics:
            lines.extend([
                "",
                "## Kafka Benchmark",
                f"- Messages sent: `{kafka_metrics.get('total_messages')}`",
                f"- Throughput: `{kafka_metrics.get('throughput_messages_per_sec')}` messages/sec",
                "",
                "Latency percentiles:",
                f"- p50: `{kafka_metrics.get('p50_latency_ms')}` ms",
                f"- p95: `{kafka_metrics.get('p95_latency_ms')}` ms",
                f"- p99: `{kafka_metrics.get('p99_latency_ms')}` ms",
            ])

        graphs = summary.get("generated_graphs") or []
        lines.extend(["", "## Generated Graphs"])
        if graphs:
            lines.extend(f"- `{graph}`" for graph in graphs)
        else:
            lines.append("No graphs generated.")

        return "\n".join(lines) + "\n"

    def generate(self, experiment_id, output_dir=None, adapter=None, iterations=None, kafka_enabled=None, timestamp=None):
        experiment_dir = ExperimentLoader.experiment_dir(experiment_id)
        summary = self.build_summary(
            experiment_dir,
            adapter=adapter,
            iterations=iterations,
            kafka_enabled=kafka_enabled,
            timestamp=timestamp,
        )
        markdown = self.build_markdown(summary)
        output_dir = output_dir or experiment_dir
        self.storage.save_summary_json(summary, output_dir)
        self.storage.save_summary_markdown(markdown, output_dir)
        return summary

    def _build_comparison_graphs(self, comparison_dir, summary_a, summary_b):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception as exc:
            print(f"[WARNING] Comparison graph generation failed: {exc}")
            return {}

        graphs_dir = os.path.join(comparison_dir, "graphs")
        os.makedirs(graphs_dir, exist_ok=True)

        endpoints = sorted(
            set(summary_a.get("endpoint_latency_table", {}).keys())
            | set(summary_b.get("endpoint_latency_table", {}).keys())
        )
        generated = {}
        if endpoints:
            values_a = [
                (summary_a.get("endpoint_latency_table", {}).get(endpoint, {}) or {}).get("average_latency_ms")
                or (summary_a.get("endpoint_latency_table", {}).get(endpoint, {}) or {}).get("mean_latency")
                or 0
                for endpoint in endpoints
            ]
            values_b = [
                (summary_b.get("endpoint_latency_table", {}).get(endpoint, {}) or {}).get("average_latency_ms")
                or (summary_b.get("endpoint_latency_table", {}).get(endpoint, {}) or {}).get("mean_latency")
                or 0
                for endpoint in endpoints
            ]
            positions = list(range(len(endpoints)))
            width = 0.4
            figure, axis = plt.subplots(figsize=(12, 6))
            axis.bar([p - width / 2 for p in positions], values_a, width=width, label=summary_a["experiment_id"])
            axis.bar([p + width / 2 for p in positions], values_b, width=width, label=summary_b["experiment_id"])
            axis.set_xticks(positions)
            axis.set_xticklabels(endpoints, rotation=35, ha="right")
            axis.set_ylabel("Average latency (ms)")
            axis.set_title("Endpoint latency comparison")
            axis.legend()
            figure.tight_layout()
            path = os.path.join(graphs_dir, "endpoint_latency_comparison.png")
            figure.savefig(path, dpi=180)
            plt.close(figure)
            generated["endpoint_latency_comparison"] = path

        kafka_a = summary_a.get("kafka_metrics") or {}
        kafka_b = summary_b.get("kafka_metrics") or {}
        if kafka_a and kafka_b:
            labels = ["p50", "p95", "p99"]
            values_a = [kafka_a.get("p50_latency_ms", 0), kafka_a.get("p95_latency_ms", 0), kafka_a.get("p99_latency_ms", 0)]
            values_b = [kafka_b.get("p50_latency_ms", 0), kafka_b.get("p95_latency_ms", 0), kafka_b.get("p99_latency_ms", 0)]
            positions = list(range(len(labels)))
            width = 0.35
            figure, axis = plt.subplots(figsize=(8, 6))
            axis.bar([p - width / 2 for p in positions], values_a, width=width, label=summary_a["experiment_id"])
            axis.bar([p + width / 2 for p in positions], values_b, width=width, label=summary_b["experiment_id"])
            axis.set_xticks(positions)
            axis.set_xticklabels(labels)
            axis.set_ylabel("Latency (ms)")
            axis.set_title("Kafka percentile comparison")
            axis.legend()
            figure.tight_layout()
            path = os.path.join(graphs_dir, "kafka_percentiles_comparison.png")
            figure.savefig(path, dpi=180)
            plt.close(figure)
            generated["kafka_percentiles_comparison"] = path

        return generated

    def compare(self, experiment_a, experiment_b, output_dir=None):
        summary_a = self.build_summary(ExperimentLoader.experiment_dir(experiment_a))
        summary_b = self.build_summary(ExperimentLoader.experiment_dir(experiment_b))
        comparison_dir = output_dir or self.storage.create_comparison_directory(
            summary_a["experiment_id"],
            summary_b["experiment_id"],
        )
        graphs = self._build_comparison_graphs(comparison_dir, summary_a, summary_b)
        comparison = {
            "experiment_a": summary_a,
            "experiment_b": summary_b,
            "graphs": sorted(os.path.basename(path) for path in graphs.values()),
        }
        markdown_lines = [
            f"# Experiment Comparison: {summary_a['experiment_id']} vs {summary_b['experiment_id']}",
            "",
            "## Control Plane Summary",
            "",
            "| Experiment | Raw requests | Tests passed | Tests failed |",
            "| --- | ---: | ---: | ---: |",
            f"| {summary_a['experiment_id']} | {summary_a.get('raw_request_count', 0)} | {summary_a.get('test_summary', {}).get('tests_passed', 0)} | {summary_a.get('test_summary', {}).get('tests_failed', 0)} |",
            f"| {summary_b['experiment_id']} | {summary_b.get('raw_request_count', 0)} | {summary_b.get('test_summary', {}).get('tests_passed', 0)} | {summary_b.get('test_summary', {}).get('tests_failed', 0)} |",
            "",
            "## Graphs",
        ]
        if comparison["graphs"]:
            markdown_lines.extend(f"- `{graph}`" for graph in comparison["graphs"])
        else:
            markdown_lines.append("No comparison graphs generated.")

        self.storage.save_comparison_json(comparison, comparison_dir)
        self.storage.save_comparison_markdown("\n".join(markdown_lines) + "\n", comparison_dir)
        return {"comparison_dir": comparison_dir, **comparison}
