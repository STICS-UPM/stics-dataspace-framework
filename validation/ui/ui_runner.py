from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from deployers.infrastructure.lib.contracts import DeploymentContext, ValidationProfile
from validation.components.artifact_cleanup import cleanup_empty_experiment_artifact_dirs


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def ui_root_dir() -> Path:
    return _project_root() / "validation" / "ui"


def _normalize_playwright_config(config_path: str | None) -> str:
    value = str(config_path or "").replace("\\", "/").strip()
    if value.startswith("validation/ui/"):
        value = value[len("validation/ui/") :]
    return value


def build_playwright_artifact_paths(experiment_dir: str, adapter: str) -> dict[str, str]:
    base_dir = Path(experiment_dir) / "ui" / adapter
    output_dir = base_dir / "test-results"
    html_report_dir = base_dir / "playwright-report"
    blob_report_dir = base_dir / "blob-report"
    json_report_file = base_dir / "results.json"
    summary_file = base_dir / "playwright_validation.json"

    output_dir.mkdir(parents=True, exist_ok=True)
    html_report_dir.mkdir(parents=True, exist_ok=True)
    blob_report_dir.mkdir(parents=True, exist_ok=True)

    return {
        "base_dir": str(base_dir),
        "output_dir": str(output_dir),
        "html_report_dir": str(html_report_dir),
        "blob_report_dir": str(blob_report_dir),
        "json_report_file": str(json_report_file),
        "summary_file": str(summary_file),
    }


def _build_playwright_environment(
    *,
    context: DeploymentContext,
    profile: ValidationProfile,
    artifact_paths: dict[str, str],
) -> dict[str, str]:
    env = dict(os.environ)
    config = dict(context.config or {})

    env["UI_ADAPTER"] = profile.adapter or context.deployer
    env["UI_DATASPACE"] = context.dataspace_name
    env["UI_ENVIRONMENT"] = context.environment
    env["UI_DS_DOMAIN"] = context.ds_domain_base
    env["UI_KEYCLOAK_URL"] = str(
        config.get("KC_INTERNAL_URL")
        or config.get("KC_URL")
        or env.get("UI_KEYCLOAK_URL")
        or ""
    ).strip()
    env["UI_KEYCLOAK_CLIENT_ID"] = str(
        env.get("UI_KEYCLOAK_CLIENT_ID")
        or config.get("EDC_DASHBOARD_PROXY_CLIENT_ID")
        or "dataspace-users"
    ).strip()

    connectors = list(context.connectors or [])
    if connectors:
        env["UI_PROVIDER_CONNECTOR"] = connectors[0]
        env.setdefault("UI_PORTAL_CONNECTOR", connectors[0])
    if len(connectors) > 1:
        env["UI_CONSUMER_CONNECTOR"] = connectors[1]

    env["PLAYWRIGHT_OUTPUT_DIR"] = artifact_paths["output_dir"]
    env["PLAYWRIGHT_HTML_REPORT_DIR"] = artifact_paths["html_report_dir"]
    env["PLAYWRIGHT_BLOB_REPORT_DIR"] = artifact_paths["blob_report_dir"]
    env["PLAYWRIGHT_JSON_REPORT_FILE"] = artifact_paths["json_report_file"]
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKERS", "1")
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "150")

    return env


def _iter_specs(suites: list[dict[str, Any]] | None, parent_file: str | None = None):
    for suite in suites or []:
        suite_file = suite.get("file") or parent_file or suite.get("title")
        for child_suite in suite.get("suites") or []:
            yield from _iter_specs([child_suite], suite_file)
        for spec in suite.get("specs") or []:
            normalized = dict(spec)
            normalized["_suite_file"] = suite_file
            yield normalized


def _extract_spec_status(spec: dict[str, Any]) -> tuple[str, int | None]:
    tests = spec.get("tests") or []
    if not tests:
        return "skipped", None
    results = tests[0].get("results") or []
    if not results:
        return "skipped", None
    latest = results[-1]
    return str(latest.get("status") or "skipped").lower(), latest.get("duration")


def _summarize_playwright_json(json_report_file: str) -> dict[str, Any]:
    if not json_report_file or not os.path.exists(json_report_file):
        return {
            "total_specs": 0,
            "status_counts": {},
            "spec_results": [],
        }

    with open(json_report_file, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    status_counts: dict[str, int] = {}
    spec_results: list[dict[str, Any]] = []
    for spec in _iter_specs(payload.get("suites") or []):
        status, duration_ms = _extract_spec_status(spec)
        status_counts[status] = status_counts.get(status, 0) + 1
        spec_results.append(
            {
                "file": spec.get("file") or spec.get("_suite_file"),
                "title": spec.get("title"),
                "status": status,
                "duration_ms": duration_ms,
            }
        )

    return {
        "total_specs": len(spec_results),
        "status_counts": status_counts,
        "spec_results": spec_results,
    }


def run_playwright_validation(
    *,
    profile: ValidationProfile,
    context: DeploymentContext,
    experiment_dir: str,
) -> dict[str, Any]:
    adapter_name = profile.adapter or context.deployer or "unknown"
    artifact_paths = build_playwright_artifact_paths(experiment_dir, adapter_name)
    ui_dir = ui_root_dir()
    config_path = _normalize_playwright_config(profile.playwright_config)

    command = [
        "npx",
        "playwright",
        "test",
        "--config",
        config_path,
    ]
    env = _build_playwright_environment(
        context=context,
        profile=profile,
        artifact_paths=artifact_paths,
    )

    error = None
    try:
        completed = subprocess.run(
            command,
            cwd=str(ui_dir),
            env=env,
            check=False,
        )
        exit_code = completed.returncode
        status = "passed" if exit_code == 0 else "failed"
    except OSError as exc:
        exit_code = None
        status = "failed"
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }

    result = {
        "adapter": adapter_name,
        "config": config_path,
        "status": status,
        "exit_code": exit_code,
        "experiment_dir": experiment_dir,
        "command": command,
        "artifacts": artifact_paths,
        "summary": _summarize_playwright_json(artifact_paths["json_report_file"]),
        "error": error,
    }

    with open(artifact_paths["summary_file"], "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)

    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=_project_root() / "experiments")
    return result
