import json
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib import error, parse, request

from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime

COMPONENT_KEY = "ontology-hub"
API_SEARCH_PATH = "/dataset/api/v2/term/search"
SPARQL_PATH = "/dataset/sparql"
PATTERNS_PATH = "/dataset/patterns"
HOME_PATH = "/dataset"
API_DOCS_PATH = "/dataset/api"

API_CASE_METADATA: Dict[str, Dict[str, str]] = {
    "PT5-OH-08": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
    },
    "PT5-OH-09": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "composite_ui_api",
        "execution_mode": "composite_ui_api",
        "coverage_status": "automated",
    },
    "PT5-OH-13": {
        "case_group": "pt5",
        "validation_type": "interoperability",
        "dataspace_dimension": "interoperability",
        "mapping_status": "mapped",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
    },
    "PT5-OH-14": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "services",
        "mapping_status": "mapped",
        "automation_mode": "composite_ui_api",
        "execution_mode": "composite_ui_api",
        "coverage_status": "automated",
    },
    "PT5-OH-15": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "integration",
        "mapping_status": "mapped",
        "automation_mode": "composite_ui_api",
        "execution_mode": "composite_ui_api",
        "coverage_status": "automated",
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


def _http_get(url: str, timeout: int = 20) -> Tuple[int, str, str]:
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), response.headers.get("Content-Type", ""), body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.headers.get("Content-Type", ""), body


def _http_get_until_stable(
    url: str,
    *,
    attempts: int = 8,
    delay_seconds: float = 5.0,
    transient_statuses: Sequence[int] = (502, 503, 504),
) -> Tuple[int, str, str, List[Dict[str, Any]]]:
    history: List[Dict[str, Any]] = []
    last_status = 0
    last_content_type = ""
    last_body = ""

    for attempt in range(1, max(1, attempts) + 1):
        try:
            last_status, last_content_type, last_body = _http_get(url)
            history.append(
                {
                    "attempt": attempt,
                    "http_status": last_status,
                    "content_type": last_content_type,
                }
            )
        except error.URLError as exc:
            last_status = 0
            last_content_type = ""
            last_body = str(exc)
            history.append(
                {
                    "attempt": attempt,
                    "http_status": 0,
                    "error": str(exc),
                }
            )

        if last_status not in transient_statuses:
            break
        if attempt < attempts:
            time.sleep(delay_seconds)

    return last_status, last_content_type, last_body, history


def _parse_curl_with_markers(stdout: str) -> Tuple[int, str, str]:
    status_match = re.search(r"\n__PIONERA_HTTP_STATUS__:(\d{3})\s*", stdout)
    content_type_match = re.search(r"\n__PIONERA_CONTENT_TYPE__:(.*?)\s*$", stdout, flags=re.DOTALL)
    body_end = status_match.start() if status_match else len(stdout)
    body = stdout[:body_end]
    status = int(status_match.group(1)) if status_match else 0
    content_type = content_type_match.group(1).strip() if content_type_match else ""
    return status, content_type, body


def _kubectl_exec_http_get(
    *,
    namespace: str,
    deployment_name: str,
    url: str,
    timeout: int = 20,
) -> Tuple[int, str, str, Dict[str, Any]]:
    target = f"deployment/{deployment_name}"
    command = [
        "kubectl",
        "exec",
        "-n",
        namespace,
        target,
        "--",
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--max-time",
        str(timeout),
        "--write-out",
        "\n__PIONERA_HTTP_STATUS__:%{http_code}\n__PIONERA_CONTENT_TYPE__:%{content_type}\n",
        url,
    ]
    diagnostic: Dict[str, Any] = {
        "executed": False,
        "namespace": namespace,
        "target": target,
        "url": url,
    }
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
    except FileNotFoundError as exc:
        diagnostic["error"] = f"kubectl not found: {exc}"
        return 0, "", diagnostic["error"], diagnostic
    except subprocess.TimeoutExpired as exc:
        diagnostic["error"] = f"kubectl exec timed out after {exc.timeout}s"
        return 0, "", diagnostic["error"], diagnostic

    diagnostic["executed"] = True
    diagnostic["returncode"] = completed.returncode
    if completed.stderr:
        diagnostic["stderr"] = completed.stderr.strip()

    http_status, content_type, body = _parse_curl_with_markers(completed.stdout or "")
    if completed.returncode != 0 and not body:
        body = (completed.stderr or "").strip()
    if completed.returncode != 0:
        diagnostic["error"] = (completed.stderr or completed.stdout or "").strip()
    return http_status, content_type, body, diagnostic


