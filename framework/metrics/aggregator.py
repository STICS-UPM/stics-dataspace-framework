import statistics


class MetricsAggregator:
    """Aggregate request, test, negotiation and Kafka metrics."""

    @staticmethod
    def _percentile(values, percentile):
        ordered = sorted(float(value) for value in values)
        if not ordered:
            return None
        if len(ordered) == 1:
            return round(float(ordered[0]), 2)

        rank = (len(ordered) - 1) * percentile
        lower_index = int(rank)
        upper_index = min(lower_index + 1, len(ordered) - 1)
        weight = rank - lower_index
        lower = float(ordered[lower_index])
        upper = float(ordered[upper_index])
        return round(lower + (upper - lower) * weight, 2)

    @classmethod
    def aggregate_request_metrics(cls, raw_requests):
        grouped = {}

        for item in raw_requests or []:
            endpoint = item.get("endpoint") or item.get("request_name") or item.get("request")
            latency = item.get("latency_ms")
            status_code = item.get("status_code")
            method = item.get("method")

            if not endpoint:
                continue

            try:
                latency_value = float(latency)
            except (TypeError, ValueError):
                continue

            bucket = grouped.setdefault(endpoint, {
                "latencies": [],
                "errors": 0,
                "methods": set(),
            })
            bucket["latencies"].append(latency_value)
            if method:
                bucket["methods"].add(str(method))
            try:
                if int(status_code) >= 400:
                    bucket["errors"] += 1
            except (TypeError, ValueError):
                pass

        aggregated = {}
        for endpoint in sorted(grouped):
            values = grouped[endpoint]["latencies"]
            aggregated[endpoint] = {
                "count": len(values),
                "request_count": len(values),
                "error_rate": round(grouped[endpoint]["errors"] / max(len(values), 1), 4),
                "mean_latency": round(statistics.mean(values), 2),
                "average_latency_ms": round(statistics.mean(values), 2),
                "min_latency_ms": round(min(values), 2),
                "max_latency_ms": round(max(values), 2),
                "p50": cls._percentile(values, 0.50),
                "p95": cls._percentile(values, 0.95),
                "p99": cls._percentile(values, 0.99),
                "p50_latency_ms": cls._percentile(values, 0.50),
                "p95_latency_ms": cls._percentile(values, 0.95),
                "p99_latency_ms": cls._percentile(values, 0.99),
                "methods": sorted(grouped[endpoint]["methods"]),
            }
        return aggregated

    @classmethod
    def aggregate_negotiation_metrics(cls, negotiation_metrics):
        metrics = negotiation_metrics or []
        keys = ("catalog_latency_ms", "negotiation_latency_ms", "transfer_latency_ms", "log_negotiation_latency_ms")
        aggregated = {}
        for key in keys:
            values = []
            for item in metrics:
                try:
                    value = item.get(key)
                    if value is not None:
                        values.append(float(value))
                except (TypeError, ValueError, AttributeError):
                    continue
            if not values:
                continue
            aggregated[key] = {
                "count": len(values),
                "mean_latency": round(statistics.mean(values), 2),
                "p50": cls._percentile(values, 0.50),
                "p95": cls._percentile(values, 0.95),
                "p99": cls._percentile(values, 0.99),
                "max_latency": round(max(values), 2),
            }
        return aggregated

    @staticmethod
    def summarize_test_results(test_results):
        results = test_results or []
        passed = sum(1 for item in results if item.get("status") == "pass")
        failed = sum(1 for item in results if item.get("status") == "fail")
        return {
            "total_tests": len(results),
            "tests_passed": passed,
            "tests_failed": failed,
            "failure_details": [item for item in results if item.get("status") == "fail"],
        }
