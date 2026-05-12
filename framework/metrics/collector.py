import json
import os
import re

from .aggregator import MetricsAggregator
from .negotiation_parser import NegotiationLogParser


class ExperimentMetricsCollector:
    """Collect experiment metrics from Newman reports and connector logs."""

    NEGOTIATION_HINTS = {
        "catalog_latency_ms": {"catalog", "federated catalog", "direct dsp catalog"},
        "negotiation_latency_ms": {"contract negotiation", "negotiation status"},
        "transfer_latency_ms": {"transfer process", "transfer status", "endpoint data reference"},
    }

    @staticmethod
    def _extract_run_index(report_path):
        normalized = str(report_path).replace("\\", "/")
        match = re.findall(r"run_(\d+)", normalized)
        return int(match[-1]) if match else 1

    @staticmethod
    def _load_report(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def load_newman_reports(cls, report_dir):
        reports = []
        if not report_dir or not os.path.isdir(report_dir):
            return reports
        for root, _, files in os.walk(report_dir):
            for file_name in sorted(files):
                if file_name.endswith(".json"):
                    path = os.path.join(root, file_name)
                    reports.append({"path": path, "report": cls._load_report(path)})
        return reports

    @classmethod
    def extract_request_metrics(cls, reports, experiment_id=None):
        metrics = []
        for item in reports:
            report_path = item["path"]
            report = item["report"]
            collection_name = report.get("collection", {}).get("info", {}).get("name") or os.path.splitext(os.path.basename(report_path))[0]
            run_index = cls._extract_run_index(report_path)

            for execution in report.get("run", {}).get("executions", []) or []:
                request = execution.get("request", {}) or {}
                request_url = request.get("url", {}) or {}
                response = execution.get("response", {}) or {}
                cursor = execution.get("cursor", {}) or {}
                item_name = (execution.get("item") or {}).get("name") or execution.get("id") or "unknown_request"

                endpoint = request_url.get("raw") if isinstance(request_url, dict) else request_url
                if isinstance(request_url, dict) and not endpoint:
                    path_parts = request_url.get("path") or []
                    endpoint = "/" + "/".join(str(part) for part in path_parts) if path_parts else None

                metrics.append({
                    "timestamp": cursor.get("started") or response.get("timestamp") or request.get("timestamp"),
                    "endpoint": endpoint,
                    "method": request.get("method"),
                    "status_code": response.get("code"),
                    "latency_ms": response.get("responseTime"),
                    "iteration": run_index,
                    "run_index": run_index,
                    "request_name": item_name,
                    "collection": collection_name,
                    "experiment_id": experiment_id,
                })
        return metrics

    @classmethod
    def extract_test_results(cls, reports):
        results = []
        for item in reports:
            report_path = item["path"]
            report = item["report"]
            run_index = cls._extract_run_index(report_path)
            failures = report.get("run", {}).get("failures", []) or []
            failed_keys = set()

            for failure in failures:
                source = failure.get("source", {}) or {}
                request = source.get("name") or failure.get("source", {}).get("id") or "unknown_request"
                test_name = failure.get("error", {}).get("test") or failure.get("error", {}).get("name") or failure.get("parent", {}).get("name") or "unknown_test"
                key = (request, test_name)
                failed_keys.add(key)
                results.append({
                    "test_name": test_name,
                    "endpoint": request,
                    "status": "fail",
                    "error_message": failure.get("error", {}).get("message"),
                    "iteration": run_index,
                })

            for execution in report.get("run", {}).get("executions", []) or []:
                request_name = (execution.get("item") or {}).get("name") or "unknown_request"
                for assertion in execution.get("assertions", []) or []:
                    test_name = assertion.get("assertion") or "unknown_test"
                    key = (request_name, test_name)
                    if key in failed_keys:
                        continue
                    results.append({
                        "test_name": test_name,
                        "endpoint": request_name,
                        "status": "pass",
                        "error_message": None,
                        "iteration": run_index,
                    })
        return results

    @classmethod
    def extract_negotiation_metrics(cls, request_metrics, log_metrics=None):
        grouped = {}
        for item in request_metrics or []:
            iteration = item.get("iteration") or item.get("run_index") or 1
            request_name = str(item.get("request_name") or "").lower()
            try:
                latency = float(item.get("latency_ms"))
            except (TypeError, ValueError):
                continue

            record = grouped.setdefault(iteration, {"iteration": iteration})
            for field_name, hints in cls.NEGOTIATION_HINTS.items():
                if any(hint in request_name for hint in hints):
                    record.setdefault(field_name, []).append(latency)

        metrics = []
        for iteration in sorted(grouped):
            record = {"iteration": iteration}
            for field_name, values in grouped[iteration].items():
                if field_name == "iteration":
                    continue
                if isinstance(values, list) and values:
                    record[field_name] = round(sum(values) / len(values), 2)
            metrics.append(record)

        for item in log_metrics or []:
            iteration = item.get("iteration") or 1
            target = next((entry for entry in metrics if entry.get("iteration") == iteration), None)
            if target is None:
                target = {"iteration": iteration}
                metrics.append(target)
            for key, value in item.items():
                if key != "iteration":
                    target[key] = value

        return sorted(metrics, key=lambda item: item.get("iteration", 0))

    @classmethod
    def collect_connector_log_metrics(cls, connector_logs):
        metrics = []
        for connector_name, log_text in (connector_logs or {}).items():
            metrics.extend(NegotiationLogParser.parse_log_text(log_text, connector_name=connector_name))
        return metrics

    @classmethod
    def build_artifacts(cls, report_dir, experiment_id=None, connector_logs=None):
        reports = cls.load_newman_reports(report_dir)
        request_metrics = cls.extract_request_metrics(reports, experiment_id=experiment_id)
        test_results = cls.extract_test_results(reports)
        newman_results = [item["report"] for item in reports]
        log_metrics = cls.collect_connector_log_metrics(connector_logs)
        negotiation_metrics = cls.extract_negotiation_metrics(request_metrics, log_metrics=log_metrics)
        aggregated_metrics = MetricsAggregator.aggregate_request_metrics(request_metrics)
        aggregated_negotiation_metrics = MetricsAggregator.aggregate_negotiation_metrics(negotiation_metrics)
        return {
            "newman_results": newman_results,
            "raw_requests": request_metrics,
            "test_results": test_results,
            "negotiation_metrics": negotiation_metrics,
            "aggregated_metrics": aggregated_metrics,
            "aggregated_negotiation_metrics": aggregated_negotiation_metrics,
            "connector_log_metrics": log_metrics,
        }
