import json
import os
import tempfile
import textwrap


class MetricsGraphGenerator:
    """Generate experiment graphs from stored artifacts."""

    PRESENTATION_LIMIT = 10
    STATUS_COLORS = {
        "passed": "#2e7d32",
        "failed": "#c62828",
        "skipped": "#757575",
        "other": "#546e7a",
    }
    STAGE_LABELS = {
        "catalog_latency_ms": "Catalog request",
        "negotiation_latency_ms": "Contract negotiation",
        "transfer_latency_ms": "Transfer start",
        "log_negotiation_latency_ms": "Agreement visibility",
    }

    @staticmethod
    def _load_plot_backend():
        try:
            if not os.environ.get("MPLCONFIGDIR"):
                cache_dir = os.path.join(tempfile.gettempdir(), "pionera-matplotlib-cache")
                os.makedirs(cache_dir, exist_ok=True)
                os.environ["MPLCONFIGDIR"] = cache_dir
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
    def _safe_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _mean(values):
        numeric = [float(value) for value in values]
        return sum(numeric) / len(numeric) if numeric else 0.0

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

    @staticmethod
    def _write_manifest(graphs_dir, manifest):
        if not manifest:
            return
        path = os.path.join(graphs_dir, "graph_manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "graphs": manifest}, f, indent=2, sort_keys=True)

    @staticmethod
    def _shorten(value, max_chars=56):
        text = str(value or "").strip()
        if len(text) <= max_chars:
            return text
        return f"{text[: max_chars - 3].rstrip()}..."

    @classmethod
    def _wrap_label(cls, value, width=24, max_lines=2):
        label = cls._shorten(value, width * max_lines)
        wrapped = textwrap.wrap(label, width=width, break_long_words=False, break_on_hyphens=False)
        if len(wrapped) <= max_lines:
            return "\n".join(wrapped) if wrapped else label
        return "\n".join(wrapped[: max_lines - 1] + [cls._shorten(" ".join(wrapped[max_lines - 1:]), width)])

    @staticmethod
    def _participant_label(value):
        label = str(value or "").strip()
        if label.startswith("conn-"):
            label = label[len("conn-") :]
        if label.endswith("-pionera"):
            label = label[: -len("-pionera")]
        return label or "unknown"

    @classmethod
    def _request_label(cls, item):
        for key in ("request_name", "request", "endpoint"):
            value = item.get(key)
            if value:
                return cls._shorten(value, 64)
        return "Request"

    @staticmethod
    def _component_display_label(value):
        labels = {
            "ai-model-hub": "AI Model Hub",
            "ontology-hub": "Ontology Hub",
            "semantic-virtualization": "Semantic Virtualization",
        }
        key = str(value or "").strip().lower()
        return labels.get(key, key.replace("-", " ").title() if key else "Component")

    @classmethod
    def _sorted_group_items(cls, groups, metric="mean", limit=None):
        def score(pair):
            values = pair[1]
            if metric == "p95":
                return cls._percentile(values, 0.95) or 0.0
            if metric == "p99":
                return cls._percentile(values, 0.99) or 0.0
            return cls._mean(values)

        items = sorted(groups.items(), key=score, reverse=True)
        return items[:limit] if limit else items

    @staticmethod
    def _annotate_barh(axis, values, precision=1):
        if not values:
            return
        max_value = max(values) if values else 0
        offset = max(max_value * 0.012, 0.5)
        for idx, value in enumerate(values):
            axis.text(value + offset, idx, f"{value:.{precision}f}", va="center", fontsize=8)
        axis.set_xlim(0, max_value + max(max_value * 0.18, 1))

    @staticmethod
    def _latency_scale(values):
        numeric = [value for value in values if value is not None]
        if numeric and max(numeric) >= 1000:
            return [value / 1000 for value in values], "Latency (s)", 2
        return values, "Latency (ms)", 1

    @classmethod
    def _record_graph(cls, generated, manifest, key, path, title, description, aliases=None):
        generated[key] = path
        item = {
            "key": key,
            "file": os.path.basename(path),
            "title": title,
            "description": description,
        }
        if aliases:
            item["aliases"] = aliases
        manifest.append(item)

    @classmethod
    def _raw_request_groups(cls, raw_requests):
        request_groups = {}
        iteration_groups = {}
        all_latencies = []
        aliases = {}
        for item in raw_requests:
            latency = cls._safe_float(item.get("latency_ms"))
            iteration = item.get("iteration") or item.get("run_index")
            label = cls._request_label(item)
            if label and latency is not None:
                request_groups.setdefault(label, []).append(latency)
                all_latencies.append(latency)
                record = aliases.setdefault(
                    label,
                    {
                        "label": label,
                        "request_names": set(),
                        "endpoints": set(),
                        "collections": set(),
                        "methods": set(),
                    },
                )
                for source, target in (
                    ("request_name", "request_names"),
                    ("endpoint", "endpoints"),
                    ("collection", "collections"),
                    ("method", "methods"),
                ):
                    value = item.get(source)
                    if value:
                        record[target].add(str(value))
            if iteration is not None and latency is not None:
                try:
                    iteration_groups.setdefault(int(iteration), []).append(latency)
                except (TypeError, ValueError):
                    continue
        normalized_aliases = {}
        for label, record in aliases.items():
            normalized_aliases[label] = {
                key: sorted(value) if isinstance(value, set) else value
                for key, value in record.items()
            }
        return request_groups, iteration_groups, all_latencies, normalized_aliases

    @classmethod
    def _status_rows(cls, experiment_dir):
        rows = []
        test_results = cls._read_json(os.path.join(experiment_dir, "test_results.json"), default=[]) or []
        if isinstance(test_results, list) and test_results:
            counts = {"passed": 0, "failed": 0, "skipped": 0, "other": 0}
            for item in test_results:
                status = str(item.get("status") or "").lower()
                if status in ("pass", "passed"):
                    counts["passed"] += 1
                elif status in ("fail", "failed", "error"):
                    counts["failed"] += 1
                elif status in ("skip", "skipped"):
                    counts["skipped"] += 1
                else:
                    counts["other"] += 1
            rows.append(("EDC API checks", counts))

        ui_path = os.path.join(experiment_dir, "ui", "inesdata", "playwright_validation.json")
        ui_payload = cls._read_json(ui_path, default={}) or {}
        ui_summary = ui_payload.get("summary") or {}
        ui_counts = ui_summary.get("status_counts") or {}
        if ui_counts:
            rows.append((
                "INESData UI",
                {
                    "passed": cls._safe_int(ui_counts.get("passed")),
                    "failed": cls._safe_int(ui_counts.get("failed")),
                    "skipped": cls._safe_int(ui_counts.get("skipped")),
                    "other": sum(
                        cls._safe_int(value)
                        for key, value in ui_counts.items()
                        if key not in ("passed", "failed", "skipped")
                    ),
                },
            ))

        components_dir = os.path.join(experiment_dir, "components")
        if os.path.isdir(components_dir):
            for component_dir in sorted(os.listdir(components_dir)):
                component_path = os.path.join(components_dir, component_dir)
                if not os.path.isdir(component_path):
                    continue
                expected_name = f"{component_dir.replace('-', '_')}_component_validation.json"
                validation_path = os.path.join(component_path, expected_name)
                payload = cls._read_json(validation_path, default={}) or {}
                summary = payload.get("summary") or {}
                if not summary:
                    continue
                label = cls._component_display_label(payload.get("component") or component_dir)
                rows.append((
                    label,
                    {
                        "passed": cls._safe_int(summary.get("passed")),
                        "failed": cls._safe_int(summary.get("failed")),
                        "skipped": cls._safe_int(summary.get("skipped")),
                        "other": max(
                            cls._safe_int(summary.get("total"))
                            - cls._safe_int(summary.get("passed"))
                            - cls._safe_int(summary.get("failed"))
                            - cls._safe_int(summary.get("skipped")),
                            0,
                        ),
                    },
                ))
        return rows

    @classmethod
    def _kafka_runs(cls, kafka_metrics, kafka_transfer_results):
        runs = []
        if isinstance(kafka_metrics, dict):
            if isinstance(kafka_metrics.get("kafka_benchmark"), dict):
                runs.append(dict(kafka_metrics["kafka_benchmark"]))
            elif isinstance(kafka_metrics.get("runs"), list):
                for item in kafka_metrics["runs"]:
                    if isinstance(item, dict) and isinstance(item.get("kafka_benchmark"), dict):
                        runs.append(dict(item["kafka_benchmark"]))
        if isinstance(kafka_transfer_results, list):
            for idx, item in enumerate(kafka_transfer_results, start=1):
                if not isinstance(item, dict):
                    continue
                metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                run = dict(metrics)
                run.setdefault("status", "completed" if item.get("status") == "passed" else item.get("status"))
                run.setdefault("run_index", idx)
                provider = cls._participant_label(item.get("provider"))
                consumer = cls._participant_label(item.get("consumer"))
                run["direction"] = f"{provider} -> {consumer}"
                runs.append(run)
        return [item for item in runs if item.get("status", "completed") in ("completed", "passed")]

    def generate(self, experiment_dir):
        plt = self._load_plot_backend()
        if plt is None:
            return {}

        graphs_dir = self._graphs_dir(experiment_dir)
        raw_requests = self._read_jsonl(os.path.join(experiment_dir, "raw_requests.jsonl"))
        negotiation_metrics = self._read_json(os.path.join(experiment_dir, "negotiation_metrics.json"), default=[]) or []
        kafka_metrics = self._read_json(os.path.join(experiment_dir, "kafka_metrics.json"), default={}) or {}
        kafka_transfer_results = self._read_json(os.path.join(experiment_dir, "kafka_transfer_results.json"), default=[]) or []

        generated = {}
        manifest = []

        if raw_requests:
            endpoint_groups, iteration_groups, all_latencies, aliases = self._raw_request_groups(raw_requests)

            if endpoint_groups:
                top_by_mean = self._sorted_group_items(endpoint_groups, metric="mean", limit=self.PRESENTATION_LIMIT)
                labels = [self._wrap_label(label) for label, _ in top_by_mean]

                boxplot_path = os.path.join(graphs_dir, "latency_boxplot.png")
                figure, axis = plt.subplots(figsize=(11, max(5, 0.55 * len(labels) + 1.5)))
                axis.boxplot(
                    [values for _, values in top_by_mean],
                    tick_labels=labels,
                    orientation="horizontal",
                    patch_artist=True,
                )
                axis.set_title(f"Request latency spread - top {len(labels)} slowest operations")
                axis.set_xlabel("Latency (ms)")
                axis.grid(axis="x", alpha=0.25)
                axis.invert_yaxis()
                self._save_figure(figure, boxplot_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "latency_boxplot",
                    boxplot_path,
                    "Request latency spread",
                    "Boxplot for the slowest request groups, using readable request names instead of raw endpoint URLs.",
                    {label: aliases.get(label, {}) for label, _ in top_by_mean},
                )

                endpoint_bar_path = os.path.join(graphs_dir, "endpoint_latency_bar.png")
                means = [self._mean(values) for _, values in top_by_mean]
                figure, axis = plt.subplots(figsize=(11, max(5, 0.55 * len(labels) + 1.5)))
                axis.barh(labels, means, color="#2f6f9f")
                axis.set_title(f"Average request latency - top {len(labels)} operations")
                axis.set_xlabel("Latency (ms)")
                axis.grid(axis="x", alpha=0.25)
                axis.invert_yaxis()
                self._annotate_barh(axis, means)
                self._save_figure(figure, endpoint_bar_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "endpoint_latency_bar",
                    endpoint_bar_path,
                    "Average request latency",
                    "Horizontal top-N chart designed for presentation without overlapping endpoint labels.",
                    {label: aliases.get(label, {}) for label, _ in top_by_mean},
                )

                pct_items = self._sorted_group_items(endpoint_groups, metric="p95", limit=self.PRESENTATION_LIMIT)
                pct_labels = [self._wrap_label(label) for label, _ in pct_items]
                positions = list(range(len(pct_items)))
                p50_values = [self._percentile(values, 0.50) or 0 for _, values in pct_items]
                p95_values = [self._percentile(values, 0.95) or 0 for _, values in pct_items]
                p99_values = [self._percentile(values, 0.99) or 0 for _, values in pct_items]
                percentile_path = os.path.join(graphs_dir, "endpoint_latency_percentiles.png")
                figure, axis = plt.subplots(figsize=(11, max(5, 0.62 * len(pct_labels) + 1.8)))
                height = 0.23
                axis.barh([p - height for p in positions], p50_values, height=height, label="p50", color="#4c78a8")
                axis.barh(positions, p95_values, height=height, label="p95", color="#f58518")
                axis.barh([p + height for p in positions], p99_values, height=height, label="p99", color="#e45756")
                axis.set_yticks(positions)
                axis.set_yticklabels(pct_labels)
                axis.set_title(f"Request latency percentiles - top {len(pct_labels)} by p95")
                axis.set_xlabel("Latency (ms)")
                axis.grid(axis="x", alpha=0.25)
                axis.legend(loc="lower right")
                axis.invert_yaxis()
                self._save_figure(figure, percentile_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "endpoint_latency_percentiles",
                    percentile_path,
                    "Request latency percentiles",
                    "p50/p95/p99 view for the slowest request groups, suitable for supervisor-level latency discussion.",
                    {label: aliases.get(label, {}) for label, _ in pct_items},
                )

            if all_latencies:
                histogram_path = os.path.join(graphs_dir, "latency_histogram.png")
                figure, axis = plt.subplots(figsize=(10, 6))
                axis.hist(all_latencies, bins=min(max(len(all_latencies), 1), 20))
                axis.set_title("Request latency distribution")
                axis.set_xlabel("Latency (ms)")
                axis.set_ylabel("Count")
                axis.grid(axis="y", alpha=0.25)
                self._save_figure(figure, histogram_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "latency_histogram",
                    histogram_path,
                    "Request latency distribution",
                    "Distribution of all valid request latency samples.",
                )

            if iteration_groups:
                over_iterations_path = os.path.join(graphs_dir, "latency_over_iterations.png")
                ordered_iterations = sorted(iteration_groups)
                means = [sum(iteration_groups[idx]) / len(iteration_groups[idx]) for idx in ordered_iterations]
                figure, axis = plt.subplots(figsize=(10, 6))
                axis.plot(ordered_iterations, means, marker="o")
                axis.set_title("Mean latency over iterations")
                axis.set_xlabel("Iteration")
                axis.set_ylabel("Mean latency (ms)")
                axis.grid(alpha=0.25)
                self._save_figure(figure, over_iterations_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "latency_over_iterations",
                    over_iterations_path,
                    "Mean latency over iterations",
                    "Trend of average request latency over experiment iterations.",
                )

        if negotiation_metrics:
            latency_columns = tuple(self.STAGE_LABELS)
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
                axis.grid(axis="y", alpha=0.25)
                self._save_figure(figure, neg_hist_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "negotiation_latency_histogram",
                    neg_hist_path,
                    "Negotiation latency distribution",
                    "Distribution of catalog, negotiation and transfer phase latency samples.",
                )

            if per_metric:
                flow_path = os.path.join(graphs_dir, "edc_flow_latency.png")
                flow_labels = [self.STAGE_LABELS.get(label, label) for label in per_metric]
                flow_values = [self._mean(values) for values in per_metric.values()]
                figure, axis = plt.subplots(figsize=(10, max(4, 0.55 * len(flow_labels) + 1.5)))
                axis.barh(flow_labels, flow_values, color="#3d7f5f")
                axis.set_title("EDC flow latency by phase")
                axis.set_xlabel("Average latency (ms)")
                axis.grid(axis="x", alpha=0.25)
                axis.invert_yaxis()
                self._annotate_barh(axis, flow_values, precision=2)
                self._save_figure(figure, flow_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "edc_flow_latency",
                    flow_path,
                    "EDC flow latency",
                    "Average latency for the catalog, contract negotiation and transfer phases.",
                )

                neg_pct_path = os.path.join(graphs_dir, "negotiation_percentiles.png")
                labels = list(per_metric.keys())
                display_labels = [self.STAGE_LABELS.get(label, label) for label in labels]
                p50_values = [self._percentile(per_metric[label], 0.50) or 0 for label in labels]
                p95_values = [self._percentile(per_metric[label], 0.95) or 0 for label in labels]
                p99_values = [self._percentile(per_metric[label], 0.99) or 0 for label in labels]
                positions = list(range(len(labels)))
                height = 0.23
                figure, axis = plt.subplots(figsize=(10, max(4, 0.62 * len(display_labels) + 1.8)))
                axis.barh([p - height for p in positions], p50_values, height=height, label="p50", color="#4c78a8")
                axis.barh(positions, p95_values, height=height, label="p95", color="#f58518")
                axis.barh([p + height for p in positions], p99_values, height=height, label="p99", color="#e45756")
                axis.set_yticks(positions)
                axis.set_yticklabels(display_labels)
                axis.set_xlabel("Latency (ms)")
                axis.set_title("Negotiation latency percentiles")
                axis.grid(axis="x", alpha=0.25)
                axis.legend()
                axis.invert_yaxis()
                self._save_figure(figure, neg_pct_path)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "negotiation_percentiles",
                    neg_pct_path,
                    "Negotiation latency percentiles",
                    "p50/p95/p99 latency by EDC negotiation phase.",
                )

        status_rows = self._status_rows(experiment_dir)
        if status_rows:
            status_path = os.path.join(graphs_dir, "validation_status_summary.png")
            labels = [self._wrap_label(label, width=22) for label, _ in status_rows]
            figure, axis = plt.subplots(figsize=(11, max(4.5, 0.58 * len(labels) + 1.8)))
            left = [0] * len(status_rows)
            totals = [sum(counts.values()) for _, counts in status_rows]
            for status in ("passed", "failed", "skipped", "other"):
                counts = [row_counts.get(status, 0) for _, row_counts in status_rows]
                values = [
                    (count / total * 100) if total else 0
                    for count, total in zip(counts, totals)
                ]
                if not any(counts):
                    continue
                bars = axis.barh(
                    labels,
                    values,
                    left=left,
                    label=status.title(),
                    color=self.STATUS_COLORS[status],
                )
                for bar, count, value in zip(bars, counts, values):
                    if count and value >= 5:
                        axis.text(
                            bar.get_x() + bar.get_width() / 2,
                            bar.get_y() + bar.get_height() / 2,
                            str(count),
                            ha="center",
                            va="center",
                            color="white",
                            fontsize=8,
                        )
                left = [current + value for current, value in zip(left, values)]
            for idx, total in enumerate(totals):
                axis.text(101.5, idx, f"n={total}", va="center", fontsize=8)
            axis.set_xlim(0, 112)
            axis.set_title("Validation outcome by evidence family")
            axis.set_xlabel("Share of checks / cases (%)")
            axis.grid(axis="x", alpha=0.25)
            axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=4, frameon=False)
            axis.invert_yaxis()
            self._save_figure(figure, status_path)
            plt.close(figure)
            self._record_graph(
                generated,
                manifest,
                "validation_status_summary",
                status_path,
                "Validation evidence summary",
                "Passed, failed and skipped checks by evidence family and component.",
            )

        kafka_runs = self._kafka_runs(kafka_metrics, kafka_transfer_results)

        if kafka_runs:
            avg_latencies = [self._safe_float(item.get("average_latency_ms")) for item in kafka_runs]
            avg_latencies = [value for value in avg_latencies if value is not None]
            if avg_latencies:
                scaled_latencies, latency_label, latency_precision = self._latency_scale(avg_latencies)
                kafka_hist = os.path.join(graphs_dir, "kafka_latency_histogram.png")
                figure, axis = plt.subplots(figsize=(10, 6))
                axis.hist(scaled_latencies, bins=min(max(len(scaled_latencies), 1), 10))
                axis.set_title("Kafka latency distribution")
                axis.set_xlabel(latency_label)
                axis.set_ylabel("Count")
                axis.grid(axis="y", alpha=0.25)
                self._save_figure(figure, kafka_hist)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "kafka_latency_histogram",
                    kafka_hist,
                    "Kafka latency distribution",
                    "Distribution of Kafka transfer average latency across completed runs.",
                )

                direction_rows = [
                    (item.get("direction") or str(item.get("run_index", idx + 1)), self._safe_float(item.get("average_latency_ms")))
                    for idx, item in enumerate(kafka_runs)
                ]
                direction_rows = [(label, value) for label, value in direction_rows if value is not None]
                if direction_rows:
                    direction_path = os.path.join(graphs_dir, "kafka_transfer_latency_by_direction.png")
                    labels = [self._wrap_label(label, width=18) for label, _ in direction_rows]
                    values = [value for _, value in direction_rows]
                    scaled_values, latency_label, latency_precision = self._latency_scale(values)
                    figure, axis = plt.subplots(figsize=(10, max(4, 0.55 * len(labels) + 1.5)))
                    axis.barh(labels, scaled_values, color="#8064a2")
                    axis.set_title("Kafka transfer latency by direction")
                    axis.set_xlabel(f"Average {latency_label.lower()}")
                    axis.grid(axis="x", alpha=0.25)
                    axis.invert_yaxis()
                    self._annotate_barh(axis, scaled_values, precision=latency_precision)
                    self._save_figure(figure, direction_path)
                    plt.close(figure)
                    self._record_graph(
                        generated,
                        manifest,
                        "kafka_transfer_latency_by_direction",
                        direction_path,
                        "Kafka transfer latency by direction",
                        "Average Kafka transfer latency for each provider-consumer direction.",
                    )

            throughputs = [self._safe_float(item.get("throughput_messages_per_second")) for item in kafka_runs]
            throughputs = [value for value in throughputs if value is not None]
            if throughputs:
                kafka_bar = os.path.join(graphs_dir, "kafka_throughput_bar.png")
                figure, axis = plt.subplots(figsize=(8, 6))
                axis.bar([str(item.get("run_index", idx + 1)) for idx, item in enumerate(kafka_runs)], throughputs)
                axis.set_title("Kafka throughput")
                axis.set_ylabel("Messages/s")
                axis.grid(axis="y", alpha=0.25)
                self._save_figure(figure, kafka_bar)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "kafka_throughput_bar",
                    kafka_bar,
                    "Kafka throughput",
                    "Kafka transfer throughput for completed runs.",
                )

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
                scaled_values, latency_label, _ = self._latency_scale(percentile_values)
                figure, axis = plt.subplots(figsize=(8, 6))
                axis.bar(percentile_labels, scaled_values, color="#5f8c47")
                axis.set_title("Kafka latency percentiles")
                axis.set_ylabel(latency_label)
                axis.grid(axis="y", alpha=0.25)
                self._save_figure(figure, kafka_pct)
                plt.close(figure)
                self._record_graph(
                    generated,
                    manifest,
                    "kafka_latency_percentiles",
                    kafka_pct,
                    "Kafka latency percentiles",
                    "Average p50/p95/p99 Kafka transfer latency across completed runs.",
                )

        self._write_manifest(graphs_dir, manifest)
        return generated
