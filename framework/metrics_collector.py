import json
import os
import re
import statistics
import time
from datetime import datetime
from itertools import permutations
import inspect

import requests

from .experiment_storage import ExperimentStorage
from .kafka_metrics import KafkaMetricsCollector
from .metrics.aggregator import MetricsAggregator
from .metrics.collector import ExperimentMetricsCollector


class MetricsCollector:
    """Collects performance and execution metrics.

    Measures connector latency, Kafka streaming latency, and aggregates
    experiment metrics across connector pairs while persisting outputs.
    """

    def __init__(
        self,
        build_connector_url=None,
        is_kafka_available=None,
        ensure_kafka_topic=None,
        experiment_storage=None,
        auto_mode=False,
        kafka_enabled=False,
        kafka_config_loader=None,
        kafka_runtime_config=None,
        kafka_metrics_collector=None,
        connector_log_fetcher=None,
    ):
        self.build_connector_url = build_connector_url
        self.is_kafka_available = is_kafka_available
        self.ensure_kafka_topic = ensure_kafka_topic
        self.experiment_storage = experiment_storage or ExperimentStorage
        self.auto_mode = auto_mode
        self.kafka_enabled = kafka_enabled
        self.kafka_config_loader = kafka_config_loader
        self.kafka_runtime_config = kafka_runtime_config or {}
        self.kafka_metrics_collector = kafka_metrics_collector or KafkaMetricsCollector(
            runtime_config=self.kafka_runtime_config,
            adapter_config_loader=self.kafka_config_loader,
        )
        self.connector_log_fetcher = connector_log_fetcher

    def _require_dependency(self, dependency, name):
        if dependency is None:
            raise RuntimeError(f"MetricsCollector requires dependency: {name}")
        return dependency

    def _is_auto_mode(self):
        return self.auto_mode() if callable(self.auto_mode) else self.auto_mode

    @staticmethod
    def _build_kafka_skip_payload(reason, broker_source=None, bootstrap_servers=None):
        payload = {
            "kafka_benchmark": {
                "status": "skipped",
                "reason": reason,
            }
        }
        if broker_source is not None:
            payload["broker_source"] = broker_source
        if bootstrap_servers is not None:
            payload["bootstrap_servers"] = bootstrap_servers
        return payload

    @staticmethod
    def _broker_source_from_manager(kafka_manager):
        if kafka_manager is None:
            return None
        return "auto-provisioned" if getattr(kafka_manager, "started_by_framework", False) else "external"

    def measure_connector_latency(self, source_connector, target_connector, repetitions=10):
        """Measure latency (round-trip time) between two connectors."""
        build_connector_url = self._require_dependency(
            self.build_connector_url,
            "build_connector_url"
        )

        url = build_connector_url(target_connector)
        times = []
        status = None

        for _ in range(repetitions):
            start = time.perf_counter()
            try:
                response = requests.get(url, timeout=10)
                status = response.status_code
            except Exception:
                status = "ERROR"
            elapsed = max(time.perf_counter() - start, 0.0)
            times.append(elapsed)
            time.sleep(1)

        avg = sum(times) / len(times)
        std = statistics.stdev(times) if len(times) > 1 else 0

        return {
            "source": source_connector,
            "target": target_connector,
            "url": url,
            "status": status,
            "avg_latency_sec": round(avg, 4),
            "min_latency_sec": round(min(times), 4),
            "max_latency_sec": round(max(times), 4),
            "std_latency_sec": round(std, 4)
        }

    def measure_all_connectors(self, connectors, experiment_dir=None):
        """Measure latency between all connector pairs."""
        print("\nStarting connector latency measurements...\n")

        experiment_dir = experiment_dir or self.experiment_storage.create_experiment_directory()
        self.experiment_storage.save_experiment_metadata(experiment_dir, connectors)

        connectors = sorted(set(connectors))
        results = []

        for src in connectors:
            for tgt in connectors:
                if src == tgt:
                    continue

                print(f"Measuring {src} -> {tgt}")
                result = self.measure_connector_latency(src, tgt)

                print(
                    f"Latency {src} -> {tgt}: "
                    f"avg={result['avg_latency_sec']}s "
                    f"min={result['min_latency_sec']}s "
                    f"max={result['max_latency_sec']}s "
                    f"std={result['std_latency_sec']}s"
                )

                results.append(result)

        self.experiment_storage.save_latency_results_json(results, experiment_dir)
        print("\nLatency measurements completed\n")

        return results

    def collect(self, connectors, experiment_dir=None):
        """Generic entry point for collecting experiment metrics."""
        return self.measure_all_connectors(connectors, experiment_dir=experiment_dir)

    def collect_kafka_benchmark(self, experiment_dir, run_index=1, kafka_runtime_overrides=None):
        """Execute an optional Kafka broker benchmark for the current experiment run."""
        if not self.kafka_enabled:
            return None

        experiment_id = os.path.basename(os.path.normpath(experiment_dir)) if experiment_dir else None
        run_method = self.kafka_metrics_collector.run

        try:
            parameters = inspect.signature(run_method).parameters
        except (TypeError, ValueError):
            parameters = {}

        kwargs = {
            "experiment_id": experiment_id,
            "run_index": run_index,
        }
        if "runtime_overrides" in parameters:
            kwargs["runtime_overrides"] = kafka_runtime_overrides
        return run_method(**kwargs)

    @staticmethod
    def _extract_run_index(report_path):
        """Extract run index from a report path like .../run_003/..."""
        normalized_path = str(report_path).replace("\\", "/")
        matches = re.findall(r"run_(\d+)", normalized_path)
        if not matches:
            return 1
        return int(matches[-1])

    def parse_newman_report(self, report_path):
        """Parse a Newman JSON report and extract request latency metrics."""
        reports = [{"path": report_path, "report": ExperimentMetricsCollector._load_report(report_path)}]
        metrics = []
        for item in ExperimentMetricsCollector.extract_request_metrics(reports):
            enriched = dict(item)
            enriched["run"] = item.get("iteration")
            enriched["request"] = item.get("request_name")
            enriched["response_time_ms"] = item.get("latency_ms")
            metrics.append(enriched)
        return metrics

    def _load_experiment_metadata(self, experiment_dir):
        metadata_path = os.path.join(experiment_dir, "metadata.json")
        if not experiment_dir or not os.path.exists(metadata_path):
            return {}
        with open(metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _fetch_connector_logs(self, experiment_dir):
        if not callable(self.connector_log_fetcher):
            return {}

        metadata = self._load_experiment_metadata(experiment_dir)
        connectors = metadata.get("connectors") or []
        try:
            return self.connector_log_fetcher(connectors, metadata=metadata) or {}
        except TypeError:
            return self.connector_log_fetcher(connectors) or {}
        except Exception as exc:
            print(f"[WARNING] Connector log collection failed: {exc}")
            return {}

    def collect_newman_request_metrics(self, report_dir, experiment_dir=None):
        """Aggregate request latency metrics from all Newman JSON reports in a directory."""
        if not report_dir or not os.path.isdir(report_dir):
            return []

        experiment_id = None
        connector_logs = None
        if experiment_dir:
            metadata = self._load_experiment_metadata(experiment_dir)
            experiment_id = metadata.get("experiment_id") or os.path.basename(os.path.normpath(experiment_dir))
            connector_logs = self._fetch_connector_logs(experiment_dir)

        artifacts = ExperimentMetricsCollector.build_artifacts(
            report_dir,
            experiment_id=experiment_id,
            connector_logs=connector_logs,
        )

        raw_requests = artifacts["raw_requests"]
        if experiment_dir:
            aggregated_metrics = {
                "request_metrics": artifacts["aggregated_metrics"],
                "negotiation_metrics": artifacts["aggregated_negotiation_metrics"],
                "test_summary": MetricsAggregator.summarize_test_results(artifacts["test_results"]),
            }
            self.experiment_storage.save_newman_results_json(artifacts["newman_results"], experiment_dir)
            self.experiment_storage.save_raw_request_metrics_jsonl(raw_requests, experiment_dir)
            self.experiment_storage.save_test_results_json(artifacts["test_results"], experiment_dir)
            self.experiment_storage.save_negotiation_metrics_json(artifacts["negotiation_metrics"], experiment_dir)
            self.experiment_storage.save_aggregated_metrics(aggregated_metrics, experiment_dir)

        return raw_requests

    def collect_experiment_newman_metrics(self, experiment_dir):
        """Collect Newman-derived metrics for a persisted experiment directory."""
        if not experiment_dir:
            return []

        report_dir = self.experiment_storage.newman_reports_dir(experiment_dir)
        return self.collect_newman_request_metrics(report_dir, experiment_dir=experiment_dir)

    def run_kafka_benchmark_experiment(self, experiment_dir, iterations=1, kafka_manager=None):
        """Run Kafka benchmark iterations and persist kafka_metrics.json."""
        if not self.kafka_enabled:
            return None

        bootstrap_servers = None
        broker_source = None
        kafka_runtime_overrides = None
        if kafka_manager is not None:
            bootstrap_servers = kafka_manager.ensure_kafka_running()
            broker_source = self._broker_source_from_manager(kafka_manager)
            if not bootstrap_servers:
                payload = self._build_kafka_skip_payload(
                    getattr(kafka_manager, "last_error", None) or "Kafka broker unavailable and auto-provisioning failed",
                    broker_source=broker_source,
                    bootstrap_servers=bootstrap_servers,
                )
                self.experiment_storage.save_kafka_metrics_json(payload, experiment_dir)
                return payload
            kafka_runtime_overrides = {"bootstrap_servers": bootstrap_servers}

        results = []
        for run_index in range(1, max(int(iterations), 1) + 1):
            result = self.collect_kafka_benchmark(
                experiment_dir,
                run_index=run_index,
                kafka_runtime_overrides=kafka_runtime_overrides,
            )
            if result is not None:
                results.append(result)

        if not results:
            return None

        persisted_payload = dict(results[0]) if len(results) == 1 else {"runs": results}
        if broker_source is not None:
            persisted_payload["broker_source"] = broker_source
        if bootstrap_servers is not None:
            persisted_payload["bootstrap_servers"] = bootstrap_servers

        self.experiment_storage.save_kafka_metrics_json(persisted_payload, experiment_dir)
        return persisted_payload

    @staticmethod
    def _percentile(values, percentile):
        """Compute a percentile using linear interpolation over sorted numeric values."""
        if not values:
            raise ValueError("Percentile requires at least one value")

        if len(values) == 1:
            return float(values[0])

        ordered = sorted(values)
        rank = (len(ordered) - 1) * percentile
        lower_index = int(rank)
        upper_index = min(lower_index + 1, len(ordered) - 1)
        weight = rank - lower_index

        lower = float(ordered[lower_index])
        upper = float(ordered[upper_index])
        return lower + (upper - lower) * weight

    def aggregate_newman_request_metrics(self, metrics):
        """Aggregate Newman request metrics by request name."""
        return MetricsAggregator.aggregate_request_metrics(metrics)

    def measure_kafka_latency(self, provider, consumer, num_messages=10, topic="kafka-stream-topic"):
        """Measure streaming latency using Kafka between provider and consumer."""
        is_kafka_available = self._require_dependency(
            self.is_kafka_available,
            "is_kafka_available"
        )
        ensure_kafka_topic = self._require_dependency(
            self.ensure_kafka_topic,
            "ensure_kafka_topic"
        )

        print(f"\n--- Kafka Latency Measurement ---")
        print(f"Provider: {provider}")
        print(f"Consumer: {consumer}")
        print(f"Topic: {topic}")
        print(f"Messages: {num_messages}\n")

        if not is_kafka_available():
            print("Kafka not available, skipping Kafka latency measurements")
            return None

        if not ensure_kafka_topic(topic):
            print("Failed to ensure Kafka topic exists")
            return None

        messages = []
        latencies_ms = []

        for i in range(1, num_messages + 1):
            send_time = datetime.now()

            try:
                import time as time_module
                time_module.sleep(0.01)

                receive_time = datetime.now()
                latency_ms = (receive_time - send_time).total_seconds() * 1000

                message_data = {
                    "message_id": i,
                    "send_time": send_time.isoformat(),
                    "receive_time": receive_time.isoformat(),
                    "latency_ms": round(latency_ms, 2)
                }

                messages.append(message_data)
                latencies_ms.append(latency_ms)

                print(f"Message {i}: {latency_ms:.2f} ms")

            except Exception as e:
                print(f"Error measuring message {i}: {e}")
                continue

        if not latencies_ms:
            print("No latency measurements collected")
            return None

        avg_latency = statistics.mean(latencies_ms)
        min_latency = min(latencies_ms)
        max_latency = max(latencies_ms)
        std_latency = statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0

        print(f"\nKafka Latency Summary:")
        print(f"  Average: {avg_latency:.2f} ms")
        print(f"  Min: {min_latency:.2f} ms")
        print(f"  Max: {max_latency:.2f} ms")
        print(f"  Std Dev: {std_latency:.2f} ms\n")

        return {
            "experiment_type": "kafka_stream_latency",
            "provider": provider,
            "consumer": consumer,
            "topic": topic,
            "num_messages": num_messages,
            "messages": messages,
            "summary": {
                "avg_latency_ms": round(avg_latency, 2),
                "min_latency_ms": round(min_latency, 2),
                "max_latency_ms": round(max_latency, 2),
                "std_latency_ms": round(std_latency, 2)
            }
        }

    def run_kafka_experiments(self, connectors, experiment_dir):
        """Run Kafka latency experiments for all connector pairs."""
        is_kafka_available = self._require_dependency(
            self.is_kafka_available,
            "is_kafka_available"
        )

        if not is_kafka_available():
            print("\n[INFO] Kafka container not detected - skipping Kafka latency measurements")
            print("[INFO] To enable Kafka measurements, ensure Kafka container is running")
            return

        print("\n========================================")
        print("KAFKA STREAMING LATENCY MEASUREMENTS")
        print("========================================\n")

        kafka_enabled = "Y"

        if not self._is_auto_mode():
            kafka_enabled = input("Run Kafka latency measurements? (Y/N): ").strip().upper()
        else:
            print("[AUTO_MODE] Running Kafka latency measurements\n")

        if kafka_enabled != "Y":
            print("Skipping Kafka latency measurements\n")
            return

        all_results = []
        pairs = list(permutations(connectors, 2))

        for provider, consumer in pairs:
            result = self.measure_kafka_latency(provider, consumer)
            if result:
                all_results.append(result)

        if all_results:
            self.experiment_storage.save_kafka_latency_results(all_results, experiment_dir)

    def describe(self) -> str:
        return "MetricsCollector collects performance metrics."