def _kubectl_exec_shell(
    *,
    namespace: str,
    deployment_name: str,
    script: str,
    timeout: int = 180,
) -> Dict[str, Any]:
    target = f"deployment/{deployment_name}"
    command = [
        "kubectl",
        "exec",
        "-n",
        namespace,
        target,
        "--",
        "sh",
        "-lc",
        script,
    ]
    diagnostic: Dict[str, Any] = {
        "executed": False,
        "namespace": namespace,
        "target": target,
    }
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        diagnostic["error"] = f"kubectl not found: {exc}"
        return diagnostic
    except subprocess.TimeoutExpired as exc:
        diagnostic["error"] = f"kubectl exec timed out after {exc.timeout}s"
        return diagnostic

    diagnostic.update(
        {
            "executed": True,
            "returncode": completed.returncode,
            "stdout_excerpt": (completed.stdout or "")[-3000:],
            "stderr_excerpt": (completed.stderr or "")[-3000:],
        }
    )
    if completed.returncode != 0:
        diagnostic["error"] = (completed.stderr or completed.stdout or "").strip()
    return diagnostic


def _kubectl_http_get_until_stable(
    *,
    namespace: str,
    deployment_name: str,
    url: str,
    attempts: int = 8,
    delay_seconds: float = 5.0,
    transient_statuses: Sequence[int] = (0, 502, 503, 504),
) -> Tuple[int, str, str, List[Dict[str, Any]], bool]:
    history: List[Dict[str, Any]] = []
    last_status = 0
    last_content_type = ""
    last_body = ""
    ever_executed = False

    for attempt in range(1, max(1, attempts) + 1):
        last_status, last_content_type, last_body, diagnostic = _kubectl_exec_http_get(
            namespace=namespace,
            deployment_name=deployment_name,
            url=url,
        )
        ever_executed = ever_executed or bool(diagnostic.get("executed"))
        history.append(
            {
                "attempt": attempt,
                "http_status": last_status,
                "content_type": last_content_type,
                **diagnostic,
            }
        )

        if not diagnostic.get("executed"):
            break
        if last_status not in transient_statuses:
            break
        if attempt < attempts:
            time.sleep(delay_seconds)

    return last_status, last_content_type, last_body, history, ever_executed


def _prepare_sparql_store(runtime: Dict[str, Any]) -> Dict[str, Any]:
    script = r'''
set -u
export PATH="/opt/java/openjdk/bin:/opt/java/openjdk/jre/bin:${PATH}"
if [ ! -s /app/public/lov.nq ] && [ -x /app/setup/lovInitialization.sh ]; then
  bash /app/setup/lovInitialization.sh
fi
if [ ! -s /app/public/lov.nq ]; then
  echo "Missing /app/public/lov.nq; cannot prepare SPARQL store"
  exit 21
fi
pkill -f "[f]useki-server" || true
sleep 1
rm -f /app/jena/tdb_lov_db/*
FORCE_RELOAD=true bash /app/setup/jena.sh
'''
    return _kubectl_exec_shell(
        namespace=runtime["componentsNamespace"],
        deployment_name=runtime["releaseName"],
        script=script,
        timeout=240,
    )


