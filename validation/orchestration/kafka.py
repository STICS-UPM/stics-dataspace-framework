"""Kafka-related validation helpers for Level 6."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable


def should_run_kafka_edc_validation(
    *,
    flag_enabled: Callable[[str, bool], bool] | None = None,
) -> bool:
    """Kafka transfer validation is a standard Level 6 step after Newman."""
    return True


def run_kafka_edc_validation(
    connectors: list[str],
    experiment_dir: str,
    *,
    validator: Any,
    experiment_storage: Any,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    if len(connectors) < 2:
        results = [
            {
                "status": "skipped",
                "reason": "not_enough_connectors",
                "timestamp": datetime.now().isoformat(),
            }
        ]
        experiment_storage.save_kafka_edc_results_json(results, experiment_dir)
        return results

    try:
        run_kwargs = {
            "experiment_dir": experiment_dir,
        }
        if progress_callback is not None:
            run_kwargs["progress_callback"] = progress_callback
        results = list(validator.run_all(connectors, **run_kwargs) or [])
    except Exception as exc:
        results = [
            {
                "status": "failed",
                "reason": "execution_error",
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        ]
    experiment_storage.save_kafka_edc_results_json(results, experiment_dir)
    return results
