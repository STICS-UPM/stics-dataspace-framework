import json
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib import error, parse, request

from deployers.shared.lib import ai_model_hub_model_server as model_server_config


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "model-server-use-cases-api"
CASE_ID_DISCOVERY = "MH-MODEL-SERVER-01"
CASE_ID_OPTIONAL_EXECUTION = "MH-MODEL-SERVER-02"


def _parse_bool(value, *, default=False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _component_dir(experiment_dir: str | None) -> str | None:
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, "components", COMPONENT_KEY)
    os.makedirs(path, exist_ok=True)
    return path


def _build_url(base_url: str, relative_path: str) -> str:
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    if not relative_path or relative_path == "/":
        return normalized_base_url
    return parse.urljoin(f"{normalized_base_url}/", relative_path.lstrip("/"))


def _http_request(method: str, url: str, *, payload: Any = None, timeout: int = 30) -> Tuple[int, str, str]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), response.headers.get("Content-Type", ""), response_body
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.headers.get("Content-Type", ""), response_body
    except error.URLError as exc:
        return 0, "", str(exc)


def _json_payload(body_text: str) -> Any:
    try:
        return json.loads(body_text)
    except json.JSONDecodeError:
        return None


def _summarize_cases(executed_cases: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"total": len(executed_cases), "passed": 0, "failed": 0, "skipped": 0}
    for case in executed_cases:
        status = str(((case.get("evaluation") or {}).get("status") or "")).lower()
        if status in summary:
            summary[status] += 1
    return summary


def _case_result(
    *,
    case_id: str,
    description: str,
    status: str,
    request_payload: Dict[str, Any],
    response_payload: Dict[str, Any],
    assertions: List[str],
) -> Dict[str, Any]:
    return {
        "test_case_id": case_id,
        "description": description,
        "type": "api",
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "component-runtime",
        "mapping_status": "supporting",
        "automation_mode": "api_support",
        "execution_mode": "api_support",
        "coverage_status": "automated" if status == "passed" else "supporting",
        "request": request_payload,
        "response": response_payload,
        "evaluation": {
            "status": status,
            "assertions": assertions,
        },
        "expected_result": "The real AI Model Hub model-server exposes discoverable use-case metadata",
    }


def model_server_use_case_validation_enabled(environ: Dict[str, str] | None = None) -> bool:
    values = dict(environ or os.environ)
    explicit = values.get("AI_MODEL_HUB_ENABLE_MODEL_SERVER_USE_CASES")
    if explicit is not None:
        return _parse_bool(explicit)
    mode, _raw_mode = model_server_config.model_server_mode(values)
    return mode in {"use-cases", "combined"}


def resolve_model_server_validation_url(environ: Dict[str, str] | None = None) -> str:
    values = dict(environ or os.environ)
    for key in (
        "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
        "MODEL_SERVER_PUBLIC_URL",
        "AI_MODEL_HUB_MODEL_SERVER_BASE_URL",
        "UI_AI_MODEL_HUB_MODEL_SERVER_BASE_URL",
    ):
        candidate = str(values.get(key) or "").strip().rstrip("/")
        if candidate:
            return candidate
    derived_public_url = model_server_config.public_url(values)
    if derived_public_url:
        return derived_public_url.rstrip("/")
    return ""


