from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from deployers.infrastructure.lib.contracts import DeploymentContext, ValidationProfile
from deployers.infrastructure.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    normalize_topology,
)
from deployers.shared.lib.vm_distributed_public_access import (
    is_vm_public_placeholder_url,
    resolve_vm_distributed_public_urls,
)
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


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _connector_env_prefix(connector_name: str) -> str:
    return str(connector_name or "").strip().upper().replace("-", "_")


def _string_config(config: dict[str, Any], topology: str) -> dict[str, str]:
    values = {
        str(key): str(value)
        for key, value in (config or {}).items()
        if value is not None
    }
    values["TOPOLOGY"] = topology
    return values


def _edc_connector_public_access_urls(
    config: dict[str, Any],
    *,
    topology: str,
    connector: str,
    dataspace: str,
    environment: str,
) -> dict[str, str]:
    if topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
        return {}
    try:
        from deployers.edc.bootstrap import build_connector_public_access_urls
    except (ImportError, OSError):
        return {}

    urls = build_connector_public_access_urls(
        _string_config(config, topology),
        connector,
        dataspace,
        environment,
    )
    return {str(key): str(value).strip() for key, value in urls.items() if str(value or "").strip()}


def _export_edc_public_connector_runtime_urls(
    env: dict[str, str],
    *,
    config: dict[str, Any],
    topology: str,
    connectors: list[str],
    dataspace: str,
    environment: str,
    protocol_address_mode: str,
) -> None:
    if topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
        return

    use_public_protocol = str(protocol_address_mode or "").strip().lower() == "public"
    for connector in connectors:
        env_prefix = _connector_env_prefix(connector)
        if not env_prefix:
            continue
        urls = _edc_connector_public_access_urls(
            config,
            topology=topology,
            connector=connector,
            dataspace=dataspace,
            environment=environment,
        )
        portal_url = _first_non_empty(urls.get("edc_dashboard_login"), urls.get("connector_ingress"))
        management_url = _first_non_empty(
            urls.get("connector_management_api_v3"),
            _join_url_path(urls.get("connector_ingress"), "/management/v3"),
        )
        protocol_url = _first_non_empty(
            urls.get("connector_protocol_api"),
            _join_url_path(urls.get("connector_ingress"), "/protocol"),
        )

        if portal_url:
            env.setdefault(f"UI_{env_prefix}_PORTAL_URL", portal_url)
        if management_url:
            env.setdefault(f"UI_{env_prefix}_MANAGEMENT_URL", management_url)
        if use_public_protocol and protocol_url:
            env.setdefault(f"UI_{env_prefix}_PROTOCOL_URL", protocol_url)


def _configured_playwright_ingress_proxy_port(config: dict[str, Any]) -> str:
    return _first_non_empty(
        os.environ.get("PLAYWRIGHT_INGRESS_PROXY_PORT"),
        os.environ.get("UI_INGRESS_PORT"),
        config.get("PLAYWRIGHT_INGRESS_PROXY_PORT"),
        config.get("UI_INGRESS_PORT"),
        config.get("LOCAL_PLAYWRIGHT_INGRESS_PROXY_PORT"),
        config.get("LOCAL_INGRESS_PROXY_PORT"),
        config.get("LOCAL_INGRESS_PORT"),
        config.get("INGRESS_PROXY_PORT"),
    )


def _configured_playwright_ingress_proxy_host(config: dict[str, Any]) -> str:
    return _first_non_empty(
        os.environ.get("PLAYWRIGHT_INGRESS_PROXY_HOST"),
        config.get("PLAYWRIGHT_INGRESS_PROXY_HOST"),
        config.get("LOCAL_PLAYWRIGHT_INGRESS_PROXY_HOST"),
        config.get("LOCAL_INGRESS_PROXY_HOST"),
        "127.0.0.1",
    )


