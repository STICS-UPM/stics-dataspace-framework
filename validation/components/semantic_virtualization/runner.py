import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib import error, parse, request

from validation.components.artifact_contract import attach_component_artifact_manifest
from validation.components.semantic_virtualization.gtfs_bench_materialization import (
    run_gtfs_bench_official_materialization_validation,
)
from validation.components.semantic_virtualization.gtfs_bench_dataset import run_gtfs_bench_official_dataset_validation
from validation.components.semantic_virtualization.gtfs_bench_official import (
    run_gtfs_bench_official_source_validation,
)
from validation.components.semantic_virtualization.mapping_validation import run_semantic_virtualization_mapping_validation
from validation.components.semantic_virtualization.ui_runner import run_semantic_virtualization_ui_validation


COMPONENT_KEY = "semantic-virtualization"
ROOT_PATH = os.environ.get("SEMANTIC_VIRTUALIZATION_ROOT_PATH", "/")
HEALTH_PATH = os.environ.get("SEMANTIC_VIRTUALIZATION_HEALTH_PATH", "/")
CAPABILITIES_PATH = os.environ.get(
    "SEMANTIC_VIRTUALIZATION_CAPABILITIES_PATH",
    "/openapi.json",
)
QUERY_PATH = os.environ.get(
    "SEMANTIC_VIRTUALIZATION_QUERY_PATH",
    "/?query=SELECT%20*%20WHERE%20%7B%20%3Fs%20%3Fp%20%3Fo%20.%20%7D%20LIMIT%201",
)
CONTROLLED_ERROR_QUERY_PATH = os.environ.get(
    "SEMANTIC_VIRTUALIZATION_CONTROLLED_ERROR_QUERY_PATH",
    "/?query=SELECT%20WHERE%20%7B",
)

CASE_METADATA: Dict[str, Dict[str, str]] = {
    "SV-BOOTSTRAP-01": {
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "automation_mode": "api_support",
        "execution_mode": "api_support",
        "coverage_status": "automated",
        "expected_result": "The Semantic Virtualization service root is reachable",
    },
    "SV-API-01": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "api",
        "mapping_status": "phase_1",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
        "expected_result": "The Semantic Virtualization API health endpoint responds successfully",
    },
    "SV-API-02": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "api",
        "mapping_status": "phase_1",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
        "expected_result": "The Semantic Virtualization API exposes machine-readable capabilities",
    },
    "SV-API-03": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "semantic_query",
        "mapping_status": "phase_1",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
        "expected_result": "The Semantic Virtualization SPARQL endpoint returns a successful query response",
    },
    "SV-API-04": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "error_handling",
        "mapping_status": "phase_1",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated",
        "expected_result": "An invalid SPARQL query returns a controlled HTTP 4xx error response",
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