def _collect_strings(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        results: List[str] = []
        for item in value.values():
            results.extend(_collect_strings(item))
        return results
    if isinstance(value, (list, tuple, set)):
        results = []
        for item in value:
            results.extend(_collect_strings(item))
        return results
    return [str(value)]


def _flatten_text(value: Any) -> str:
    return " ".join(_collect_strings(value)).strip()


def _get_result_value(result: Dict[str, Any], key: str) -> Any:
    if key in result:
        return result.get(key)
    current: Any = result
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current


def _find_bucket(aggregations: Dict[str, Any], agg_name: str, bucket_key: str) -> Dict[str, Any] | None:
    buckets = (((aggregations or {}).get(agg_name) or {}).get("buckets")) or []
    for bucket in buckets:
        if str(bucket.get("key")) == str(bucket_key):
            return bucket
    return None


def _result_contains_value(result: Dict[str, Any], key: str, expected_value: str) -> bool:
    flattened = _flatten_text(_get_result_value(result, key)).lower()
    return expected_value.lower() in flattened


def evaluate_term_search_response(
    http_status: int,
    content_type: str,
    body_text: str,
    *,
    expected_query: str,
    expected_vocab: str | None = None,
    expected_tag: str | None = None,
    require_results: bool = True,
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

    result["json_type"] = type(payload).__name__
    if isinstance(payload, dict):
        embedded_status = payload.get("statusCode")
        if isinstance(embedded_status, int) and embedded_status >= 400:
            result["status"] = "failed"
            result["assertions"].append(
                f"Application payload reports embedded error statusCode={embedded_status}"
            )
        if payload.get("error") or payload.get("msg"):
            result["status"] = "failed"
            result["assertions"].append("Application payload contains error markers")
        result["payload_keys"] = sorted(payload.keys())
        results_payload = payload.get("results")
        total_results = payload.get("total_results")
        filters = payload.get("filters") or {}
        aggregations = payload.get("aggregations") or {}
        result["reported_total_results"] = total_results

        if require_results:
            if not isinstance(results_payload, list) or not results_payload:
                result["status"] = "failed"
                result["assertions"].append("Expected at least one search result, but the payload is empty")
                return result

            if isinstance(total_results, int) and total_results < 1:
                result["status"] = "failed"
                result["assertions"].append("Expected total_results >= 1")

            matched_query = False
            matched_vocab = expected_vocab is None
            matched_tag = expected_tag is None
            for item in results_payload:
                flattened = _flatten_text(item).lower()
                if expected_query.lower() in flattened:
                    matched_query = True
                if expected_vocab and _result_contains_value(item, "vocabulary.prefix", expected_vocab):
                    matched_vocab = True
                if expected_tag and _result_contains_value(item, "tags", expected_tag):
                    matched_tag = True
            if not matched_query:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected at least one result containing the search term '{expected_query}'"
                )
            if not matched_vocab:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected at least one result belonging to vocabulary '{expected_vocab}'"
                )
            if not matched_tag:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected at least one result tagged with '{expected_tag}'"
                )

        if expected_vocab:
            if filters.get("vocab") and filters.get("vocab") != expected_vocab:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected filter vocab='{expected_vocab}', got '{filters.get('vocab')}'"
                )
            if (
                filters.get("vocab") != expected_vocab
                and _find_bucket(aggregations, "vocabs", expected_vocab) is None
            ):
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected the response to expose vocabulary '{expected_vocab}' either in filters or aggregations"
                )

        if expected_tag:
            if filters.get("tag") and filters.get("tag") != expected_tag:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected filter tag='{expected_tag}', got '{filters.get('tag')}'"
                )
            if filters.get("tag") != expected_tag and _find_bucket(aggregations, "tags", expected_tag) is None:
                result["status"] = "failed"
                result["assertions"].append(
                    f"Expected the response to expose tag '{expected_tag}' either in filters or aggregations"
                )
    else:
        result["payload_size"] = len(payload)

    return result


