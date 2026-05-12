import json
import os
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple
from urllib import error, parse, request


COMPONENT_KEY = "ai-model-hub"
DASHBOARD_PATH = os.environ.get("AI_MODEL_HUB_DASHBOARD_PATH", "")
APP_CONFIG_PATH = os.environ.get("AI_MODEL_HUB_APP_CONFIG_PATH", "config/app-config.json")

SUPPORT_CASE_METADATA: Dict[str, Dict[str, str]] = {
    "MH-BOOTSTRAP-01": {
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "automation_mode": "api_support",
        "execution_mode": "api_support",
        "coverage_status": "automated",
        "expected_result": "The dashboard shell is served successfully",
    },
    "MH-BOOTSTRAP-02": {
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "automation_mode": "api_support",
        "execution_mode": "api_support",
        "coverage_status": "automated",
        "expected_result": "Runtime configuration is available and usable",
    },
}


def _component_dir(experiment_dir: str | None) -> str | None:
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, "components", COMPONENT_KEY)
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _build_url(base_url: str, relative_path: str) -> str:
    normalized_base_url = (base_url or "").rstrip("/")
    if not relative_path or relative_path == "/":
        return normalized_base_url
    return parse.urljoin(f"{normalized_base_url}/", relative_path.lstrip("/"))


def _http_get(url: str, timeout: int = 20) -> Tuple[int, str, str]:
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), response.headers.get("Content-Type", ""), body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.headers.get("Content-Type", ""), body
    except error.URLError as exc:
        return 0, "", str(exc)