def _validation_endpoint_paths(environ: Dict[str, str] | None = None) -> List[str]:
    values = dict(environ or os.environ)
    raw_value = str(values.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS") or "").strip()
    return [entry.strip() for entry in raw_value.replace(";", ",").split(",") if entry.strip()]


def _validation_payload(environ: Dict[str, str] | None = None) -> Any:
    values = dict(environ or os.environ)
    raw_value = str(values.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD") or "").strip()
    if not raw_value:
        return {"text": "This validation input is useful for the PIONERA framework."}
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return {"text": raw_value}


def run_ai_model_hub_model_server_use_cases_validation(
    experiment_dir: str | None = None,
    environ: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    values = dict(environ or os.environ)
    mode, raw_mode = model_server_config.model_server_mode(values)
    base_url = resolve_model_server_validation_url(values)

    if not model_server_use_case_validation_enabled(values):
        skip_reason = f"model-server mode '{raw_mode}' does not require use-case validation"
        executed_cases = [
            _case_result(
                case_id=CASE_ID_DISCOVERY,
                description="Real use-case model-server discovery endpoint",
                status="skipped",
                request_payload={"method": "GET", "url": ""},
                response_payload={},
                assertions=[skip_reason],
            ),
            _case_result(
                case_id=CASE_ID_OPTIONAL_EXECUTION,
                description="Configured real use-case model-server inference endpoints",
                status="skipped",
                request_payload={"method": "POST", "paths": []},
                response_payload={},
                assertions=[skip_reason],
            ),
        ]
        return {
            "component": COMPONENT_KEY,
            "suite": SUITE_NAME,
            "status": "skipped",
            "summary": _summarize_cases(executed_cases),
            "executed_cases": executed_cases,
            "evidence_index": [],
            "artifacts": {},
            "skip_reason": skip_reason,
            "model_server": {
                "mode": mode,
                "configured_mode": raw_mode,
                "base_url": base_url,
            },
        }

    discovery_path = str(
        values.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_DISCOVERY_PATH")
        or values.get("AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH")
        or "/models"
    ).strip()
    if not discovery_path.startswith("/"):
        discovery_path = f"/{discovery_path}"

    executed_cases: List[Dict[str, Any]] = []
    artifacts: Dict[str, str] = {}
    evidence_index: List[Dict[str, Any]] = []
    component_dir = _component_dir(experiment_dir)

    assertions: List[str] = []
    discovery_url = _build_url(base_url, discovery_path)
    discovery_status = 0
    discovery_content_type = ""
    discovery_body = ""
    discovery_payload: Any = None
    if not base_url:
        assertions.append(
            "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL or AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL is required"
        )
    else:
        discovery_status, discovery_content_type, discovery_body = _http_request("GET", discovery_url)
        discovery_payload = _json_payload(discovery_body)
        if discovery_status != 200:
            assertions.append(f"Expected HTTP 200 from discovery endpoint, got HTTP {discovery_status}")
        if discovery_payload is None:
            assertions.append("Discovery endpoint did not return valid JSON")
        elif isinstance(discovery_payload, (list, dict)) and len(discovery_payload) == 0:
            assertions.append("Discovery endpoint returned an empty JSON payload")

    discovery_case = _case_result(
        case_id=CASE_ID_DISCOVERY,
        description="Real use-case model-server discovery endpoint",
        status="failed" if assertions else "passed",
        request_payload={"method": "GET", "url": discovery_url},
        response_payload={
            "http_status": discovery_status,
            "content_type": discovery_content_type,
            "body_excerpt": discovery_body[:1000],
            "json_payload": discovery_payload,
        },
        assertions=assertions,
    )
    executed_cases.append(discovery_case)

    endpoint_paths = _validation_endpoint_paths(values)
    if endpoint_paths:
        endpoint_assertions: List[str] = []
        endpoint_results = []
        payload = _validation_payload(values)
        for endpoint_path in endpoint_paths:
            endpoint_url = _build_url(base_url, endpoint_path)
            status, content_type, body = _http_request("POST", endpoint_url, payload=payload)
            response_payload = _json_payload(body)
            endpoint_results.append(
                {
                    "url": endpoint_url,
                    "http_status": status,
                    "content_type": content_type,
                    "body_excerpt": body[:1000],
                    "json_payload": response_payload,
                }
            )
            if status < 200 or status >= 300:
                endpoint_assertions.append(f"{endpoint_url} returned HTTP {status}")
            if response_payload is None:
                endpoint_assertions.append(f"{endpoint_url} did not return valid JSON")

        executed_cases.append(
            _case_result(
                case_id=CASE_ID_OPTIONAL_EXECUTION,
                description="Configured real use-case model-server inference endpoints",
                status="failed" if endpoint_assertions else "passed",
                request_payload={
                    "method": "POST",
                    "paths": endpoint_paths,
                    "payload": payload,
                },
                response_payload={"endpoint_results": endpoint_results},
                assertions=endpoint_assertions,
            )
        )

    summary = _summarize_cases(executed_cases)
    suite_status = "failed" if summary["failed"] else "passed"

    result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "timestamp": started_at,
        "status": suite_status,
        "summary": summary,
        "executed_cases": executed_cases,
        "evidence_index": evidence_index,
        "artifacts": artifacts,
        "model_server": {
            "mode": mode,
            "configured_mode": raw_mode,
            "base_url": base_url,
            "discovery_path": discovery_path,
            "source_repository": values.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY") or "",
            "source_ref": values.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF") or "",
        },
    }

    if component_dir:
        report_path = os.path.join(component_dir, "ai_model_hub_model_server_use_cases_validation.json")
        discovery_path_json = os.path.join(component_dir, "mh-model-server-01-response.json")
        artifacts.update(
            {
                "report_json": report_path,
                "mh-model-server-01-response.json": discovery_path_json,
            }
        )
        _write_json(
            discovery_path_json,
            {
                "request": discovery_case["request"],
                "response": discovery_case["response"],
                "evaluation": discovery_case["evaluation"],
            },
        )
        evidence_index.append(
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "report_json",
                "path": report_path,
            }
        )
        evidence_index.append(
            {
                "scope": "case",
                "suite": SUITE_NAME,
                "test_case_id": CASE_ID_DISCOVERY,
                "artifact_name": "mh-model-server-01-response.json",
                "path": discovery_path_json,
            }
        )
        if len(executed_cases) > 1:
            execution_path_json = os.path.join(component_dir, "mh-model-server-02-response.json")
            artifacts["mh-model-server-02-response.json"] = execution_path_json
            _write_json(
                execution_path_json,
                {
                    "request": executed_cases[1]["request"],
                    "response": executed_cases[1]["response"],
                    "evaluation": executed_cases[1]["evaluation"],
                },
            )
            evidence_index.append(
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": CASE_ID_OPTIONAL_EXECUTION,
                    "artifact_name": "mh-model-server-02-response.json",
                    "path": execution_path_json,
                }
            )
        _write_json(report_path, result)

    return result