def _http_get(url: str, timeout: int = 20, headers: Dict[str, str] | None = None) -> Tuple[int, str, str]:
    request_headers = {"Cache-Control": "no-store"}
    request_headers.update(headers or {})
    req = request.Request(url, method="GET", headers=request_headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.getcode(), response.headers.get("Content-Type", ""), body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.headers.get("Content-Type", ""), body
    except error.URLError as exc:
        return 0, "", str(exc)


def _http_get_json_with_retry(
    url: str,
    *,
    timeout: int = 20,
    headers: Dict[str, str] | None = None,
    attempts: int = 8,
    delay_seconds: float = 0.75,
) -> Tuple[int, str, str]:
    last_response = 0, "", ""
    request_headers = {"Accept": "application/json"}
    request_headers.update(headers or {})
    for attempt in range(max(1, attempts)):
        last_response = _http_get(url, timeout=timeout, headers=request_headers)
        http_status, content_type, body_text = last_response
        if http_status == 200 and "application/json" in content_type.lower():
            try:
                json.loads(body_text)
                return last_response
            except json.JSONDecodeError:
                pass
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return last_response


def _http_get_controlled_error_with_retry(
    url: str,
    *,
    timeout: int = 20,
    headers: Dict[str, str] | None = None,
    attempts: int = 8,
    delay_seconds: float = 0.75,
) -> Tuple[int, str, str]:
    last_response = 0, "", ""
    for attempt in range(max(1, attempts)):
        last_response = _http_get(url, timeout=timeout, headers=headers)
        http_status, content_type, body_text = last_response
        if 400 <= http_status < 500:
            return last_response
        if http_status == 200 and "application/json" in content_type.lower():
            lowered = body_text.lower()
            if '"status"' in lowered and "error" in lowered:
                return last_response
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return last_response


def evaluate_http_response(
    http_status: int,
    content_type: str,
    body_text: str,
    *,
    require_json: bool = False,
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

    if not require_json:
        return result

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as exc:
        result["status"] = "failed"
        result["assertions"].append(f"Response is not valid JSON: {exc}")
        return result

    if not isinstance(payload, (dict, list)):
        result["status"] = "failed"
        result["assertions"].append("JSON response must be an object or array")
        return result

    if isinstance(payload, dict):
        result["payload_keys"] = sorted(payload.keys())
    else:
        result["payload_length"] = len(payload)
    return result


def evaluate_controlled_error_response(
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

    if http_status == 0:
        result["status"] = "failed"
        result["assertions"].append("Expected a controlled HTTP 4xx response, but no HTTP response was received")
        return result

    if 200 <= http_status < 300:
        result["status"] = "failed"
        result["assertions"].append(f"Invalid SPARQL query unexpectedly succeeded with HTTP {http_status}")
        return result

    if http_status >= 500:
        result["status"] = "failed"
        result["assertions"].append(f"Expected a controlled HTTP 4xx response, got server error HTTP {http_status}")
        return result

    if not (400 <= http_status < 500):
        result["status"] = "failed"
        result["assertions"].append(f"Expected a controlled HTTP 4xx response, got HTTP {http_status}")
        return result

    if not body_text.strip():
        result["status"] = "failed"
        result["assertions"].append("Controlled error response should include a diagnostic body")
        return result

    result["controlled_error"] = True
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


def _suite_cases(suite_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(
        suite_result.get("executed_cases")
        or suite_result.get("test_cases")
        or suite_result.get("pt5_case_results")
        or suite_result.get("support_checks")
        or []
    )


def _tag_suite_cases(suite_name: str, suite_result: Dict[str, Any], phase: str) -> List[Dict[str, Any]]:
    tagged_cases: List[Dict[str, Any]] = []
    for case in _suite_cases(suite_result):
        tagged = dict(case)
        tagged["source_phase"] = phase
        tagged.setdefault("source_suite", suite_result.get("suite") or suite_name)
        tagged_cases.append(tagged)
    return tagged_cases


def _suite_evidence(suite_result: Dict[str, Any], phase: str) -> List[Dict[str, Any]]:
    return [
        {**evidence, "source_phase": phase}
        for evidence in list(suite_result.get("evidence_index") or [])
    ]


def _suite_failure_result(suite_name: str, exc: Exception) -> Dict[str, Any]:
    failure_case = {
        "test_case_id": f"{suite_name}-failure",
        "description": f"{suite_name} suite failed before producing case evidence",
        "type": "suite",
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "automation_mode": "framework",
        "execution_mode": "framework",
        "coverage_status": "automated",
        "evaluation": {
            "status": "failed",
            "assertions": [f"{type(exc).__name__}: {exc}"],
        },
    }
    return {
        "component": COMPONENT_KEY,
        "suite": suite_name,
        "status": "failed",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "executed_cases": [failure_case],
        "test_cases": [failure_case],
        "support_checks": [failure_case],
        "evidence_index": [],
        "artifacts": {},
        "findings": [
            {
                "scope": suite_name,
                "status": "failed",
                "assertions": [f"{type(exc).__name__}: {exc}"],
            }
        ],
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def _evidence_index(executed_cases: List[Dict[str, Any]], artifacts: Dict[str, str]) -> List[Dict[str, Any]]:
    evidence = [
        {
            "scope": "suite",
            "suite": "api",
            "artifact_name": "report_json",
            "path": artifacts["report_json"],
        }
    ]
    for case in executed_cases:
        artifact_key = f"{str(case.get('test_case_id') or '').lower()}-response.json"
        artifact_path = artifacts.get(artifact_key)
        if artifact_path:
            evidence.append(
                {
                    "scope": "case",
                    "suite": "api",
                    "test_case_id": case.get("test_case_id"),
                    "artifact_name": artifact_key,
                    "path": artifact_path,
                }
            )
    return evidence


def run_semantic_virtualization_validation(
    base_url: str,
    experiment_dir: str | None = None,
) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    normalized_base_url = (base_url or "").rstrip("/")

    checks = [
        (
            "SV-BOOTSTRAP-01",
            "preflight",
            "Service root availability",
            ROOT_PATH,
            False,
            None,
            "success",
        ),
        (
            "SV-API-04",
            "functional",
            "Invalid SPARQL query returns a controlled error",
            CONTROLLED_ERROR_QUERY_PATH,
            False,
            {"Accept": "application/sparql-results+json"},
            "controlled_error",
        ),
        (
            "SV-API-01",
            "integration",
            "API health endpoint availability",
            HEALTH_PATH,
            False,
            None,
            "success",
        ),
        (
            "SV-API-02",
            "integration",
            "API capabilities endpoint availability",
            CAPABILITIES_PATH,
            True,
            None,
            "success",
        ),
        (
            "SV-API-03",
            "integration",
            "SPARQL query endpoint returns results",
            QUERY_PATH,
            False,
            {"Accept": "application/sparql-results+json"},
            "success",
        ),
    ]

    component_dir = _component_dir(experiment_dir)
    artifacts: Dict[str, str] = {}
    executed_cases: List[Dict[str, Any]] = []
    api_cases: List[Dict[str, Any]] = []
    functional_suite_results: Dict[str, Dict[str, Any]] = {}
    api_cases_by_phase: Dict[str, List[Dict[str, Any]]] = {
        "preflight": [],
        "functional": [],
        "integration": [],
    }

    def run_api_phase(phase_name: str) -> None:
        phase_checks = [check for check in checks if check[1] == phase_name]
        if not phase_checks:
            return
        if phase_name == "functional":
            print("\nComponent suite: Virtualizador functional\n")
        elif phase_name == "integration":
            print("\nComponent suite: Virtualizador integration\n")

        for case_id, phase, description, relative_path, require_json, request_headers, expectation in phase_checks:
            url = _build_url(normalized_base_url, relative_path)
            if expectation == "controlled_error":
                http_status, content_type, body_text = _http_get_controlled_error_with_retry(
                    url,
                    headers=request_headers,
                )
            elif require_json:
                http_status, content_type, body_text = _http_get_json_with_retry(
                    url,
                    headers=request_headers,
                )
            else:
                http_status, content_type, body_text = _http_get(url, headers=request_headers)
            if expectation == "controlled_error":
                evaluation = evaluate_controlled_error_response(
                    http_status,
                    content_type,
                    body_text,
                )
            else:
                evaluation = evaluate_http_response(
                    http_status,
                    content_type,
                    body_text,
                    require_json=require_json,
                )
            response_payload = {
                "http_status": http_status,
                "content_type": content_type,
                "body_excerpt": body_text[:500],
                **{
                    key: value
                    for key, value in evaluation.items()
                    if key in {"payload_keys", "payload_length", "controlled_error"}
                },
            }
            case_result = _build_case_result(
                case_id=case_id,
                description=description,
                metadata=CASE_METADATA[case_id],
                status=evaluation["status"],
                request_payload={
                    "method": "GET",
                    "url": url,
                    "path": relative_path,
                    "headers": request_headers or {},
                },
                response_payload=response_payload,
                assertions=list(evaluation.get("assertions") or []),
            )
            case_result["source_phase"] = phase
            executed_cases.append(case_result)
            api_cases.append(case_result)
            api_cases_by_phase.setdefault(phase, []).append(case_result)

            if component_dir:
                artifact_key = f"{case_id.lower()}-response.json"
                artifact_path = os.path.join(component_dir, artifact_key)
                _write_json(artifact_path, case_result)
                artifacts[artifact_key] = artifact_path

    run_api_phase("preflight")
    run_api_phase("functional")
    functional_runners = [
        ("mapping_fixtures", "mapping-fixtures", run_semantic_virtualization_mapping_validation),
        ("gtfs_bench_source", "gtfs-bench-official-source", run_gtfs_bench_official_source_validation),
        ("gtfs_bench_dataset", "gtfs-bench-official-dataset", run_gtfs_bench_official_dataset_validation),
        (
            "gtfs_bench_materialization",
            "gtfs-bench-official-materialization",
            run_gtfs_bench_official_materialization_validation,
        ),
    ]
    for suite_key, suite_name, runner in functional_runners:
        try:
            suite_result = runner(experiment_dir=experiment_dir)
        except Exception as exc:  # pragma: no cover - defensive integration guard
            suite_result = _suite_failure_result(suite_name, exc)
        functional_suite_results[suite_key] = suite_result
        executed_cases.extend(_tag_suite_cases(suite_key, suite_result, "functional"))
    ui_result = run_semantic_virtualization_ui_validation(
        normalized_base_url,
        experiment_dir=experiment_dir,
    )
    ui_cases = [
        {**case, "source_phase": "functional"}
        for case in list(ui_result.get("executed_cases") or [])
    ]
    executed_cases.extend(ui_cases)
    run_api_phase("integration")

    summary = _summarize_cases(executed_cases)
    status = "failed" if summary["failed"] or str(ui_result.get("status") or "").lower() in {"failed", "error"} else "passed"
    pt5_case_results = [case for case in executed_cases if case.get("case_group") == "pt5"]
    support_checks = [case for case in executed_cases if case.get("case_group") == "support"]
    findings = [
        {
            "scope": case.get("source_phase") or case.get("case_group") or "component",
            "test_case_id": case.get("test_case_id"),
            "status": "failed",
            "assertions": list((case.get("evaluation") or {}).get("assertions") or []),
        }
        for case in executed_cases
        if ((case.get("evaluation") or {}).get("status") or "").lower() == "failed"
    ]
    pt5_summary = _summarize_cases(pt5_case_results)
    support_summary = _summarize_cases(support_checks)
    phase_order = ["preflight", "functional", "integration"]
    phases = {}
    for phase in phase_order:
        phase_cases = [case for case in executed_cases if case.get("source_phase") == phase]
        suite_results = {}
        phase_api_cases = list(api_cases_by_phase.get(phase) or [])
        if phase_api_cases:
            suite_results["api"] = {
                "status": "failed"
                if any(((case.get("evaluation") or {}).get("status") == "failed") for case in phase_api_cases)
                else "passed",
                "summary": _summarize_cases(phase_api_cases),
                "executed_cases": phase_api_cases,
            }
        if phase == "functional":
            suite_results.update(functional_suite_results)
            suite_results["ui"] = ui_result
        suite_statuses = [
            str(suite_result.get("status") or "").lower()
            for suite_result in suite_results.values()
            if isinstance(suite_result, dict)
        ]
        phase_summary = _summarize_cases(phase_cases)
        if any(status in {"failed", "error"} for status in suite_statuses):
            phase_status = "failed"
        elif any(status == "passed" for status in suite_statuses) or phase_cases:
            phase_status = "failed" if phase_summary["failed"] else "passed"
        elif any(status == "skipped" for status in suite_statuses):
            phase_status = "skipped"
        else:
            phase_status = "skipped"
        phases[phase] = {
            "status": phase_status,
            "summary": phase_summary,
            "suites": suite_results,
        }

    result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "api",
        "base_url": normalized_base_url,
        "timestamp": started_at,
        "status": status,
        "summary": summary,
        "phase_order": phase_order,
        "phases": phases,
        "suites": {
            "api": {
                "status": "failed" if any(((case.get("evaluation") or {}).get("status") == "failed") for case in api_cases)
                else "passed",
                "summary": _summarize_cases(api_cases),
                "executed_cases": api_cases,
            },
            **functional_suite_results,
            "ui": ui_result,
        },
        "executed_cases": executed_cases,
        "pt5_case_results": pt5_case_results,
        "pt5_cases": pt5_case_results,
        "pt5_summary": pt5_summary,
        "support_checks": support_checks,
        "support_summary": support_summary,
        "findings": findings,
    }

    if component_dir:
        report_path = os.path.join(component_dir, "semantic_virtualization_component_validation.json")
        pt5_cases_path = os.path.join(component_dir, "semantic_virtualization_pt5_case_results.json")
        support_checks_path = os.path.join(component_dir, "semantic_virtualization_support_checks.json")
        evidence_index_path = os.path.join(component_dir, "semantic_virtualization_evidence_index.json")
        findings_path = os.path.join(component_dir, "semantic_virtualization_findings.json")
        artifacts.update(
            {
                "report_json": report_path,
                "pt5_case_results_json": pt5_cases_path,
                "support_checks_json": support_checks_path,
                "evidence_index_json": evidence_index_path,
                "findings_json": findings_path,
                "ui_report_json": (ui_result.get("artifacts") or {}).get("report_json", ""),
                "ui_test_results_dir": (ui_result.get("artifacts") or {}).get("test_results_dir", ""),
                "ui_html_report_dir": (ui_result.get("artifacts") or {}).get("html_report_dir", ""),
                "ui_blob_report_dir": (ui_result.get("artifacts") or {}).get("blob_report_dir", ""),
                "ui_json_report_file": (ui_result.get("artifacts") or {}).get("json_report_file", ""),
            }
        )
        result["artifacts"] = artifacts
        result["evidence_index"] = _evidence_index(api_cases, artifacts) + [
            evidence
            for suite_result in functional_suite_results.values()
            for evidence in _suite_evidence(suite_result, "functional")
        ] + [
            {**evidence, "source_phase": "functional"}
            for evidence in list(ui_result.get("evidence_index") or [])
        ] + [
            {"scope": "component", "suite": "component", "artifact_name": "report_json", "path": report_path},
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "pt5_case_results_json",
                "path": pt5_cases_path,
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
            {"scope": "component", "suite": "component", "artifact_name": "findings_json", "path": findings_path},
        ]
        attach_component_artifact_manifest(result, component_dir)

        _write_json(pt5_cases_path, {"pt5_case_results": pt5_case_results, "summary": pt5_summary})
        _write_json(support_checks_path, {"support_checks": support_checks, "summary": support_summary})
        _write_json(findings_path, {"findings": findings})
        _write_json(evidence_index_path, {"evidence_index": result["evidence_index"]})
        _write_json(report_path, result)
    else:
        result["artifacts"] = {
            **artifacts,
            "ui_report_json": (ui_result.get("artifacts") or {}).get("report_json", ""),
        }
        result["evidence_index"] = [
            {**evidence, "source_phase": "functional"}
            for evidence in list(ui_result.get("evidence_index") or [])
        ]

    return result
