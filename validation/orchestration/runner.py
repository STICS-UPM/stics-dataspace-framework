"""Reusable Level 6 validation orchestration.

This module owns the Level 6 execution sequence. Runtime-specific details
remain injected so the legacy INESData entrypoint can keep compatibility while
the orchestration moves into the validation layer.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Level6Runtime:
    newman_executor: Any
    ensure_connectors_ready: Callable[[], list[str]]
    ensure_connector_hosts: Callable[[list[str]], None]
    validate_connectors_deployment: Callable[[list[str]], bool]
    ensure_all_minio_policies: Callable[[list[str]], Any]
    wait_for_keycloak_readiness: Callable[[], bool]
    wait_for_validation_ready: Callable[..., dict[str, Any]]
    validation_engine: Any
    metrics_collector: Any
    experiment_storage: Any
    save_experiment_state: Callable[..., dict[str, Any]]
    should_run_kafka_edc_validation: Callable[[], bool]
    run_kafka_edc_validation: Callable[[list[str], str], list[dict[str, Any]]]
    run_kafka_benchmark: Callable[[str], Any]
    should_run_ui_dataspace: Callable[[], bool]
    should_run_ui_ops: Callable[[str], bool]
    should_run_component_validation: Callable[[], bool]
    run_component_validations: Callable[[str], list[dict[str, Any]]]
    script_dir: Callable[[], str]
    load_connector_credentials: Callable[[str], dict[str, Any] | None]
    build_connector_url: Callable[[str], str]
    run_ui_smoke: Callable[..., dict[str, Any]]
    run_ui_dataspace: Callable[..., dict[str, Any]]
    run_ui_ops: Callable[..., dict[str, Any]]


def _format_console_metric(value: Any, suffix: str = "") -> str:
    if value in (None, ""):
        return "n/a"
    return f"{value}{suffix}"


def _console_supports_color(stream=None) -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False

    force_color = os.getenv("FORCE_COLOR")
    if force_color is not None:
        return str(force_color).strip().lower() not in ("0", "false", "no", "off", "")

    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def _console_status_icon(status: Any, *, stream=None) -> str:
    status_icons = {
        "passed": ("✓", "\033[32m"),
        "failed": ("✗", "\033[31m"),
        "skipped": ("-", "\033[33m"),
    }
    normalized = str(status or "unknown").lower()
    icon, color = status_icons.get(normalized, ("?", "\033[36m"))
    if not _console_supports_color(stream=stream):
        return icon
    return f"{color}{icon}\033[0m"


def _print_kafka_transfer_steps(result: dict[str, Any], indent: str = "    ") -> None:
    steps = result.get("steps") if isinstance(result, dict) else None
    if not isinstance(steps, list) or not steps:
        return

    detail_keys = (
        "http_status",
        "state",
        "topic",
        "asset_id",
        "agreement_id",
        "transfer_id",
        "messages_consumed",
        "average_latency_ms",
    )
    print(f"{indent}Steps:")
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = _console_status_icon(step.get("status", "unknown"))
        name = step.get("name", "unknown_step")
        details = [
            f"{key}={step[key]}"
            for key in detail_keys
            if step.get(key) not in (None, "")
        ]
        suffix = f" ({', '.join(details)})" if details else ""
        print(f"{indent}  {status} {name}{suffix}")


def run_level6(runtime: Level6Runtime) -> None:
    """Run Level 6 validation using injected runtime-specific operations."""

    print("\n========================================")
    print("LEVEL 6 - VALIDATION TESTS")
    print("========================================\n")

    if not runtime.newman_executor.is_available():
        raise RuntimeError("Newman not installed. Install with: npm install or npm install -g newman")

    connectors = runtime.ensure_connectors_ready()

    if not connectors:
        raise RuntimeError("No connectors running after Vault recovery")

    runtime.ensure_connector_hosts(connectors)

    if len(connectors) < 2:
        raise RuntimeError("At least 2 connectors required")

    print(f"Detected connectors: {connectors}\n")
    experiment_dir = runtime.experiment_storage.create_experiment_directory()
    runtime.experiment_storage.save_experiment_metadata(experiment_dir, connectors)
    runtime.experiment_storage.newman_reports_dir(experiment_dir)

    validation_reports = []
    newman_request_metrics = []
    kafka_metrics = None
    kafka_edc_results = []
    storage_checks = []
    level6_readiness = None
    ui_results = []
    component_results = []
    runtime.save_experiment_state(
        experiment_dir,
        connectors,
        status="running",
        level6_readiness=level6_readiness,
        validation_reports=validation_reports,
        newman_request_metrics=newman_request_metrics,
        kafka_metrics=kafka_metrics,
        kafka_edc_results=kafka_edc_results,
        storage_checks=storage_checks,
        ui_results=ui_results,
        component_results=component_results,
    )

    try:
        if not runtime.validate_connectors_deployment(connectors):
            raise RuntimeError("Connector deployment validation failed")

        runtime.ensure_all_minio_policies(connectors)

        if not runtime.wait_for_keycloak_readiness():
            raise RuntimeError("Keycloak authentication readiness check failed")

        level6_readiness = runtime.wait_for_validation_ready(
            connectors,
            experiment_dir=experiment_dir,
        )
        runtime.save_experiment_state(
            experiment_dir,
            connectors,
            status="running",
            level6_readiness=level6_readiness,
            validation_reports=validation_reports,
            newman_request_metrics=newman_request_metrics,
            kafka_metrics=kafka_metrics,
            kafka_edc_results=kafka_edc_results,
            storage_checks=storage_checks,
            ui_results=ui_results,
            component_results=component_results,
        )
        if level6_readiness.get("status") != "passed":
            raise RuntimeError("Level 6 validation readiness check failed")

        runtime.validation_engine.last_storage_checks = []
        validation_reports = runtime.validation_engine.run_all_dataspace_tests(
            connectors,
            experiment_dir=experiment_dir,
        ) or []
        storage_checks = list(getattr(runtime.validation_engine, "last_storage_checks", []) or [])
        runtime.save_experiment_state(
            experiment_dir,
            connectors,
            status="running",
            level6_readiness=level6_readiness,
            validation_reports=validation_reports,
            newman_request_metrics=newman_request_metrics,
            kafka_metrics=kafka_metrics,
            kafka_edc_results=kafka_edc_results,
            storage_checks=storage_checks,
            ui_results=ui_results,
            component_results=component_results,
        )

        newman_request_metrics = runtime.metrics_collector.collect_experiment_newman_metrics(experiment_dir) or []
        runtime.save_experiment_state(
            experiment_dir,
            connectors,
            status="running",
            level6_readiness=level6_readiness,
            validation_reports=validation_reports,
            newman_request_metrics=newman_request_metrics,
            kafka_metrics=kafka_metrics,
            kafka_edc_results=kafka_edc_results,
            storage_checks=storage_checks,
            ui_results=ui_results,
            component_results=component_results,
        )

        if runtime.should_run_kafka_edc_validation():
            print("\nRunning Kafka transfer validation suite...")
            kafka_edc_results = runtime.run_kafka_edc_validation(connectors, experiment_dir) or []
            print("Kafka transfer validation results:")
            for result in kafka_edc_results:
                provider = result.get("provider", "unknown-provider")
                consumer = result.get("consumer", "unknown-consumer")
                status = result.get("status", "unknown")
                metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
                if status == "passed":
                    print(f"  {_console_status_icon(status)} Kafka transfer: {provider} -> {consumer}")
                    _print_kafka_transfer_steps(result)
                    if metrics:
                        print(
                            "    Messages: "
                            f"produced={_format_console_metric(metrics.get('messages_produced'))} "
                            f"consumed={_format_console_metric(metrics.get('messages_consumed'))}"
                        )
                        print(
                            "    Latency: "
                            f"avg={_format_console_metric(metrics.get('average_latency_ms'), 'ms')} "
                            f"p50={_format_console_metric(metrics.get('p50_latency_ms'), 'ms')} "
                            f"p95={_format_console_metric(metrics.get('p95_latency_ms'), 'ms')} "
                            f"p99={_format_console_metric(metrics.get('p99_latency_ms'), 'ms')}"
                        )
                elif status == "failed":
                    error = (result.get("error") or {}).get("message", "unknown reason")
                    print(f"  {_console_status_icon(status)} Kafka transfer: {provider} -> {consumer} ({error})")
                    _print_kafka_transfer_steps(result)
                else:
                    reason = result.get("reason", "unknown reason")
                    print(f"  {_console_status_icon(status)} Kafka transfer: {provider} -> {consumer} ({reason})")
                    _print_kafka_transfer_steps(result)

            runtime.save_experiment_state(
                experiment_dir,
                connectors,
                status="running",
                level6_readiness=level6_readiness,
                validation_reports=validation_reports,
                newman_request_metrics=newman_request_metrics,
                kafka_metrics=kafka_metrics,
                kafka_edc_results=kafka_edc_results,
                storage_checks=storage_checks,
                ui_results=ui_results,
                component_results=component_results,
            )

        kafka_metrics = runtime.run_kafka_benchmark(experiment_dir)
        runtime.save_experiment_state(
            experiment_dir,
            connectors,
            status="running",
            level6_readiness=level6_readiness,
            validation_reports=validation_reports,
            newman_request_metrics=newman_request_metrics,
            kafka_metrics=kafka_metrics,
            kafka_edc_results=kafka_edc_results,
            storage_checks=storage_checks,
            ui_results=ui_results,
            component_results=component_results,
        )

        _run_level6_ui(runtime, connectors, experiment_dir, ui_results)

        if runtime.should_run_component_validation():
            print("\nRunning component validation suite...")
            try:
                component_results = runtime.run_component_validations(experiment_dir) or []
            except Exception as exc:
                component_results = [
                    {
                        "component": "_component-validation",
                        "status": "failed",
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
                ]

            for result in component_results:
                component = result.get("component", "unknown-component")
                status = result.get("status", "unknown")
                if status == "passed":
                    print(f"  Component validation passed for {component}")
                elif status == "failed":
                    print(f"  Warning: component validation failed for {component}")
                else:
                    reason = result.get("reason") or (result.get("error") or {}).get("message", "unknown reason")
                    print(f"  Component validation skipped for {component} ({reason})")

        runtime.save_experiment_state(
            experiment_dir,
            connectors,
            status="completed",
            level6_readiness=level6_readiness,
            validation_reports=validation_reports,
            newman_request_metrics=newman_request_metrics,
            kafka_metrics=kafka_metrics,
            kafka_edc_results=kafka_edc_results,
            storage_checks=storage_checks,
            ui_results=ui_results,
            component_results=component_results,
        )
    except Exception as exc:
        if not newman_request_metrics:
            try:
                newman_request_metrics = runtime.metrics_collector.collect_experiment_newman_metrics(experiment_dir) or []
            except Exception as metrics_exc:
                print(f"[WARNING] Newman metrics collection failed during Level 6 error handling: {metrics_exc}")
        if kafka_metrics is None:
            try:
                kafka_metrics = runtime.run_kafka_benchmark(experiment_dir)
            except Exception as kafka_exc:
                print(f"[WARNING] Kafka benchmark failed during Level 6 error handling: {kafka_exc}")
        runtime.save_experiment_state(
            experiment_dir,
            connectors,
            status="failed",
            level6_readiness=level6_readiness,
            validation_reports=validation_reports,
            newman_request_metrics=newman_request_metrics,
            kafka_metrics=kafka_metrics,
            kafka_edc_results=kafka_edc_results,
            storage_checks=storage_checks,
            ui_results=ui_results,
            component_results=component_results,
            error={
                "type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise

    print("\n========================================")
    print("VALIDATION COMPLETED")
    print("========================================\n")


def _run_level6_ui(runtime: Level6Runtime, connectors: list[str], experiment_dir: str, ui_results: list[dict[str, Any]]) -> None:
    ui_test_dir = os.path.join(runtime.script_dir(), "validation", "ui")
    if not os.path.isdir(ui_test_dir):
        print("Warning: validation/ui directory not found - skipping UI smoke tests")
        return

    for connector in connectors:
        creds = runtime.load_connector_credentials(connector)
        if not creds:
            print(f"  No credentials for {connector}, skipping UI smoke tests")
            ui_results.append({
                "connector": connector,
                "test": "ui-core-smoke",
                "status": "skipped",
                "reason": "missing_credentials",
            })
            continue
        portal_url = runtime.build_connector_url(connector)
        portal_user = creds.get("connector_user", {}).get("user", "")
        portal_pass = creds.get("connector_user", {}).get("passwd", "")
        print(f"\nRunning UI core smoke suite for {connector}...")
        ui_result = runtime.run_ui_smoke(
            ui_test_dir,
            connector,
            portal_url,
            portal_user,
            portal_pass,
            experiment_dir,
        )
        ui_results.append(ui_result)
        if ui_result["status"] == "failed":
            print(
                f"  Warning: UI core smoke suite failed for {connector} "
                f"(exit {ui_result['exit_code']})"
            )
        elif ui_result["status"] == "skipped":
            skip_reason = (ui_result.get("error") or {}).get("message", "unknown reason")
            print(f"  Warning: UI core smoke suite skipped for {connector} ({skip_reason})")
        else:
            print(f"  UI core smoke suite passed for {connector}")

    if runtime.should_run_ui_dataspace():
        _run_level6_ui_dataspace(runtime, connectors, experiment_dir, ui_results)

    if runtime.should_run_ui_ops(ui_test_dir):
        _run_level6_ui_ops(runtime, connectors, experiment_dir, ui_results)


def _run_level6_ui_dataspace(
    runtime: Level6Runtime,
    connectors: list[str],
    experiment_dir: str,
    ui_results: list[dict[str, Any]],
) -> None:
    if len(connectors) < 2:
        print("Warning: not enough connectors for UI dataspace suite - skipping")
        ui_results.append({
            "test": "ui-core-dataspace",
            "status": "skipped",
            "reason": "not_enough_connectors",
        })
        return

    provider_connector = os.environ.get("UI_PROVIDER_CONNECTOR") or connectors[0]
    consumer_connector = os.environ.get("UI_CONSUMER_CONNECTOR") or next(
        (connector for connector in connectors if connector != provider_connector),
        connectors[1],
    )
    print(
        f"\nRunning UI dataspace suite for "
        f"{provider_connector} -> {consumer_connector}..."
    )
    ui_result = runtime.run_ui_dataspace(
        os.path.join(runtime.script_dir(), "validation", "ui"),
        provider_connector,
        consumer_connector,
        experiment_dir,
    )
    ui_results.append(ui_result)
    if ui_result["status"] == "failed":
        print(
            f"  Warning: UI dataspace suite failed for "
            f"{provider_connector} -> {consumer_connector} "
            f"(exit {ui_result['exit_code']})"
        )
    elif ui_result["status"] == "skipped":
        skip_reason = (ui_result.get("error") or {}).get("message", "unknown reason")
        print(
            f"  Warning: UI dataspace suite skipped for "
            f"{provider_connector} -> {consumer_connector} ({skip_reason})"
        )
    else:
        print(
            f"  UI dataspace suite passed for "
            f"{provider_connector} -> {consumer_connector}"
        )


def _run_level6_ui_ops(
    runtime: Level6Runtime,
    connectors: list[str],
    experiment_dir: str,
    ui_results: list[dict[str, Any]],
) -> None:
    if len(connectors) < 2:
        print("Warning: not enough connectors for UI ops MinIO suite - skipping")
        ui_results.append({
            "test": "ui-ops-minio-console",
            "status": "skipped",
            "reason": "not_enough_connectors",
        })
        return

    provider_connector = os.environ.get("UI_PROVIDER_CONNECTOR") or connectors[0]
    consumer_connector = os.environ.get("UI_CONSUMER_CONNECTOR") or next(
        (connector for connector in connectors if connector != provider_connector),
        connectors[1],
    )
    print(
        f"\nRunning UI ops MinIO suite for "
        f"{provider_connector} -> {consumer_connector}..."
    )
    ui_ops_result = runtime.run_ui_ops(
        os.path.join(runtime.script_dir(), "validation", "ui"),
        provider_connector,
        consumer_connector,
        experiment_dir,
    )
    ui_results.append(ui_ops_result)
    if ui_ops_result["status"] == "failed":
        print(
            "  Warning: UI ops MinIO suite failed "
            f"(exit {ui_ops_result['exit_code']})"
        )
    elif ui_ops_result["status"] == "skipped":
        skip_reason = (ui_ops_result.get("error") or {}).get("message", "unknown reason")
        print(f"  Warning: UI ops MinIO suite skipped ({skip_reason})")
    else:
        print("  UI ops MinIO suite passed")
