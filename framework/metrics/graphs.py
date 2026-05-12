import json
import os


class MetricsGraphGenerator:
    """Generate experiment graphs from stored artifacts."""

    @staticmethod
    def _load_plot_backend():
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            return plt
        except Exception as exc:
            print(f"[WARNING] MetricsGraphGenerator could not import matplotlib: {exc}")
            return None

    @staticmethod
    def _load_pandas():
        return None

    @staticmethod
    def _graphs_dir(experiment_dir):
        graphs_dir = os.path.join(experiment_dir, "graphs")
        os.makedirs(graphs_dir, exist_ok=True)
        return graphs_dir

    @staticmethod
    def _read_json(path, default=None):
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _read_jsonl(path):
        if not os.path.exists(path):
            return []
        items = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _percentile(values, percentile):
        ordered = sorted(float(value) for value in values)
        if not ordered:
            return None
        if len(ordered) == 1:
            return ordered[0]
        rank = (len(ordered) - 1) * percentile
        lower_index = int(rank)
        upper_index = min(lower_index + 1, len(ordered) - 1)
        weight = rank - lower_index
        lower = ordered[lower_index]
        upper = ordered[upper_index]
        return lower + (upper - lower) * weight

    @staticmethod
    def _save_figure(figure, output_path):
        figure.tight_layout()
        figure.savefig(output_path, dpi=200)

    def generate(self, experiment_dir):
        plt = self._load_plot_backend()
        if plt is None:
            return {}

        graphs_dir = self._graphs_dir(experiment_dir)
        raw_requests = self._read_jsonl(os.path.join(experiment_dir, "raw_requests.jsonl"))
        negotiation_metrics = self._read_json(os.path.join(experiment_dir, "negotiation_metrics.json"), default=[]) or []
        kafka_metrics = self._read_json(os.path.join(experiment_dir, "kafka_metrics.json"), default={}) or {}

        generated = {}

        if raw_requests:
            endpoint_groups = {}
            iteration_groups = {}
            all_latencies = []
            for item in raw_requests:
                endpoint = item.get("endpoint") or item.get("request_name") or item.get("request")
                latency = self._safe_float(item.get("latency_ms"))
                iteration = item.get("iteration") or item.get("run_index")
                if endpoint and latency is not None:
                    endpoint_groups.setdefault(str(endpoint), []).append(latency)
                    all_latencies.append(latency)
                if iteration is not None and latency is not None:
                    iteration_groups.setdefault(int(iteration), []).append(latency)

            if endpoint_groups:
                boxplot_path = os.path.join(graphs_dir, "latency_boxplot.png")
                figure, axis = plt.subplots(figsize=(12, 6))
                axis.boxplot([endpoint_groups[key] for key in endpoint_groups], tick_labels=list(endpoint_groups.keys()))
                axis.set_title("Latency per endpoint")
                axis.set_ylabel("Latency (ms)")
                axis.tick_params(axis="x", rotation=45)
                self._save_figure(figure, boxplot_path)
                plt.close(figure)
                generated["latency_boxplot"] = boxplot_path

                endpoint_bar_path = os.path.join(graphs_dir, "endpoint_latency_bar.png")
                labels = list(endpoint_groups.keys())
                means = [sum(values) / len(values) for values in endpoint_groups.values()]
                figure, axis = plt.subplots(figsize=(12, 6))
                axis.bar(labels, means)
                axis.set_title("Average latency per endpoint")
                axis.set_ylabel("Latency (ms)")
                axis.tick_params(axis="x", rotation=35)
                self._save_figure(figure, endpoint_bar_path)
                plt.close(figure)
                generated["endpoint_latency_bar"] = endpoint_bar_path

            if all_latencies:
                histogram_path = os.path.join(graphs_dir, "latency_histogram.png")
                figure, axis = plt.subplots(figsize=(10, 6))
                axis.hist(all_latencies, bins=min(max(len(all_latencies), 1), 20))
                axis.set_title("Request latency distribution")
                axis.set_xlabel("Latency (ms)")
                axis.set_ylabel("Count")
                self._save_figure(figure, histogram_path)
                plt.close(figure)
                generated["latency_histogram"] = histogram_path

            if iteration_groups:
                over_iterations_path = os.path.join(graphs_dir, "latency_over_iterations.png")
                ordered_iterations = sorted(iteration_groups)
                means = [sum(iteration_groups[idx]) / len(iteration_groups[idx]) for idx in ordered_iterations]
                figure, axis = plt.subplots(figsize=(10, 6))
                axis.plot(ordered_iterations, means, marker="o")
                axis.set_title("Mean latency over iterations")
                axis.set_xlabel("Iteration")
                axis.set_ylabel("Mean latency (ms)")
                self._save_figure(figure, over_iterations_path)
                plt.close(figure)
                generated["latency_over_iterations"] = over_iterations_path

        if negotiation_metrics:
            latency_columns = ("catalog_latency_ms", "negotiation_latency_ms", "transfer_latency_ms", "log_negotiation_latency_ms")
            values = []
            per_metric = {}
            for item in negotiation_metrics:
                for column in latency_columns:
                    value = self._safe_float(item.get(column))
                    if value is not None:
                        values.append(value)
                        per_metric.setdefault(column, []).append(value)

            if values:
                neg_hist_path = os.path.join(graphs_dir, "negotiation_latency_histogram.png")
                figure, axis = plt.subplots(figsize=(10, 6))
                axis.hist(values, bins=min(max(len(values), 1), 20))
                axis.set_title("Negotiation latency distribution")
                axis.set_xlabel("Latency (ms)")
                axis.set_ylabel("Count")
                self._save_figure(figure, neg_hist_path)
                plt.close(figure)
                generated["negotiation_latency_histogram"] = neg_hist_path

            if per_metric:
                neg_pct_path = os.path.join(graphs_dir, "negotiation_percentiles.png")
                labels = list(per_metric.keys())
                p50_values = [self._percentile(per_metric[label], 0.50) or 0 for label in labels]
                p95_values = [self._percentile(per_metric[label], 0.95) or 0 for label in labels]
                p99_values = [self._percentile(per_metric[label], 0.99) or 0 for label in labels]
                positions = list(range(len(labels)))
                width = 0.25
                figure, axis = plt.subplots(figsize=(12, 6))
                axis.bar([p - width for p in positions], p50_values, width=width, label="p50")
                axis.bar(positions, p95_values, width=width, label="p95")
                axis.bar([p + width for p in positions], p99_values, width=width, label="p99")
                axis.set_xticks(positions)
                axis.set_xticklabels(labels, rotation=35, ha="right")
                axis.set_ylabel("Latency (ms)")
                axis.set_title("Negotiation latency percentiles")
                axis.legend()
                self._save_figure(figure, neg_pct_path)
                plt.close(figure)
                generated["negotiation_percentiles"] = neg_pct_path

        kafka_runs = []
        if isinstance(kafka_metrics, dict):
            if isinstance(kafka_metrics.get("kafka_benchmark"), dict):
                kafka_runs = [kafka_metrics["kafka_benchmark"]]
            elif isinstance(kafka_metrics.get("runs"), list):
                kafka_runs = [item.get("kafka_benchmark", {}) for item in kafka_metrics["runs"] if isinstance(item, dict)]
        kafka_runs = [item for item in kafka_runs if item.get("status", "completed") == "completed"]

        if kafka_runs:
            avg_latencies = [self._safe_float(item.get("average_latency_ms")) for item in kafka_runs]
            avg_latencies = [value for value in avg_latencies if value is not None]
            if avg_latencies:
                kafka_hist = os.path.join(graphs_dir, "kafka_latency_histogram.png")
                figure, axis = plt.subplots(figsize=(10, 6))
                axis.hist(avg_latencies, bins=min(max(len(avg_latencies), 1), 10))
                axis.set_title("Kafka latency distribution")
                axis.set_xlabel("Latency (ms)")
                axis.set_ylabel("Count")
                self._save_figure(figure, kafka_hist)
                plt.close(figure)
                generated["kafka_latency_histogram"] = kafka_hist

            throughputs = [self._safe_float(item.get("throughput_messages_per_second")) for item in kafka_runs]
            throughputs = [value for value in throughputs if value is not None]
            if throughputs:
                kafka_bar = os.path.join(graphs_dir, "kafka_throughput_bar.png")
                figure, axis = plt.subplots(figsize=(8, 6))
                axis.bar([str(item.get("run_index", idx + 1)) for idx, item in enumerate(kafka_runs)], throughputs)
                axis.set_title("Kafka throughput")
                axis.set_ylabel("Messages/s")
                self._save_figure(figure, kafka_bar)
                plt.close(figure)
                generated["kafka_throughput_bar"] = kafka_bar

            percentile_map = {
                "p50": [self._safe_float(item.get("p50_latency_ms")) for item in kafka_runs],
                "p95": [self._safe_float(item.get("p95_latency_ms")) for item in kafka_runs],
                "p99": [self._safe_float(item.get("p99_latency_ms")) for item in kafka_runs],
            }
            percentile_values = []
            percentile_labels = []
            for label, values in percentile_map.items():
                numeric = [value for value in values if value is not None]
                if numeric:
                    percentile_labels.append(label)
                    percentile_values.append(sum(numeric) / len(numeric))
            if percentile_values:
                kafka_pct = os.path.join(graphs_dir, "kafka_latency_percentiles.png")
                figure, axis = plt.subplots(figsize=(8, 6))
                axis.bar(percentile_labels, percentile_values)
                axis.set_title("Kafka latency percentiles")
                axis.set_ylabel("Latency (ms)")
                self._save_figure(figure, kafka_pct)
                plt.close(figure)
                generated["kafka_latency_percentiles"] = kafka_pct

        return generated
