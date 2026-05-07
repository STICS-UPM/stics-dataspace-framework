from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from validation.components.semantic_virtualization.dataspace_integration import (
    GTFS_MADRID_BENCH_MINI_DIR,
    load_gtfs_madrid_bench_mini_context,
)


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "mobility-benchmarking-api"
CASE_ID = "MH-MOB-01"

DEFAULT_MODELS = [
    {
        "asset_id": "model-gtfs-mobility-route-baseline-a",
        "name": "GTFS Mobility Route Baseline A",
        "variant": "route-baseline-a",
        "task": "mobility-route-estimation",
        "base_latency_ms": 36,
        "latency_step_ms": 4,
        "mispredict_case_ids": [],
        "description": "Controlled mobility baseline that mirrors GTFS-Madrid-Bench-mini expected route and duration outputs.",
    },
    {
        "asset_id": "model-gtfs-mobility-eta-baseline-b",
        "name": "GTFS Mobility ETA Baseline B",
        "variant": "eta-baseline-b",
        "task": "mobility-route-estimation",
        "base_latency_ms": 25,
        "latency_step_ms": 3,
        "mispredict_case_ids": ["mob-case-002"],
        "duration_offset_minutes": 2,
        "description": "Controlled mobility baseline with lower latency and one deterministic ETA deviation.",
    },
]


def _component_dir(experiment_dir: str | None) -> str | None:
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, "components", COMPONENT_KEY, "functional")
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _default_experiment_dir() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join("experiments", f"ai-model-hub-mobility-benchmarking-api-{timestamp}")


def _duration_minutes(stop_times: list[dict[str, Any]], origin_stop_id: str, destination_stop_id: str) -> int:
    origin = next(row for row in stop_times if row["stop_id"] == origin_stop_id)
    destination = next(row for row in stop_times if row["stop_id"] == destination_stop_id)
    start = datetime.strptime(origin["departure_time"], "%H:%M:%S")
    end = datetime.strptime(destination["arrival_time"], "%H:%M:%S")
    return int((end - start).total_seconds() / 60)


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((percentile / 100.0) * len(ordered)) - 1))
    return float(ordered[index])


def _round_metric(value: float) -> float:
    return round(float(value), 2)


def load_gtfs_mobility_fixture(fixture_dir: str | None = None) -> dict[str, Any]:
    fixture_root = Path(fixture_dir or GTFS_MADRID_BENCH_MINI_DIR)
    context = load_gtfs_madrid_bench_mini_context(str(fixture_root))
    return {
        "context": context,
        "metadata": _read_json(fixture_root / "metadata.json"),
        "schema": _read_json(fixture_root / "schema.json"),
        "sample": _read_json(fixture_root / "benchmark_sample.json"),
        "expected_outputs": _read_json(fixture_root / "expected_outputs.json"),
    }