def evaluate_html_page_response(
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
    normalized_type = (content_type or "").lower()
    if "html" not in normalized_type and "<html" not in normalized_body and "<!doctype html" not in normalized_body:
        result["status"] = "failed"
        result["assertions"].append("Expected an HTML response")

    embedded_error_markers = (
        "500 - oops! something went wrong - 500",
        "cannot read properties of null",
        "typeerror:",
        "edition.jade:",
        "/app/app/views/edition.jade",
    )
    if any(marker in normalized_body for marker in embedded_error_markers):
        result["status"] = "failed"
        result["assertions"].append("HTML response renders an embedded server error page")

    missing_markers = [marker for marker in required_markers if marker.lower() not in normalized_body]
    if missing_markers:
        result["status"] = "failed"
        result["assertions"].append(
            f"Missing expected page markers: {', '.join(missing_markers)}"
        )

    return result


def _build_case_result(
    *,
    test_case_id: str,
    description: str,
    case_type: str,
    metadata: Dict[str, str],
    requests_payload: Dict[str, Any] | List[Dict[str, Any]],
    responses_payload: Dict[str, Any] | List[Dict[str, Any]],
    evaluation: Dict[str, Any],
    expected_result: str,
) -> Dict[str, Any]:
    return {
        "test_case_id": test_case_id,
        "description": description,
        "type": case_type,
        "case_group": metadata["case_group"],
        "validation_type": metadata["validation_type"],
        "dataspace_dimension": metadata["dataspace_dimension"],
        "mapping_status": metadata["mapping_status"],
        "automation_mode": metadata["automation_mode"],
        "execution_mode": metadata["execution_mode"],
        "coverage_status": metadata["coverage_status"],
        "request": requests_payload,
        "response": responses_payload,
        "evaluation": evaluation,
        "expected_result": expected_result,
    }


def _summarize_case_list(executed_cases: List[Dict[str, Any]]) -> Dict[str, int]:
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


def _build_api_evidence_index(
    executed_cases: List[Dict[str, Any]],
    report_path: str | None,
    raw_artifact_paths: Dict[str, str],
) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = []
    if report_path:
        evidence_index.append(
            {
                "scope": "suite",
                "suite": "api",
                "artifact_name": "report_json",
                "path": report_path,
            }
        )

    for case in executed_cases:
        artifact_path = raw_artifact_paths.get(case.get("test_case_id", ""))
        if not artifact_path:
            continue
        evidence_index.append(
            {
                "scope": "case",
                "suite": "api",
                "test_case_id": case.get("test_case_id"),
                "case_group": case.get("case_group"),
                "artifact_name": "raw_response",
                "path": artifact_path,
            }
        )
    return evidence_index


def _run_search_case(
    *,
    base_url: str,
    test_case_id: str,
    description: str,
    query_params: Dict[str, str],
    expected_result: str,
    expected_vocab: str | None = None,
    expected_tag: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    request_url = f"{base_url}{API_SEARCH_PATH}?{parse.urlencode(query_params)}"
    http_status, content_type, body_text = _http_get(request_url)
    evaluation = evaluate_term_search_response(
        http_status,
        content_type,
        body_text,
        expected_query=query_params["q"],
        expected_vocab=expected_vocab,
        expected_tag=expected_tag,
    )
    case_result = _build_case_result(
        test_case_id=test_case_id,
        description=description,
        case_type="api",
        metadata=API_CASE_METADATA[test_case_id],
        requests_payload={
            "method": "GET",
            "url": request_url,
            "query": dict(query_params),
        },
        responses_payload={
            "http_status": http_status,
            "content_type": content_type,
        },
        evaluation=evaluation,
        expected_result=expected_result,
    )
    raw_artifact = {
        "url": request_url,
        "http_status": http_status,
        "content_type": content_type,
        "body": body_text,
    }
    return case_result, raw_artifact


def _run_html_case(
    *,
    base_url: str,
    test_case_id: str,
    description: str,
    path: str,
    required_markers: Sequence[str],
    expected_result: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    request_url = f"{base_url}{path}"
    http_status, content_type, body_text = _http_get(request_url)
    evaluation = evaluate_html_page_response(
        http_status,
        content_type,
        body_text,
        required_markers=required_markers,
    )
    case_result = _build_case_result(
        test_case_id=test_case_id,
        description=description,
        case_type="api",
        metadata=API_CASE_METADATA[test_case_id],
        requests_payload={
            "method": "GET",
            "url": request_url,
        },
        responses_payload={
            "http_status": http_status,
            "content_type": content_type,
        },
        evaluation=evaluation,
        expected_result=expected_result,
    )
    raw_artifact = {
        "url": request_url,
        "http_status": http_status,
        "content_type": content_type,
        "body": body_text,
    }
    return case_result, raw_artifact


def _run_ui_api_access_case(base_url: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ui_url = f"{base_url}{HOME_PATH}"
    api_url = f"{base_url}{API_DOCS_PATH}"
    ui_status, ui_type, ui_body = _http_get(ui_url)
    api_status, api_type, api_body = _http_get(api_url)
    ui_evaluation = evaluate_html_page_response(
        ui_status,
        ui_type,
        ui_body,
        required_markers=["/dataset/api", "/dataset/vocabs"],
    )
    api_evaluation = evaluate_html_page_response(
        api_status,
        api_type,
        api_body,
        required_markers=["/api/v2/term/search", "/dataset/api/v2/agent/list"],
    )
    overall_status = "passed"
    assertions: List[str] = []
    if ui_evaluation["status"] != "passed":
        overall_status = "failed"
        assertions.extend(f"UI: {message}" for message in ui_evaluation["assertions"])
    if api_evaluation["status"] != "passed":
        overall_status = "failed"
        assertions.extend(f"API docs: {message}" for message in api_evaluation["assertions"])

    case_result = _build_case_result(
        test_case_id="PT5-OH-15",
        description="Acceso coordinado via UI y API",
        case_type="api",
        metadata=API_CASE_METADATA["PT5-OH-15"],
        requests_payload=[
            {"method": "GET", "url": ui_url, "role": "ui"},
            {"method": "GET", "url": api_url, "role": "api_docs"},
        ],
        responses_payload=[
            {"http_status": ui_status, "content_type": ui_type, "role": "ui"},
            {"http_status": api_status, "content_type": api_type, "role": "api_docs"},
        ],
        evaluation={
            "status": overall_status,
            "assertions": assertions,
            "checks": {
                "ui": ui_evaluation,
                "api_docs": api_evaluation,
            },
        },
        expected_result="La UI principal y la documentacion API se publican de forma coordinada y accesible.",
    )
    raw_artifact = {
        "ui": {
            "url": ui_url,
            "http_status": ui_status,
            "content_type": ui_type,
            "body": ui_body,
        },
        "api_docs": {
            "url": api_url,
            "http_status": api_status,
            "content_type": api_type,
            "body": api_body,
        },
    }
    return case_result, raw_artifact


def evaluate_sparql_response(
    http_status: int,
    content_type: str,
    body_text: str,
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

    normalized_type = (content_type or "").lower()
    if "xml" in normalized_type or body_text.lstrip().startswith("<?xml"):
        xml_match = re.search(r"<boolean>\s*(true|false)\s*</boolean>", body_text, flags=re.IGNORECASE)
        if not xml_match:
            result["status"] = "failed"
            result["assertions"].append("SPARQL XML response does not contain a <boolean> result")
            return result
        boolean_value = xml_match.group(1).lower() == "true"
        result["boolean"] = boolean_value
        if not boolean_value:
            result["status"] = "failed"
            result["assertions"].append("Expected SPARQL ASK query to return boolean=true")
        return result

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as exc:
        result["status"] = "failed"
        result["assertions"].append(f"SPARQL response is not valid JSON: {exc}")
        return result

    result["payload_keys"] = sorted(payload.keys()) if isinstance(payload, dict) else []
    boolean_value = payload.get("boolean") if isinstance(payload, dict) else None
    result["boolean"] = boolean_value
    if boolean_value is not True:
        result["status"] = "failed"
        result["assertions"].append("Expected SPARQL ASK query to return boolean=true")
    return result


def _assertion_summary(evaluation: Dict[str, Any]) -> str:
    assertions = list(evaluation.get("assertions") or [])
    if assertions:
        return "; ".join(str(message) for message in assertions)
    status = evaluation.get("http_status")
    if status:
        return f"HTTP {status}"
    return str(evaluation.get("body_excerpt") or "unknown error")[:240]


def _combine_sparql_evaluations(
    *,
    internal_evaluation: Dict[str, Any],
    public_evaluation: Dict[str, Any],
    internal_executed: bool,
) -> Dict[str, Any]:
    internal_passed = internal_evaluation.get("status") == "passed"
    public_passed = public_evaluation.get("status") == "passed"
    assertions: List[str] = []
    warnings: List[str] = []

    if internal_executed:
        if not internal_passed:
            assertions.append(f"Internal cluster SPARQL check failed: {_assertion_summary(internal_evaluation)}")
    elif not public_passed:
        assertions.append("Internal cluster SPARQL check could not be executed and the public endpoint also failed.")
    else:
        warnings.append("Internal cluster SPARQL check could not be executed; public endpoint evidence was used.")

    if not public_passed:
        message = (
            "Public SPARQL exposure through ingress did not pass. "
            f"Diagnostic: {_assertion_summary(public_evaluation)}"
        )
        if internal_passed:
            warnings.append(message)
        else:
            assertions.append(message)

    return {
        "status": "failed" if assertions else "passed",
        "assertions": assertions,
        "warnings": warnings,
        "internal_cluster_status": internal_evaluation.get("status"),
        "public_ingress_status": public_evaluation.get("status"),
        "checks": {
            "internal_cluster": internal_evaluation,
            "public_ingress": public_evaluation,
        },
    }


def _run_sparql_access_case(base_url: str, runtime: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    expected_resource_uri = runtime["expectedSparqlResourceUri"]
    sparql_query = f"ASK {{ GRAPH ?g {{ <{expected_resource_uri}> ?p ?o }} }}"
    query_string = parse.urlencode({"query": sparql_query})
    public_request_url = f"{base_url}{SPARQL_PATH}?{query_string}"
    internal_request_url = f"{runtime['internalBaseUrl']}{SPARQL_PATH}?{query_string}"
    preparation: Dict[str, Any] = {
        "attempted": False,
        "enabled": bool(runtime.get("prepareSparqlStore", True)),
    }

    internal_status, internal_type, internal_body, internal_retry_history, internal_executed = _kubectl_http_get_until_stable(
        namespace=runtime["componentsNamespace"],
        deployment_name=runtime["releaseName"],
        url=internal_request_url,
    )
    internal_evaluation = evaluate_sparql_response(internal_status, internal_type, internal_body)
    internal_evaluation["retry_history"] = internal_retry_history
    internal_evaluation["executed"] = internal_executed

    if runtime.get("prepareSparqlStore", True) and internal_executed and internal_evaluation.get("status") != "passed":
        preparation = {
            "attempted": True,
            "enabled": True,
            **_prepare_sparql_store(runtime),
        }
        internal_status, internal_type, internal_body, internal_retry_history, internal_executed = _kubectl_http_get_until_stable(
            namespace=runtime["componentsNamespace"],
            deployment_name=runtime["releaseName"],
            url=internal_request_url,
            attempts=4,
        )
        internal_evaluation = evaluate_sparql_response(internal_status, internal_type, internal_body)
        internal_evaluation["retry_history"] = internal_retry_history
        internal_evaluation["executed"] = internal_executed
        internal_evaluation["preparation"] = preparation

    public_status, public_type, public_body, public_retry_history = _http_get_until_stable(public_request_url)
    public_evaluation = evaluate_sparql_response(public_status, public_type, public_body)
    public_evaluation["retry_history"] = public_retry_history

    evaluation = _combine_sparql_evaluations(
        internal_evaluation=internal_evaluation,
        public_evaluation=public_evaluation,
        internal_executed=internal_executed,
    )
    case_result = _build_case_result(
        test_case_id="PT5-OH-13",
        description="Consulta SPARQL real sobre la ontologia de ejemplo sembrada",
        case_type="api",
        metadata=API_CASE_METADATA["PT5-OH-13"],
        requests_payload=[
            {
                "role": "internal_cluster",
                "method": "GET",
                "url": internal_request_url,
                "query": sparql_query,
                "expected_resource_uri": expected_resource_uri,
                "namespace": runtime["componentsNamespace"],
                "deployment": runtime["releaseName"],
            },
            {
                "role": "public_ingress",
                "method": "GET",
                "url": public_request_url,
                "query": sparql_query,
                "expected_resource_uri": expected_resource_uri,
            },
        ],
        responses_payload=[
            {
                "role": "internal_cluster",
                "http_status": internal_status,
                "content_type": internal_type,
                "executed": internal_executed,
            },
            {
                "role": "public_ingress",
                "http_status": public_status,
                "content_type": public_type,
            },
        ],
        evaluation=evaluation,
        expected_result=(
            "La consulta ASK sobre el recurso RDF sembrado devuelve true dentro del cluster. "
            "La exposicion publica por ingress queda registrada como evidencia diagnostica."
        ),
    )
    raw_artifact = {
        "query": sparql_query,
        "expected_resource_uri": expected_resource_uri,
        "preparation": preparation,
        "internal_cluster": {
            "url": internal_request_url,
            "namespace": runtime["componentsNamespace"],
            "deployment": runtime["releaseName"],
            "http_status": internal_status,
            "content_type": internal_type,
            "body": internal_body,
            "retry_history": internal_retry_history,
            "executed": internal_executed,
        },
        "public_ingress": {
            "url": public_request_url,
            "http_status": public_status,
            "content_type": public_type,
            "body": public_body,
            "retry_history": public_retry_history,
        },
        "evaluation": evaluation,
    }
    return case_result, raw_artifact


def run_ontology_hub_validation(
    base_url: str,
    experiment_dir: str | None = None,
    case_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> Dict[str, Any]:
    runtime = resolve_ontology_hub_runtime(base_url=base_url)
    normalized_base_url = runtime["baseUrl"]
    started_at = datetime.now().isoformat()
    requested_case_ids = {str(case_id or "").strip().upper() for case_id in (case_ids or []) if str(case_id or "").strip()}

    executed_cases: List[Dict[str, Any]] = []
    raw_artifacts: List[Tuple[str, str, Dict[str, Any]]] = []

    def requested(test_case_id: str) -> bool:
        return not requested_case_ids or test_case_id.upper() in requested_case_ids

    if requested("PT5-OH-08"):
        pt5_oh_08, artifact_08 = _run_search_case(
            base_url=normalized_base_url,
            test_case_id="PT5-OH-08",
            description="Busqueda de vocabularios por texto libre con contenido real indexado",
            query_params={
                "q": runtime["expectedSearchTerm"],
                "type": "class",
            },
            expected_result="La busqueda devuelve al menos un termino indexado de ejemplo, con agregaciones y contenido coherentes.",
            expected_vocab=runtime["expectedVocabularyPrefix"],
        )
        executed_cases.append(pt5_oh_08)
        raw_artifacts.append(("PT5-OH-08", "pt5-oh-08-response.json", artifact_08))

    if requested("PT5-OH-09"):
        pt5_oh_09, artifact_09 = _run_search_case(
            base_url=normalized_base_url,
            test_case_id="PT5-OH-09",
            description="Filtrado de vocabularios mediante vocabulario y etiqueta",
            query_params={
                "q": runtime["expectedSearchTerm"],
                "type": "class",
                "vocab": runtime["expectedVocabularyPrefix"],
                "tag": runtime["expectedPrimaryTag"],
            },
            expected_result="La busqueda filtrada devuelve resultados coherentes con el vocabulario y la etiqueta de ejemplo.",
            expected_vocab=runtime["expectedVocabularyPrefix"],
            expected_tag=runtime["expectedPrimaryTag"],
        )
        executed_cases.append(pt5_oh_09)
        raw_artifacts.append(("PT5-OH-09", "pt5-oh-09-response.json", artifact_09))

    if requested("PT5-OH-13"):
        pt5_oh_13, artifact_13 = _run_sparql_access_case(normalized_base_url, runtime)
        executed_cases.append(pt5_oh_13)
        raw_artifacts.append(("PT5-OH-13", "pt5-oh-13-response.json", artifact_13))

    if requested("PT5-OH-14"):
        pt5_oh_14, artifact_14 = _run_html_case(
            base_url=normalized_base_url,
            test_case_id="PT5-OH-14",
            description="Acceso al servicio de patrones",
            path=f"{PATTERNS_PATH}?{parse.urlencode({'q': runtime['expectedVocabularyPrefix']})}",
            required_markers=["selected vocabularies", f"checkbox_{runtime['expectedVocabularyPrefix']}"],
            expected_result="La pagina del servicio de patrones esta publicada y accesible.",
        )
        executed_cases.append(pt5_oh_14)
        raw_artifacts.append(("PT5-OH-14", "pt5-oh-14-response.json", artifact_14))

    if requested("PT5-OH-15"):
        pt5_oh_15, artifact_15 = _run_ui_api_access_case(normalized_base_url)
        executed_cases.append(pt5_oh_15)
        raw_artifacts.append(("PT5-OH-15", "pt5-oh-15-response.json", artifact_15))

    summary = {
        "total": len(executed_cases),
        "passed": sum(1 for case in executed_cases if case["evaluation"]["status"] == "passed"),
        "failed": sum(1 for case in executed_cases if case["evaluation"]["status"] == "failed"),
        "skipped": 0,
    }
    overall_status = "failed" if summary["failed"] else "passed" if summary["total"] else "skipped"
    pt5_summary = _summarize_case_list(executed_cases)

    component_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "base_url": normalized_base_url,
        "status": overall_status,
        "timestamp": started_at,
        "seed_expectations": {
            "search_term": runtime["expectedSearchTerm"],
            "expected_label": runtime["expectedLabel"],
            "expected_vocabulary": runtime["expectedVocabularyPrefix"],
            "expected_tag": runtime["expectedPrimaryTag"],
        },
        "runtime": runtime,
        "executed_cases": executed_cases,
        "summary": summary,
        "pt5_cases": executed_cases,
        "support_checks": [],
        "pt5_summary": pt5_summary,
        "support_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "evidence_index": [],
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        artifact_paths: Dict[str, str] = {}
        case_artifact_paths: Dict[str, str] = {}
        for test_case_id, file_name, payload in raw_artifacts:
            artifact_path = os.path.join(component_dir, file_name)
            _write_json(artifact_path, payload)
            artifact_paths[file_name] = artifact_path
            case_artifact_paths[test_case_id] = artifact_path
        report_path = os.path.join(component_dir, "ontology_hub_validation.json")
        component_result["evidence_index"] = _build_api_evidence_index(
            executed_cases,
            report_path,
            case_artifact_paths,
        )
        _write_json(report_path, component_result)
        component_result["artifacts"] = {
            "report_json": report_path,
            **artifact_paths,
        }

    return component_result