def evaluate_html_shell_response(
    http_status: int,
    content_type: str,
    body_text: str,
    *,
    required_markers: Sequence[str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "http_status": http_status,
        "content_type": content_type,
        "body_excerpt": body_text[:500],
        "status": "passed",
        "assertions": [],
    }

    if http_status != 200:
        result["status"] = "failed"
        result["assertions"].append(f"Expected HTTP 200, got HTTP {http_status}")
        return result

    normalized_body = body_text.lower()
    missing = [marker for marker in required_markers if marker.lower() not in normalized_body]
    if missing:
        result["status"] = "failed"
        result["assertions"].append(
            f"Dashboard shell is missing expected markers: {', '.join(missing)}"
        )

    return result


def evaluate_runtime_config_response(
    http_status: int,
    content_type: str,
    body_text: str,
    *,
    required_keys: Sequence[str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "http_status": http_status,
        "content_type": content_type,
        "body_excerpt": body_text[:500],
        "status": "passed",
        "assertions": [],
    }

    if http_status != 200:
        result["status"] = "failed"
        result["assertions"].append(f"Expected HTTP 200, got HTTP {http_status}")
        return result

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as exc:
        result["status"] = "failed"
        result["assertions"].append(f"Response is not valid JSON: {exc}")
        return result

    if not isinstance(payload, dict):
        result["status"] = "failed"
        result["assertions"].append("Runtime configuration payload must be a JSON object")
        return result

    result["payload_keys"] = sorted(payload.keys())
    missing = [key for key in required_keys if key not in payload]
    if missing:
        result["status"] = "failed"
        result["assertions"].append(
            f"Runtime configuration is missing required keys: {', '.join(missing)}"
        )

    menu_items = payload.get("menuItems")
    if "menuItems" in payload and not isinstance(menu_items, list):
        result["status"] = "failed"
        result["assertions"].append("Runtime configuration field 'menuItems' must be a list")

    app_title = payload.get("appTitle")
    if "appTitle" in payload and app_title is not None and not isinstance(app_title, str):
        result["status"] = "failed"
        result["assertions"].append("Runtime configuration field 'appTitle' must be a string")

    health_check_interval_seconds = payload.get("healthCheckIntervalSeconds")
    if (
        "healthCheckIntervalSeconds" in payload
        and health_check_interval_seconds is not None
        and not isinstance(health_check_interval_seconds, int)
    ):
        result["status"] = "failed"
        result["assertions"].append(
            "Runtime configuration field 'healthCheckIntervalSeconds' must be an integer"
        )

    enable_user_config = payload.get("enableUserConfig")
    if "enableUserConfig" in payload and not isinstance(enable_user_config, bool):
        result["status"] = "failed"
        result["assertions"].append(
            "Runtime configuration field 'enableUserConfig' must be a boolean"
        )

    result["app_title"] = app_title
    result["menu_items_count"] = len(menu_items) if isinstance(menu_items, list) else 0
    result["health_check_interval_seconds"] = health_check_interval_seconds
    result["enable_user_config"] = enable_user_config
    return result


def _build_case_result(
    *,
    case_id: str,
    description: str,
    metadata: Dict[str, str],
    status: str,
    request_payload: Dict[str, Any],
    response_payload: Dict[str, Any],
    assertions: List[str],
) -> Dict[str, Any]:
    return {
        "test_case_id": case_id,
        "description": description,
        "type": "api",
        "case_group": metadata["case_group"],
        "validation_type": metadata["validation_type"],
        "dataspace_dimension": metadata["dataspace_dimension"],
        "mapping_status": metadata["mapping_status"],
        "automation_mode": metadata["automation_mode"],
        "execution_mode": metadata["execution_mode"],
        "coverage_status": metadata["coverage_status"],
        "request": request_payload,
        "response": response_payload,
        "evaluation": {
            "status": status,
            "assertions": assertions,
        },
        "expected_result": metadata["expected_result"],
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


def _build_evidence_index(
    executed_cases: List[Dict[str, Any]],
    artifacts: Dict[str, str],
) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = [
        {
            "scope": "suite",
            "suite": "bootstrap",
            "artifact_name": "report_json",
            "path": artifacts["report_json"],
        }
    ]

    for case in executed_cases:
        artifact_key = f"{str(case.get('test_case_id') or '').lower()}-response.json"
        artifact_path = artifacts.get(artifact_key)
        if artifact_path:
            evidence_index.append(
                {
                    "scope": "case",
                    "suite": "bootstrap",
                    "test_case_id": case.get("test_case_id"),
                    "artifact_name": artifact_key,
                    "path": artifact_path,
                }
            )

    return evidence_index


def run_ai_model_hub_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    normalized_base_url = (base_url or "").rstrip("/")

    shell_url = _build_url(normalized_base_url, DASHBOARD_PATH)
    shell_status, shell_content_type, shell_body = _http_get(shell_url)
    shell_evaluation = evaluate_html_shell_response(
        shell_status,
        shell_content_type,
        shell_body,
        required_markers=["<html", "app-root"],
    )
    shell_case = _build_case_result(
        case_id="MH-BOOTSTRAP-01",
        description="Dashboard shell availability",
        metadata=SUPPORT_CASE_METADATA["MH-BOOTSTRAP-01"],
        status=shell_evaluation["status"],
        request_payload={
            "method": "GET",
            "url": shell_url,
        },
        response_payload={
            "http_status": shell_status,
            "content_type": shell_content_type,
            "body_excerpt": shell_body[:500],
        },
        assertions=list(shell_evaluation.get("assertions") or []),
    )

    config_url = _build_url(normalized_base_url, APP_CONFIG_PATH)
    config_status, config_content_type, config_body = _http_get(config_url)
    config_evaluation = evaluate_runtime_config_response(
        config_status,
        config_content_type,
        config_body,
        required_keys=["menuItems"],
    )
    config_case = _build_case_result(
        case_id="MH-BOOTSTRAP-02",
        description="Runtime application configuration availability",
        metadata=SUPPORT_CASE_METADATA["MH-BOOTSTRAP-02"],
        status=config_evaluation["status"],
        request_payload={
            "method": "GET",
            "url": config_url,
        },
        response_payload={
            "http_status": config_status,
            "content_type": config_content_type,
            "body_excerpt": config_body[:500],
            "payload_keys": config_evaluation.get("payload_keys"),
            "app_title": config_evaluation.get("app_title"),
            "menu_items_count": config_evaluation.get("menu_items_count"),
            "health_check_interval_seconds": config_evaluation.get("health_check_interval_seconds"),
            "enable_user_config": config_evaluation.get("enable_user_config"),
        },
        assertions=list(config_evaluation.get("assertions") or []),
    )

    executed_cases = [shell_case, config_case]
    summary = _summarize_cases(executed_cases)
    support_summary = dict(summary)
    pt5_summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }

    suite_status = "passed"
    if summary["failed"]:
        suite_status = "failed"
    elif summary["total"] == 0 or summary["skipped"] == summary["total"]:
        suite_status = "skipped"

    suite_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "bootstrap",
        "base_url": normalized_base_url,
        "timestamp": started_at,
        "status": suite_status,
        "summary": summary,
        "executed_cases": executed_cases,
        "pt5_cases": [],
        "pt5_summary": pt5_summary,
        "support_checks": executed_cases,
        "support_summary": support_summary,
        "evidence_index": [],
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ai_model_hub_validation.json")
        shell_response_path = os.path.join(component_dir, "mh-bootstrap-01-response.json")
        config_response_path = os.path.join(component_dir, "mh-bootstrap-02-response.json")
        artifacts = {
            "report_json": report_path,
            "mh-bootstrap-01-response.json": shell_response_path,
            "mh-bootstrap-02-response.json": config_response_path,
        }
        evidence_index = _build_evidence_index(executed_cases, artifacts)
        suite_result["artifacts"] = artifacts
        suite_result["evidence_index"] = evidence_index

        _write_json(
            shell_response_path,
            {
                "request": shell_case["request"],
                "response": shell_case["response"],
                "evaluation": shell_case["evaluation"],
            },
        )
        _write_json(
            config_response_path,
            {
                "request": config_case["request"],
                "response": config_case["response"],
                "evaluation": config_case["evaluation"],
            },
        )
        _write_json(report_path, suite_result)

    return suite_result
