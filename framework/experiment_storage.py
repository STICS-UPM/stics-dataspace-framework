import json
import os
from datetime import datetime


class ExperimentStorage:
    """Persist experiment artifacts under experiments/<experiment_id>/."""

    @staticmethod
    def project_root():
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    @classmethod
    def experiments_base_dir(cls):
        return os.path.join(cls.project_root(), "experiments")

    @staticmethod
    def create_experiment_directory():
        """Create a unique timestamped directory for experiment results."""
        base_dir = ExperimentStorage.experiments_base_dir()
        os.makedirs(base_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        experiment_dir = os.path.join(base_dir, f"experiment_{timestamp}")
        suffix = 1
        while os.path.exists(experiment_dir):
            experiment_dir = os.path.join(base_dir, f"experiment_{timestamp}_{suffix:02d}")
            suffix += 1

        os.makedirs(experiment_dir, exist_ok=True)
        return experiment_dir

    @staticmethod
    def _write_json(path, payload):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path

    @staticmethod
    def _write_text(path, content):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    @staticmethod
    def save_experiment_metadata(
        experiment_dir,
        connectors,
        adapter=None,
        adapter_name=None,
        iterations=1,
        baseline=False,
        cluster="minikube",
        cluster_runtime=None,
        topology=None,
        environment=None,
    ):
        """Save normalized experiment metadata to metadata.json."""
        connectors = list(connectors or [])
        experiment_id = os.path.basename(os.path.normpath(experiment_dir))
        runtime = cluster_runtime or cluster
        metadata = {
            "experiment_id": experiment_id,
            "timestamp": datetime.now().isoformat(),
            "adapter": adapter,
            "adapter_name": adapter_name,
            "iterations": iterations,
            "baseline": bool(baseline),
            "topology": topology,
            "cluster": runtime,
            "cluster_runtime": runtime,
            "connectors": connectors,
            "environment": environment or runtime or "minikube",
            "num_connectors": len(connectors),
            "measurement_type": "connector_latency",
        }

        metadata_file = os.path.join(experiment_dir, "metadata.json")
        ExperimentStorage._write_json(metadata_file, metadata)
        print(f"Experiment metadata saved: {metadata_file}")
        return metadata_file

    @staticmethod
    def save_latency_results_json(results, experiment_dir):
        """Save connector latency measurement results to JSON file."""
        file_name = os.path.join(experiment_dir, "latency_results.json")

        formatted_results = []
        for r in results:
            formatted_results.append({
                "source": r["source"],
                "target": r["target"],
                "url": r["url"],
                "status": r["status"],
                "avg_latency_sec": r["avg_latency_sec"],
                "min_latency_sec": r["min_latency_sec"],
                "max_latency_sec": r["max_latency_sec"],
                "std_latency_sec": r["std_latency_sec"]
            })

        ExperimentStorage._write_json(file_name, formatted_results)

        print(f"Latency results saved to {file_name}")

    @staticmethod
    def save_kafka_latency_results(results, experiment_dir):
        """Save Kafka latency measurement results to JSON file."""
        if not results:
            return

        file_name = os.path.join(experiment_dir, "kafka_latency_results.json")

        ExperimentStorage._write_json(file_name, results)

        print(f"Kafka latency results saved to {file_name}")

    @staticmethod
    def newman_reports_dir(experiment_dir):
        """Return the directory used for Newman JSON reports."""
        report_dir = os.path.join(experiment_dir, "newman_reports")
        os.makedirs(report_dir, exist_ok=True)
        return report_dir

    @staticmethod
    def save_raw_request_metrics_jsonl(results, experiment_dir):
        """Persist raw request metrics as JSON Lines for pandas-friendly loading."""
        file_name = os.path.join(experiment_dir, "raw_requests.jsonl")

        with open(file_name, "w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

        print(f"Raw request metrics saved to {file_name}")
        return file_name

    @staticmethod
    def save_aggregated_metrics(results, experiment_dir):
        """Persist aggregated request latency statistics as human-readable JSON."""
        file_name = os.path.join(experiment_dir, "aggregated_metrics.json")
        ExperimentStorage._write_json(file_name, results)
        print(f"Aggregated metrics saved to {file_name}")
        return file_name

    @staticmethod
    def save_newman_request_metrics(results, experiment_dir):
        """Backward-compatible wrapper for raw Newman request metrics storage."""
        return ExperimentStorage.save_raw_request_metrics_jsonl(results, experiment_dir)

    @staticmethod
    def save_newman_results_json(results, experiment_dir):
        """Persist Newman JSON report payloads to newman_results.json."""
        file_name = os.path.join(experiment_dir, "newman_results.json")
        ExperimentStorage._write_json(file_name, results)
        print(f"Newman results saved to {file_name}")
        return file_name

    @staticmethod
    def save_negotiation_metrics_json(results, experiment_dir):
        """Persist negotiation metrics to negotiation_metrics.json."""
        file_name = os.path.join(experiment_dir, "negotiation_metrics.json")
        ExperimentStorage._write_json(file_name, results)
        print(f"Negotiation metrics saved to {file_name}")
        return file_name

    @staticmethod
    def save_test_results_json(results, experiment_dir):
        """Persist normalized test results to test_results.json."""
        file_name = os.path.join(experiment_dir, "test_results.json")
        ExperimentStorage._write_json(file_name, results)
        print(f"Test results saved to {file_name}")
        return file_name

    @staticmethod
    def save_kafka_metrics_json(results, experiment_dir):
        """Persist Kafka benchmark results to JSON."""
        file_name = os.path.join(experiment_dir, "kafka_metrics.json")
        ExperimentStorage._write_json(file_name, results)
        print(f"Kafka benchmark metrics saved to {file_name}")
        return file_name

    @staticmethod
    def save_kafka_edc_results_json(results, experiment_dir):
        """Persist Kafka transfer validation results to JSON."""
        file_name = os.path.join(experiment_dir, "kafka_transfer_results.json")
        legacy_file_name = os.path.join(experiment_dir, "kafka_edc_results.json")
        ExperimentStorage._write_json(file_name, results)
        ExperimentStorage._write_json(legacy_file_name, results)
        print(f"Kafka transfer validation results saved to {file_name}")
        return file_name

    @staticmethod
    def save_summary_json(results, experiment_dir):
        """Persist normalized experiment summary to summary.json."""
        file_name = os.path.join(experiment_dir, "summary.json")
        ExperimentStorage._write_json(file_name, results)
        print(f"Experiment summary saved to {file_name}")
        return file_name

    @staticmethod
    def save_summary_markdown(content, experiment_dir):
        """Persist human-readable experiment summary to summary.md."""
        file_name = os.path.join(experiment_dir, "summary.md")
        ExperimentStorage._write_text(file_name, content)
        print(f"Experiment markdown summary saved to {file_name}")
        return file_name

    @staticmethod
    def create_comparison_directory(experiment_a, experiment_b):
        """Create a unique directory for experiment comparisons."""
        base_dir = os.path.join(ExperimentStorage.experiments_base_dir(), "comparisons")
        os.makedirs(base_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_a = os.path.basename(os.path.normpath(str(experiment_a)))
        safe_b = os.path.basename(os.path.normpath(str(experiment_b)))
        comparison_dir = os.path.join(base_dir, f"comparison_{timestamp}_{safe_a}__vs__{safe_b}")
        os.makedirs(comparison_dir, exist_ok=True)
        return comparison_dir

    @staticmethod
    def save_comparison_json(results, comparison_dir, file_name="comparison_summary.json"):
        path = os.path.join(comparison_dir, file_name)
        ExperimentStorage._write_json(path, results)
        print(f"Comparison summary saved to {path}")
        return path

    @staticmethod
    def save_comparison_markdown(content, comparison_dir, file_name="comparison_report.md"):
        path = os.path.join(comparison_dir, file_name)
        ExperimentStorage._write_text(path, content)
        print(f"Comparison markdown report saved to {path}")
        return path

    @staticmethod
    def save(results, experiment_dir=None, file_name="experiment_results.json"):
        """Save a generic experiment result bundle to JSON."""
        experiment_dir = experiment_dir or ExperimentStorage.create_experiment_directory()
        file_path = os.path.join(experiment_dir, file_name)
        ExperimentStorage._write_json(file_path, results)
        print(f"Experiment results saved to {file_path}")
        return file_path

    def describe(self) -> str:
        return "ExperimentStorage saves experiment results."