def _build_benchmark_rows(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    sample = fixture["sample"]
    expected_outputs = fixture["expected_outputs"]
    stop_times_by_trip: dict[str, list[dict[str, Any]]] = {}
    for stop_time in sample.get("stop_times") or []:
        stop_times_by_trip.setdefault(stop_time["trip_id"], []).append(stop_time)
    for rows in stop_times_by_trip.values():
        rows.sort(key=lambda row: row["stop_sequence"])

    expected_cases = {
        row["case_id"]: row
        for row in (expected_outputs.get("benchmark_sample", {}).get("transferCases") or [])
    }
    rows = []
    for case in sample.get("transfer_benchmark_cases") or []:
        expected_case = expected_cases.get(case["case_id"], {})
        trip_stop_times = stop_times_by_trip[case["expected_trip_id"]]
        route_sequence = [row["stop_id"] for row in trip_stop_times]
        rows.append(
            {
                "case_id": case["case_id"],
                "input": {
                    "origin_stop_id": case["origin_stop_id"],
                    "destination_stop_id": case["destination_stop_id"],
                    "query_time": case["query_time"],
                },
                "expected": {
                    "route_id": expected_case.get("expected_route_id") or case["expected_route_id"],
                    "trip_id": expected_case.get("expected_trip_id") or case["expected_trip_id"],
                    "duration_minutes": expected_case.get("expected_duration_minutes") or case["expected_duration_minutes"],
                    "route_stop_sequence": route_sequence,
                },
            }
        )
    return rows


def _validate_fixture(fixture: dict[str, Any], benchmark_rows: list[dict[str, Any]]) -> list[str]:
    assertions: list[str] = []
    context = fixture["context"]
    metadata = fixture["metadata"]
    sample = fixture["sample"]
    expected_outputs = fixture["expected_outputs"]

    if metadata.get("datasetName") != "GTFS-Madrid-Bench-mini":
        assertions.append("metadata.datasetName must be GTFS-Madrid-Bench-mini")
    if metadata.get("domain") != "mobility":
        assertions.append("metadata.domain must be mobility")

    expected_counts = expected_outputs.get("benchmark_sample", {}).get("recordCounts") or {}
    for entity, expected_count in expected_counts.items():
        if len(sample.get(entity) or []) != expected_count:
            assertions.append(f"{entity} count must be {expected_count}")

    stop_ids = {row["stop_id"] for row in sample.get("stops") or []}
    route_ids = {row["route_id"] for row in sample.get("routes") or []}
    trip_ids = {row["trip_id"] for row in sample.get("trips") or []}
    trip_route_ids = {row["trip_id"]: row["route_id"] for row in sample.get("trips") or []}
    if not {row["route_id"] for row in sample.get("trips") or []}.issubset(route_ids):
        assertions.append("All trip.route_id values must reference a known route")
    if not {row["trip_id"] for row in sample.get("stop_times") or []}.issubset(trip_ids):
        assertions.append("All stop_times.trip_id values must reference a known trip")
    if not {row["stop_id"] for row in sample.get("stop_times") or []}.issubset(stop_ids):
        assertions.append("All stop_times.stop_id values must reference a known stop")

    stop_times_by_trip: dict[str, list[dict[str, Any]]] = {}
    for stop_time in sample.get("stop_times") or []:
        stop_times_by_trip.setdefault(stop_time["trip_id"], []).append(stop_time)
    for rows in stop_times_by_trip.values():
        rows.sort(key=lambda row: row["stop_sequence"])

    for case in sample.get("transfer_benchmark_cases") or []:
        if case["origin_stop_id"] not in stop_ids or case["destination_stop_id"] not in stop_ids:
            assertions.append(f"{case['case_id']} must reference known origin and destination stops")
        if trip_route_ids.get(case["expected_trip_id"]) != case["expected_route_id"]:
            assertions.append(f"{case['case_id']} expected trip must belong to expected route")
        duration = _duration_minutes(stop_times_by_trip[case["expected_trip_id"]], case["origin_stop_id"], case["destination_stop_id"])
        if duration != case["expected_duration_minutes"]:
            assertions.append(f"{case['case_id']} expected duration must match stop_times")

    if context.get("join_keys") != ["route_id", "trip_id", "stop_id"]:
        assertions.append("Fixture must preserve route_id, trip_id and stop_id join keys")
    if not benchmark_rows:
        assertions.append("Benchmark rows must not be empty")
    return assertions


def _execute_model(model: dict[str, Any], row: dict[str, Any], row_index: int) -> dict[str, Any]:
    expected = dict(row.get("expected") or {})
    predicted = dict(expected)
    correct = True
    if row["case_id"] in set(model.get("mispredict_case_ids") or []):
        predicted["duration_minutes"] = int(expected["duration_minutes"]) + int(model.get("duration_offset_minutes") or 1)
        correct = False
    latency_ms = int(model.get("base_latency_ms") or 0) + (row_index % 3) * int(model.get("latency_step_ms") or 0)
    return {
        "model_asset_id": model.get("asset_id"),
        "model_name": model.get("name"),
        "case_id": row.get("case_id"),
        "input_fingerprint": _sha256_payload(dict(row.get("input") or {})),
        "expected": expected,
        "response": {
            "result": predicted,
            "model": model.get("name"),
            "variant": model.get("variant"),
        },
        "latency_ms": latency_ms,
        "status": "passed",
        "correct": correct,
    }


def _calculate_metrics(model: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
    sample_count = len(executions)
    success_count = sum(1 for execution in executions if execution.get("status") == "passed")
    correct_count = sum(1 for execution in executions if execution.get("correct"))
    latencies = [int(execution.get("latency_ms") or 0) for execution in executions]
    total_latency_ms = sum(latencies)
    average_latency_ms = (total_latency_ms / sample_count) if sample_count else 0.0
    success_rate = (success_count / sample_count * 100.0) if sample_count else 0.0
    route_accuracy_percent = (correct_count / sample_count * 100.0) if sample_count else 0.0
    throughput_rps = (sample_count / (total_latency_ms / 1000.0)) if total_latency_ms else 0.0
    latency_score = max(0.0, 100.0 - average_latency_ms)
    score = (route_accuracy_percent * 0.65) + (success_rate * 0.2) + (latency_score * 0.15)
    return {
        "model_asset_id": model.get("asset_id"),
        "model_name": model.get("name"),
        "variant": model.get("variant"),
        "sample_count": sample_count,
        "success_count": success_count,
        "correct_count": correct_count,
        "route_accuracy_percent": _round_metric(route_accuracy_percent),
        "success_rate": _round_metric(success_rate),
        "average_latency_ms": _round_metric(average_latency_ms),
        "p95_latency_ms": _round_metric(_percentile(latencies, 95)),
        "throughput_rps": _round_metric(throughput_rps),
        "score": _round_metric(score),
    }


def _rank_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(metrics, key=lambda item: (-float(item.get("score") or 0), float(item.get("average_latency_ms") or 0)))
    return [{**metric, "rank": index + 1} for index, metric in enumerate(ranked)]


def _build_visualization_data(ranked_metrics: list[dict[str, Any]], benchmark_rows: list[dict[str, Any]]) -> dict[str, Any]:
    table_rows = [
        {
            "rank": metric.get("rank"),
            "model": metric.get("model_name"),
            "route_accuracy_percent": metric.get("route_accuracy_percent"),
            "success_rate": metric.get("success_rate"),
            "average_latency_ms": metric.get("average_latency_ms"),
            "p95_latency_ms": metric.get("p95_latency_ms"),
            "throughput_rps": metric.get("throughput_rps"),
            "score": metric.get("score"),
        }
        for metric in ranked_metrics
    ]
    return {
        "title": "AI Model Hub GTFS-Madrid-Bench-mini mobility benchmark",
        "best_model": table_rows[0]["model"] if table_rows else None,
        "benchmark_case_ids": [row.get("case_id") for row in benchmark_rows],
        "table_rows": table_rows,
        "chart_series": [
            {
                "metric": "route_accuracy_percent",
                "label": "Route and ETA accuracy (%)",
                "points": [{"model": metric.get("model_name"), "value": metric.get("route_accuracy_percent")} for metric in ranked_metrics],
            },
            {
                "metric": "average_latency_ms",
                "label": "Average latency (ms)",
                "points": [{"model": metric.get("model_name"), "value": metric.get("average_latency_ms")} for metric in ranked_metrics],
            },
            {
                "metric": "score",
                "label": "Mobility benchmark score",
                "points": [{"model": metric.get("model_name"), "value": metric.get("score")} for metric in ranked_metrics],
            },
        ],
    }


def _case_result(assertions: list[str], evidence_artifact: str, observed: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_case_id": CASE_ID,
        "description": "Validate GTFS-Madrid-Bench-mini mobility use case as executable AI Model Hub benchmark fixture",
        "type": "api",
        "case_group": "functional_use_case",
        "validation_type": "functional",
        "dataspace_dimension": "mobility",
        "mapping_status": "phase_3",
        "automation_mode": "api_fixture",
        "execution_mode": "api_fixture_opt_in",
        "coverage_status": "automated_fixture",
        "observed": observed,
        "evaluation": {
            "status": "failed" if assertions else "passed",
            "assertions": assertions,
        },
        "evidence_artifact": evidence_artifact,
    }


def run_ai_model_hub_mobility_benchmarking_validation(
    *,
    fixture_dir: str | None = None,
    experiment_dir: str | None = None,
    models: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat()
    fixture = load_gtfs_mobility_fixture(fixture_dir)
    benchmark_rows = _build_benchmark_rows(fixture)
    fixture_assertions = _validate_fixture(fixture, benchmark_rows)
    selected_models = [dict(model) for model in (models or DEFAULT_MODELS)]
    model_ids = [str(model.get("asset_id")) for model in selected_models]
    benchmark_assertions: list[str] = []
    if len(selected_models) < 2:
        benchmark_assertions.append("At least two controlled mobility models must be selected")
    if len(set(model_ids)) != len(model_ids):
        benchmark_assertions.append("Selected mobility model identifiers must be unique")

    executions_by_model = {
        str(model["asset_id"]): [
            _execute_model(model, row, row_index)
            for row_index, row in enumerate(benchmark_rows)
        ]
        for model in selected_models
    }
    expected_execution_count = len(selected_models) * len(benchmark_rows)
    actual_execution_count = sum(len(executions) for executions in executions_by_model.values())
    if actual_execution_count != expected_execution_count:
        benchmark_assertions.append(f"Expected {expected_execution_count} executions, got {actual_execution_count}")

    metrics = _rank_metrics([
        _calculate_metrics(model, executions_by_model[str(model["asset_id"])])
        for model in selected_models
    ])
    visualization_data = _build_visualization_data(metrics, benchmark_rows)
    if len(visualization_data.get("table_rows") or []) != len(selected_models):
        benchmark_assertions.append("Visualization table must include one row per selected mobility model")
    if not visualization_data.get("best_model"):
        benchmark_assertions.append("Visualization data must identify the best mobility model")

    assertions = fixture_assertions + benchmark_assertions
    executed_cases = [
        _case_result(
            assertions,
            "mh-mob-01-mobility-benchmark-results.json",
            {
                "fixture": fixture["context"],
                "benchmark_case_count": len(benchmark_rows),
                "selected_models": model_ids,
                "execution_count": actual_execution_count,
                "best_model": visualization_data.get("best_model"),
            },
        )
    ]
    summary = {
        "total": len(executed_cases),
        "passed": sum(1 for case in executed_cases if case["evaluation"]["status"] == "passed"),
        "failed": sum(1 for case in executed_cases if case["evaluation"]["status"] == "failed"),
        "skipped": 0,
    }
    status = "failed" if summary["failed"] else "passed"
    dataset_summary = {
        "name": fixture["context"].get("fixture_name"),
        "domain": fixture["metadata"].get("domain"),
        "task": fixture["metadata"].get("task"),
        "version": fixture["metadata"].get("version"),
        "record_counts": fixture["context"].get("record_counts"),
        "join_keys": fixture["context"].get("join_keys"),
        "expected_outputs_source": fixture["context"].get("expected_outputs_source"),
    }
    result = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "status": status,
        "summary": summary,
        "timestamp": started_at,
        "dataset": dataset_summary,
        "benchmark_rows": benchmark_rows,
        "selected_models": selected_models,
        "executions_by_model": executions_by_model,
        "metrics": metrics,
        "visualization_data": visualization_data,
        "executed_cases": executed_cases,
        "evidence_index": [],
        "artifacts": {},
        "limitations": [
            "This suite validates MH-MOB-01 with a deterministic GTFS fixture and controlled model outputs.",
            "It does not call a live AI Model Hub mobility inference endpoint because that endpoint is not yet selected as a stable component contract.",
            "The generated data is UI-ready for a future Model Benchmarking mobility demo.",
        ],
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ai_model_hub_mobility_benchmarking_api.json")
        fixture_path = os.path.join(component_dir, "mh-mob-01-mobility-fixture-validation.json")
        benchmark_path = os.path.join(component_dir, "mh-mob-01-mobility-benchmark-results.json")
        artifacts = {
            "report_json": report_path,
            "mh-mob-01-mobility-fixture-validation.json": fixture_path,
            "mh-mob-01-mobility-benchmark-results.json": benchmark_path,
        }
        _write_json(
            fixture_path,
            {
                "dataset": dataset_summary,
                "benchmark_rows": benchmark_rows,
                "evaluation": {
                    "status": "failed" if fixture_assertions else "passed",
                    "assertions": fixture_assertions,
                },
            },
        )
        _write_json(
            benchmark_path,
            {
                "dataset": dataset_summary,
                "selected_models": selected_models,
                "executions_by_model": executions_by_model,
                "metrics": metrics,
                "visualization_data": visualization_data,
                "evaluation": executed_cases[0]["evaluation"],
            },
        )
        result["artifacts"] = artifacts
        result["evidence_index"] = [
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "report_json",
                "path": report_path,
            },
            {
                "scope": "case",
                "suite": SUITE_NAME,
                "test_case_id": CASE_ID,
                "artifact_name": "mh-mob-01-mobility-fixture-validation.json",
                "path": fixture_path,
            },
            {
                "scope": "case",
                "suite": SUITE_NAME,
                "test_case_id": CASE_ID,
                "artifact_name": "mh-mob-01-mobility-benchmark-results.json",
                "path": benchmark_path,
            },
        ]
        _write_json(report_path, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MH-MOB-01 AI Model Hub mobility benchmark fixture validation.")
    parser.add_argument("--fixture-dir", default="")
    parser.add_argument("--experiment-dir", default="")
    args = parser.parse_args(argv)

    result = run_ai_model_hub_mobility_benchmarking_validation(
        fixture_dir=args.fixture_dir or None,
        experiment_dir=args.experiment_dir or _default_experiment_dir(),
    )
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "summary": result.get("summary"),
                "artifact": (result.get("artifacts") or {}).get("report_json"),
            },
            indent=2,
        )
    )
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
