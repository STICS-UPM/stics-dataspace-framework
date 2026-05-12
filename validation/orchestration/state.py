"""Experiment state persistence helpers for Level 6 validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable


def save_level6_experiment_state(
    experiment_dir: str,
    connectors: list[str],
    *,
    status: str,
    experiment_storage: Any,
    aggregate_ui_results: Callable[..., dict[str, Any]],
    source: str = "validation.orchestration:level6",
    level6_readiness: dict[str, Any] | None = None,
    validation_reports: list[Any] | None = None,
    newman_request_metrics: list[Any] | None = None,
    kafka_metrics: Any = None,
    kafka_edc_results: list[Any] | None = None,
    storage_checks: list[Any] | None = None,
    ui_results: list[Any] | None = None,
    component_results: list[Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ui_validation = aggregate_ui_results(
        ui_results or [],
        experiment_dir=experiment_dir,
    )
    payload = {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "connectors": list(connectors or []),
        "level6_readiness": level6_readiness,
        "validation_reports": list(validation_reports or []),
        "newman_request_metrics": list(newman_request_metrics or []),
        "kafka_metrics": kafka_metrics,
        "kafka_edc_results": list(kafka_edc_results or []),
        "storage_checks": list(storage_checks or []),
        "ui_results": list(ui_results or []),
        "ui_validation": ui_validation,
        "component_results": list(component_results or []),
        "error": error,
    }
    experiment_storage.save(payload, experiment_dir=experiment_dir)
    return payload


def save_interactive_core_ui_experiment_state(
    experiment_dir: str,
    connectors: list[str],
    *,
    mode: dict[str, Any] | None,
    experiment_storage: Any,
    aggregate_ui_results: Callable[..., dict[str, Any]],
    source: str = "validation.orchestration:interactive-core-ui",
    ui_results: list[Any] | None = None,
) -> dict[str, Any]:
    ui_validation = aggregate_ui_results(
        ui_results or [],
        experiment_dir=experiment_dir,
    )
    payload = {
        "status": "completed",
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "mode": (mode or {}).get("label"),
        "connectors": list(connectors or []),
        "ui_results": list(ui_results or []),
        "ui_validation": ui_validation,
    }
    experiment_storage.save(payload, experiment_dir=experiment_dir)
    return payload
