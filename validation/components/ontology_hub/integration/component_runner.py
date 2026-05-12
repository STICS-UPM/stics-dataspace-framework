import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

from validation.components.ontology_hub.integration.runner import run_ontology_hub_validation
from validation.components.ontology_hub.integration.ui_runner import run_ontology_hub_ui_validation


COMPONENT_KEY = "ontology-hub"
CATALOG_PATH = Path(__file__).resolve().parent / "test_cases.yaml"

CASE_DEFAULTS: Dict[str, Dict[str, str]] = {
    "OH-LOGIN": {
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "coverage_status": "automated",
    },
    "OH-LIST-SEARCH": {
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "coverage_status": "automated",
    },
    "PT5-OH-01": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "publication",
        "mapping_status": "mapped",
        "coverage_status": "automated",
    },
    "PT5-OH-08": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "coverage_status": "automated",
    },
    "PT5-OH-09": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "partial",
        "coverage_status": "partial",
    },
    "PT5-OH-10": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "partial",
        "coverage_status": "partial",
    },
    "PT5-OH-11": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "visualization",
        "mapping_status": "mapped",
        "coverage_status": "automated",
    },
    "PT5-OH-12": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "visualization",
        "mapping_status": "mapped",
        "coverage_status": "automated",
    },
    "PT5-OH-13": {
        "case_group": "pt5",
        "validation_type": "interoperability",
        "dataspace_dimension": "interoperability",
        "mapping_status": "mapped",
        "coverage_status": "automated",
    },
    "PT5-OH-14": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "services",
        "mapping_status": "partial",
        "coverage_status": "partial",
    },
    "PT5-OH-15": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "integration",
        "mapping_status": "partial",
        "coverage_status": "partial",
    },
}

STATUS_PRIORITY = {
    "failed": 3,
    "passed": 2,
    "skipped": 1,
}

MAPPING_PRIORITY = {
    "mapped": 3,
    "partial": 2,
    "supporting": 1,
}

