import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import yaml


CATALOG_PATH = Path(__file__).resolve().parent / "test_cases.yaml"

SUITE_METADATA = {
    "ui-core-smoke": {
        "suite": "ui-core",
        "scope": "dataspace_ui",
        "report_file_name": "ui_core_validation.json",
    },
    "ui-core-dataspace": {
        "suite": "ui-core-dataspace",
        "scope": "dataspace_ui",
        "report_file_name": "ui_dataspace_validation.json",
    },
    "ui-ops-minio-console": {
        "suite": "ui-ops",
        "scope": "dataspace_ui",
        "report_file_name": "ui_ops_validation.json",
    },
}

SUMMARY_FILE_NAME = "ui_validation_summary.json"


def _normalize_spec_path(spec_path: str | None) -> str:
    value = str(spec_path or "").replace("\\", "/").strip()
    if value.startswith("./"):
        value = value[2:]
    if value.startswith("validation/ui/"):
        value = value[len("validation/ui/"):]
    return value


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _normalize_catalog_entry(entry: Dict[str, Any], default_case_group: str) -> Dict[str, Any]:
    normalized = dict(entry or {})
    normalized["id"] = str(normalized.get("id") or "").strip()
    normalized["case_group"] = normalized.get("case_group") or default_case_group
    normalized["scope"] = normalized.get("scope") or "dataspace_ui"
    normalized["validation_type"] = normalized.get("validation_type") or (
        "support" if normalized["case_group"] == "support" else "functional"
    )
    normalized["dataspace_dimension"] = normalized.get("dataspace_dimension") or (
        "support" if normalized["case_group"] == "support" else normalized["validation_type"]
    )
    normalized["execution_mode"] = normalized.get("execution_mode") or "ui"
    normalized["coverage_status"] = normalized.get("coverage_status") or "manual"
    normalized["mapping_status"] = normalized.get("mapping_status") or "partial"
    normalized["automation"] = dict(normalized.get("automation") or {})
    normalized["traceability"] = list(normalized.get("traceability") or [])
    normalized["operations"] = [str(operation).strip() for operation in list(normalized.get("operations") or []) if str(operation).strip()]
    return normalized


def load_ui_catalog() -> Dict[str, Any]:
    with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    support_checks = [
        _normalize_catalog_entry(entry, "support")
        for entry in list(payload.get("support_checks") or [])
    ]
    dataspace_cases = [
        _normalize_catalog_entry(entry, "dataspace")
        for entry in list(payload.get("test_cases") or [])
    ]
    ops_checks = [
        _normalize_catalog_entry(entry, "ops")
        for entry in list(payload.get("ops_checks") or [])
    ]

    return {
        "source_file": str(CATALOG_PATH),
        "source_documents": list(payload.get("source_documents") or []),
        "support_checks": support_checks,
        "dataspace_cases": dataspace_cases,
        "ops_checks": ops_checks,
    }