def _detect_local_ingress_proxy_port(config: dict[str, Any]) -> str:
    enabled = str(
        os.environ.get("PLAYWRIGHT_INGRESS_PROXY_AUTO_DETECT")
        or config.get("PLAYWRIGHT_INGRESS_PROXY_AUTO_DETECT")
        or config.get("LOCAL_INGRESS_PROXY_AUTO_DETECT")
        or "true"
    ).strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return ""

    try:
        completed = subprocess.run(
            ["ps", "-eo", "args"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""

    output = getattr(completed, "stdout", "")
    if not isinstance(output, str):
        return ""

    for line in output.splitlines():
        normalized = line.lower()
        if "kubectl" not in normalized or "port-forward" not in normalized:
            continue
        if "ingress-nginx" not in normalized or "ingress-nginx-controller" not in normalized:
            continue
        match = re.search(r"(?:(?:127\.0\.0\.1|localhost):)?([0-9]{2,5}):80\b", line)
        if match:
            return match.group(1)
    return ""


def _resolve_playwright_ingress_proxy(config: dict[str, Any], topology: str) -> tuple[str, str]:
    explicit_port = _configured_playwright_ingress_proxy_port(config)
    if explicit_port:
        return _configured_playwright_ingress_proxy_host(config), explicit_port
    if topology != LOCAL_TOPOLOGY:
        return "", ""
    detected_port = _detect_local_ingress_proxy_port(config)
    if detected_port:
        return _configured_playwright_ingress_proxy_host(config), detected_port
    return "", ""


def _hostname_from_url_or_raw(value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    parsed = urlsplit(raw_value if "://" in raw_value else f"http://{raw_value}")
    return (parsed.hostname or raw_value.split("/", 1)[0]).strip()


def _infer_local_common_domain(config: dict[str, Any], fallback_domain: str | None = None) -> str:
    explicit_domain = _hostname_from_url_or_raw(
        _first_non_empty(config.get("DOMAIN_BASE"), config.get("COMMON_DOMAIN_BASE"))
    )
    if explicit_domain:
        return explicit_domain

    for key in (
        "MINIO_CONSOLE_HOSTNAME",
        "MINIO_HOSTNAME",
        "KEYCLOAK_HOSTNAME",
        "KEYCLOAK_ADMIN_HOSTNAME",
        "KC_INTERNAL_URL",
        "KC_URL",
        "KEYCLOAK_FRONTEND_URL",
        "KEYCLOAK_PUBLIC_URL",
    ):
        hostname = _hostname_from_url_or_raw(config.get(key))
        if not hostname:
            continue
        for prefix in ("console.minio-s3.", "minio.", "admin.auth.", "keycloak.", "auth.", "org1."):
            if hostname.startswith(prefix):
                return hostname[len(prefix) :]
    return str(fallback_domain or "").strip()


def _local_common_service_url(
    config: dict[str, Any],
    *,
    hostname_key: str,
    default_prefix: str,
    fallback_domain: str | None = None,
) -> str:
    hostname = _hostname_from_url_or_raw(config.get(hostname_key))
    if not hostname:
        domain = _infer_local_common_domain(config, fallback_domain=fallback_domain)
        if not domain:
            return ""
        hostname = f"{default_prefix}.{domain}"
    return _force_url_scheme(hostname, "http")


def _topology_public_urls(config: dict[str, Any], topology: str) -> dict[str, str]:
    if topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
        return {}
    values = {str(key): str(value) for key, value in (config or {}).items()}
    values["TOPOLOGY"] = topology
    return resolve_vm_distributed_public_urls(values)


def _resolve_ui_keycloak_url(config: dict[str, Any], topology: str, fallback_domain: str | None = None) -> str:
    public_urls = _topology_public_urls(config, topology)
    if public_urls:
        public_keycloak_url = _first_non_empty(
            public_urls.get("KEYCLOAK_FRONTEND_URL"),
            public_urls.get("KEYCLOAK_PUBLIC_URL"),
        )
        if public_keycloak_url:
            return public_keycloak_url.rstrip("/")

    if topology == LOCAL_TOPOLOGY:
        explicit_public_url = _first_non_empty(config.get("KEYCLOAK_FRONTEND_URL"), config.get("KEYCLOAK_PUBLIC_URL"))
        if explicit_public_url and not is_vm_public_placeholder_url(explicit_public_url):
            return explicit_public_url.rstrip("/")

        local_keycloak_url = _local_common_service_url(
            config,
            hostname_key="KEYCLOAK_HOSTNAME",
            default_prefix="auth",
            fallback_domain=fallback_domain,
        )
        if local_keycloak_url:
            return local_keycloak_url
        return _first_non_empty(
            config.get("KC_INTERNAL_URL"),
            config.get("KC_URL"),
            os.environ.get("UI_KEYCLOAK_URL"),
        ).rstrip("/")

    return _first_non_empty(
        config.get("KEYCLOAK_FRONTEND_URL"),
        config.get("KEYCLOAK_PUBLIC_URL"),
        config.get("KC_INTERNAL_URL"),
        config.get("KC_URL"),
        os.environ.get("UI_KEYCLOAK_URL"),
    ).rstrip("/")


def _resolve_ui_minio_console_url(config: dict[str, Any], topology: str, fallback_domain: str | None = None) -> str:
    public_urls = _topology_public_urls(config, topology)
    if public_urls.get("MINIO_CONSOLE_PUBLIC_URL"):
        return public_urls["MINIO_CONSOLE_PUBLIC_URL"].rstrip("/")

    if topology == LOCAL_TOPOLOGY:
        return _local_common_service_url(
            config,
            hostname_key="MINIO_CONSOLE_HOSTNAME",
            default_prefix="console.minio-s3",
            fallback_domain=fallback_domain,
        )

    return _first_non_empty(
        config.get("MINIO_CONSOLE_PUBLIC_URL"),
        config.get("MINIO_PUBLIC_URL"),
        os.environ.get("UI_MINIO_CONSOLE_URL"),
    ).rstrip("/")


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
    explicit_public = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL")
        or config.get("MODEL_SERVER_PUBLIC_URL")
        or ""
    ).strip()
    if explicit_public:
        return explicit_public.rstrip("/")

    for base_candidate in (
        config.get("VM_COMMON_PUBLIC_URL"),
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL"),
        config.get("COMPONENTS_PUBLIC_BASE_URL"),
        config.get("VM_COMMON_HTTP_URL"),
    ):
        base_url = str(base_candidate or "").strip().rstrip("/")
        if base_url and "://" not in base_url:
            base_url = _force_url_scheme(base_url, "https")
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


def _split_model_server_validation_endpoints(config: dict[str, Any]) -> list[str]:
    raw_value = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS")
        or os.environ.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS")
        or ""
    ).strip()
    return [entry.strip() for entry in raw_value.replace(";", ",").split(",") if entry.strip()]


def _export_ai_model_hub_model_server_validation_env(env: dict[str, str], config: dict[str, Any]) -> None:
    endpoints = _split_model_server_validation_endpoints(config)
    if endpoints:
        env["UI_AI_MODEL_HUB_MODEL_PATH"] = endpoints[0]
        env["UI_AI_MODEL_HUB_EXTERNAL_MODEL_PATH"] = endpoints[0]
        if len(endpoints) >= 2:
            env["UI_AI_MODEL_HUB_BENCHMARK_MODEL_PATHS"] = ",".join(endpoints[:2])

    payload = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD")
        or os.environ.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD")
        or ""
    ).strip()
    if payload:
        env["UI_AI_MODEL_HUB_MODEL_PAYLOAD"] = payload
        env["UI_AI_MODEL_HUB_EXTERNAL_MODEL_PAYLOAD"] = payload

