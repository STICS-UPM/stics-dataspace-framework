import json
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib import error, parse, request

from deployers.shared.lib import ai_model_hub_model_server as model_server_config


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "model-server-use-cases-api"
SUITE_DISPLAY_NAME = "AI Model Hub use cases"
CASE_ID_DISCOVERY = "MH-MODEL-SERVER-01"
CASE_ID_DATASETS = "MH-MODEL-SERVER-02"
CASE_ID_OPTIONAL_EXECUTION = "MH-MODEL-SERVER-03"


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


def _payload_item_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    if isinstance(payload.get("models"), list):
        return len(payload["models"])
    if isinstance(payload.get("datasets"), list):
        return len(payload["datasets"])
    count = 0
    for value in payload.values():
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += 1
        elif value not in (None, "", []):
            count += 1
    return count


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
        "expected_result": "The AI Model Hub use-case model-server exposes the expected API contract",
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


def _validation_endpoint_payloads(environ: Dict[str, str] | None = None) -> Dict[str, Any]:
    values = dict(environ or os.environ)
    raw_value = str(values.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINT_PAYLOADS") or "").strip()
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _default_mobility_payload() -> List[Dict[str, Any]]:
    return [
        {
            "trip_id": "L13_1_05:45_LxI",
            "from_stop_id": "7716",
            "to_stop_id": "19219",
            "route_id": "13",
            "scheduled_travel_time": 120,
            "shape_distance": 681.1956848810403,
            "is_peak": 0,
            "hour_sin": 0.7071067811865475,
            "hour_cos": 0.7071067811865476,
            "weekday_sin": 0.9749279121818236,
            "weekday_cos": -0.22252093395631434,
            "previous_delay_ratio": 0.2499999979166667,
            "previous_delay_delta": 0.0,
        }
    ]


def _default_flares_text_payload() -> List[Dict[str, Any]]:
    return [
        {
            "Id": 840,
            "Text": (
                "El comite de medicamentos humanos espera poder concluir el analisis "
                "de todo el paquete de datos a mediados de marzo."
            ),
        }
    ]


def _default_flares_reliability_payload() -> List[Dict[str, Any]]:
    row = _default_flares_text_payload()[0]
    return [
        {
            **row,
            "Tag_Start": 0,
            "Tag_End": 38,
            "5W1H_Label": "WHO",
            "Tag_Text": "El comite de medicamentos humanos",
        }
    ]


def _payload_for_endpoint(
    endpoint_path: str,
    *,
    environ: Dict[str, str],
    configured_endpoint_payloads: Dict[str, Any],
    configured_global_payload: Any | None,
) -> Any:
    normalized_path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
    if normalized_path in configured_endpoint_payloads:
        return configured_endpoint_payloads[normalized_path]
    if endpoint_path in configured_endpoint_payloads:
        return configured_endpoint_payloads[endpoint_path]
    if configured_global_payload is not None:
        return configured_global_payload
    lowered = normalized_path.lower()
    if lowered.startswith("/mobility/"):
        return _default_mobility_payload()
    if lowered.startswith("/flares/") and "reliability" in lowered:
        return _default_flares_reliability_payload()
    if lowered.startswith("/flares/"):
        return _default_flares_text_payload()
    return _validation_payload(environ)


def _discovered_endpoint_paths(discovery_payload: Any) -> List[str]:
    if not isinstance(discovery_payload, dict):
        return []
    paths: List[str] = []
    for model_name in discovery_payload.get("flares") or []:
        if str(model_name or "").strip():
            paths.append(f"/flares/{model_name}")
    for model_name in discovery_payload.get("mobility") or []:
        if str(model_name or "").strip():
            paths.append(f"/mobility/{model_name}")
    return paths


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
                description="Use-case model discovery endpoint",
                status="skipped",
                request_payload={"method": "GET", "url": ""},
                response_payload={},
                assertions=[skip_reason],
            ),
            _case_result(
                case_id=CASE_ID_DATASETS,
                description="Use-case dataset discovery endpoint",
                status="skipped",
                request_payload={"method": "GET", "url": ""},
                response_payload={},
                assertions=[skip_reason],
            ),
            _case_result(
                case_id=CASE_ID_OPTIONAL_EXECUTION,
                description="Configured use-case inference endpoints",
                status="skipped",
                request_payload={"method": "POST", "paths": []},
                response_payload={},
                assertions=[skip_reason],
            ),
        ]
        return {
            "component": COMPONENT_KEY,
            "suite": SUITE_NAME,
            "suite_display_name": SUITE_DISPLAY_NAME,
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
    configured_datasets_path = values.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_DATASETS_PATH")
    if configured_datasets_path is None:
        configured_datasets_path = values.get("AI_MODEL_HUB_MODEL_SERVER_DATASETS_PATH")
    default_datasets_path = "disabled" if mode == "use-cases" else "/datasets"
    datasets_path = str(
        configured_datasets_path if configured_datasets_path is not None else default_datasets_path
    ).strip()
    datasets_validation_enabled = datasets_path.lower() not in {"", "0", "false", "no", "none", "skip", "disabled"}
    if datasets_validation_enabled and not datasets_path.startswith("/"):
        datasets_path = f"/{datasets_path}"

    executed_cases: List[Dict[str, Any]] = []
    artifacts: Dict[str, str] = {}
    evidence_index: List[Dict[str, Any]] = []
    component_dir = _component_dir(experiment_dir)

    def _get_discovery_case(*, case_id: str, description: str, path: str, label: str) -> Dict[str, Any]:
        assertions: List[str] = []
        url = _build_url(base_url, path)
        status = 0
        content_type = ""
        body = ""
        payload: Any = None
        if not base_url:
            assertions.append(
                "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL or AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL is required"
            )
        else:
            status, content_type, body = _http_request("GET", url)
            payload = _json_payload(body)
            if status != 200:
                assertions.append(f"Expected HTTP 200 from {label} endpoint, got HTTP {status}")
            if payload is None:
                assertions.append(f"{label.capitalize()} endpoint did not return valid JSON")
            elif _payload_item_count(payload) == 0:
                assertions.append(f"{label.capitalize()} endpoint returned no entries")
        return _case_result(
            case_id=case_id,
            description=description,
            status="failed" if assertions else "passed",
            request_payload={"method": "GET", "url": url},
            response_payload={
                "http_status": status,
                "content_type": content_type,
                "body_excerpt": body[:1000],
                "json_payload": payload,
                "item_count": _payload_item_count(payload),
            },
            assertions=assertions,
        )

    discovery_case = _get_discovery_case(
        case_id=CASE_ID_DISCOVERY,
        description="Use-case model discovery endpoint",
        path=discovery_path,
        label="model discovery",
    )
    executed_cases.append(discovery_case)
    datasets_case: Dict[str, Any] | None = None
    if datasets_validation_enabled:
        datasets_case = _get_discovery_case(
            case_id=CASE_ID_DATASETS,
            description="Use-case dataset discovery endpoint",
            path=datasets_path,
            label="dataset discovery",
        )
        executed_cases.append(datasets_case)

    configured_endpoint_paths = _validation_endpoint_paths(values)
    discovery_payload = (discovery_case.get("response") or {}).get("json_payload")
    endpoint_paths = configured_endpoint_paths or _discovered_endpoint_paths(discovery_payload)
    execution_case: Dict[str, Any] | None = None
    if endpoint_paths:
        endpoint_assertions: List[str] = []
        endpoint_results = []
        configured_endpoint_payloads = _validation_endpoint_payloads(values)
        raw_global_payload = str(values.get("AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD") or "").strip()
        configured_global_payload = _validation_payload(values) if raw_global_payload else None
        for endpoint_path in endpoint_paths:
            payload = _payload_for_endpoint(
                endpoint_path,
                environ=values,
                configured_endpoint_payloads=configured_endpoint_payloads,
                configured_global_payload=configured_global_payload,
            )
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

        execution_case = _case_result(
            case_id=CASE_ID_OPTIONAL_EXECUTION,
            description="Configured use-case inference endpoints",
            status="failed" if endpoint_assertions else "passed",
            request_payload={
                "method": "POST",
                "paths": endpoint_paths,
                "source": "configured" if configured_endpoint_paths else "discovered",
            },
            response_payload={"endpoint_results": endpoint_results},
            assertions=endpoint_assertions,
        )
        executed_cases.append(execution_case)

    summary = _summarize_cases(executed_cases)
    suite_status = "failed" if summary["failed"] else "passed"

    result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "suite_display_name": SUITE_DISPLAY_NAME,
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
            "datasets_path": datasets_path,
            "datasets_validation_enabled": datasets_validation_enabled,
            "source_repository": values.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY") or "",
            "source_ref": values.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF") or "",
        },
    }

    if component_dir:
        report_path = os.path.join(component_dir, "ai_model_hub_model_server_use_cases_validation.json")
        discovery_path_json = os.path.join(component_dir, "mh-model-server-01-response.json")
        datasets_path_json = os.path.join(component_dir, "mh-model-server-02-response.json")
        artifacts.update(
            {
                "report_json": report_path,
                "mh-model-server-01-response.json": discovery_path_json,
            }
        )
        if datasets_case is not None:
            artifacts["mh-model-server-02-response.json"] = datasets_path_json
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
        if datasets_case is not None:
            _write_json(
                datasets_path_json,
                {
                    "request": datasets_case["request"],
                    "response": datasets_case["response"],
                    "evaluation": datasets_case["evaluation"],
                },
            )
            evidence_index.append(
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": CASE_ID_DATASETS,
                    "artifact_name": "mh-model-server-02-response.json",
                    "path": datasets_path_json,
                }
            )
        if execution_case is not None:
            execution_path_json = os.path.join(component_dir, "mh-model-server-03-response.json")
            artifacts["mh-model-server-03-response.json"] = execution_path_json
            _write_json(
                execution_path_json,
                {
                    "request": execution_case["request"],
                    "response": execution_case["response"],
                    "evaluation": execution_case["evaluation"],
                },
            )
            evidence_index.append(
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": CASE_ID_OPTIONAL_EXECUTION,
                    "artifact_name": "mh-model-server-03-response.json",
                    "path": execution_path_json,
                }
            )
        _write_json(report_path, result)

    return result
