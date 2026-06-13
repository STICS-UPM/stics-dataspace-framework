import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib import parse

import requests
import yaml

from validation.components.artifact_contract import attach_component_artifact_manifest
from validation.components.console_output import print_component_case_results, print_component_suite_header
from validation.components.ai_model_hub.runner import run_ai_model_hub_validation
from validation.components.ai_model_hub.functional_runner import run_ai_model_hub_functional_validation
from validation.components.ai_model_hub.model_server_use_cases_api import (
    run_ai_model_hub_model_server_use_cases_validation,
)
from validation.components.ai_model_hub.model_server_policy import model_server_validation_state
from validation.components.ai_model_hub.ui_runner import run_ai_model_hub_ui_validation
from validation.components.execution_mode import component_api_only_enabled
from validation.components.fail_fast import component_fail_fast_enabled


COMPONENT_KEY = "ai-model-hub"
CATALOG_PATH = Path(__file__).resolve().parent / "test_cases.yaml"
CONNECTOR_GOVERNANCE_ENV = "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE"
MODEL_EXECUTION_ENV = "AI_MODEL_HUB_ENABLE_MODEL_EXECUTION"
MODEL_BENCHMARKING_ENV = "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING"
MOBILITY_BENCHMARKING_ENV = "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING"
MODEL_OBSERVER_ENV = "AI_MODEL_HUB_ENABLE_MODEL_OBSERVER"
MODEL_OBSERVER_BASE_URL_ENVS = (
    "AI_MODEL_HUB_OBSERVER_API_BASE_URL",
    "AI_MODEL_OBSERVER_API_BASE_URL",
    "AI_MODEL_HUB_PUBLIC_PORTAL_BACKEND_URL",
    "INESDATA_PUBLIC_PORTAL_BACKEND_URL",
)
MODEL_OBSERVER_BEARER_TOKEN_ENVS = (
    "AI_MODEL_HUB_OBSERVER_API_BEARER_TOKEN",
    "AI_MODEL_OBSERVER_API_BEARER_TOKEN",
)
MODEL_OBSERVER_CONNECTOR_ENVS = (
    "AI_MODEL_HUB_MODEL_OBSERVER_CONNECTOR",
    "AI_MODEL_HUB_CONNECTOR_GOVERNANCE_PROVIDER",
    "AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER",
)

STATUS_PRIORITY = {
    "failed": 3,
    "passed": 2,
    "skipped": 1,
}


def _component_dir(experiment_dir: str | None) -> str | None:
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, "components", COMPONENT_KEY)
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    import json

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _case_sort_key(case: Dict[str, Any]) -> tuple[str, int, str]:
    test_case_id = str(case.get("test_case_id") or case.get("id") or "")
    parts = test_case_id.split("-")
    if len(parts) >= 3 and parts[-1].isdigit():
        return ("-".join(parts[:-1]), int(parts[-1]), test_case_id)
    return (test_case_id, 0, test_case_id)


def _load_catalog() -> Dict[str, Any]:
    with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    return {
        "source_file": str(CATALOG_PATH),
        "source_documents": list(payload.get("source_documents") or []),
        "pt5_cases": sorted(list(payload.get("test_cases") or []), key=_case_sort_key),
        "functional_use_cases": sorted(list(payload.get("functional_use_cases") or []), key=_case_sort_key),
        "observer_cases": sorted(list(payload.get("observer_cases") or []), key=_case_sort_key),
        "support_checks": sorted(list(payload.get("support_checks") or []), key=_case_sort_key),
    }


