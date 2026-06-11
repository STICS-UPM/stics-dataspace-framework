from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime
from typing import Any

import requests

from validation.components.ai_model_hub.model_execution_api import (
    FLARES_DATASET_DIR,
    load_flares_dataset,
)
from validation.components.ai_model_hub.model_server_policy import (
    model_server_execution_labels,
    model_server_validation_state,
)


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "model-benchmarking-api"
CASE_IDS = ["PT5-MH-12", "PT5-MH-13", "PT5-MH-14", "PT5-MH-15"]
BENCHMARK_MAPPING = {
    "inputPath": "request",
    "expectedPath": "expected_label",
    "predictionPath": "0.Reliability_Label",
}

DEFAULT_MODELS = [
    {
        "asset_id": "model-flares-reliability-albert",
        "name": "FLARES Reliability ALBERT",
        "variant": "albert",
        "task": "text-classification",
        "framework": "flares",
        "endpoint_path": "/flares/dccuchile-albert-base-spanish-reliability",
        "base_latency_ms": 54,
        "latency_step_ms": 5,
        "description": "Real FLARES reliability Transformer model exposed by the AIModelHub use-case model server.",
    },
    {
        "asset_id": "model-flares-reliability-bert",
        "name": "FLARES Reliability BERT",
        "variant": "bert",
        "task": "text-classification",
        "framework": "flares",
        "endpoint_path": "/flares/dccuchile-bert-base-spanish-wwm-uncased-reliability",
        "base_latency_ms": 72,
        "latency_step_ms": 6,
        "description": "Real FLARES reliability Transformer model exposed by the AIModelHub use-case model server.",
    },
    {
        "asset_id": "model-flares-reliability-distilbert",
        "name": "FLARES Reliability DistilBERT",
        "variant": "distilbert",
        "task": "text-classification",
        "framework": "flares",
        "endpoint_path": "/flares/dccuchile-distilbert-base-spanish-uncased-reliability",
        "base_latency_ms": 40,
        "latency_step_ms": 4,
        "description": "Real FLARES reliability Transformer model exposed by the AIModelHub use-case model server.",
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


def _default_experiment_dir() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join("experiments", f"ai-model-hub-model-benchmarking-api-{timestamp}")


def _summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(cases), "passed": 0, "failed": 0, "skipped": 0}
    for case in cases:
        status = ((case.get("evaluation") or {}).get("status") or "").lower()
        if status in summary:
            summary[status] += 1
    return summary


def _expected_labels_by_id(fixture: dict[str, Any]) -> dict[int, str]:
    records = ((fixture.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get("records") or []
    return {
        int(record["Id"]): str(record["expectedReliability"])
        for record in records
        if "Id" in record and "expectedReliability" in record
    }


def build_flares_benchmark_rows(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    expected_labels = _expected_labels_by_id(fixture)
    rows: list[dict[str, Any]] = []
    for record in list(fixture.get("trial_sample") or []):
        record_id = int(record["Id"])
        expected_label = expected_labels.get(record_id) or str(record.get("Reliability_Label") or "")
        rows.append(
            {
                "record_id": record_id,
                "input": {
                    "text": record.get("Text"),
                    "w1h_label": record.get("5W1H_Label"),
                    "tag_text": record.get("Tag_Text"),
                },
                "request": [
                    {
                        "Id": record_id,
                        "Text": record.get("Text"),
                        "5W1H_Label": record.get("5W1H_Label"),
                        "Tag_Text": record.get("Tag_Text"),
                        "Tag_Start": record.get("Tag_Start"),
                        "Tag_End": record.get("Tag_End"),
                    }
                ],
                "expected_label": expected_label,
                "annotation": {
                    "tag_start": record.get("Tag_Start"),
                    "tag_end": record.get("Tag_End"),
                },
            }
        )
    return rows


def _input_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _model_server_base_url(explicit_base_url: str | None = None) -> str:
    candidates = [
        explicit_base_url,
        os.environ.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL"),
        os.environ.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL"),
        os.environ.get("AI_MODEL_HUB_MODEL_SERVER_BASE_URL"),
        os.environ.get("UI_AI_MODEL_HUB_MODEL_SERVER_BASE_URL"),
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip().rstrip("/")
        if normalized:
            return normalized
    return ""


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{str(path or '').lstrip('/')}"


def _predicted_label_from_response(body: Any) -> str:
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return str(body[0].get("Reliability_Label") or "")
    if isinstance(body, dict):
        result = body.get("result")
        if isinstance(result, dict):
            return str(result.get("label") or result.get("Reliability_Label") or "")
        return str(body.get("Reliability_Label") or body.get("label") or "")
    return ""


def _predict_label(model: dict[str, Any], row: dict[str, Any]) -> str:
    record_id = int(row.get("record_id"))
    if record_id in set(model.get("mispredict_record_ids") or []):
        return str(model.get("misprediction_label") or "confiable")
    return str(row.get("expected_label") or "")


def _execute_model(
    model: dict[str, Any],
    row: dict[str, Any],
    row_index: int,
    *,
    model_server_base_url: str = "",
) -> dict[str, Any]:
    expected_label = str(row.get("expected_label") or "")
    request_payload = row.get("request")
    endpoint_path = str(model.get("endpoint_path") or "")
    endpoint_url = _join_url(model_server_base_url, endpoint_path) if model_server_base_url and endpoint_path else ""
    response_body: Any
    http_status: int | None
    error = ""

    if endpoint_url:
        started = time.perf_counter()
        try:
            response = requests.post(endpoint_url, json=request_payload, timeout=60)
            latency_ms = int((time.perf_counter() - started) * 1000)
            http_status = response.status_code
            try:
                response_body = response.json()
            except ValueError:
                response_body = {"text": response.text[:500]}
            predicted_label = _predicted_label_from_response(response_body)
            status = "passed" if 200 <= response.status_code < 300 and predicted_label else "failed"
            if response.status_code < 200 or response.status_code >= 300:
                error = f"Model server returned HTTP {response.status_code}"
            elif not predicted_label:
                error = "Model server response did not include Reliability_Label"
        except requests.RequestException as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            http_status = None
            response_body = None
            predicted_label = ""
            status = "failed"
            error = str(exc)
    else:
        latency_ms = int(model.get("base_latency_ms") or 0) + (row_index % 3) * int(model.get("latency_step_ms") or 0)
        predicted_label = _predict_label(model, row)
        http_status = None
        response_body = [{"Reliability_Label": predicted_label}]
        status = "passed"

    return {
        "model_asset_id": model.get("asset_id"),
        "model_name": model.get("name"),
        "record_id": row.get("record_id"),
        "input_fingerprint": _input_fingerprint(request_payload),
        "expected_label": expected_label,
        "request": request_payload,
        "endpoint_url": endpoint_url,
        "http_status": http_status,
        "response": response_body,
        "latency_ms": latency_ms,
        "status": status,
        "error": error,
        "correct": predicted_label == expected_label,
    }


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((percentile / 100.0) * len(ordered)) - 1))
    return float(ordered[index])


def _round_metric(value: float) -> float:
    return round(float(value), 2)


def _calculate_metrics(model: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
    sample_count = len(executions)
    success_count = sum(1 for execution in executions if execution.get("status") == "passed")
    correct_count = sum(1 for execution in executions if execution.get("correct"))
    latencies = [int(execution.get("latency_ms") or 0) for execution in executions]
    total_latency_ms = sum(latencies)
    average_latency_ms = (total_latency_ms / sample_count) if sample_count else 0.0
    success_rate = (success_count / sample_count * 100.0) if sample_count else 0.0
    accuracy_percent = (correct_count / sample_count * 100.0) if sample_count else 0.0
    throughput_rps = (sample_count / (total_latency_ms / 1000.0)) if total_latency_ms else 0.0
    latency_score = max(0.0, 100.0 - average_latency_ms)
    score = (accuracy_percent * 0.6) + (success_rate * 0.2) + (latency_score * 0.2)
    return {
        "model_asset_id": model.get("asset_id"),
        "model_name": model.get("name"),
        "variant": model.get("variant"),
        "sample_count": sample_count,
        "success_count": success_count,
        "error_count": sample_count - success_count,
        "correct_count": correct_count,
        "success_rate": _round_metric(success_rate),
        "accuracy_percent": _round_metric(accuracy_percent),
        "average_latency_ms": _round_metric(average_latency_ms),
        "p95_latency_ms": _round_metric(_percentile(latencies, 95)),
        "throughput_rps": _round_metric(throughput_rps),
        "score": _round_metric(score),
    }


def _rank_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(metrics, key=lambda item: (-float(item.get("score") or 0), float(item.get("average_latency_ms") or 0)))
    return [{**metric, "rank": index + 1} for index, metric in enumerate(ranked)]


def _build_visualization_data(ranked_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    table_rows = [
        {
            "rank": metric.get("rank"),
            "model": metric.get("model_name"),
            "accuracy_percent": metric.get("accuracy_percent"),
            "success_rate": metric.get("success_rate"),
            "average_latency_ms": metric.get("average_latency_ms"),
            "p95_latency_ms": metric.get("p95_latency_ms"),
            "throughput_rps": metric.get("throughput_rps"),
            "score": metric.get("score"),
        }
        for metric in ranked_metrics
    ]
    chart_series = [
        {
            "metric": "accuracy_percent",
            "label": "Accuracy (%)",
            "points": [{"model": metric.get("model_name"), "value": metric.get("accuracy_percent")} for metric in ranked_metrics],
        },
        {
            "metric": "average_latency_ms",
            "label": "Average latency (ms)",
            "points": [{"model": metric.get("model_name"), "value": metric.get("average_latency_ms")} for metric in ranked_metrics],
        },
        {
            "metric": "score",
            "label": "Benchmark score",
            "points": [{"model": metric.get("model_name"), "value": metric.get("score")} for metric in ranked_metrics],
        },
    ]
    return {
        "title": "AI Model Hub FLARES benchmark comparison",
        "best_model": table_rows[0]["model"] if table_rows else None,
        "table_rows": table_rows,
        "chart_series": chart_series,
    }


def _case_result(
    *,
    case_id: str,
    description: str,
    validation_type: str,
    dataspace_dimension: str,
    execution_mode: str,
    coverage_status: str,
    assertions: list[str],
    evidence_artifact: str,
    observed: dict[str, Any],
) -> dict[str, Any]:
    return {
        "test_case_id": case_id,
        "description": description,
        "type": "api",
        "case_group": "pt5",
        "validation_type": validation_type,
        "dataspace_dimension": dataspace_dimension,
        "mapping_status": "phase_3",
        "automation_mode": "api_fixture",
        "execution_mode": execution_mode,
        "coverage_status": coverage_status,
        "observed": observed,
        "evaluation": {
            "status": "failed" if assertions else "passed",
            "assertions": assertions,
        },
        "evidence_artifact": evidence_artifact,
    }


def run_ai_model_hub_model_benchmarking_validation(
    *,
    source_dir: str | None = None,
    experiment_dir: str | None = None,
    models: list[dict[str, Any]] | None = None,
    model_server_base_url: str | None = None,
    model_server_mode: str | None = None,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat()
    dataset = load_flares_dataset(source_dir or FLARES_DATASET_DIR)
    benchmark_rows = build_flares_benchmark_rows(dataset)
    selected_models = [dict(model) for model in (models or DEFAULT_MODELS)]
    resolved_model_server_base_url = _model_server_base_url(model_server_base_url)
    policy_config: dict[str, Any] = {}
    if resolved_model_server_base_url:
        policy_config["AI_MODEL_HUB_MODEL_SERVER_BASE_URL"] = resolved_model_server_base_url
    if model_server_mode:
        policy_config["AI_MODEL_HUB_MODEL_SERVER_MODE"] = model_server_mode
    model_server_state = model_server_validation_state(policy_config)
    if resolved_model_server_base_url:
        execution_mode, coverage_status = model_server_execution_labels(str(model_server_state.get("mode") or ""))
    else:
        execution_mode = "api_fixture"
        coverage_status = "automated_fixture_fallback"
    executions_by_model = {
        str(model["asset_id"]): [
            _execute_model(model, row, row_index, model_server_base_url=resolved_model_server_base_url)
            for row_index, row in enumerate(benchmark_rows)
        ]
        for model in selected_models
    }
    raw_metrics = [
        _calculate_metrics(model, executions_by_model[str(model["asset_id"])])
        for model in selected_models
    ]
    ranked_metrics = _rank_metrics(raw_metrics)
    visualization_data = _build_visualization_data(ranked_metrics)
    dataset_summary = {
        "name": (dataset.get("metadata") or {}).get("datasetName") or "FLARES",
        "domain": (dataset.get("metadata") or {}).get("domain") or "linguistic",
        "row_count": len(benchmark_rows),
        "mapping": BENCHMARK_MAPPING,
        "model_server_base_url": resolved_model_server_base_url,
        "model_server_mode": model_server_state.get("mode"),
        "expected_outputs_source": dataset.get("expected_outputs_source"),
        "class_distribution": ((dataset.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get(
            "classDistribution"
        ),
    }

    comparable_input_fingerprints = {
        row.get("record_id"): _input_fingerprint(row.get("request"))
        for row in benchmark_rows
    }
    selected_model_ids = [str(model.get("asset_id")) for model in selected_models]
    selection_assertions: list[str] = []
    if len(selected_models) < 2:
        selection_assertions.append("At least two models must be selected for comparison")
    if not benchmark_rows:
        selection_assertions.append("Benchmark dataset must contain at least one row")
    if len(set(selected_model_ids)) != len(selected_model_ids):
        selection_assertions.append("Selected model asset identifiers must be unique")

    execution_assertions: list[str] = []
    expected_execution_count = len(selected_models) * len(benchmark_rows)
    actual_execution_count = sum(len(executions) for executions in executions_by_model.values())
    if actual_execution_count != expected_execution_count:
        execution_assertions.append(
            f"Expected {expected_execution_count} executions, got {actual_execution_count}"
        )
    for model_id, executions in executions_by_model.items():
        executed_fingerprints = {
            execution.get("record_id"): execution.get("input_fingerprint")
            for execution in executions
        }
        if executed_fingerprints != comparable_input_fingerprints:
            execution_assertions.append(f"Model {model_id} was not executed with the same benchmark inputs")
        failed_executions = [execution for execution in executions if execution.get("status") != "passed"]
        if failed_executions:
            first_error = str(failed_executions[0].get("error") or "unknown error")
            execution_assertions.append(f"Model {model_id} had {len(failed_executions)} failed real executions: {first_error}")

    metrics_assertions: list[str] = []
    if len(ranked_metrics) != len(selected_models):
        metrics_assertions.append("Metrics must be produced for every selected model")
    for metric in ranked_metrics:
        accuracy = metric.get("accuracy_percent")
        if accuracy is None or not 0 <= float(accuracy) <= 100:
            metrics_assertions.append("Accuracy metrics must stay between 0 and 100")
            break
    if [metric.get("rank") for metric in ranked_metrics] != list(range(1, len(ranked_metrics) + 1)):
        metrics_assertions.append("Benchmark metrics must include a stable ranking")

    visualization_assertions: list[str] = []
    if len(visualization_data.get("table_rows") or []) != len(selected_models):
        visualization_assertions.append("Visualization table must include one row per model")
    if len(visualization_data.get("chart_series") or []) < 3:
        visualization_assertions.append("Visualization data must include accuracy, latency and score series")
    if not visualization_data.get("best_model"):
        visualization_assertions.append("Visualization data must identify the best model")

    executed_cases = [
        _case_result(
            case_id="PT5-MH-12",
            description="Select multiple comparable models for AI Model Hub benchmarking",
            validation_type="functional",
            dataspace_dimension="comparison",
            execution_mode=execution_mode,
            coverage_status=coverage_status,
            assertions=selection_assertions,
            evidence_artifact="pt5-mh-12-model-selection.json",
            observed={
                "selected_models": selected_model_ids,
                "dataset_row_count": len(benchmark_rows),
                "mapping": BENCHMARK_MAPPING,
            },
        ),
        _case_result(
            case_id="PT5-MH-13",
            description="Execute selected models with the same FLARES benchmark inputs",
            validation_type="functional",
            dataspace_dimension="comparison",
            execution_mode=execution_mode,
            coverage_status=coverage_status,
            assertions=execution_assertions,
            evidence_artifact="pt5-mh-13-benchmark-executions.json",
            observed={
                "model_count": len(selected_models),
                "dataset_row_count": len(benchmark_rows),
                "execution_count": actual_execution_count,
            },
        ),
        _case_result(
            case_id="PT5-MH-14",
            description="Collect and calculate coherent comparison metrics",
            validation_type="functional",
            dataspace_dimension="comparison",
            execution_mode=execution_mode,
            coverage_status=coverage_status,
            assertions=metrics_assertions,
            evidence_artifact="pt5-mh-14-benchmark-metrics.json",
            observed={
                "metrics": ranked_metrics,
                "best_model": visualization_data.get("best_model"),
            },
        ),
        _case_result(
            case_id="PT5-MH-15",
            description="Produce renderable benchmark tables and chart data",
            validation_type="functional",
            dataspace_dimension="comparison",
            execution_mode=execution_mode,
            coverage_status=coverage_status,
            assertions=visualization_assertions,
            evidence_artifact="pt5-mh-15-benchmark-visualization-data.json",
            observed={
                "table_rows": len(visualization_data.get("table_rows") or []),
                "chart_series": [series.get("metric") for series in visualization_data.get("chart_series") or []],
                "best_model": visualization_data.get("best_model"),
            },
        ),
    ]

    summary = _summary(executed_cases)
    status = "failed" if summary["failed"] else "passed"
    result = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "status": status,
        "summary": summary,
        "timestamp": started_at,
        "dataset": dataset_summary,
        "selected_models": selected_models,
        "model_server_base_url": resolved_model_server_base_url,
        "model_server": {
            "enabled": bool(model_server_state.get("enabled")) if resolved_model_server_base_url else False,
            "mode": model_server_state.get("mode"),
            "configured_mode": model_server_state.get("configured_mode"),
            "coverage_status": coverage_status,
            "execution_mode": execution_mode,
        },
        "executions_by_model": executions_by_model,
        "metrics": ranked_metrics,
        "visualization_data": visualization_data,
        "executed_cases": executed_cases,
        "evidence_index": [],
        "artifacts": {},
        "limitations": [],
    }
    if not resolved_model_server_base_url:
        result["limitations"].append(
            "This run did not receive an AI Model Hub model-server URL; the suite used deterministic fixture fallback evidence instead of real FLARES model-server calls."
        )
    elif model_server_state.get("mode") == "mock":
        result["limitations"].append(
            "The AI Model Hub model-server endpoint was configured in mock mode; evidence covers framework integration with deterministic responses, not production model quality."
        )

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ai_model_hub_model_benchmarking_api.json")
        selection_path = os.path.join(component_dir, "pt5-mh-12-model-selection.json")
        executions_path = os.path.join(component_dir, "pt5-mh-13-benchmark-executions.json")
        metrics_path = os.path.join(component_dir, "pt5-mh-14-benchmark-metrics.json")
        visualization_path = os.path.join(component_dir, "pt5-mh-15-benchmark-visualization-data.json")
        artifacts = {
            "report_json": report_path,
            "pt5-mh-12-model-selection.json": selection_path,
            "pt5-mh-13-benchmark-executions.json": executions_path,
            "pt5-mh-14-benchmark-metrics.json": metrics_path,
            "pt5-mh-15-benchmark-visualization-data.json": visualization_path,
        }
        _write_json(
            selection_path,
            {
                "dataset": dataset_summary,
                "selected_models": selected_models,
                "evaluation": executed_cases[0]["evaluation"],
            },
        )
        _write_json(
            executions_path,
            {
                "dataset": dataset_summary,
                "input_fingerprints": comparable_input_fingerprints,
                "executions_by_model": executions_by_model,
                "evaluation": executed_cases[1]["evaluation"],
            },
        )
        _write_json(
            metrics_path,
            {
                "metrics": ranked_metrics,
                "evaluation": executed_cases[2]["evaluation"],
            },
        )
        _write_json(
            visualization_path,
            {
                "visualization_data": visualization_data,
                "evaluation": executed_cases[3]["evaluation"],
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
            *[
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": case_id,
                    "artifact_name": artifact_name,
                    "path": artifacts[artifact_name],
                }
                for case_id, artifact_name in zip(CASE_IDS, list(artifacts.keys())[1:])
            ],
        ]
        _write_json(report_path, result)

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PT5-MH-12..15 AI Model Hub model benchmarking validation.")
    parser.add_argument("--source-dir", default="")
    parser.add_argument("--experiment-dir", default="")
    args = parser.parse_args(argv)

    result = run_ai_model_hub_model_benchmarking_validation(
        source_dir=args.source_dir or None,
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