def _catalog_entries_by_spec(catalog: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for entry in list(catalog.get("support_checks") or []) + list(catalog.get("dataspace_cases") or []) + list(
        catalog.get("ops_checks") or []
    ):
        spec_path = _normalize_spec_path((entry.get("automation") or {}).get("ui_spec"))
        if spec_path:
            mapping[spec_path] = entry
    return mapping


def _iter_specs(suites: Iterable[Dict[str, Any]], parent_file: str | None = None) -> Iterable[Dict[str, Any]]:
    for suite in suites or []:
        suite_file = suite.get("file") or parent_file or suite.get("title")
        for child_suite in suite.get("suites") or []:
            yield from _iter_specs([child_suite], suite_file)
        for spec in suite.get("specs") or []:
            normalized = dict(spec)
            normalized["_suite_file"] = suite_file
            yield normalized


def _spec_result_status(spec: Dict[str, Any]) -> str:
    tests = spec.get("tests") or []
    if not tests:
        return "skipped"
    results = tests[0].get("results") or []
    if not results:
        return "skipped"
    return (results[-1].get("status") or "skipped").lower()


def _spec_assertions(spec: Dict[str, Any]) -> List[str]:
    tests = spec.get("tests") or []
    if not tests:
        return []
    results = tests[0].get("results") or []
    if not results:
        return []

    assertions: List[str] = []
    for error in results[-1].get("errors") or []:
        if isinstance(error, str):
            assertions.append(error)
            continue
        message = error.get("message") or error.get("value") or error.get("location")
        if message:
            assertions.append(str(message))
    return assertions


def _attachments_from_spec(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    tests = spec.get("tests") or []
    if not tests:
        return []
    results = tests[0].get("results") or []
    if not results:
        return []

    attachments = results[-1].get("attachments") or []
    normalized: List[Dict[str, str]] = []
    for attachment in attachments:
        normalized.append(
            {
                "name": attachment.get("name", ""),
                "content_type": attachment.get("contentType", ""),
                "path": attachment.get("path", ""),
            }
        )
    return normalized


def _build_case_result(
    *,
    catalog_entry: Dict[str, Any],
    status: str,
    request_payload: Dict[str, Any],
    attachments: List[Dict[str, str]],
    assertions: List[str],
) -> Dict[str, Any]:
    return {
        "test_case_id": catalog_entry.get("id"),
        "description": catalog_entry.get("description", ""),
        "type": catalog_entry.get("type", "ui"),
        "scope": catalog_entry.get("scope", "dataspace_ui"),
        "case_group": catalog_entry.get("case_group", "dataspace"),
        "validation_type": catalog_entry.get("validation_type"),
        "dataspace_dimension": catalog_entry.get("dataspace_dimension"),
        "execution_mode": catalog_entry.get("execution_mode"),
        "coverage_status": catalog_entry.get("coverage_status"),
        "mapping_status": catalog_entry.get("mapping_status"),
        "traceability": list(catalog_entry.get("traceability") or []),
        "operations": list(catalog_entry.get("operations") or []),
        "expected_result": catalog_entry.get("expected_result"),
        "request": request_payload,
        "response": {
            "status": status,
            "attachments": attachments,
        },
        "evaluation": {
            "status": status,
            "assertions": assertions,
        },
        "catalog_case": {
            "id": catalog_entry.get("id"),
            "case_group": catalog_entry.get("case_group"),
            "validation_type": catalog_entry.get("validation_type"),
            "dataspace_dimension": catalog_entry.get("dataspace_dimension"),
            "execution_mode": catalog_entry.get("execution_mode"),
            "coverage_status": catalog_entry.get("coverage_status"),
            "mapping_status": catalog_entry.get("mapping_status"),
            "operations": list(catalog_entry.get("operations") or []),
        },
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


def _filter_case_group(executed_cases: List[Dict[str, Any]], case_group: str) -> List[Dict[str, Any]]:
    return [case for case in executed_cases if case.get("case_group") == case_group]


def _build_evidence_index(
    executed_cases: List[Dict[str, Any]],
    artifacts: Dict[str, Any],
    suite_name: str,
) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = []
    for artifact_name in (
        "report_json",
        "json_report_file",
        "html_report_dir",
        "blob_report_dir",
        "test_results_dir",
    ):
        artifact_path = artifacts.get(artifact_name)
        if artifact_path:
            evidence_index.append(
                {
                    "scope": "suite",
                    "suite": suite_name,
                    "artifact_name": artifact_name,
                    "path": artifact_path,
                }
            )

    for case in executed_cases:
        for attachment in (case.get("response") or {}).get("attachments") or []:
            evidence_index.append(
                {
                    "scope": "case",
                    "suite": suite_name,
                    "test_case_id": case.get("test_case_id"),
                    "case_group": case.get("case_group"),
                    "artifact_name": attachment.get("name", ""),
                    "content_type": attachment.get("content_type", ""),
                    "path": attachment.get("path", ""),
                }
            )

    return evidence_index


def _build_findings(executed_cases: List[Dict[str, Any]], suite_name: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for case in executed_cases:
        status = ((case.get("evaluation") or {}).get("status") or "").lower()
        if status != "failed":
            continue
        findings.append(
            {
                "scope": case.get("case_group") or "dataspace",
                "suite": suite_name,
                "test_case_id": case.get("test_case_id"),
                "status": status,
                "assertions": list((case.get("evaluation") or {}).get("assertions") or []),
            }
        )
    return findings


def _operations_involved(executed_cases: Sequence[Dict[str, Any]]) -> List[str]:
    operations = {
        str(operation).strip()
        for case in executed_cases or []
        for operation in list(case.get("operations") or [])
        if str(operation).strip()
    }
    return sorted(operations)


def _build_operation_summary(executed_cases: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    raw_summary: Dict[str, Dict[str, Any]] = {}
    for case in executed_cases or []:
        status = str(((case.get("evaluation") or {}).get("status") or "skipped")).lower()
        test_case_id = str(case.get("test_case_id") or "")
        for operation in list(case.get("operations") or []):
            normalized_operation = str(operation).strip()
            if not normalized_operation:
                continue
            bucket = raw_summary.setdefault(
                normalized_operation,
                {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "test_case_ids": set(),
                },
            )
            bucket["total"] += 1
            if status in {"passed", "failed", "skipped"}:
                bucket[status] += 1
            if test_case_id:
                bucket["test_case_ids"].add(test_case_id)

    operation_summary: Dict[str, Dict[str, Any]] = {}
    for operation in sorted(raw_summary):
        bucket = dict(raw_summary[operation])
        bucket["test_case_ids"] = sorted(bucket["test_case_ids"])
        operation_summary[operation] = bucket
    return operation_summary


def _status_priority(status: str) -> int:
    normalized = str(status or "").lower()
    if normalized == "failed":
        return 3
    if normalized == "passed":
        return 2
    if normalized == "skipped":
        return 1
    return 0


def _combine_suite_status(results: Sequence[Dict[str, Any]]) -> str:
    if not results:
        return "not_run"
    statuses = [str((item or {}).get("status") or "").lower() for item in results]
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "passed" for status in statuses):
        return "passed"
    if any(status == "skipped" for status in statuses):
        return "skipped"
    return "not_run"


def _summarize_suite_runs(results: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    summary = {
        "total": len(list(results or [])),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "not_run": 0,
    }
    for result in results or []:
        status = str((result or {}).get("status") or "not_run").lower()
        if status not in summary:
            status = "not_run"
        summary[status] += 1
    return summary


def _case_sort_key(case: Dict[str, Any]) -> tuple[str, int, str]:
    test_case_id = str(case.get("test_case_id") or case.get("id") or "")
    parts = test_case_id.split("-")
    if len(parts) >= 3 and parts[-1].isdigit():
        return ("-".join(parts[:-1]), int(parts[-1]), test_case_id)
    return (test_case_id, 0, test_case_id)


def _catalog_sort_key(case: Dict[str, Any]) -> tuple[str, int, str]:
    return _case_sort_key({"test_case_id": case.get("id") or case.get("test_case_id")})


def _execution_context(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "test": result.get("test"),
        "suite": result.get("suite"),
        "connector": result.get("connector"),
        "provider_connector": result.get("provider_connector"),
        "consumer_connector": result.get("consumer_connector"),
        "portal_url": result.get("portal_url"),
    }


def _flatten_case_group(results: Sequence[Dict[str, Any]], field_name: str) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    for result in results or []:
        context = _execution_context(result)
        for case in list((result or {}).get(field_name) or []):
            item = dict(case)
            item["execution_context"] = context
            flattened.append(item)
    return flattened


def _flatten_evidence_index(results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    for result in results or []:
        context = _execution_context(result)
        for entry in list((result or {}).get("evidence_index") or []):
            item = dict(entry)
            item["execution_context"] = context
            flattened.append(item)
    return flattened


def _flatten_findings(results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    for result in results or []:
        context = _execution_context(result)
        for entry in list((result or {}).get("findings") or []):
            item = dict(entry)
            item["execution_context"] = context
            flattened.append(item)
    return flattened


def _summarize_unique_case_statuses(cases: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    best_status_by_case: Dict[str, str] = {}
    for case in cases or []:
        case_id = str(case.get("test_case_id") or "")
        if not case_id:
            continue
        candidate_status = str(((case.get("evaluation") or {}).get("status") or "skipped")).lower()
        current_status = best_status_by_case.get(case_id)
        if current_status is None or _status_priority(candidate_status) > _status_priority(current_status):
            best_status_by_case[case_id] = candidate_status

    summary = {
        "total": len(best_status_by_case),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }
    for status in best_status_by_case.values():
        if status in summary:
            summary[status] += 1
    return summary


def _best_unique_cases(cases: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best_case_by_id: Dict[str, Dict[str, Any]] = {}
    for case in cases or []:
        case_id = str(case.get("test_case_id") or "")
        if not case_id:
            continue
        current = best_case_by_id.get(case_id)
        candidate_status = str(((case.get("evaluation") or {}).get("status") or "skipped")).lower()
        current_status = str((((current or {}).get("evaluation") or {}).get("status") or "skipped")).lower()
        if current is None or _status_priority(candidate_status) > _status_priority(current_status):
            best_case_by_id[case_id] = case
    return sorted(best_case_by_id.values(), key=_case_sort_key)


def _build_aggregate_catalog_alignment(
    catalog: Dict[str, Any],
    dataspace_cases: Sequence[Dict[str, Any]],
    support_checks: Sequence[Dict[str, Any]],
    ops_checks: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    unique_dataspace_cases = _best_unique_cases(dataspace_cases)
    unique_support_checks = _best_unique_cases(support_checks)
    unique_ops_checks = _best_unique_cases(ops_checks)
    return _build_catalog_alignment(
        catalog,
        unique_dataspace_cases,
        unique_support_checks,
        unique_ops_checks,
    )


def _suite_runs(results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    for result in results or []:
        artifacts = dict((result or {}).get("artifacts") or {})
        runs.append(
            {
                "test": result.get("test"),
                "suite": result.get("suite"),
                "status": result.get("status"),
                "connector": result.get("connector"),
                "provider_connector": result.get("provider_connector"),
                "consumer_connector": result.get("consumer_connector"),
                "portal_url": result.get("portal_url"),
                "summary": dict((result or {}).get("summary") or {}),
                "artifacts": {
                    "report_json": artifacts.get("report_json"),
                    "json_report_file": artifacts.get("json_report_file"),
                    "html_report_dir": artifacts.get("html_report_dir"),
                    "blob_report_dir": artifacts.get("blob_report_dir"),
                    "test_results_dir": artifacts.get("test_results_dir"),
                },
            }
        )
    return runs


def _build_catalog_alignment(
    catalog: Dict[str, Any],
    dataspace_cases: List[Dict[str, Any]],
    support_checks: List[Dict[str, Any]],
    ops_checks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    declared_dataspace = list(catalog.get("dataspace_cases") or [])
    declared_support = list(catalog.get("support_checks") or [])
    declared_ops = list(catalog.get("ops_checks") or [])

    executed_dataspace_ids = {str(case.get("test_case_id") or "") for case in dataspace_cases}
    executed_support_ids = {str(case.get("test_case_id") or "") for case in support_checks}
    executed_ops_ids = {str(case.get("test_case_id") or "") for case in ops_checks}

    return {
        "source_file": catalog.get("source_file"),
        "source_documents": list(catalog.get("source_documents") or []),
        "summary": {
            "declared_dataspace_cases": len(declared_dataspace),
            "executed_dataspace_cases": len(dataspace_cases),
            "uncovered_dataspace_cases": len(
                [case for case in declared_dataspace if case.get("id") not in executed_dataspace_ids]
            ),
            "declared_support_checks": len(declared_support),
            "executed_support_checks": len(support_checks),
            "missing_support_checks": len(
                [case for case in declared_support if case.get("id") not in executed_support_ids]
            ),
            "declared_ops_checks": len(declared_ops),
            "executed_ops_checks": len(ops_checks),
            "missing_ops_checks": len([case for case in declared_ops if case.get("id") not in executed_ops_ids]),
        },
        "declared_dataspace_cases": declared_dataspace,
        "declared_support_checks": declared_support,
        "declared_ops_checks": declared_ops,
        "uncovered_dataspace_cases": [
            case for case in declared_dataspace if case.get("id") not in executed_dataspace_ids
        ],
        "missing_support_checks": [
            case for case in declared_support if case.get("id") not in executed_support_ids
        ],
        "missing_ops_checks": [
            case for case in declared_ops if case.get("id") not in executed_ops_ids
        ],
    }


def _load_playwright_payload(json_report_file: str | None) -> Dict[str, Any] | None:
    if not json_report_file or not os.path.exists(json_report_file):
        return None
    with open(json_report_file, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _placeholder_case_results(
    spec_paths: Sequence[str],
    status: str,
    catalog_cases_by_spec: Dict[str, Dict[str, Any]],
    result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    executed_cases: List[Dict[str, Any]] = []
    for spec_path in spec_paths or []:
        catalog_entry = catalog_cases_by_spec.get(_normalize_spec_path(spec_path))
        if not catalog_entry:
            continue
        executed_cases.append(
            _build_case_result(
                catalog_entry=catalog_entry,
                status=(status or "skipped").lower(),
                request_payload={
                    "runner": "playwright",
                    "spec": (catalog_entry.get("automation") or {}).get("ui_spec") or spec_path,
                    "base_url": result.get("portal_url"),
                    "provider_connector": result.get("provider_connector"),
                    "consumer_connector": result.get("consumer_connector"),
                },
                attachments=[],
                assertions=[],
            )
        )
    return executed_cases


def _extract_cases_from_payload(
    payload: Dict[str, Any],
    result: Dict[str, Any],
    catalog_cases_by_spec: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    executed_cases: List[Dict[str, Any]] = []
    selected_specs = {_normalize_spec_path(spec) for spec in list(result.get("specs") or [])}

    for spec in _iter_specs(payload.get("suites") or []):
        spec_file = _normalize_spec_path(spec.get("file") or spec.get("_suite_file"))
        if selected_specs and spec_file not in selected_specs:
            continue
        catalog_entry = catalog_cases_by_spec.get(spec_file)
        if not catalog_entry:
            continue
        status = _spec_result_status(spec)
        executed_cases.append(
            _build_case_result(
                catalog_entry=catalog_entry,
                status=status,
                request_payload={
                    "runner": "playwright",
                    "spec": (catalog_entry.get("automation") or {}).get("ui_spec") or spec_file,
                    "base_url": result.get("portal_url"),
                    "provider_connector": result.get("provider_connector"),
                    "consumer_connector": result.get("consumer_connector"),
                },
                attachments=_attachments_from_spec(spec),
                assertions=_spec_assertions(spec),
            )
        )

    return executed_cases


def enrich_level6_ui_result(result: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(result or {})
    test_name = str(enriched.get("test") or "")
    suite_meta = SUITE_METADATA.get(
        test_name,
        {
            "suite": test_name or "ui",
            "scope": "dataspace_ui",
            "report_file_name": "ui_validation.json",
        },
    )
    artifacts = dict(enriched.get("artifacts") or {})
    if not artifacts.get("report_json") and artifacts.get("json_report_file"):
        artifacts["report_json"] = os.path.join(
            os.path.dirname(artifacts["json_report_file"]),
            suite_meta["report_file_name"],
        )

    catalog = load_ui_catalog()
    catalog_cases_by_spec = _catalog_entries_by_spec(catalog)
    payload = _load_playwright_payload(artifacts.get("json_report_file"))
    if payload is None:
        executed_cases = _placeholder_case_results(
            enriched.get("specs") or [],
            str(enriched.get("status") or "skipped"),
            catalog_cases_by_spec,
            enriched,
        )
    else:
        executed_cases = _extract_cases_from_payload(payload, enriched, catalog_cases_by_spec)

    dataspace_cases = _filter_case_group(executed_cases, "dataspace")
    support_checks = _filter_case_group(executed_cases, "support")
    ops_checks = _filter_case_group(executed_cases, "ops")

    summary = _summarize_cases(executed_cases)
    dataspace_summary = _summarize_cases(dataspace_cases)
    support_summary = _summarize_cases(support_checks)
    ops_summary = _summarize_cases(ops_checks)
    evidence_index = _build_evidence_index(executed_cases, artifacts, suite_meta["suite"])
    findings = _build_findings(executed_cases, suite_meta["suite"])
    catalog_alignment = _build_catalog_alignment(catalog, dataspace_cases, support_checks, ops_checks)
    operations_involved = _operations_involved(executed_cases)
    operation_summary = _build_operation_summary(executed_cases)

    enriched["suite"] = suite_meta["suite"]
    enriched["scope"] = suite_meta["scope"]
    enriched["summary"] = summary
    enriched["executed_cases"] = executed_cases
    enriched["dataspace_cases"] = dataspace_cases
    enriched["support_checks"] = support_checks
    enriched["ops_checks"] = ops_checks
    enriched["dataspace_summary"] = dataspace_summary
    enriched["support_summary"] = support_summary
    enriched["ops_summary"] = ops_summary
    enriched["evidence_index"] = evidence_index
    enriched["findings"] = findings
    enriched["catalog_alignment"] = catalog_alignment
    enriched["operations_involved"] = operations_involved
    enriched["operation_summary"] = operation_summary
    enriched["artifacts"] = artifacts

    report_path = artifacts.get("report_json")
    if report_path:
        _write_json(report_path, enriched)

    return enriched


def aggregate_level6_ui_results(
    ui_results: Sequence[Dict[str, Any]],
    *,
    experiment_dir: str | None = None,
) -> Dict[str, Any]:
    results = list(ui_results or [])
    catalog = load_ui_catalog()
    support_checks = _flatten_case_group(results, "support_checks")
    dataspace_cases = _flatten_case_group(results, "dataspace_cases")
    ops_checks = _flatten_case_group(results, "ops_checks")
    executed_cases = sorted(
        support_checks + dataspace_cases + ops_checks,
        key=_case_sort_key,
    )
    suite_runs = _suite_runs(results)
    artifacts: Dict[str, Any] = {}
    if experiment_dir:
        artifacts["report_json"] = os.path.join(experiment_dir, SUMMARY_FILE_NAME)

    aggregate = {
        "scope": "dataspace_ui",
        "status": _combine_suite_status(results),
        "summary": _summarize_suite_runs(results),
        "suite_runs": suite_runs,
        "executed_cases": executed_cases,
        "dataspace_cases": dataspace_cases,
        "support_checks": support_checks,
        "ops_checks": ops_checks,
        "execution_summary": _summarize_cases(executed_cases),
        "dataspace_summary": _summarize_cases(dataspace_cases),
        "support_summary": _summarize_cases(support_checks),
        "ops_summary": _summarize_cases(ops_checks),
        "catalog_coverage_summary": {
            "dataspace_cases": _summarize_unique_case_statuses(dataspace_cases),
            "support_checks": _summarize_unique_case_statuses(support_checks),
            "ops_checks": _summarize_unique_case_statuses(ops_checks),
        },
        "operations_involved": _operations_involved(executed_cases),
        "operation_summary": _build_operation_summary(executed_cases),
        "evidence_index": _flatten_evidence_index(results),
        "findings": _flatten_findings(results),
        "catalog_alignment": _build_aggregate_catalog_alignment(
            catalog,
            dataspace_cases,
            support_checks,
            ops_checks,
        ),
        "artifacts": artifacts,
    }

    report_path = artifacts.get("report_json")
    if report_path:
        _write_json(report_path, aggregate)

    return aggregate
