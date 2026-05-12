"""Playwright runners used by Level 6 validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from validation.components.artifact_cleanup import cleanup_empty_experiment_artifact_dirs


LEVEL6_UI_SMOKE_SPECS = (
    os.path.join("core", "01-login-readiness.spec.ts"),
    os.path.join("core", "04-consumer-catalog.spec.ts"),
)
LEVEL6_UI_DATASPACE_SPECS = (
    os.path.join("core", "03-provider-setup.spec.ts"),
    os.path.join("core", "03b-provider-policy-create.spec.ts"),
    os.path.join("core", "03c-provider-contract-definition-create.spec.ts"),
    os.path.join("core", "05-consumer-negotiation.spec.ts"),
    os.path.join("core", "06-consumer-transfer.spec.ts"),
)
LEVEL6_UI_OPS_SPEC = os.path.join("ops", "minio-bucket-visibility.spec.ts")
LEVEL6_UI_OPS_CONFIG = "playwright.ops.config.ts"
DEFAULT_INTERACTION_MARKER_DELAY_MS = "150"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ui_ops_suite_available(ui_test_dir: str) -> bool:
    spec_path = os.path.join(ui_test_dir, LEVEL6_UI_OPS_SPEC)
    config_path = os.path.join(ui_test_dir, LEVEL6_UI_OPS_CONFIG)
    return os.path.isfile(spec_path) and os.path.isfile(config_path)


def build_ui_artifact_paths(experiment_dir: str, connector: str) -> dict[str, str]:
    base_dir = os.path.join(experiment_dir, "ui", connector)
    paths = {
        "base_dir": base_dir,
        "output_dir": os.path.join(base_dir, "test-results"),
        "html_report_dir": os.path.join(base_dir, "playwright-report"),
        "blob_report_dir": os.path.join(base_dir, "blob-report"),
        "json_report_file": os.path.join(base_dir, "results.json"),
        "report_json": os.path.join(base_dir, "ui_core_validation.json"),
    }
    _ensure_artifact_paths(paths)
    return paths


def build_ui_ops_artifact_paths(experiment_dir: str) -> dict[str, str]:
    base_dir = os.path.join(experiment_dir, "ui-ops", "minio-console")
    paths = {
        "base_dir": base_dir,
        "output_dir": os.path.join(base_dir, "test-results"),
        "html_report_dir": os.path.join(base_dir, "playwright-report"),
        "blob_report_dir": os.path.join(base_dir, "blob-report"),
        "json_report_file": os.path.join(base_dir, "results.json"),
        "report_json": os.path.join(base_dir, "ui_ops_validation.json"),
    }
    _ensure_artifact_paths(paths)
    return paths


def build_ui_dataspace_artifact_paths(
    experiment_dir: str,
    provider_connector: str,
    consumer_connector: str,
) -> dict[str, str]:
    base_dir = os.path.join(
        experiment_dir,
        "ui-dataspace",
        f"{provider_connector}__{consumer_connector}",
    )
    paths = {
        "base_dir": base_dir,
        "output_dir": os.path.join(base_dir, "test-results"),
        "html_report_dir": os.path.join(base_dir, "playwright-report"),
        "blob_report_dir": os.path.join(base_dir, "blob-report"),
        "json_report_file": os.path.join(base_dir, "results.json"),
        "report_json": os.path.join(base_dir, "ui_dataspace_validation.json"),
    }
    _ensure_artifact_paths(paths)
    return paths


def run_ui_smoke(
    ui_test_dir: str,
    connector: str,
    portal_url: str,
    portal_user: str,
    portal_pass: str,
    experiment_dir: str,
    *,
    subprocess_module: Any,
    enrich_result: Callable[[dict[str, Any]], dict[str, Any]],
    environment: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    artifact_paths = build_ui_artifact_paths(experiment_dir, connector)
    env = {
        **(environment or os.environ),
        "PORTAL_BASE_URL": portal_url,
        "PORTAL_USER": portal_user,
        "PORTAL_PASSWORD": portal_pass,
        "PLAYWRIGHT_OUTPUT_DIR": artifact_paths["output_dir"],
        "PLAYWRIGHT_HTML_REPORT_DIR": artifact_paths["html_report_dir"],
        "PLAYWRIGHT_BLOB_REPORT_DIR": artifact_paths["blob_report_dir"],
        "PLAYWRIGHT_JSON_REPORT_FILE": artifact_paths["json_report_file"],
    }
    if extra_env:
        env.update(extra_env)
    _enable_interaction_markers_by_default(env)
    specs = list(LEVEL6_UI_SMOKE_SPECS)
    print(f"  Level 6 UI smoke profile for {connector}: {', '.join(specs)}")
    command = ["npx", "playwright", "test", *specs]
    if extra_args:
        command.extend(extra_args)

    status, exit_code, error = _run_playwright_command(
        subprocess_module,
        command,
        ui_test_dir,
        env,
    )
    result = enrich_result(
        {
            "connector": connector,
            "test": "ui-core-smoke",
            "status": status,
            "exit_code": exit_code,
            "portal_url": portal_url,
            "specs": specs,
            "artifacts": _result_artifacts(artifact_paths),
            "error": error,
        }
    )
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=_project_root() / "experiments")
    return result


def run_ui_dataspace(
    ui_test_dir: str,
    provider_connector: str,
    consumer_connector: str,
    experiment_dir: str,
    *,
    subprocess_module: Any,
    enrich_result: Callable[[dict[str, Any]], dict[str, Any]],
    environment: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    artifact_paths = build_ui_dataspace_artifact_paths(
        experiment_dir,
        provider_connector,
        consumer_connector,
    )
    base_environment = environment or os.environ
    env = {
        **base_environment,
        "UI_PROVIDER_CONNECTOR": provider_connector,
        "UI_CONSUMER_CONNECTOR": consumer_connector,
        "PORTAL_TEST_FILE_MB": base_environment.get("PORTAL_TEST_FILE_MB") or "10",
        "PLAYWRIGHT_OUTPUT_DIR": artifact_paths["output_dir"],
        "PLAYWRIGHT_HTML_REPORT_DIR": artifact_paths["html_report_dir"],
        "PLAYWRIGHT_BLOB_REPORT_DIR": artifact_paths["blob_report_dir"],
        "PLAYWRIGHT_JSON_REPORT_FILE": artifact_paths["json_report_file"],
    }
    if extra_env:
        env.update(extra_env)
    _enable_interaction_markers_by_default(env)
    specs = list(LEVEL6_UI_DATASPACE_SPECS)
    print(
        f"  Level 6 UI dataspace profile for {provider_connector} -> "
        f"{consumer_connector}: {', '.join(specs)}"
    )
    command = ["npx", "playwright", "test", "--workers=1", *specs]
    if extra_args:
        command.extend(extra_args)

    status, exit_code, error = _run_playwright_command(
        subprocess_module,
        command,
        ui_test_dir,
        env,
    )
    result = enrich_result(
        {
            "provider_connector": provider_connector,
            "consumer_connector": consumer_connector,
            "test": "ui-core-dataspace",
            "status": status,
            "exit_code": exit_code,
            "specs": specs,
            "artifacts": _result_artifacts(artifact_paths),
            "error": error,
        }
    )
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=_project_root() / "experiments")
    return result


def run_ui_ops(
    ui_test_dir: str,
    provider_connector: str,
    consumer_connector: str,
    experiment_dir: str,
    *,
    subprocess_module: Any,
    enrich_result: Callable[[dict[str, Any]], dict[str, Any]],
    environment: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    artifact_paths = build_ui_ops_artifact_paths(experiment_dir)
    env = {
        **(environment or os.environ),
        "UI_PROVIDER_CONNECTOR": provider_connector,
        "UI_CONSUMER_CONNECTOR": consumer_connector,
        "PLAYWRIGHT_OPS_OUTPUT_DIR": artifact_paths["output_dir"],
        "PLAYWRIGHT_OPS_HTML_REPORT_DIR": artifact_paths["html_report_dir"],
        "PLAYWRIGHT_OPS_BLOB_REPORT_DIR": artifact_paths["blob_report_dir"],
        "PLAYWRIGHT_OPS_JSON_REPORT_FILE": artifact_paths["json_report_file"],
    }
    if extra_env:
        env.update(extra_env)
    _enable_interaction_markers_by_default(env)
    command = [
        "npx",
        "playwright",
        "test",
        "--config",
        LEVEL6_UI_OPS_CONFIG,
        LEVEL6_UI_OPS_SPEC,
    ]
    if extra_args:
        command.extend(extra_args)

    status, exit_code, error = _run_playwright_command(
        subprocess_module,
        command,
        ui_test_dir,
        env,
    )
    result = enrich_result(
        {
            "test": "ui-ops-minio-console",
            "status": status,
            "exit_code": exit_code,
            "provider_connector": provider_connector,
            "consumer_connector": consumer_connector,
            "specs": [LEVEL6_UI_OPS_SPEC],
            "playwright_config": LEVEL6_UI_OPS_CONFIG,
            "artifacts": _result_artifacts(artifact_paths),
            "error": error,
        }
    )
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=_project_root() / "experiments")
    return result


def run_core_ui_tests(
    mode: dict[str, Any],
    *,
    ui_test_dir: str,
    ui_test_dir_exists: Callable[[str], bool],
    get_connectors: Callable[[], list[str]],
    create_experiment_directory: Callable[[], str],
    load_connector_credentials: Callable[[str], dict[str, Any] | None],
    build_connector_url: Callable[[str], str],
    run_ui_smoke: Callable[..., dict[str, Any] | None],
    run_ui_dataspace: Callable[..., dict[str, Any] | None],
    run_ui_ops: Callable[..., dict[str, Any] | None],
    ui_ops_suite_available: Callable[[str], bool],
    save_interactive_state: Callable[..., dict[str, Any]],
    environment: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not ui_test_dir_exists(ui_test_dir):
        print("Warning: validation/ui directory not found - skipping UI tests")
        return None

    connectors = get_connectors()
    if not connectors:
        print("No running connectors detected - skipping UI tests")
        return None

    experiment_dir = create_experiment_directory()
    extra_args = mode.get("args") or []
    extra_env = mode.get("env") or {}
    ui_results = []

    for connector in connectors:
        creds = load_connector_credentials(connector)
        if not creds:
            print(f"  No credentials for {connector}, skipping UI smoke tests")
            continue
        portal_url = build_connector_url(connector)
        portal_user = creds.get("connector_user", {}).get("user", "")
        portal_pass = creds.get("connector_user", {}).get("passwd", "")
        print(f"\nRunning UI core smoke suite for {connector} ({mode['label']})...")
        ui_result = run_ui_smoke(
            ui_test_dir,
            connector,
            portal_url,
            portal_user,
            portal_pass,
            experiment_dir,
            extra_args=extra_args,
            extra_env=extra_env,
        )
        if ui_result:
            ui_results.append(ui_result)

    if len(connectors) < 2:
        print("Warning: not enough connectors for UI dataspace suite - skipping")
        payload = save_interactive_state(
            experiment_dir,
            connectors,
            mode=mode,
            ui_results=ui_results,
        )
        print(f"Interactive UI results saved to {os.path.join(experiment_dir, 'experiment_results.json')}")
        return payload

    active_environment = environment or os.environ
    provider_connector = active_environment.get("UI_PROVIDER_CONNECTOR") or connectors[0]
    consumer_connector = active_environment.get("UI_CONSUMER_CONNECTOR") or next(
        (connector for connector in connectors if connector != provider_connector),
        connectors[1],
    )
    print(
        f"\nRunning UI dataspace suite for {provider_connector} -> {consumer_connector} "
        f"({mode['label']})..."
    )
    ui_result = run_ui_dataspace(
        ui_test_dir,
        provider_connector,
        consumer_connector,
        experiment_dir,
        extra_args=extra_args,
        extra_env=extra_env,
    )
    if ui_result:
        ui_results.append(ui_result)

    if ui_ops_suite_available(ui_test_dir):
        print(
            f"\nRunning UI ops MinIO suite for {provider_connector} -> {consumer_connector} "
            f"({mode['label']})..."
        )
        ui_result = run_ui_ops(
            ui_test_dir,
            provider_connector,
            consumer_connector,
            experiment_dir,
            extra_args=extra_args,
            extra_env=extra_env,
        )
        if ui_result:
            ui_results.append(ui_result)

    payload = save_interactive_state(
        experiment_dir,
        connectors,
        mode=mode,
        ui_results=ui_results,
    )
    print(f"Interactive UI results saved to {os.path.join(experiment_dir, 'experiment_results.json')}")
    return payload


def _ensure_artifact_paths(paths: dict[str, str]) -> None:
    for path in paths.values():
        if path.endswith(".json"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            os.makedirs(path, exist_ok=True)


def _enable_interaction_markers_by_default(env: dict[str, str]) -> None:
    """Keep Playwright videos readable unless the user explicitly disables markers."""
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKERS", "1")
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", DEFAULT_INTERACTION_MARKER_DELAY_MS)


def _result_artifacts(paths: dict[str, str]) -> dict[str, str]:
    return {
        "test_results_dir": paths["output_dir"],
        "html_report_dir": paths["html_report_dir"],
        "blob_report_dir": paths["blob_report_dir"],
        "json_report_file": paths["json_report_file"],
        "report_json": paths["report_json"],
    }


def _run_playwright_command(
    subprocess_module: Any,
    command: list[str],
    cwd: str,
    env: dict[str, str],
) -> tuple[str, int | None, dict[str, str] | None]:
    try:
        result = subprocess_module.run(
            command,
            cwd=cwd,
            env=env,
        )
        status = "passed" if result.returncode == 0 else "failed"
        return status, result.returncode, None
    except OSError as exc:
        return (
            "skipped",
            None,
            {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        )