def _summarize_cases(executed_cases: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {
        "total": len(executed_cases),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }
    for case in executed_cases:
        status = ((case.get("evaluation") or {}).get("status") or "").lower()
        if status in summary:
            summary[status] += 1
    return summary


def _combine_status(current: str, candidate: str) -> str:
    current_status = (current or "skipped").lower()
    candidate_status = (candidate or "skipped").lower()
    if STATUS_PRIORITY.get(candidate_status, 0) > STATUS_PRIORITY.get(current_status, 0):
        return candidate_status
    return current_status


def _suite_failed(suite_result: Dict[str, Any]) -> bool:
    summary = suite_result.get("summary") or {}
    return (
        str(suite_result.get("status") or "").strip().lower() == "failed"
        or int(summary.get("failed") or 0) > 0
    )


def _bootstrap_config_shape(bootstrap_result: Dict[str, Any]) -> str:
    for case in list(bootstrap_result.get("executed_cases") or []):
        response = case.get("response") or {}
        config_shape = str(response.get("config_shape") or "").strip().lower()
        if config_shape:
            return config_shape
    return ""


def _uses_inesdata_connector_interface(bootstrap_result: Dict[str, Any]) -> bool:
    return _bootstrap_config_shape(bootstrap_result) == "inesdata-connector-interface"


def _uses_edc_dashboard_adapter() -> bool:
    return _component_adapter_name() == "edc"


def _skipped_playwright_suite_result(
    *,
    suite: str,
    base_url: str,
    reason: str,
    experiment_dir: str | None,
    artifact_subdir: str,
    report_filename: str,
) -> Dict[str, Any]:
    artifacts: Dict[str, Any] = {}
    evidence_index: List[Dict[str, Any]] = []
    if experiment_dir:
        base_dir = os.path.join(experiment_dir, "components", COMPONENT_KEY, artifact_subdir)
        os.makedirs(base_dir, exist_ok=True)
        report_path = os.path.join(base_dir, report_filename)
        artifacts = {
            "report_json": report_path,
            "test_results_dir": os.path.join(base_dir, "test-results"),
            "html_report_dir": os.path.join(base_dir, "playwright-report"),
            "blob_report_dir": os.path.join(base_dir, "blob-report"),
            "json_report_file": os.path.join(base_dir, "results.json"),
        }
        evidence_index = [
            {
                "scope": "suite",
                "suite": suite,
                "artifact_name": "report_json",
                "path": report_path,
            }
        ]

    suite_result = {
        "component": COMPONENT_KEY,
        "suite": suite,
        "status": "skipped",
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "executed_cases": [],
        "evidence_index": evidence_index,
        "artifacts": artifacts,
        "skip_reason": reason,
        "base_url": base_url,
        "execution_channel": "playwright",
    }
    if artifacts.get("report_json"):
        _write_json(artifacts["report_json"], suite_result)
    return suite_result


def _attach_catalog_metadata(
    executed_cases: List[Dict[str, Any]],
    catalog_cases_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    enriched_cases: List[Dict[str, Any]] = []
    for case in executed_cases:
        enriched = dict(case)
        catalog_case = catalog_cases_by_id.get(str(case.get("test_case_id") or ""))
        if catalog_case:
            enriched["traceability"] = list(catalog_case.get("traceability") or [])
            enriched["catalog_case"] = {
                "id": catalog_case.get("id"),
                "type": catalog_case.get("type"),
                "validation_type": catalog_case.get("validation_type"),
                "dataspace_dimension": catalog_case.get("dataspace_dimension"),
                "execution_mode": catalog_case.get("execution_mode"),
                "coverage_status": catalog_case.get("coverage_status"),
                "mapping_status": catalog_case.get("mapping_status"),
            }
        enriched_cases.append(enriched)
    return enriched_cases


def _build_findings(
    pt5_case_results: List[Dict[str, Any]],
    functional_use_case_results: List[Dict[str, Any]],
    observer_case_results: List[Dict[str, Any]],
    support_checks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for case in pt5_case_results + functional_use_case_results + observer_case_results + support_checks:
        status = ((case.get("evaluation") or {}).get("status") or "").lower()
        if status != "failed":
            continue
        findings.append(
            {
                "scope": case.get("case_group") or "support",
                "test_case_id": case.get("test_case_id"),
                "status": status,
                "source_suites": [case.get("source_suite")],
                "assertions": list((case.get("evaluation") or {}).get("assertions") or []),
            }
        )
    return findings


def _build_catalog_alignment(
    catalog: Dict[str, Any],
    pt5_case_results: List[Dict[str, Any]],
    functional_use_case_results: List[Dict[str, Any]],
    observer_case_results: List[Dict[str, Any]],
    support_checks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    declared_pt5_cases = list(catalog.get("pt5_cases") or [])
    declared_functional_use_cases = list(catalog.get("functional_use_cases") or [])
    declared_observer_cases = list(catalog.get("observer_cases") or [])
    declared_support_checks = list(catalog.get("support_checks") or [])
    declared_pt5_by_id = {case.get("id"): case for case in declared_pt5_cases}
    declared_functional_by_id = {case.get("id"): case for case in declared_functional_use_cases}
    declared_observer_by_id = {case.get("id"): case for case in declared_observer_cases}
    declared_support_by_id = {case.get("id"): case for case in declared_support_checks}

    executed_pt5_ids = {str(case.get("test_case_id") or "") for case in pt5_case_results}
    executed_functional_ids = {
        str(case.get("test_case_id") or "")
        for case in functional_use_case_results
    }
    executed_observer_ids = {
        str(case.get("test_case_id") or "")
        for case in observer_case_results
    }
    executed_support_ids = {str(case.get("test_case_id") or "") for case in support_checks}

    uncovered_pt5_cases = [
        case for case in declared_pt5_cases if case.get("id") not in executed_pt5_ids
    ]
    uncovered_functional_use_cases = [
        case
        for case in declared_functional_use_cases
        if case.get("id") not in executed_functional_ids
    ]
    uncovered_observer_cases = [
        case
        for case in declared_observer_cases
        if case.get("id") not in executed_observer_ids
    ]
    missing_support_checks = [
        case for case in declared_support_checks if case.get("id") not in executed_support_ids
    ]
    executed_pt5_not_in_catalog = sorted(
        case_id for case_id in executed_pt5_ids if case_id not in declared_pt5_by_id
    )
    executed_support_not_in_catalog = sorted(
        case_id for case_id in executed_support_ids if case_id not in declared_support_by_id
    )
    executed_functional_not_in_catalog = sorted(
        case_id for case_id in executed_functional_ids if case_id not in declared_functional_by_id
    )
    executed_observer_not_in_catalog = sorted(
        case_id for case_id in executed_observer_ids if case_id not in declared_observer_by_id
    )

    return {
        "source_file": catalog.get("source_file"),
        "source_documents": list(catalog.get("source_documents") or []),
        "summary": {
            "declared_pt5_cases": len(declared_pt5_cases),
            "executed_pt5_cases": len(pt5_case_results),
            "uncovered_pt5_cases": len(uncovered_pt5_cases),
            "declared_functional_use_cases": len(declared_functional_use_cases),
            "executed_functional_use_cases": len(executed_functional_ids),
            "uncovered_functional_use_cases": len(uncovered_functional_use_cases),
            "declared_observer_cases": len(declared_observer_cases),
            "executed_observer_cases": len(executed_observer_ids),
            "uncovered_observer_cases": len(uncovered_observer_cases),
            "declared_support_checks": len(declared_support_checks),
            "executed_support_checks": len(support_checks),
            "missing_support_checks": len(missing_support_checks),
            "executed_pt5_not_in_catalog": len(executed_pt5_not_in_catalog),
            "executed_functional_not_in_catalog": len(executed_functional_not_in_catalog),
            "executed_observer_not_in_catalog": len(executed_observer_not_in_catalog),
            "executed_support_not_in_catalog": len(executed_support_not_in_catalog),
        },
        "declared_pt5_cases": declared_pt5_cases,
        "declared_functional_use_cases": declared_functional_use_cases,
        "declared_observer_cases": declared_observer_cases,
        "declared_support_checks": declared_support_checks,
        "uncovered_pt5_cases": uncovered_pt5_cases,
        "uncovered_functional_use_cases": uncovered_functional_use_cases,
        "uncovered_observer_cases": uncovered_observer_cases,
        "missing_support_checks": missing_support_checks,
        "executed_pt5_not_in_catalog": executed_pt5_not_in_catalog,
        "executed_functional_not_in_catalog": executed_functional_not_in_catalog,
        "executed_observer_not_in_catalog": executed_observer_not_in_catalog,
        "executed_support_not_in_catalog": executed_support_not_in_catalog,
    }


def _collect_suite_evidence(suite_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = []
    for evidence in list(suite_result.get("evidence_index") or []):
        normalized = dict(evidence)
        normalized.setdefault("suite", suite_result.get("suite") or "bootstrap")
        evidence_index.append(normalized)
    return evidence_index


def _phase_summary(named_suite_results: List[tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    suite_results = [suite_result for _, suite_result in named_suite_results]
    combined_status = "skipped"
    for suite_result in suite_results:
        combined_status = _combine_status(combined_status, suite_result.get("status", "skipped"))
    return {
        "status": combined_status,
        "summary": {
            "total": sum(int(suite.get("summary", {}).get("total", 0)) for suite in suite_results),
            "passed": sum(int(suite.get("summary", {}).get("passed", 0)) for suite in suite_results),
            "failed": sum(int(suite.get("summary", {}).get("failed", 0)) for suite in suite_results),
            "skipped": sum(int(suite.get("summary", {}).get("skipped", 0)) for suite in suite_results),
        },
        "suites": {name: suite_result for name, suite_result in named_suite_results},
    }


def _suite_enabled(env_name: str, *, default: bool = True) -> bool:
    raw_value = os.environ.get(env_name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _skipped_model_execution_result(
    *,
    provider: str,
    model_path: str,
    reason: str,
    model_server_state: Dict[str, Any],
    experiment_dir: str | None = None,
) -> Dict[str, Any]:
    artifacts: Dict[str, str] = {}
    evidence_index: List[Dict[str, Any]] = []
    executed_cases = [
        {
            "test_case_id": "PT5-MH-10",
            "description": "Execute inference through the connector-side model execution API with a controlled baseline",
            "type": "api",
            "case_group": "pt5",
            "validation_type": "integration",
            "dataspace_dimension": "execution",
            "mapping_status": "mapped",
            "automation_mode": "api",
            "execution_mode": "skipped_model_server_not_deployed",
            "coverage_status": "skipped_model_server_not_deployed",
            "model_server_mode": model_server_state.get("mode") or "disabled",
            "request": {"provider": provider, "model_path": model_path},
            "response": {},
            "evaluation": {
                "status": "skipped",
                "assertions": [reason],
            },
            "expected_result": (
                "The model execution API resolves the controlled HttpData asset and returns "
                "a deterministic model response"
            ),
            "traceability": ["MH-34", "MH-35"],
        }
    ]
    if experiment_dir:
        component_dir = os.path.join(experiment_dir, "components", COMPONENT_KEY, "integration")
        os.makedirs(component_dir, exist_ok=True)
        report_path = os.path.join(component_dir, "ai_model_hub_model_execution_api.json")
        artifacts["report_json"] = report_path
        evidence_index.append(
            {
                "scope": "suite",
                "suite": "model-execution-api",
                "artifact_name": "report_json",
                "path": report_path,
            }
        )

    result = {
        "component": COMPONENT_KEY,
        "suite": "model-execution-api",
        "status": "skipped",
        "summary": {
            "total": 1,
            "passed": 0,
            "failed": 0,
            "skipped": 1,
            "steps": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        },
        "provider": provider,
        "model_path": model_path,
        "model_server": dict(model_server_state),
        "skip_reason": reason,
        "executed_cases": executed_cases,
        "evidence_index": evidence_index,
        "artifacts": artifacts,
    }
    if artifacts.get("report_json"):
        _write_json(artifacts["report_json"], result)
    return result


def _connector_governance_enabled() -> bool:
    return _suite_enabled(CONNECTOR_GOVERNANCE_ENV)


def _model_execution_enabled() -> bool:
    return _suite_enabled(MODEL_EXECUTION_ENV)


def _model_benchmarking_enabled() -> bool:
    return _suite_enabled(MODEL_BENCHMARKING_ENV)


def _mobility_benchmarking_enabled() -> bool:
    return _suite_enabled(MOBILITY_BENCHMARKING_ENV)


def _model_observer_enabled() -> bool:
    return _suite_enabled(MODEL_OBSERVER_ENV)


def _component_adapter_name() -> str:
    return (
        os.environ.get("AI_MODEL_HUB_COMPONENT_ADAPTER")
        or os.environ.get("PIONERA_ADAPTER")
        or "inesdata"
    ).strip().lower() or "inesdata"


def _split_model_server_validation_endpoints() -> List[str]:
    raw_value = str(os.environ.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS") or "").strip()
    return [entry.strip() for entry in raw_value.replace(";", ",").split(",") if entry.strip()]


def _parse_json_env(*names: str) -> Any | None:
    for name in names:
        raw_value = str(os.environ.get(name) or "").strip()
        if raw_value:
            return json.loads(raw_value)
    return None


def _model_observer_topology() -> str:
    return (
        os.environ.get("AI_MODEL_HUB_MODEL_OBSERVER_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or "local"
    )


def _explicit_model_observer_base_url_configured() -> bool:
    return any(str(os.environ.get(env_name) or "").strip() for env_name in MODEL_OBSERVER_BASE_URL_ENVS)


def _protocol_from_config(config: Dict[str, Any]) -> str:
    environment = str(config.get("ENVIRONMENT") or config.get("DEPLOYMENT_ENVIRONMENT") or "").strip().upper()
    return "https" if environment == "PRO" else "http"


def _url_origin(url: str) -> str:
    parsed = parse.urlsplit(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _public_urls_from_credentials(credentials: Dict[str, Any] | None) -> Dict[str, str]:
    if not isinstance(credentials, dict):
        return {}
    public_urls = credentials.get("public_access_urls")
    if isinstance(public_urls, dict) and public_urls:
        return {str(key): str(value) for key, value in public_urls.items()}
    access_urls = credentials.get("access_urls")
    if isinstance(access_urls, dict):
        return {str(key): str(value) for key, value in access_urls.items()}
    return {}


def _preferred_model_observer_connector(adapter: Any) -> str:
    for env_name in MODEL_OBSERVER_CONNECTOR_ENVS:
        candidate = str(os.environ.get(env_name) or "").strip()
        if candidate:
            return candidate
    connectors = list(adapter.get_cluster_connectors() or [])
    return str(connectors[0] or "").strip() if connectors else ""


def _derive_edc_model_observer_base_url(adapter: Any, config: Dict[str, Any], ds_domain: str) -> str:
    connector = _preferred_model_observer_connector(adapter)
    if not connector:
        return ""

    credentials = None
    loader = getattr(adapter, "load_connector_credentials", None)
    if callable(loader):
        credentials = loader(connector)
    public_urls = _public_urls_from_credentials(credentials)

    connector_default_api = str(public_urls.get("connector_default_api") or "").strip().rstrip("/")
    if connector_default_api:
        return connector_default_api

    connector_ingress = str(public_urls.get("connector_ingress") or "").strip().rstrip("/")
    if connector_ingress:
        return f"{connector_ingress}/api"

    dashboard_login = str(public_urls.get("edc_dashboard_login") or "").strip().rstrip("/")
    dashboard_origin = _url_origin(dashboard_login)
    if dashboard_origin:
        return f"{dashboard_origin}/edc-dashboard-api/connectors/{parse.quote(connector, safe='')}/api"

    if ds_domain:
        return f"{_protocol_from_config(config)}://{connector}.{ds_domain}/api"
    return ""


def _keycloak_realm_url_from_config(config: Dict[str, Any], public_urls: Dict[str, str], dataspace: str) -> str:
    realm_url = str(public_urls.get("keycloak_realm") or "").strip().rstrip("/")
    if realm_url:
        return realm_url
    keycloak_base = str(
        config.get("KEYCLOAK_PUBLIC_URL")
        or config.get("KEYCLOAK_FRONTEND_URL")
        or config.get("KC_URL")
        or ""
    ).strip().rstrip("/")
    if not keycloak_base:
        return ""
    if f"/realms/{dataspace}" in keycloak_base:
        return keycloak_base
    return f"{keycloak_base}/realms/{dataspace}"


def _explicit_model_observer_auth_headers() -> Dict[str, str]:
    for env_name in MODEL_OBSERVER_BEARER_TOKEN_ENVS:
        token = str(os.environ.get(env_name) or "").strip()
        if token:
            return {"Authorization": f"Bearer {token}"}
    return {}


def _derive_edc_model_observer_auth_headers_from_adapter() -> Dict[str, str]:
    explicit = _explicit_model_observer_auth_headers()
    if explicit:
        return explicit
    if _component_adapter_name() != "edc":
        return {}

    try:
        from validation.components.ai_model_hub.connector_governance_api import (
            _build_adapter,
            _dataspace_name_loader,
        )

        adapter = _build_adapter(_component_adapter_name(), _model_observer_topology())
        config = dict(adapter.load_deployer_config() or {})
        dataspace = str(
            _dataspace_name_loader(adapter)()
            or config.get("DS_1_NAME")
            or config.get("DS_NAME")
            or "demo"
        ).strip()
        connector = _preferred_model_observer_connector(adapter)
        if not connector:
            return {}
        credentials = adapter.load_connector_credentials(connector) or {}
        connector_user = credentials.get("connector_user") or {}
        username = str(connector_user.get("user") or "").strip()
        password = str(connector_user.get("passwd") or "").strip()
        public_urls = _public_urls_from_credentials(credentials)
        realm_url = _keycloak_realm_url_from_config(config, public_urls, dataspace)
        if not username or not password or not realm_url:
            return {}

        response = requests.post(
            f"{realm_url}/protocol/openid-connect/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "password",
                "client_id": "dataspace-users",
                "username": username,
                "password": password,
                "scope": "openid profile email",
            },
            timeout=20,
        )
        if response.status_code != 200:
            return {}
        token = response.json().get("access_token")
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}
    except Exception:
        return {}


def _derive_model_observer_base_url_from_adapter() -> str:
    try:
        from validation.components.ai_model_hub.connector_governance_api import (
            _build_adapter,
            _dataspace_name_loader,
        )

        adapter = _build_adapter(_component_adapter_name(), _model_observer_topology())
        config = dict(adapter.load_deployer_config() or {})
        explicit_candidates = (
            config.get("AI_MODEL_HUB_OBSERVER_API_BASE_URL"),
            config.get("AI_MODEL_OBSERVER_API_BASE_URL"),
            config.get("AI_MODEL_HUB_PUBLIC_PORTAL_BACKEND_URL"),
            config.get("INESDATA_PUBLIC_PORTAL_BACKEND_URL"),
            config.get("PUBLIC_PORTAL_BACKEND_URL"),
        )
        for candidate in explicit_candidates:
            normalized = str(candidate or "").strip().rstrip("/")
            if normalized:
                return normalized

        adapter_name = _component_adapter_name()
        dataspace = str(
            _dataspace_name_loader(adapter)()
            or config.get("DS_1_NAME")
            or config.get("DS_NAME")
            or "demo"
        ).strip()
        ds_domain = str(config.get("DS_DOMAIN_BASE") or adapter.config.ds_domain_base() or "").strip()
        if adapter_name == "edc":
            return _derive_edc_model_observer_base_url(adapter, config, ds_domain)
        if dataspace and ds_domain:
            return f"{_protocol_from_config(config)}://backend-{dataspace}.{ds_domain}"
    except Exception:
        return ""
    return ""


def _resolve_model_observer_base_url(fallback_base_url: str | None = None) -> str:
    from validation.components.ai_model_hub.model_observer_api import resolve_model_observer_api_base_url

    adapter_name = _component_adapter_name()
    if _explicit_model_observer_base_url_configured():
        return resolve_model_observer_api_base_url(adapter_name=adapter_name)

    derived_base_url = _derive_model_observer_base_url_from_adapter()
    if derived_base_url:
        return resolve_model_observer_api_base_url(derived_base_url, adapter_name=adapter_name)
    return resolve_model_observer_api_base_url(fallback_base_url, adapter_name=adapter_name)


def run_ai_model_hub_connector_governance_validation(experiment_dir: str | None = None) -> Dict[str, Any]:
    from validation.components.ai_model_hub.connector_governance_api import (
        build_ai_model_hub_connector_governance_suite,
        default_model_url,
    )

    topology = (
        os.environ.get("AI_MODEL_HUB_CONNECTOR_GOVERNANCE_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or "local"
    )
    suite, adapter = build_ai_model_hub_connector_governance_suite(
        adapter_name=_component_adapter_name(),
        topology=topology,
    )
    connectors = list(adapter.get_cluster_connectors() or [])
    provider = os.environ.get("AI_MODEL_HUB_CONNECTOR_GOVERNANCE_PROVIDER") or (connectors[0] if connectors else "")
    consumer = os.environ.get("AI_MODEL_HUB_CONNECTOR_GOVERNANCE_CONSUMER") or (
        connectors[1] if len(connectors) > 1 else ""
    )
    if not provider or not consumer:
        return {
            "component": COMPONENT_KEY,
            "suite": "connector-governance-api",
            "status": "skipped",
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "executed_cases": [],
            "evidence_index": [],
            "artifacts": {},
            "skip_reason": "Provider and consumer connectors are not discoverable",
        }
    model_path = os.environ.get("AI_MODEL_HUB_CONNECTOR_GOVERNANCE_MODEL_PATH") or None
    model_url = os.environ.get("AI_MODEL_HUB_CONNECTOR_GOVERNANCE_MODEL_URL") or default_model_url(
        adapter,
        model_path or None,
    )
    run_access_transfer = (os.environ.get("AI_MODEL_HUB_CONNECTOR_GOVERNANCE_SKIP_ACCESS_TRANSFER") or "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }
    return suite.run(
        provider=provider,
        consumer=consumer,
        model_url=model_url,
        model_path=model_path or "/api/v1/nlp/ecommerce-sentiment",
        run_access_transfer=run_access_transfer,
        experiment_dir=experiment_dir,
    )


def run_ai_model_hub_model_execution_validation(experiment_dir: str | None = None) -> Dict[str, Any]:
    from validation.components.ai_model_hub.model_execution_api import (
        DEFAULT_EXPECTED_MODEL,
        build_flares_execution_context,
        build_ai_model_hub_model_execution_suite,
        default_model_url,
    )

    topology = (
        os.environ.get("AI_MODEL_HUB_MODEL_EXECUTION_TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("INESDATA_TOPOLOGY")
        or "local"
    )
    suite, adapter = build_ai_model_hub_model_execution_suite(
        adapter_name=_component_adapter_name(),
        topology=topology,
    )
    connectors = list(adapter.get_cluster_connectors() or [])
    provider = os.environ.get("AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER") or (connectors[0] if connectors else "")
    if not provider:
        return {
            "component": COMPONENT_KEY,
            "suite": "model-execution-api",
            "status": "skipped",
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "executed_cases": [],
            "evidence_index": [],
            "artifacts": {},
            "skip_reason": "Provider connector is not discoverable",
        }

    validation_endpoints = _split_model_server_validation_endpoints()
    model_path = (
        os.environ.get("AI_MODEL_HUB_MODEL_EXECUTION_MODEL_PATH")
        or (validation_endpoints[0] if validation_endpoints else None)
    )
    config_loader = getattr(adapter, "load_deployer_config", None)
    deployer_config = config_loader() if callable(config_loader) else {}
    if not isinstance(deployer_config, dict):
        deployer_config = {}
    explicit_model_url = str(os.environ.get("AI_MODEL_HUB_MODEL_EXECUTION_MODEL_URL") or "").strip()
    policy_config = dict(deployer_config)
    if explicit_model_url:
        policy_config["AI_MODEL_HUB_MODEL_EXECUTION_MODEL_URL"] = explicit_model_url
    model_server_state = model_server_validation_state(policy_config, topology=topology)
    if not model_server_state.get("enabled"):
        return _skipped_model_execution_result(
            provider=provider,
            model_path=model_path or "/api/v1/nlp/ecommerce-sentiment",
            reason=str(model_server_state.get("skip_reason") or "AI Model Hub model-server is not deployed"),
            model_server_state=model_server_state,
            experiment_dir=experiment_dir,
        )

    model_url = explicit_model_url or (
        default_model_url(adapter, model_path) if model_path else default_model_url(adapter)
    )
    payload = _parse_json_env(
        "AI_MODEL_HUB_MODEL_EXECUTION_PAYLOAD",
        "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD",
    )
    functional_context = None
    if payload is None and str(model_path or "").startswith("/flares/"):
        functional_context = build_flares_execution_context()
        payload = functional_context["payload"]

    expected_model = os.environ.get("AI_MODEL_HUB_MODEL_EXECUTION_EXPECTED_MODEL")
    if expected_model is None:
        expected_model = "" if str(model_path or "").startswith("/flares/") else DEFAULT_EXPECTED_MODEL

    return suite.run(
        provider=provider,
        model_url=model_url,
        payload=payload,
        expected_model=expected_model or None,
        functional_context=functional_context,
        experiment_dir=experiment_dir,
        model_server_mode=str(model_server_state.get("mode") or ""),
    )


def run_ai_model_hub_model_benchmarking_validation(experiment_dir: str | None = None) -> Dict[str, Any]:
    from validation.components.ai_model_hub.model_benchmarking_api import (
        run_ai_model_hub_model_benchmarking_validation as run_benchmarking_suite,
    )

    source_dir = os.environ.get("AI_MODEL_HUB_BENCHMARKING_SOURCE_DIR") or None
    model_server_state = model_server_validation_state()
    return run_benchmarking_suite(
        source_dir=source_dir,
        experiment_dir=experiment_dir,
        model_server_mode=str(model_server_state.get("mode") or ""),
    )


def run_ai_model_hub_mobility_benchmarking_validation(experiment_dir: str | None = None) -> Dict[str, Any]:
    from validation.components.ai_model_hub.mobility_benchmarking_api import (
        run_ai_model_hub_mobility_benchmarking_validation as run_mobility_suite,
    )

    source_dir = os.environ.get("AI_MODEL_HUB_MOBILITY_SOURCE_DIR") or None
    return run_mobility_suite(
        source_dir=source_dir,
        experiment_dir=experiment_dir,
    )


def run_ai_model_hub_model_observer_validation(
    base_url: str | None = None,
    experiment_dir: str | None = None,
) -> Dict[str, Any]:
    from validation.components.ai_model_hub.model_observer_api import (
        run_ai_model_hub_model_observer_validation as run_observer_suite,
    )

    return run_observer_suite(
        base_url=base_url,
        experiment_dir=experiment_dir,
        adapter_name=_component_adapter_name(),
        auth_headers=_derive_edc_model_observer_auth_headers_from_adapter(),
    )


def run_ai_model_hub_component_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    normalized_base_url = (base_url or "").rstrip("/")
    api_only = component_api_only_enabled()

    current_suite_header: tuple[str, str] | None = None

    def print_suite_header(title: str, channel: str) -> None:
        nonlocal current_suite_header
        header_key = (channel, title)
        if current_suite_header == header_key:
            return
        print_component_suite_header(title, channel)
        current_suite_header = header_key

    print_suite_header("AI Model Hub preflight", "api")
    bootstrap_result = run_ai_model_hub_validation(normalized_base_url, experiment_dir=experiment_dir)
    bootstrap_result.setdefault("execution_channel", "api")
    print_component_case_results(bootstrap_result.get("executed_cases") or [])

    preflight_suite_results = [
        ("bootstrap", bootstrap_result),
    ]
    ui_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "ui",
        "status": "skipped",
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "executed_cases": [],
        "evidence_index": [],
        "artifacts": {},
        "skip_reason": "component validation is running in API-only mode",
        "execution_channel": "playwright",
    }
    functional_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "linguistic_functional",
        "status": "skipped",
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "executed_cases": [],
        "evidence_index": [],
        "artifacts": {},
        "skip_reason": "component validation is running in API-only mode",
        "execution_channel": "playwright",
    }
    functional_suite_results: List[tuple[str, Dict[str, Any]]] = []
    if not api_only:
        print_suite_header("AI Model Hub functional", "playwright")
        if _uses_edc_dashboard_adapter():
            skip_reason = (
                "Legacy AI Model Hub dashboard Playwright specs are not applicable to the "
                "EDC dashboard layout exposed by this deployment. AI Model Hub UI evidence "
                "for EDC is collected by the EDC integration Playwright suite."
            )
            print(f"AI Model Hub Playwright suites skipped: {skip_reason}")
            ui_result = _skipped_playwright_suite_result(
                suite="ui",
                base_url=normalized_base_url,
                reason=skip_reason,
                experiment_dir=experiment_dir,
                artifact_subdir="ui",
                report_filename="ai_model_hub_ui_validation.json",
            )
            functional_result = _skipped_playwright_suite_result(
                suite="linguistic-functional",
                base_url=normalized_base_url,
                reason=skip_reason,
                experiment_dir=experiment_dir,
                artifact_subdir="functional",
                report_filename="ai_model_hub_functional_validation.json",
            )
        elif _uses_inesdata_connector_interface(bootstrap_result):
            skip_reason = (
                "Legacy AI Model Hub dashboard Playwright specs are not applicable to the "
                "INESData connector interface layout exposed by this deployment."
            )
            print(f"AI Model Hub Playwright suites skipped: {skip_reason}")
            ui_result = _skipped_playwright_suite_result(
                suite="ui",
                base_url=normalized_base_url,
                reason=skip_reason,
                experiment_dir=experiment_dir,
                artifact_subdir="ui",
                report_filename="ai_model_hub_ui_validation.json",
            )
            functional_result = _skipped_playwright_suite_result(
                suite="linguistic-functional",
                base_url=normalized_base_url,
                reason=skip_reason,
                experiment_dir=experiment_dir,
                artifact_subdir="functional",
                report_filename="ai_model_hub_functional_validation.json",
            )
        else:
            ui_result = run_ai_model_hub_ui_validation(normalized_base_url, experiment_dir=experiment_dir)
            ui_result.setdefault("execution_channel", "playwright")
            functional_result = run_ai_model_hub_functional_validation(normalized_base_url, experiment_dir=experiment_dir)
            functional_result.setdefault("execution_channel", "playwright")
        functional_suite_results.extend(
            [
                ("ui", ui_result),
                ("linguistic_functional", functional_result),
            ]
        )
    integration_suite_results: List[tuple[str, Dict[str, Any]]] = []
    playwright_failed = any(_suite_failed(suite_result) for _, suite_result in functional_suite_results)
    if not api_only and playwright_failed and component_fail_fast_enabled():
        print("AI Model Hub integration suites skipped after Playwright failure because Level 6 fail-fast is enabled.")
    else:
        print_suite_header("AI Model Hub functional", "api")
        model_server_use_cases_result = run_ai_model_hub_model_server_use_cases_validation(
            experiment_dir=experiment_dir,
        )
        model_server_use_cases_result.setdefault("execution_channel", "api")
        print_component_case_results(model_server_use_cases_result.get("executed_cases") or [])
        functional_suite_results.append(
            (
                "model_server_use_cases",
                model_server_use_cases_result,
            )
        )
        if _model_benchmarking_enabled():
            print_suite_header("AI Model Hub functional", "api")
            model_benchmarking_result = run_ai_model_hub_model_benchmarking_validation(experiment_dir=experiment_dir)
            model_benchmarking_result.setdefault("execution_channel", "api")
            print_component_case_results(model_benchmarking_result.get("executed_cases") or [])
            functional_suite_results.append(
                (
                    "model_benchmarking",
                    model_benchmarking_result,
                )
            )
        if _mobility_benchmarking_enabled():
            print_suite_header("AI Model Hub functional", "api")
            mobility_benchmarking_result = run_ai_model_hub_mobility_benchmarking_validation(experiment_dir=experiment_dir)
            mobility_benchmarking_result.setdefault("execution_channel", "api")
            print_component_case_results(mobility_benchmarking_result.get("executed_cases") or [])
            functional_suite_results.append(
                (
                    "mobility_benchmarking",
                    mobility_benchmarking_result,
                )
            )
        if _connector_governance_enabled():
            print_suite_header("AI Model Hub integration", "api")
            connector_governance_result = run_ai_model_hub_connector_governance_validation(experiment_dir=experiment_dir)
            connector_governance_result.setdefault("execution_channel", "api")
            print_component_case_results(connector_governance_result.get("executed_cases") or [])
            integration_suite_results.append(
                (
                    "connector_governance",
                    connector_governance_result,
                )
            )
        if _model_execution_enabled():
            print_suite_header("AI Model Hub integration", "api")
            model_execution_result = run_ai_model_hub_model_execution_validation(experiment_dir=experiment_dir)
            model_execution_result.setdefault("execution_channel", "api")
            print_component_case_results(model_execution_result.get("executed_cases") or [])
            integration_suite_results.append(
                (
                    "model_execution",
                    model_execution_result,
                )
            )
        if _model_observer_enabled():
            print_suite_header("AI Model Hub integration", "api")
            model_observer_result = run_ai_model_hub_model_observer_validation(
                base_url=_resolve_model_observer_base_url(normalized_base_url),
                experiment_dir=experiment_dir,
            )
            model_observer_result.setdefault("execution_channel", "api")
            print_component_case_results(model_observer_result.get("executed_cases") or [])
            integration_suite_results.append(
                (
                    "model_observer",
                    model_observer_result,
                )
            )
    named_suite_results = preflight_suite_results + functional_suite_results + integration_suite_results
    suite_results = [suite_result for _, suite_result in named_suite_results]
    catalog = _load_catalog()
    catalog_cases_by_id = {
        case.get("id"): case
        for case in list(catalog.get("pt5_cases") or [])
        + list(catalog.get("functional_use_cases") or [])
        + list(catalog.get("observer_cases") or [])
        + list(catalog.get("support_checks") or [])
    }

    executed_cases = _attach_catalog_metadata(
        [
            {
                **case,
                "source_suite": suite_result.get("suite") or "unknown",
            }
            for suite_result in suite_results
            for case in list(suite_result.get("executed_cases") or [])
        ],
        catalog_cases_by_id,
    )
    pt5_case_results = sorted(
        [case for case in executed_cases if case.get("case_group") == "pt5"],
        key=_case_sort_key,
    )
    support_checks = sorted(
        [case for case in executed_cases if case.get("case_group") == "support"],
        key=_case_sort_key,
    )
    functional_use_case_results = sorted(
        [case for case in executed_cases if case.get("case_group") == "functional_use_case"],
        key=_case_sort_key,
    )
    observer_case_results = sorted(
        [case for case in executed_cases if case.get("case_group") == "observer"],
        key=_case_sort_key,
    )
    pt5_summary = _summarize_cases(pt5_case_results)
    functional_use_case_summary = _summarize_cases(functional_use_case_results)
    observer_case_summary = _summarize_cases(observer_case_results)
    support_summary = _summarize_cases(support_checks)
    findings = _build_findings(
        pt5_case_results,
        functional_use_case_results,
        observer_case_results,
        support_checks,
    )
    catalog_alignment = _build_catalog_alignment(
        catalog,
        pt5_case_results,
        functional_use_case_results,
        observer_case_results,
        support_checks,
    )
    evidence_index = [
        evidence
        for suite_result in suite_results
        for evidence in _collect_suite_evidence(suite_result)
    ]

    summary = {
        "total": sum(int(suite.get("summary", {}).get("total", 0)) for suite in suite_results),
        "passed": sum(int(suite.get("summary", {}).get("passed", 0)) for suite in suite_results),
        "failed": sum(int(suite.get("summary", {}).get("failed", 0)) for suite in suite_results),
        "skipped": sum(int(suite.get("summary", {}).get("skipped", 0)) for suite in suite_results),
    }

    suites = {name: suite_result for name, suite_result in named_suite_results}
    phases = {
        "preflight": _phase_summary(preflight_suite_results),
        "functional": _phase_summary(functional_suite_results),
        "integration": _phase_summary(integration_suite_results),
    }
    suite_execution_channels = {
        name: str(suite_result.get("execution_channel") or "unknown")
        for name, suite_result in named_suite_results
    }
    phase_execution_channels = {
        "preflight": sorted({suite_execution_channels.get(name, "unknown") for name, _ in preflight_suite_results}),
        "functional": sorted({suite_execution_channels.get(name, "unknown") for name, _ in functional_suite_results}),
        "integration": sorted({suite_execution_channels.get(name, "unknown") for name, _ in integration_suite_results}),
    }

    combined_status = "skipped"
    for suite_result in suite_results:
        combined_status = _combine_status(combined_status, suite_result.get("status", "skipped"))

    component_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "base_url": normalized_base_url,
        "timestamp": started_at,
        "status": combined_status,
        "summary": summary,
        "validation_mode": "api" if api_only else "mixed",
        "phase_order": ["preflight", "functional", "integration"],
        "phase_execution_channels": phase_execution_channels,
        "suite_execution_channels": suite_execution_channels,
        "phases": phases,
        "suites": suites,
        "executed_cases": executed_cases,
        "pt5_case_results": pt5_case_results,
        "pt5_cases": pt5_case_results,
        "pt5_summary": pt5_summary,
        "functional_use_case_results": functional_use_case_results,
        "functional_use_cases": functional_use_case_results,
        "functional_use_case_summary": functional_use_case_summary,
        "observer_case_results": observer_case_results,
        "observer_cases": observer_case_results,
        "observer_case_summary": observer_case_summary,
        "support_checks": support_checks,
        "support_summary": support_summary,
        "evidence_index": evidence_index,
        "findings": findings,
        "catalog_alignment": catalog_alignment,
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ai_model_hub_component_validation.json")
        pt5_cases_path = os.path.join(component_dir, "ai_model_hub_pt5_case_results.json")
        functional_use_case_results_path = os.path.join(
            component_dir,
            "ai_model_hub_functional_use_case_results.json",
        )
        observer_case_results_path = os.path.join(
            component_dir,
            "ai_model_hub_observer_case_results.json",
        )
        support_checks_path = os.path.join(component_dir, "ai_model_hub_support_checks.json")
        evidence_index_path = os.path.join(component_dir, "ai_model_hub_evidence_index.json")
        findings_path = os.path.join(component_dir, "ai_model_hub_findings.json")
        catalog_alignment_path = os.path.join(component_dir, "ai_model_hub_catalog_alignment.json")

        _write_json(pt5_cases_path, {"pt5_case_results": pt5_case_results, "summary": pt5_summary})
        _write_json(
            functional_use_case_results_path,
            {
                "functional_use_case_results": functional_use_case_results,
                "summary": functional_use_case_summary,
            },
        )
        _write_json(
            observer_case_results_path,
            {
                "observer_case_results": observer_case_results,
                "summary": observer_case_summary,
            },
        )
        _write_json(support_checks_path, {"support_checks": support_checks, "summary": support_summary})
        _write_json(findings_path, {"findings": findings})
        _write_json(catalog_alignment_path, catalog_alignment)

        component_result["artifacts"] = {
            "report_json": report_path,
            "bootstrap_report_json": (bootstrap_result.get("artifacts") or {}).get("report_json"),
            "ui_report_json": (ui_result.get("artifacts") or {}).get("report_json"),
            "ui_test_results_dir": (ui_result.get("artifacts") or {}).get("test_results_dir"),
            "ui_html_report_dir": (ui_result.get("artifacts") or {}).get("html_report_dir"),
            "ui_blob_report_dir": (ui_result.get("artifacts") or {}).get("blob_report_dir"),
            "ui_json_report_file": (ui_result.get("artifacts") or {}).get("json_report_file"),
            "functional_report_json": (functional_result.get("artifacts") or {}).get("report_json"),
            "functional_test_results_dir": (functional_result.get("artifacts") or {}).get("test_results_dir"),
            "functional_html_report_dir": (functional_result.get("artifacts") or {}).get("html_report_dir"),
            "functional_blob_report_dir": (functional_result.get("artifacts") or {}).get("blob_report_dir"),
            "functional_json_report_file": (functional_result.get("artifacts") or {}).get("json_report_file"),
            "pt5_case_results_json": pt5_cases_path,
            "functional_use_case_results_json": functional_use_case_results_path,
            "observer_case_results_json": observer_case_results_path,
            "support_checks_json": support_checks_path,
            "evidence_index_json": evidence_index_path,
            "findings_json": findings_path,
            "catalog_alignment_json": catalog_alignment_path,
        }
        component_result["evidence_index"] = evidence_index + [
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "report_json",
                "path": report_path,
            },
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "pt5_case_results_json",
                "path": pt5_cases_path,
            },
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "functional_use_case_results_json",
                "path": functional_use_case_results_path,
            },
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "observer_case_results_json",
                "path": observer_case_results_path,
            },
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "support_checks_json",
                "path": support_checks_path,
            },
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "evidence_index_json",
                "path": evidence_index_path,
            },
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "findings_json",
                "path": findings_path,
            },
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "catalog_alignment_json",
                "path": catalog_alignment_path,
            },
        ]
        attach_component_artifact_manifest(component_result, component_dir)
        _write_json(evidence_index_path, {"evidence_index": component_result["evidence_index"]})
        _write_json(report_path, component_result)

    return component_result
