import base64
import html
import json
import os
import re
from pathlib import Path

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

    @staticmethod
    def _number(value):
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _read_json(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return None

    @staticmethod
    def _empty_counts():
        return {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "other": 0}

    @classmethod
    def _merge_counts(cls, *counts):
        merged = cls._empty_counts()
        for item in counts:
            if not isinstance(item, dict):
                continue
            merged["total"] += int(item.get("total") or item.get("total_tests") or 0)
            merged["passed"] += int(item.get("passed") or item.get("tests_passed") or 0)
            merged["failed"] += int(item.get("failed") or item.get("tests_failed") or 0)
            merged["skipped"] += int(item.get("skipped") or 0)
            merged["other"] += int(item.get("other") or item.get("not_run") or 0)
        return merged

    @classmethod
    def _counts_from_status_counts(cls, status_counts, total=None):
        status_counts = status_counts if isinstance(status_counts, dict) else {}
        passed = int(status_counts.get("passed") or status_counts.get("expected") or 0)
        failed = int(
            (status_counts.get("failed") or 0)
            + (status_counts.get("unexpected") or 0)
            + (status_counts.get("timedout") or 0)
            + (status_counts.get("interrupted") or 0)
        )
        skipped = int(status_counts.get("skipped") or 0)
        total_value = int(total if total is not None else sum(int(value or 0) for value in status_counts.values()))
        other = max(total_value - passed - failed - skipped, 0)
        return {
            "total": total_value,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "other": other,
        }

    @classmethod
    def _counts_from_records(cls, records, key="status"):
        counts = cls._empty_counts()
        for record in records or []:
            if not isinstance(record, dict):
                continue
            counts["total"] += 1
            status = str(record.get(key) or "").strip().lower()
            if status in {"passed", "pass", "ok", "success", "succeeded", "completed"}:
                counts["passed"] += 1
            elif status in {"failed", "fail", "error", "terminated"}:
                counts["failed"] += 1
            elif status in {"skipped", "skip"}:
                counts["skipped"] += 1
            else:
                counts["other"] += 1
        return counts

    @classmethod
    def _component_validation_summary(cls, experiment_dir):
        base = Path(experiment_dir)
        components_dir = base / "components"
        components = []
        total_summary = cls._empty_counts()
        pt5_summary = cls._empty_counts()
        support_summary = cls._empty_counts()
        if not components_dir.is_dir():
            return {
                "summary": total_summary,
                "pt5_summary": pt5_summary,
                "support_summary": support_summary,
                "components": components,
            }

        for component_dir in sorted(path for path in components_dir.iterdir() if path.is_dir()):
            expected_name = f"{component_dir.name.replace('-', '_')}_component_validation.json"
            primary_path = component_dir / expected_name
            candidate_paths = [primary_path] if primary_path.exists() else sorted(component_dir.glob("*_component_validation.json"))
            if not candidate_paths:
                continue
            payload = cls._read_json(candidate_paths[0])
            if not isinstance(payload, dict):
                continue
            summary = cls._merge_counts(payload.get("summary") or {})
            pt5 = cls._merge_counts(payload.get("pt5_summary") or {})
            support = cls._merge_counts(payload.get("support_summary") or {})
            component_entry = {
                "component": str(payload.get("component") or component_dir.name),
                "title": str(payload.get("display_name") or payload.get("component") or component_dir.name),
                "status": str(payload.get("status") or "unknown"),
                "summary": summary,
                "pt5_summary": pt5,
                "support_summary": support,
                "artifact": str(candidate_paths[0].relative_to(base)),
            }
            components.append(component_entry)
            total_summary = cls._merge_counts(total_summary, summary)
            pt5_summary = cls._merge_counts(pt5_summary, pt5)
            support_summary = cls._merge_counts(support_summary, support)

        return {
            "summary": total_summary,
            "pt5_summary": pt5_summary,
            "support_summary": support_summary,
            "components": components,
        }

    @classmethod
    def _playwright_validation_summary(cls, experiment_dir, ui_validation):
        if isinstance(ui_validation, dict) and ui_validation:
            summary = cls._merge_counts(ui_validation.get("summary") or {})
            return {
                "status": str(ui_validation.get("status") or ("failed" if summary["failed"] else "passed")),
                "summary": summary,
                "runs": [
                    {
                        "title": "ui_validation_summary.json",
                        "status": str(ui_validation.get("status") or "unknown"),
                        "summary": summary,
                        "artifact": "ui_validation_summary.json",
                    }
                ],
            }

        base = Path(experiment_dir)
        runs = []
        merged = cls._empty_counts()
        for path in sorted(base.glob("**/playwright_validation.json")):
            if "node_modules" in path.parts:
                continue
            payload = cls._read_json(path)
            if not isinstance(payload, dict):
                continue
            raw_summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
            counts = cls._counts_from_status_counts(
                raw_summary.get("status_counts") or {},
                total=raw_summary.get("total_specs"),
            )
            if not counts["total"]:
                counts = cls._merge_counts(raw_summary)
            merged = cls._merge_counts(merged, counts)
            runs.append(
                {
                    "title": str(payload.get("adapter") or path.parent.name),
                    "status": str(payload.get("status") or "unknown"),
                    "summary": counts,
                    "artifact": str(path.relative_to(base)),
                }
            )

        return {
            "status": "failed" if merged["failed"] else ("passed" if merged["total"] else "not_recorded"),
            "summary": merged,
            "runs": runs,
        }

    @classmethod
    def _kafka_transfer_summary(cls, experiment_dir):
        base = Path(experiment_dir)
        payload = None
        artifact = None
        for name in ("kafka_transfer_results.json", "kafka_edc_results.json"):
            candidate = base / name
            loaded = cls._read_json(candidate)
            if isinstance(loaded, list):
                payload = loaded
                artifact = name
                break
        records = [item for item in (payload or []) if isinstance(item, dict)]
        summary = cls._empty_counts()
        produced = 0
        consumed = 0
        missing = 0
        latencies = []
        throughputs = []
        incomplete = 0
        for record in records:
            metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
            produced_value = cls._number(metrics.get("messages_produced"))
            consumed_value = cls._number(metrics.get("messages_consumed"))
            record_incomplete = False
            if produced_value is not None:
                produced += int(produced_value)
            if consumed_value is not None:
                consumed += int(consumed_value)
            if produced_value is not None and consumed_value is not None and consumed_value < produced_value:
                record_incomplete = True
                incomplete += 1
                missing += int(produced_value - consumed_value)
            explicit_missing = cls._number(metrics.get("messages_missing"))
            if explicit_missing is not None:
                missing = max(missing, int(explicit_missing))
                record_incomplete = record_incomplete or explicit_missing > 0
            summary["total"] += 1
            status = str(record.get("status") or "").strip().lower()
            if record_incomplete:
                summary["failed"] += 1
            elif status in {"passed", "pass", "ok", "success", "succeeded", "completed"}:
                summary["passed"] += 1
            elif status in {"failed", "fail", "error", "terminated"}:
                summary["failed"] += 1
            elif status in {"skipped", "skip"}:
                summary["skipped"] += 1
            else:
                summary["other"] += 1
            latency = cls._number(metrics.get("average_latency_ms"))
            throughput = cls._number(metrics.get("throughput_messages_per_second"))
            if latency is not None:
                latencies.append(latency)
            if throughput is not None:
                throughputs.append(throughput)
        return {
            "status": "failed" if summary["failed"] or incomplete else ("passed" if summary["total"] else "not_recorded"),
            "summary": summary,
            "messages_produced": produced,
            "messages_consumed": consumed,
            "messages_missing": missing,
            "incomplete_transfers": incomplete,
            "average_latency_ms": cls._average(latencies),
            "average_throughput": cls._average(throughputs),
            "artifact": artifact,
        }

    @classmethod
    def _local_stability_summary(cls, experiment_dir):
        path = Path(experiment_dir) / "local_stability_postflight.json"
        payload = cls._read_json(path)
        if not isinstance(payload, dict):
            return {"status": "not_recorded", "new_warnings": 0, "snapshot_warnings": 0, "blocking_issues": 0}
        comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
        comparison_warnings = comparison.get("warnings") if isinstance(comparison.get("warnings"), list) else []
        snapshot_warnings = snapshot.get("warnings") if isinstance(snapshot.get("warnings"), list) else []
        blocking = payload.get("blocking_issues") if isinstance(payload.get("blocking_issues"), list) else []
        return {
            "status": str(comparison.get("status") or "unknown"),
            "new_warnings": len(comparison_warnings),
            "snapshot_warnings": len(snapshot_warnings),
            "blocking_issues": len(blocking),
            "node_not_ready_delta": comparison.get("node_not_ready_delta"),
        }

    @classmethod
    def _validation_layers(cls, summary):
        test_summary = summary.get("test_summary") or {}
        ui_summary = (summary.get("playwright_validation") or {}).get("summary") or {}
        component_summary = (summary.get("component_validation") or {}).get("summary") or {}
        pt5_summary = (summary.get("component_validation") or {}).get("pt5_summary") or {}
        kafka_summary = (summary.get("kafka_transfer") or {}).get("summary") or {}
        return {
            "Newman": cls._merge_counts(test_summary),
            "INESData/EDC UI": cls._merge_counts(ui_summary),
            "Components": cls._merge_counts(component_summary),
            "PT5 cases": cls._merge_counts(pt5_summary),
            "Kafka transfer": cls._merge_counts(kafka_summary),
        }

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
        component_validation = self._component_validation_summary(data["experiment_dir"])
        playwright_validation = self._playwright_validation_summary(data["experiment_dir"], ui_validation)
        kafka_transfer = self._kafka_transfer_summary(data["experiment_dir"])
        local_stability = self._local_stability_summary(data["experiment_dir"])
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
            "cluster_runtime": metadata.get("cluster_runtime") or metadata.get("cluster"),
            "topology": metadata.get("topology"),
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
            "kafka_transfer": kafka_transfer,
            "ui_validation": ui_validation,
            "playwright_validation": playwright_validation,
            "component_validation": component_validation,
            "local_stability": local_stability,
            "generated_graphs": self._graph_files(data["experiment_dir"]),
        }
        summary["validation_layers"] = self._validation_layers(summary)
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
            f"- **cluster_runtime**: `{summary.get('cluster_runtime')}`",
            f"- **topology**: `{summary.get('topology')}`",
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

        playwright_validation = summary.get("playwright_validation") or {}
        playwright_summary = playwright_validation.get("summary") or {}
        if playwright_summary.get("total"):
            lines.extend([
                "",
                "## Playwright Validation",
                f"- Total tests/specs: `{playwright_summary.get('total', 0)}`",
                f"- Passed: `{playwright_summary.get('passed', 0)}`",
                f"- Failed: `{playwright_summary.get('failed', 0)}`",
                f"- Skipped: `{playwright_summary.get('skipped', 0)}`",
            ])

        component_validation = summary.get("component_validation") or {}
        component_summary = component_validation.get("summary") or {}
        pt5_summary = component_validation.get("pt5_summary") or {}
        if component_summary.get("total") or pt5_summary.get("total"):
            lines.extend([
                "",
                "## Component Validation",
                "",
                "| Component | Status | Total | Passed | Failed | Skipped | PT5 Passed/Total |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ])
            for component in component_validation.get("components") or []:
                counts = component.get("summary") or {}
                pt5 = component.get("pt5_summary") or {}
                lines.append(
                    f"| {component.get('title')} | `{component.get('status')}` | "
                    f"{counts.get('total', 0)} | {counts.get('passed', 0)} | "
                    f"{counts.get('failed', 0)} | {counts.get('skipped', 0)} | "
                    f"{pt5.get('passed', 0)}/{pt5.get('total', 0)} |"
                )

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

        kafka_transfer = summary.get("kafka_transfer") or {}
        kafka_transfer_summary = kafka_transfer.get("summary") or {}
        if kafka_transfer_summary.get("total"):
            lines.extend([
                "",
                "## Kafka Transfer",
                f"- Transfers passed: `{kafka_transfer_summary.get('passed', 0)}`",
                f"- Transfers failed: `{kafka_transfer_summary.get('failed', 0)}`",
                f"- Messages produced: `{kafka_transfer.get('messages_produced', 0)}`",
                f"- Messages consumed: `{kafka_transfer.get('messages_consumed', 0)}`",
                f"- Missing messages: `{kafka_transfer.get('messages_missing', 0)}`",
                f"- Average latency: `{kafka_transfer.get('average_latency_ms')}` ms",
            ])

        local_stability = summary.get("local_stability") or {}
        if local_stability.get("status") != "not_recorded":
            lines.extend([
                "",
                "## Local Stability",
                f"- Status: `{local_stability.get('status')}`",
                f"- New warnings: `{local_stability.get('new_warnings', 0)}`",
                f"- Snapshot warnings: `{local_stability.get('snapshot_warnings', 0)}`",
                f"- Blocking issues: `{local_stability.get('blocking_issues', 0)}`",
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

    @staticmethod
    def _counts_label(counts):
        counts = counts if isinstance(counts, dict) else {}
        total = int(counts.get("total") or counts.get("total_tests") or 0)
        passed = int(counts.get("passed") or counts.get("tests_passed") or 0)
        failed = int(counts.get("failed") or counts.get("tests_failed") or 0)
        skipped = int(counts.get("skipped") or 0)
        return f"{passed}/{total} passed, {failed} failed, {skipped} skipped"

    @staticmethod
    def _pass_rate(counts):
        counts = counts if isinstance(counts, dict) else {}
        total = int(counts.get("total") or counts.get("total_tests") or 0)
        passed = int(counts.get("passed") or counts.get("tests_passed") or 0)
        if total <= 0:
            return None
        return round((passed / total) * 100.0, 2)

    @staticmethod
    def _endpoint_latency_value(endpoint_table, endpoint):
        stats = (endpoint_table or {}).get(endpoint, {}) or {}
        for key in ("average_latency_ms", "mean_latency", "avg_latency_ms", "average"):
            value = ExperimentReportGenerator._number(stats.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _short_endpoint_label(endpoint):
        raw = str(endpoint or "").strip()
        if not raw:
            return "<unknown>"
        parts = [part for part in raw.split("/") if part]
        cleaned = []
        for part in parts:
            lowered = part.lower()
            looks_like_id = (
                re.fullmatch(r"[0-9a-f]{8,}(?:-[0-9a-f]{4,})*", lowered)
                or re.fullmatch(r"[a-z0-9_-]{24,}", lowered)
                or (len(part) > 28 and any(char.isdigit() for char in part))
            )
            cleaned.append("{id}" if looks_like_id else part)
        label = "/" + "/".join(cleaned) if raw.startswith("/") else "/".join(cleaned)
        return label if len(label) <= 72 else f"{label[:69]}..."

    @classmethod
    def _endpoint_latency_rows(cls, table_a, table_b, max_rows=12):
        grouped = {}
        for endpoint in sorted(set(table_a or {}) | set(table_b or {})):
            label = cls._short_endpoint_label(endpoint)
            entry = grouped.setdefault(label, {"a": [], "b": []})
            value_a = cls._endpoint_latency_value(table_a, endpoint)
            value_b = cls._endpoint_latency_value(table_b, endpoint)
            if value_a is not None:
                entry["a"].append(value_a)
            if value_b is not None:
                entry["b"].append(value_b)

        rows = []
        for label, values in grouped.items():
            average_a = cls._average(values["a"]) or 0
            average_b = cls._average(values["b"]) or 0
            rows.append((label, average_a, average_b, max(average_a, average_b)))
        rows.sort(key=lambda item: item[3], reverse=True)
        return rows[:max_rows]

    @staticmethod
    def _annotate_bars(axis, bars, labels):
        for bar, label in zip(bars, labels):
            height = bar.get_height()
            axis.annotate(
                label,
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    @staticmethod
    def _annotate_horizontal_bars(axis, bars, labels):
        for bar, label in zip(bars, labels):
            width = bar.get_width()
            axis.annotate(
                label,
                xy=(width, bar.get_y() + bar.get_height() / 2),
                xytext=(4, 0),
                textcoords="offset points",
                ha="left",
                va="center",
                fontsize=8,
            )

    @staticmethod
    def _graph_data_uri(comparison_dir, graph):
        if not comparison_dir:
            return None
        path = Path(comparison_dir) / "graphs" / str(graph)
        if not path.is_file():
            return None
        try:
            payload = base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception:
            return None
        return f"data:image/png;base64,{payload}"

    @classmethod
    def _comparison_metrics(cls, summary_a, summary_b):
        layers_a = summary_a.get("validation_layers") or cls._validation_layers(summary_a)
        layers_b = summary_b.get("validation_layers") or cls._validation_layers(summary_b)
        layer_rows = []
        for layer in sorted(set(layers_a) | set(layers_b)):
            counts_a = layers_a.get(layer) or cls._empty_counts()
            counts_b = layers_b.get(layer) or cls._empty_counts()
            rate_a = cls._pass_rate(counts_a)
            rate_b = cls._pass_rate(counts_b)
            layer_rows.append(
                {
                    "layer": layer,
                    "experiment_a": counts_a,
                    "experiment_b": counts_b,
                    "pass_rate_a": rate_a,
                    "pass_rate_b": rate_b,
                    "pass_rate_delta": round(rate_b - rate_a, 2) if rate_a is not None and rate_b is not None else None,
                }
            )

        components_a = {
            item.get("component") or item.get("title"): item
            for item in (summary_a.get("component_validation") or {}).get("components") or []
        }
        components_b = {
            item.get("component") or item.get("title"): item
            for item in (summary_b.get("component_validation") or {}).get("components") or []
        }
        component_rows = []
        for component in sorted(set(components_a) | set(components_b)):
            item_a = components_a.get(component) or {}
            item_b = components_b.get(component) or {}
            counts_a = item_a.get("summary") or cls._empty_counts()
            counts_b = item_b.get("summary") or cls._empty_counts()
            component_rows.append(
                {
                    "component": component,
                    "title": item_b.get("title") or item_a.get("title") or component,
                    "experiment_a": counts_a,
                    "experiment_b": counts_b,
                    "pass_rate_a": cls._pass_rate(counts_a),
                    "pass_rate_b": cls._pass_rate(counts_b),
                    "pt5_a": item_a.get("pt5_summary") or cls._empty_counts(),
                    "pt5_b": item_b.get("pt5_summary") or cls._empty_counts(),
                }
            )

        kafka_a = summary_a.get("kafka_transfer") or {}
        kafka_b = summary_b.get("kafka_transfer") or {}
        stability_a = summary_a.get("local_stability") or {}
        stability_b = summary_b.get("local_stability") or {}
        return {
            "validation_layers": layer_rows,
            "components": component_rows,
            "kafka_transfer": {
                "experiment_a": kafka_a,
                "experiment_b": kafka_b,
                "messages_consumed_delta": int(kafka_b.get("messages_consumed") or 0) - int(kafka_a.get("messages_consumed") or 0),
                "missing_messages_delta": int(kafka_b.get("messages_missing") or 0) - int(kafka_a.get("messages_missing") or 0),
            },
            "local_stability": {
                "experiment_a": stability_a,
                "experiment_b": stability_b,
                "new_warnings_delta": int(stability_b.get("new_warnings") or 0) - int(stability_a.get("new_warnings") or 0),
                "blocking_issues_delta": int(stability_b.get("blocking_issues") or 0) - int(stability_a.get("blocking_issues") or 0),
            },
        }

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

        endpoint_rows = self._endpoint_latency_rows(
            summary_a.get("endpoint_latency_table") or {},
            summary_b.get("endpoint_latency_table") or {},
        )
        generated = {}
        if endpoint_rows:
            labels = [row[0] for row in endpoint_rows]
            values_a = [row[1] for row in endpoint_rows]
            values_b = [row[2] for row in endpoint_rows]
            positions = list(range(len(labels)))
            height = 0.35
            figure_height = max(5.0, 2.6 + len(labels) * 0.46)
            figure, axis = plt.subplots(figsize=(12, figure_height))
            bars_a = axis.barh([p - height / 2 for p in positions], values_a, height=height, label="Experiment A")
            bars_b = axis.barh([p + height / 2 for p in positions], values_b, height=height, label="Experiment B")
            axis.set_yticks(positions)
            axis.set_yticklabels(labels)
            axis.invert_yaxis()
            axis.set_xlabel("Average latency (ms)")
            axis.set_title("Endpoint latency comparison (top routes)")
            axis.legend()
            axis.grid(axis="x", alpha=0.2)
            self._annotate_horizontal_bars(axis, bars_a, [f"{value:.1f}" if value else "" for value in values_a])
            self._annotate_horizontal_bars(axis, bars_b, [f"{value:.1f}" if value else "" for value in values_b])
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
            bars_a = axis.bar([p - width / 2 for p in positions], values_a, width=width, label="Experiment A")
            bars_b = axis.bar([p + width / 2 for p in positions], values_b, width=width, label="Experiment B")
            axis.set_xticks(positions)
            axis.set_xticklabels(labels)
            axis.set_ylabel("Latency (ms)")
            axis.set_title("Kafka percentile comparison")
            axis.legend()
            self._annotate_bars(axis, bars_a, [str(value) for value in values_a])
            self._annotate_bars(axis, bars_b, [str(value) for value in values_b])
            figure.tight_layout()
            path = os.path.join(graphs_dir, "kafka_percentiles_comparison.png")
            figure.savefig(path, dpi=180)
            plt.close(figure)
            generated["kafka_percentiles_comparison"] = path

        layers_a = summary_a.get("validation_layers") or self._validation_layers(summary_a)
        layers_b = summary_b.get("validation_layers") or self._validation_layers(summary_b)
        layer_names = [
            name for name in ("Newman", "INESData/EDC UI", "Components", "PT5 cases", "Kafka transfer")
            if (layers_a.get(name) or {}).get("total") or (layers_b.get(name) or {}).get("total")
        ]
        if layer_names:
            values_a = [int((layers_a.get(name) or {}).get("passed") or 0) for name in layer_names]
            values_b = [int((layers_b.get(name) or {}).get("passed") or 0) for name in layer_names]
            totals_a = [int((layers_a.get(name) or {}).get("total") or 0) for name in layer_names]
            totals_b = [int((layers_b.get(name) or {}).get("total") or 0) for name in layer_names]
            positions = list(range(len(layer_names)))
            width = 0.35
            figure, axis = plt.subplots(figsize=(12, 6))
            bars_a = axis.bar([p - width / 2 for p in positions], values_a, width=width, label="Experiment A")
            bars_b = axis.bar([p + width / 2 for p in positions], values_b, width=width, label="Experiment B")
            axis.set_xticks(positions)
            axis.set_xticklabels(layer_names, rotation=0, ha="center")
            axis.set_ylim(0, max(values_a + values_b + totals_a + totals_b + [1]) * 1.12)
            axis.set_ylabel("Passed validations")
            axis.set_title("A5.2 validation scope comparison")
            axis.legend()
            self._annotate_bars(axis, bars_a, [f"{value}/{total}" for value, total in zip(values_a, totals_a)])
            self._annotate_bars(axis, bars_b, [f"{value}/{total}" for value, total in zip(values_b, totals_b)])
            figure.tight_layout()
            path = os.path.join(graphs_dir, "validation_scope_comparison.png")
            figure.savefig(path, dpi=180)
            plt.close(figure)
            generated["validation_scope_comparison"] = path

        metrics = self._comparison_metrics(summary_a, summary_b)
        component_rows = [row for row in metrics["components"] if row.get("pass_rate_a") is not None or row.get("pass_rate_b") is not None]
        if component_rows:
            labels = [row["title"] for row in component_rows]
            values_a = [row.get("pass_rate_a") or 0 for row in component_rows]
            values_b = [row.get("pass_rate_b") or 0 for row in component_rows]
            positions = list(range(len(labels)))
            width = 0.35
            figure, axis = plt.subplots(figsize=(12, 6))
            bars_a = axis.bar([p - width / 2 for p in positions], values_a, width=width, label="Experiment A")
            bars_b = axis.bar([p + width / 2 for p in positions], values_b, width=width, label="Experiment B")
            axis.set_xticks(positions)
            axis.set_xticklabels(labels, rotation=0, ha="center")
            axis.set_ylim(0, 105)
            axis.set_ylabel("Pass rate (%)")
            axis.set_title("Component validation pass rate")
            axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2)
            self._annotate_bars(axis, bars_a, [f"{value:.1f}%" for value in values_a])
            self._annotate_bars(axis, bars_b, [f"{value:.1f}%" for value in values_b])
            figure.tight_layout()
            path = os.path.join(graphs_dir, "component_pass_rate_comparison.png")
            figure.savefig(path, dpi=180)
            plt.close(figure)
            generated["component_pass_rate_comparison"] = path

        kafka_transfer_a = summary_a.get("kafka_transfer") or {}
        kafka_transfer_b = summary_b.get("kafka_transfer") or {}
        if (kafka_transfer_a.get("summary") or {}).get("total") or (kafka_transfer_b.get("summary") or {}).get("total"):
            labels = ["Experiment A", "Experiment B"]
            produced = [int(kafka_transfer_a.get("messages_produced") or 0), int(kafka_transfer_b.get("messages_produced") or 0)]
            consumed = [int(kafka_transfer_a.get("messages_consumed") or 0), int(kafka_transfer_b.get("messages_consumed") or 0)]
            positions = list(range(len(labels)))
            width = 0.35
            figure, axis = plt.subplots(figsize=(9, 5))
            bars_a = axis.bar([p - width / 2 for p in positions], produced, width=width, label="produced")
            bars_b = axis.bar([p + width / 2 for p in positions], consumed, width=width, label="consumed")
            axis.set_xticks(positions)
            axis.set_xticklabels(labels)
            axis.set_ylim(0, max(produced + consumed + [1]) * 1.15)
            axis.set_ylabel("Messages")
            axis.set_title("Kafka transfer produced vs consumed")
            axis.legend()
            self._annotate_bars(axis, bars_a, [str(value) for value in produced])
            self._annotate_bars(axis, bars_b, [str(value) for value in consumed])
            figure.tight_layout()
            path = os.path.join(graphs_dir, "kafka_transfer_messages_comparison.png")
            figure.savefig(path, dpi=180)
            plt.close(figure)
            generated["kafka_transfer_messages_comparison"] = path

        return generated

    @classmethod
    def _build_comparison_markdown(cls, summary_a, summary_b, metrics, graphs):
        lines = [
            f"# Experiment Comparison: {summary_a['experiment_id']} vs {summary_b['experiment_id']}",
            "",
            "## Executive Summary",
            "",
            "| Field | Experiment A | Experiment B |",
            "| --- | --- | --- |",
            f"| Adapter | `{summary_a.get('adapter')}` | `{summary_b.get('adapter')}` |",
            f"| Topology | `{summary_a.get('topology')}` | `{summary_b.get('topology')}` |",
            f"| Cluster runtime | `{summary_a.get('cluster_runtime')}` | `{summary_b.get('cluster_runtime')}` |",
            f"| Timestamp | `{summary_a.get('timestamp')}` | `{summary_b.get('timestamp')}` |",
            "",
            "## A5.2 Validation Scope",
            "",
            "| Layer | Experiment A | Experiment B | Pass-rate delta |",
            "| --- | ---: | ---: | ---: |",
        ]
        for row in metrics["validation_layers"]:
            delta = row.get("pass_rate_delta")
            delta_label = "n/a" if delta is None else f"{delta:+.2f} pp"
            lines.append(
                f"| {row['layer']} | {cls._counts_label(row['experiment_a'])} | "
                f"{cls._counts_label(row['experiment_b'])} | {delta_label} |"
            )

        component_rows = metrics.get("components") or []
        if component_rows:
            lines.extend([
                "",
                "## Component Coverage",
                "",
                "| Component | Experiment A | Experiment B | PT5 A | PT5 B |",
                "| --- | ---: | ---: | ---: | ---: |",
            ])
            for row in component_rows:
                lines.append(
                    f"| {row['title']} | {cls._counts_label(row['experiment_a'])} | "
                    f"{cls._counts_label(row['experiment_b'])} | "
                    f"{cls._counts_label(row['pt5_a'])} | {cls._counts_label(row['pt5_b'])} |"
                )

        kafka = metrics.get("kafka_transfer") or {}
        kafka_a = kafka.get("experiment_a") or {}
        kafka_b = kafka.get("experiment_b") or {}
        if (kafka_a.get("summary") or {}).get("total") or (kafka_b.get("summary") or {}).get("total"):
            lines.extend([
                "",
                "## Kafka Transfer",
                "",
                "| Metric | Experiment A | Experiment B | Delta |",
                "| --- | ---: | ---: | ---: |",
                f"| Transfers | {cls._counts_label(kafka_a.get('summary'))} | {cls._counts_label(kafka_b.get('summary'))} | n/a |",
                f"| Messages consumed | {kafka_a.get('messages_consumed', 0)} | {kafka_b.get('messages_consumed', 0)} | {kafka.get('messages_consumed_delta', 0):+d} |",
                f"| Missing messages | {kafka_a.get('messages_missing', 0)} | {kafka_b.get('messages_missing', 0)} | {kafka.get('missing_messages_delta', 0):+d} |",
                f"| Average latency ms | {kafka_a.get('average_latency_ms')} | {kafka_b.get('average_latency_ms')} | n/a |",
            ])

        stability = metrics.get("local_stability") or {}
        stability_a = stability.get("experiment_a") or {}
        stability_b = stability.get("experiment_b") or {}
        if stability_a.get("status") != "not_recorded" or stability_b.get("status") != "not_recorded":
            lines.extend([
                "",
                "## Local Stability",
                "",
                "| Metric | Experiment A | Experiment B | Delta |",
                "| --- | ---: | ---: | ---: |",
                f"| Status | `{stability_a.get('status')}` | `{stability_b.get('status')}` | n/a |",
                f"| New warnings | {stability_a.get('new_warnings', 0)} | {stability_b.get('new_warnings', 0)} | {stability.get('new_warnings_delta', 0):+d} |",
                f"| Blocking issues | {stability_a.get('blocking_issues', 0)} | {stability_b.get('blocking_issues', 0)} | {stability.get('blocking_issues_delta', 0):+d} |",
            ])

        lines.extend(["", "## Graphs"])
        if graphs:
            for graph in graphs:
                lines.append(f"![{graph}](graphs/{graph})")
        else:
            lines.append("No comparison graphs generated.")
        return "\n".join(lines) + "\n"

    @classmethod
    def _build_comparison_html(cls, summary_a, summary_b, metrics, graphs, comparison_dir=None):
        def esc(value):
            return html.escape(str(value if value is not None else ""))

        def table(headers, rows):
            head = "".join(f"<th>{esc(header)}</th>" for header in headers)
            body = "\n".join(
                "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

        layer_rows = [
            [
                esc(row["layer"]),
                esc(cls._counts_label(row["experiment_a"])),
                esc(cls._counts_label(row["experiment_b"])),
                esc("n/a" if row.get("pass_rate_delta") is None else f"{row['pass_rate_delta']:+.2f} pp"),
            ]
            for row in metrics["validation_layers"]
        ]
        component_rows = [
            [
                esc(row["title"]),
                esc(cls._counts_label(row["experiment_a"])),
                esc(cls._counts_label(row["experiment_b"])),
                esc(cls._counts_label(row["pt5_a"])),
                esc(cls._counts_label(row["pt5_b"])),
            ]
            for row in metrics.get("components") or []
        ]
        kafka = metrics.get("kafka_transfer") or {}
        kafka_a = kafka.get("experiment_a") or {}
        kafka_b = kafka.get("experiment_b") or {}
        kafka_section = ""
        if (kafka_a.get("summary") or {}).get("total") or (kafka_b.get("summary") or {}).get("total"):
            kafka_rows = [
                [
                    esc("Transfers"),
                    esc(cls._counts_label(kafka_a.get("summary"))),
                    esc(cls._counts_label(kafka_b.get("summary"))),
                    esc("n/a"),
                ],
                [
                    esc("Messages consumed"),
                    esc(kafka_a.get("messages_consumed", 0)),
                    esc(kafka_b.get("messages_consumed", 0)),
                    esc(f"{kafka.get('messages_consumed_delta', 0):+d}"),
                ],
                [
                    esc("Missing messages"),
                    esc(kafka_a.get("messages_missing", 0)),
                    esc(kafka_b.get("messages_missing", 0)),
                    esc(f"{kafka.get('missing_messages_delta', 0):+d}"),
                ],
                [
                    esc("Average latency ms"),
                    esc(kafka_a.get("average_latency_ms")),
                    esc(kafka_b.get("average_latency_ms")),
                    esc("n/a"),
                ],
            ]
            kafka_section = f"""
  <section>
    <h2>Kafka Transfer</h2>
    {table(["Metric", "Experiment A", "Experiment B", "Delta"], kafka_rows)}
  </section>"""
        stability = metrics.get("local_stability") or {}
        stability_a = stability.get("experiment_a") or {}
        stability_b = stability.get("experiment_b") or {}
        stability_section = ""
        if stability_a.get("status") != "not_recorded" or stability_b.get("status") != "not_recorded":
            stability_rows = [
                [esc("Status"), esc(stability_a.get("status")), esc(stability_b.get("status")), esc("n/a")],
                [
                    esc("New warnings"),
                    esc(stability_a.get("new_warnings", 0)),
                    esc(stability_b.get("new_warnings", 0)),
                    esc(f"{stability.get('new_warnings_delta', 0):+d}"),
                ],
                [
                    esc("Blocking issues"),
                    esc(stability_a.get("blocking_issues", 0)),
                    esc(stability_b.get("blocking_issues", 0)),
                    esc(f"{stability.get('blocking_issues_delta', 0):+d}"),
                ],
            ]
            stability_section = f"""
  <section>
    <h2>Local Stability</h2>
    {table(["Metric", "Experiment A", "Experiment B", "Delta"], stability_rows)}
  </section>"""
        graph_figures = []
        for graph in graphs:
            source = cls._graph_data_uri(comparison_dir, graph) or f"graphs/{graph}"
            graph_figures.append(
                f"<figure><img src='{esc(source)}' alt='{esc(graph)}'><figcaption>{esc(graph)}</figcaption></figure>"
            )
        graph_html = "\n".join(graph_figures) or "<p>No comparison graphs generated.</p>"
        title = f"{summary_a['experiment_id']} vs {summary_b['experiment_id']}"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} - Comparison</title>
  <style>
    :root {{
      --ink: #18212f;
      --muted: #667085;
      --paper: #f8fafc;
      --panel: #ffffff;
      --line: #d0d5dd;
      --accent: #145c66;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: "Aptos", "Segoe UI", sans-serif; line-height: 1.5; }}
    main {{ width: min(100%, 1680px); margin: 0 auto; padding: 32px clamp(16px, 2vw, 36px) 72px; }}
    h1 {{ margin: 0 0 8px; font-size: 2.4rem; letter-spacing: 0; }}
    h2 {{ margin: 32px 0 14px; }}
    p {{ color: var(--muted); }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin-top: 18px; overflow-x: auto; padding: 20px; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 760px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: .78rem; text-transform: uppercase; }}
    .cards {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .card span {{ color: var(--muted); display: block; font-size: .85rem; }}
    .card strong {{ display: block; margin-top: 4px; overflow-wrap: anywhere; }}
    figure {{ margin: 18px 0 0; }}
    img {{ background: white; border: 1px solid var(--line); border-radius: 8px; display: block; height: auto; max-width: 100%; }}
    figcaption {{ color: var(--muted); font-size: .88rem; margin-top: 6px; }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>{esc(title)}</h1>
    <p>Experiment comparison report for A5.2 validation evidence.</p>
  </header>
  <div class="cards">
    <div class="card"><span>Experiment A</span><strong>{esc(summary_a['experiment_id'])}</strong></div>
    <div class="card"><span>Experiment B</span><strong>{esc(summary_b['experiment_id'])}</strong></div>
    <div class="card"><span>Adapter</span><strong>{esc(summary_a.get('adapter'))} / {esc(summary_b.get('adapter'))}</strong></div>
    <div class="card"><span>Topology</span><strong>{esc(summary_a.get('topology'))} / {esc(summary_b.get('topology'))}</strong></div>
  </div>
  <section>
    <h2>A5.2 Validation Scope</h2>
    {table(["Layer", "Experiment A", "Experiment B", "Pass-rate delta"], layer_rows)}
  </section>
  <section>
    <h2>Component Coverage</h2>
    {table(["Component", "Experiment A", "Experiment B", "PT5 A", "PT5 B"], component_rows) if component_rows else "<p>No component metrics detected.</p>"}
  </section>
  {kafka_section}
  {stability_section}
  <section>
    <h2>Graphs</h2>
    {graph_html}
  </section>
</main>
</body>
</html>
"""

    def compare(self, experiment_a, experiment_b, output_dir=None):
        summary_a = self.build_summary(ExperimentLoader.experiment_dir(experiment_a))
        summary_b = self.build_summary(ExperimentLoader.experiment_dir(experiment_b))
        comparison_dir = output_dir or self.storage.create_comparison_directory(
            summary_a["experiment_id"],
            summary_b["experiment_id"],
        )
        graphs = self._build_comparison_graphs(comparison_dir, summary_a, summary_b)
        graph_names = sorted(os.path.basename(path) for path in graphs.values())
        metrics = self._comparison_metrics(summary_a, summary_b)
        comparison = {
            "experiment_a": summary_a,
            "experiment_b": summary_b,
            "metrics": metrics,
            "graphs": graph_names,
        }
        markdown = self._build_comparison_markdown(summary_a, summary_b, metrics, graph_names)
        html_report = self._build_comparison_html(summary_a, summary_b, metrics, graph_names, comparison_dir=comparison_dir)

        self.storage.save_comparison_json(comparison, comparison_dir)
        self.storage.save_comparison_markdown(markdown, comparison_dir)
        save_html = getattr(self.storage, "save_comparison_html", None)
        if callable(save_html):
            save_html(html_report, comparison_dir)
        return {"comparison_dir": comparison_dir, **comparison}