COVERAGE_PRIORITY = {
    "automated": 4,
    "partial": 3,
    "manual": 2,
    "not_currently_executable": 1,
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


def _combine_status(api_status: str, ui_status: str) -> str:
    statuses = {api_status, ui_status}
    if "failed" in statuses:
        return "failed"
    if statuses == {"skipped"}:
        return "skipped"
    return "passed"


def _case_sort_key(case: Dict[str, Any]) -> tuple[str, int, str]:
    test_case_id = str(case.get("test_case_id") or "")
    parts = test_case_id.split("-")
    if len(parts) >= 3 and parts[-1].isdigit():
        return ("-".join(parts[:-1]), int(parts[-1]), test_case_id)
    return (test_case_id, 0, test_case_id)


def _catalog_sort_key(case: Dict[str, Any]) -> tuple[str, int, str]:
    return _case_sort_key({"test_case_id": case.get("id") or case.get("test_case_id")})


def _default_case_group(test_case_id: str) -> str:
    return "pt5" if test_case_id.startswith("PT5-") else "support"


def _coverage_from_mapping(mapping_status: str) -> str:
    if mapping_status == "mapped":
        return "automated"
    if mapping_status == "partial":
        return "partial"
    if mapping_status == "supporting":
        return "manual"
    return "not_currently_executable"


def _normalize_catalog_entry(entry: Dict[str, Any], default_case_group: str) -> Dict[str, Any]:
    normalized = dict(entry or {})
    case_id = str(normalized.get("id") or normalized.get("test_case_id") or "")
    defaults = CASE_DEFAULTS.get(case_id, {})
    automation = dict(normalized.get("automation") or {})
    case_group = normalized.get("case_group") or defaults.get("case_group") or default_case_group
    mapping_status = normalized.get("mapping_status") or defaults.get("mapping_status") or (
        "supporting" if case_group == "support" else "partial"
    )

    normalized["id"] = case_id
    normalized["case_group"] = case_group
    normalized["validation_type"] = normalized.get("validation_type") or defaults.get("validation_type") or (
        "support" if case_group == "support" else "functional"
    )
    normalized["dataspace_dimension"] = normalized.get("dataspace_dimension") or defaults.get("dataspace_dimension") or (
        "support" if case_group == "support" else normalized["validation_type"]
    )
    normalized["mapping_status"] = mapping_status
    normalized["execution_mode"] = normalized.get("execution_mode") or automation.get("mode") or (
        "ui_support" if case_group == "support" else "manual"
    )
    normalized["coverage_status"] = normalized.get("coverage_status") or defaults.get("coverage_status") or _coverage_from_mapping(
        mapping_status
    )
    normalized["traceability"] = list(normalized.get("traceability") or [])
    normalized["preconditions"] = list(normalized.get("preconditions") or [])
    normalized["steps"] = list(normalized.get("steps") or [])
    normalized["automation"] = automation
    return normalized


def _load_catalog() -> Dict[str, Any]:
    with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    pt5_cases = sorted(
        [
            _normalize_catalog_entry(entry, "pt5")
            for entry in list(payload.get("test_cases") or [])
        ],
        key=_catalog_sort_key,
    )
    support_checks = sorted(
        [
            _normalize_catalog_entry(entry, "support")
            for entry in list(payload.get("support_checks") or [])
        ],
        key=_catalog_sort_key,
    )
    return {
        "source_file": str(CATALOG_PATH),
        "source_documents": list(payload.get("source_documents") or []),
        "pt5_cases": pt5_cases,
        "support_checks": support_checks,
    }


def _normalize_case(case: Dict[str, Any], suite_name: str) -> Dict[str, Any]:
    normalized = dict(case or {})
    test_case_id = str(normalized.get("test_case_id") or "")
    defaults = CASE_DEFAULTS.get(test_case_id, {})
    case_group = normalized.get("case_group") or defaults.get("case_group") or _default_case_group(test_case_id)
    mapping_status = normalized.get("mapping_status") or defaults.get("mapping_status") or (
        "supporting" if case_group == "support" else "partial"
    )
    evaluation = dict(normalized.get("evaluation") or {})
    status = (evaluation.get("status") or normalized.get("status") or "skipped").lower()
    evaluation["status"] = status
    evaluation["assertions"] = list(evaluation.get("assertions") or [])

    normalized["test_case_id"] = test_case_id
    normalized["case_group"] = case_group
    normalized["validation_type"] = normalized.get("validation_type") or defaults.get("validation_type") or (
        "support" if case_group == "support" else "functional"
    )
    normalized["dataspace_dimension"] = normalized.get("dataspace_dimension") or defaults.get("dataspace_dimension") or (
        "support" if case_group == "support" else normalized["validation_type"]
    )
    normalized["mapping_status"] = mapping_status
    normalized["coverage_status"] = normalized.get("coverage_status") or defaults.get("coverage_status") or _coverage_from_mapping(
        mapping_status
    )
    normalized["execution_mode"] = normalized.get("execution_mode") or normalized.get("automation_mode") or normalized.get(
        "type"
    ) or suite_name
    normalized["request"] = normalized.get("request") or {}
    normalized["response"] = normalized.get("response") or {}
    normalized["evaluation"] = evaluation
    normalized["source_suite"] = suite_name
    return normalized


def _normalize_suite_cases(suite_name: str, suite_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [_normalize_case(case, suite_name) for case in list(suite_result.get("executed_cases") or [])]


def _merge_status(current: str, candidate: str) -> str:
    current_status = (current or "skipped").lower()
    candidate_status = (candidate or "skipped").lower()
    if STATUS_PRIORITY.get(candidate_status, 0) > STATUS_PRIORITY.get(current_status, 0):
        return candidate_status
    return current_status


def _merge_ranked(current: str, candidate: str, priorities: Dict[str, int]) -> str:
    current_value = (current or "").lower()
    candidate_value = (candidate or "").lower()
    if priorities.get(candidate_value, 0) > priorities.get(current_value, 0):
        return candidate_value
    return current_value or candidate_value


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


def _aggregate_pt5_cases(executed_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    aggregated: Dict[str, Dict[str, Any]] = {}
    for case in executed_cases:
        if case.get("case_group") != "pt5":
            continue

        test_case_id = str(case.get("test_case_id") or "")
        status = ((case.get("evaluation") or {}).get("status") or "skipped").lower()
        prefixed_assertions = [
            f"{case.get('source_suite')}: {message}" for message in list((case.get("evaluation") or {}).get("assertions") or [])
        ]
        evidence = {
            "suite": case.get("source_suite"),
            "type": case.get("type"),
            "execution_mode": case.get("execution_mode"),
            "status": status,
            "request": case.get("request"),
            "response": case.get("response"),
            "assertions": list((case.get("evaluation") or {}).get("assertions") or []),
        }

        if test_case_id not in aggregated:
            aggregated[test_case_id] = {
                "test_case_id": test_case_id,
                "description": case.get("description", ""),
                "case_group": "pt5",
                "validation_type": case.get("validation_type"),
                "dataspace_dimension": case.get("dataspace_dimension"),
                "mapping_status": case.get("mapping_status"),
                "coverage_status": case.get("coverage_status"),
                "expected_result": case.get("expected_result"),
                "evaluation": {
                    "status": status,
                    "assertions": prefixed_assertions,
                },
                "source_suites": [case.get("source_suite")],
                "evidences": [evidence],
            }
            continue

        current = aggregated[test_case_id]
        if not current.get("description"):
            current["description"] = case.get("description", "")
        if not current.get("expected_result"):
            current["expected_result"] = case.get("expected_result")

        current["mapping_status"] = _merge_ranked(
            current.get("mapping_status", ""),
            case.get("mapping_status", ""),
            MAPPING_PRIORITY,
        )
        current["coverage_status"] = _merge_ranked(
            current.get("coverage_status", ""),
            case.get("coverage_status", ""),
            COVERAGE_PRIORITY,
        )
        current["evaluation"]["status"] = _merge_status(current["evaluation"].get("status", "skipped"), status)
        current["evaluation"]["assertions"].extend(prefixed_assertions)
        if case.get("source_suite") not in current["source_suites"]:
            current["source_suites"].append(case.get("source_suite"))
        current["evidences"].append(evidence)

    return sorted(aggregated.values(), key=_case_sort_key)


def _build_findings(
    pt5_case_results: List[Dict[str, Any]],
    support_checks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for case in pt5_case_results:
        if ((case.get("evaluation") or {}).get("status") or "").lower() != "failed":
            continue
        findings.append(
            {
                "scope": "pt5_case",
                "test_case_id": case.get("test_case_id"),
                "status": "failed",
                "source_suites": list(case.get("source_suites") or []),
                "assertions": list((case.get("evaluation") or {}).get("assertions") or []),
            }
        )

    for case in support_checks:
        if ((case.get("evaluation") or {}).get("status") or "").lower() != "failed":
            continue
        findings.append(
            {
                "scope": "support_check",
                "test_case_id": case.get("test_case_id"),
                "status": "failed",
                "source_suites": [case.get("source_suite")],
                "assertions": list((case.get("evaluation") or {}).get("assertions") or []),
            }
        )

    return findings


def _collect_suite_evidence(suite_name: str, suite_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = []
    for evidence in list(suite_result.get("evidence_index") or []):
        normalized = dict(evidence)
        normalized.setdefault("suite", suite_name)
        evidence_index.append(normalized)
    return evidence_index


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


def _build_catalog_alignment(
    catalog: Dict[str, Any],
    pt5_case_results: List[Dict[str, Any]],
    support_checks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    declared_pt5_cases = list(catalog.get("pt5_cases") or [])
    declared_support_checks = list(catalog.get("support_checks") or [])
    declared_pt5_by_id = {case.get("id"): case for case in declared_pt5_cases}
    declared_support_by_id = {case.get("id"): case for case in declared_support_checks}

    executed_pt5_ids = {str(case.get("test_case_id") or "") for case in pt5_case_results}
    executed_support_ids = {str(case.get("test_case_id") or "") for case in support_checks}

    uncovered_pt5_cases = [
        case for case in declared_pt5_cases if case.get("id") not in executed_pt5_ids
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

    return {
        "source_file": catalog.get("source_file"),
        "source_documents": list(catalog.get("source_documents") or []),
        "summary": {
            "declared_pt5_cases": len(declared_pt5_cases),
            "executed_pt5_cases": len(pt5_case_results),
            "uncovered_pt5_cases": len(uncovered_pt5_cases),
            "declared_support_checks": len(declared_support_checks),
            "executed_support_checks": len(support_checks),
            "missing_support_checks": len(missing_support_checks),
            "executed_pt5_not_in_catalog": len(executed_pt5_not_in_catalog),
            "executed_support_not_in_catalog": len(executed_support_not_in_catalog),
        },
        "declared_pt5_cases": declared_pt5_cases,
        "declared_support_checks": declared_support_checks,
        "uncovered_pt5_cases": uncovered_pt5_cases,
        "missing_support_checks": missing_support_checks,
        "executed_pt5_not_in_catalog": executed_pt5_not_in_catalog,
        "executed_support_not_in_catalog": executed_support_not_in_catalog,
    }


def run_ontology_hub_component_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    normalized_base_url = (base_url or "").rstrip("/")

    api_result = run_ontology_hub_validation(normalized_base_url, experiment_dir=experiment_dir)
    ui_result = run_ontology_hub_ui_validation(normalized_base_url, experiment_dir=experiment_dir)
    catalog = _load_catalog()
    catalog_cases_by_id = {
        case.get("id"): case
        for case in list(catalog.get("pt5_cases") or []) + list(catalog.get("support_checks") or [])
    }

    normalized_api_cases = _attach_catalog_metadata(
        _normalize_suite_cases("api", api_result),
        catalog_cases_by_id,
    )
    normalized_ui_cases = _attach_catalog_metadata(
        _normalize_suite_cases("ui", ui_result),
        catalog_cases_by_id,
    )
    executed_cases = normalized_api_cases + normalized_ui_cases
    pt5_case_results = _aggregate_pt5_cases(executed_cases)
    pt5_case_results = _attach_catalog_metadata(pt5_case_results, catalog_cases_by_id)
    support_checks = sorted(
        _attach_catalog_metadata(
            [case for case in executed_cases if case.get("case_group") == "support"],
            catalog_cases_by_id,
        ),
        key=_case_sort_key,
    )
    pt5_summary = _summarize_cases(pt5_case_results)
    support_summary = _summarize_cases(support_checks)
    evidence_index = _collect_suite_evidence("api", api_result) + _collect_suite_evidence("ui", ui_result)
    findings = _build_findings(pt5_case_results, support_checks)
    catalog_alignment = _build_catalog_alignment(catalog, pt5_case_results, support_checks)

    summary = {
        "total": int(api_result.get("summary", {}).get("total", 0))
        + int(ui_result.get("summary", {}).get("total", 0)),
        "passed": int(api_result.get("summary", {}).get("passed", 0))
        + int(ui_result.get("summary", {}).get("passed", 0)),
        "failed": int(api_result.get("summary", {}).get("failed", 0))
        + int(ui_result.get("summary", {}).get("failed", 0)),
        "skipped": int(api_result.get("summary", {}).get("skipped", 0))
        + int(ui_result.get("summary", {}).get("skipped", 0)),
    }

    component_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "base_url": normalized_base_url,
        "timestamp": started_at,
        "status": _combine_status(api_result.get("status", "skipped"), ui_result.get("status", "skipped")),
        "summary": summary,
        "suites": {
            "api": api_result,
            "ui": ui_result,
        },
        "executed_cases": executed_cases,
        "pt5_case_results": pt5_case_results,
        "pt5_cases": pt5_case_results,
        "pt5_summary": pt5_summary,
        "support_checks": support_checks,
        "support_summary": support_summary,
        "evidence_index": evidence_index,
        "findings": findings,
        "catalog_alignment": catalog_alignment,
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ontology_hub_component_validation.json")
        pt5_cases_path = os.path.join(component_dir, "ontology_hub_pt5_case_results.json")
        support_checks_path = os.path.join(component_dir, "ontology_hub_support_checks.json")
        evidence_index_path = os.path.join(component_dir, "ontology_hub_evidence_index.json")
        findings_path = os.path.join(component_dir, "ontology_hub_findings.json")
        catalog_alignment_path = os.path.join(component_dir, "ontology_hub_catalog_alignment.json")

        _write_json(pt5_cases_path, {"pt5_case_results": pt5_case_results, "summary": pt5_summary})
        _write_json(support_checks_path, {"support_checks": support_checks, "summary": support_summary})
        _write_json(findings_path, {"findings": findings})
        _write_json(catalog_alignment_path, catalog_alignment)

        component_result["artifacts"] = {
            "report_json": report_path,
            "api_report_json": (api_result.get("artifacts") or {}).get("report_json"),
            "ui_report_json": (ui_result.get("artifacts") or {}).get("report_json"),
            "ui_test_results_dir": (ui_result.get("artifacts") or {}).get("test_results_dir"),
            "ui_html_report_dir": (ui_result.get("artifacts") or {}).get("html_report_dir"),
            "ui_blob_report_dir": (ui_result.get("artifacts") or {}).get("blob_report_dir"),
            "ui_json_report_file": (ui_result.get("artifacts") or {}).get("json_report_file"),
            "pt5_case_results_json": pt5_cases_path,
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
        _write_json(evidence_index_path, {"evidence_index": component_result["evidence_index"]})
        _write_json(report_path, component_result)

    return component_result
