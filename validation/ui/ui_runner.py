from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


def _join_url_path(base_url: str | None, path_value: str | None) -> str:
    base = str(base_url or "").strip().rstrip("/")
    path = str(path_value or "").strip()
    if not base:
        return ""
    if not path:
        return base
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path.rstrip('/')}"


def _force_url_scheme(base_url: str | None, scheme: str) -> str:
    raw_value = str(base_url or "").strip().rstrip("/")
    if not raw_value:
        return ""
    parsed = urlsplit(raw_value if "://" in raw_value else f"{scheme}://{raw_value}")
    if not parsed.netloc:
        return ""
    return urlunsplit((scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _model_server_connector_base_url(config: dict[str, Any], topology: str | None = None) -> str:
    explicit = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL")
        or config.get("MODEL_SERVER_CONNECTOR_BASE_URL")
        or config.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL")
        or config.get("MODEL_SERVER_CONNECTOR_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")

    if str(topology or "").strip().lower() != "vm-distributed":
        return ""

    path_value = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH")
        or config.get("MODEL_SERVER_PUBLIC_PATH")
        or "/model-server"
    ).strip()
    for base_candidate in (
        config.get("VM_COMMON_HTTP_URL"),
        config.get("VM_COMMON_PUBLIC_URL"),
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL"),
        config.get("COMPONENTS_PUBLIC_BASE_URL"),
    ):
        base_url = _force_url_scheme(base_candidate, "http")
        if base_url:
            return _join_url_path(base_url, path_value)
    return ""


def _model_server_public_base_url(config: dict[str, Any]) -> str:
    explicit = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL")
        or config.get("MODEL_SERVER_PUBLIC_URL")
        or config.get("AI_MODEL_HUB_MODEL_SERVER_BASE_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")

    components_base = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL")
        or config.get("COMPONENTS_PUBLIC_BASE_URL")
        or ""
    ).strip()
    path_value = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH")
        or config.get("MODEL_SERVER_PUBLIC_PATH")
        or "/model-server"
    ).strip()
    return _join_url_path(components_base, path_value)


def _build_playwright_environment(
    *,
    context: DeploymentContext,
    profile: ValidationProfile,
    artifact_paths: dict[str, str],
) -> dict[str, str]:
    env = dict(os.environ)
    config = dict(context.config or {})
    adapter = profile.adapter or context.deployer or "unknown"
    keycloak_url = str(
        config.get("KEYCLOAK_FRONTEND_URL")
        or config.get("KEYCLOAK_PUBLIC_URL")
        or config.get("KC_INTERNAL_URL")
        or config.get("KC_URL")
        or env.get("UI_KEYCLOAK_URL")
        or ""
    ).strip()

    env["UI_ADAPTER"] = adapter
    env["UI_DATASPACE"] = context.dataspace_name
    env["UI_ENVIRONMENT"] = context.environment
    env["UI_DS_DOMAIN"] = context.ds_domain_base
    env["UI_TOPOLOGY"] = context.topology
    env["UI_KEYCLOAK_URL"] = keycloak_url
    runtime_dir = str(getattr(context, "runtime_dir", "") or "").strip()
    if runtime_dir:
        env["UI_RUNTIME_DIR"] = runtime_dir
    env["UI_KEYCLOAK_CLIENT_ID"] = str(
        env.get("UI_KEYCLOAK_CLIENT_ID")
        or config.get("EDC_DASHBOARD_PROXY_CLIENT_ID")
        or "dataspace-users"
    ).strip()
    components_namespace = str(
        config.get("COMPONENTS_NAMESPACE")
        or getattr(context.namespace_roles, "components_namespace", "")
        or ""
    ).strip()
    if components_namespace:
        env["UI_COMPONENTS_NAMESPACE"] = components_namespace
    explicit_ui_protocol_address_mode = str(
        env.get("UI_CONNECTOR_PROTOCOL_ADDRESS_MODE")
        or config.get("UI_CONNECTOR_PROTOCOL_ADDRESS_MODE")
        or ""
    ).strip()
    configured_protocol_address_mode = str(
        config.get("PIONERA_CONNECTOR_PROTOCOL_ADDRESS_MODE")
        or config.get("CONNECTOR_PROTOCOL_ADDRESS_MODE")
        or ""
    ).strip()
    if explicit_ui_protocol_address_mode:
        protocol_address_mode = explicit_ui_protocol_address_mode
    elif configured_protocol_address_mode:
        protocol_address_mode = configured_protocol_address_mode
    elif str(context.topology or "").strip().lower() == "vm-distributed":
        protocol_address_mode = "public"
    else:
        protocol_address_mode = ""
    if protocol_address_mode:
        env["UI_CONNECTOR_PROTOCOL_ADDRESS_MODE"] = protocol_address_mode
    connector_model_server_url = _model_server_connector_base_url(config, topology=context.topology)
    if connector_model_server_url:
        env.setdefault("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL", connector_model_server_url)
        env.setdefault("UI_AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL", connector_model_server_url)
    model_server_url = connector_model_server_url or _model_server_public_base_url(config)
    if model_server_url:
        env.setdefault("AI_MODEL_HUB_MODEL_SERVER_BASE_URL", model_server_url)

    connectors = list(context.connectors or [])
    if connectors:
        env["UI_PROVIDER_CONNECTOR"] = connectors[0]
        env.setdefault("UI_PORTAL_CONNECTOR", connectors[0])
    if len(connectors) > 1:
        env["UI_CONSUMER_CONNECTOR"] = connectors[1]

    local_store_label = str(config.get("INESDATA_LOCAL_STORE_LABEL") or "").strip()
    if local_store_label:
        env["UI_INESDATA_LOCAL_STORE_LABEL"] = local_store_label

    env["PLAYWRIGHT_OUTPUT_DIR"] = artifact_paths["output_dir"]
    env["PLAYWRIGHT_HTML_REPORT_DIR"] = artifact_paths["html_report_dir"]
    env["PLAYWRIGHT_BLOB_REPORT_DIR"] = artifact_paths["blob_report_dir"]
    env["PLAYWRIGHT_JSON_REPORT_FILE"] = artifact_paths["json_report_file"]
    if adapter.lower() == "inesdata":
        env.setdefault("PIONERA_PLAYWRIGHT_SUITE_NAME", "INESData integration")
        env.setdefault("UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO", "1")
        env.setdefault("UI_ONTOLOGY_HUB_INESDATA_DEMO", "1")
        env.setdefault("UI_AI_MODEL_HUB_HTTPDATA_DEMO", "1")
        env.setdefault("UI_AI_MODEL_OBSERVER_DEMO", "1")
    elif adapter.lower() == "edc":
        env.setdefault("PIONERA_PLAYWRIGHT_SUITE_NAME", "EDC Playwright")
    else:
        env.setdefault("PIONERA_PLAYWRIGHT_SUITE_NAME", f"{adapter} Playwright")
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

    env = _build_playwright_environment(
        context=context,
        profile=profile,
        artifact_paths=artifact_paths,
    )
    command = [
        "npx",
        "playwright",
        "test",
        "--config",
        config_path,
    ]
    max_failures = str(
        env.get("PIONERA_PLAYWRIGHT_MAX_FAILURES")
        or env.get("PLAYWRIGHT_MAX_FAILURES")
        or ""
    ).strip()
    if max_failures:
        command.extend(["--max-failures", max_failures])

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