def _build_playwright_environment(
    *,
    context: DeploymentContext,
    profile: ValidationProfile,
    artifact_paths: dict[str, str],
) -> dict[str, str]:
    env = dict(os.environ)
    config = dict(context.config or {})
    adapter = profile.adapter or context.deployer or "unknown"
    topology = normalize_topology(context.topology or config.get("TOPOLOGY"))
    fallback_domain = _first_non_empty(config.get("DOMAIN_BASE"), context.ds_domain_base)
    keycloak_url = _resolve_ui_keycloak_url(config, topology, fallback_domain=fallback_domain)
    minio_console_url = _resolve_ui_minio_console_url(config, topology, fallback_domain=fallback_domain)
    ingress_proxy_host, ingress_proxy_port = _resolve_playwright_ingress_proxy(config, topology)

    env["UI_ADAPTER"] = adapter
    env["UI_DATASPACE"] = context.dataspace_name
    env["UI_ENVIRONMENT"] = context.environment
    env["UI_DS_DOMAIN"] = context.ds_domain_base
    env["UI_DOMAIN_BASE"] = str(config.get("DOMAIN_BASE") or "").strip()
    env["UI_TOPOLOGY"] = topology
    env["UI_KEYCLOAK_URL"] = keycloak_url
    if topology == VM_DISTRIBUTED_TOPOLOGY:
        env.setdefault("UI_EDC_NEGOTIATION_TIMEOUT_MS", "360000")
    if ingress_proxy_port:
        env["UI_INGRESS_PORT"] = ingress_proxy_port
        env["PLAYWRIGHT_INGRESS_PROXY_PORT"] = ingress_proxy_port
        env["PLAYWRIGHT_INGRESS_PROXY_HOST"] = ingress_proxy_host or "127.0.0.1"
    if minio_console_url:
        env["UI_MINIO_CONSOLE_URL"] = minio_console_url
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
    adapter_name = str(adapter or "").strip().lower()
    if explicit_ui_protocol_address_mode:
        protocol_address_mode = explicit_ui_protocol_address_mode
    elif adapter_name == "edc" and topology == VM_DISTRIBUTED_TOPOLOGY:
        protocol_address_mode = "public"
    elif configured_protocol_address_mode:
        protocol_address_mode = configured_protocol_address_mode
    elif adapter_name == "edc" and topology in {LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY}:
        protocol_address_mode = "internal"
    elif topology in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}:
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
    for key in (
        "AI_MODEL_HUB_MODEL_SERVER_MODE",
        "AI_MODEL_HUB_ENABLE_MODEL_SERVER_USE_CASES",
        "AI_MODEL_HUB_USE_CASE_PUBLICATION_MODE",
    ):
        configured_value = str(config.get(key) or os.environ.get(key) or "").strip()
        if configured_value:
            env.setdefault(key, configured_value)
    if (
        env.get("AI_MODEL_HUB_MODEL_SERVER_MODE") == "use-cases"
        or str(env.get("AI_MODEL_HUB_ENABLE_MODEL_SERVER_USE_CASES") or "").lower() == "true"
        or env.get("AI_MODEL_HUB_USE_CASE_PUBLICATION_MODE") == "split"
    ):
        env.setdefault("UI_AI_MODEL_HUB_USE_CASES_DEMO", "1")
    _export_ai_model_hub_model_server_validation_env(env, config)

    connectors = list(context.connectors or [])
    if connectors:
        env["UI_PROVIDER_CONNECTOR"] = connectors[0]
        env.setdefault("UI_PORTAL_CONNECTOR", connectors[0])
    if len(connectors) > 1:
        env["UI_CONSUMER_CONNECTOR"] = connectors[1]
    if adapter_name == "edc":
        _export_edc_public_connector_runtime_urls(
            env,
            config=config,
            topology=topology,
            connectors=connectors,
            dataspace=context.dataspace_name,
            environment=context.environment,
            protocol_address_mode=protocol_address_mode,
        )

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
        env.setdefault("PIONERA_PLAYWRIGHT_SUITE_NAME", "EDC UI")
        env.setdefault("UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO", "1")
        env.setdefault("UI_ONTOLOGY_HUB_EDC_DEMO", "1")
        env.setdefault("UI_AI_MODEL_HUB_HTTPDATA_DEMO", "1")
        env.setdefault("UI_EDC_MODEL_OBSERVER_DEMO", "1")
    else:
        env.setdefault("PIONERA_PLAYWRIGHT_SUITE_NAME", f"{adapter} Playwright")
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKERS", "1")
    env.setdefault("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "150")
    env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"

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
    specs: list[str] | None = None,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
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
    if extra_env:
        env.update(extra_env)
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
    if specs:
        command.extend(specs)
    if extra_args:
        command.extend(extra_args)

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
        "specs": list(specs or []),
        "artifacts": artifact_paths,
        "summary": _summarize_playwright_json(artifact_paths["json_report_file"]),
        "error": error,
    }

    with open(artifact_paths["summary_file"], "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)

    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=_project_root() / "experiments")
    return result
