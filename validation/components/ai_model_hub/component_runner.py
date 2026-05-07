import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

from validation.components.ai_model_hub.runner import run_ai_model_hub_validation
from validation.components.ai_model_hub.ui_runner import run_ai_model_hub_ui_validation


COMPONENT_KEY = "ai-model-hub"
CATALOG_PATH = Path(__file__).resolve().parent / "test_cases.yaml"
CONNECTOR_GOVERNANCE_ENV = "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE"
MODEL_BENCHMARKING_ENV = "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING"
MOBILITY_BENCHMARKING_ENV = "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING"

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
    support_checks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for case in pt5_case_results + functional_use_case_results + support_checks:
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
    support_checks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    declared_pt5_cases = list(catalog.get("pt5_cases") or [])
    declared_functional_use_cases = list(catalog.get("functional_use_cases") or [])
    declared_support_checks = list(catalog.get("support_checks") or [])
    declared_pt5_by_id = {case.get("id"): case for case in declared_pt5_cases}
    declared_functional_by_id = {case.get("id"): case for case in declared_functional_use_cases}
    declared_support_by_id = {case.get("id"): case for case in declared_support_checks}

    executed_pt5_ids = {str(case.get("test_case_id") or "") for case in pt5_case_results}
    executed_functional_ids = {
        str(case.get("test_case_id") or "")
        for case in functional_use_case_results
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
            "declared_support_checks": len(declared_support_checks),
            "executed_support_checks": len(support_checks),
            "missing_support_checks": len(missing_support_checks),
            "executed_pt5_not_in_catalog": len(executed_pt5_not_in_catalog),
            "executed_functional_not_in_catalog": len(executed_functional_not_in_catalog),
            "executed_support_not_in_catalog": len(executed_support_not_in_catalog),
        },
        "declared_pt5_cases": declared_pt5_cases,
        "declared_functional_use_cases": declared_functional_use_cases,
        "declared_support_checks": declared_support_checks,
        "uncovered_pt5_cases": uncovered_pt5_cases,
        "uncovered_functional_use_cases": uncovered_functional_use_cases,
        "missing_support_checks": missing_support_checks,
        "executed_pt5_not_in_catalog": executed_pt5_not_in_catalog,
        "executed_functional_not_in_catalog": executed_functional_not_in_catalog,
        "executed_support_not_in_catalog": executed_support_not_in_catalog,
    }


def _collect_suite_evidence(suite_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = []
    for evidence in list(suite_result.get("evidence_index") or []):
        normalized = dict(evidence)
        normalized.setdefault("suite", suite_result.get("suite") or "bootstrap")
        evidence_index.append(normalized)
    return evidence_index


def _connector_governance_enabled() -> bool:
    return (os.environ.get(CONNECTOR_GOVERNANCE_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def _model_benchmarking_enabled() -> bool:
    return (os.environ.get(MODEL_BENCHMARKING_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def _mobility_benchmarking_enabled() -> bool:
    return (os.environ.get(MOBILITY_BENCHMARKING_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def run_ai_model_hub_connector_governance_validation(experiment_dir: str | None = None) -> Dict[str, Any]:
    from validation.components.ai_model_hub.connector_governance_api import (
        build_inesdata_ai_model_hub_connector_governance_suite,
        default_model_url,
    )

    topology = os.environ.get("AI_MODEL_HUB_CONNECTOR_GOVERNANCE_TOPOLOGY") or os.environ.get("INESDATA_TOPOLOGY") or "local"
    suite, adapter = build_inesdata_ai_model_hub_connector_governance_suite(topology=topology)
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


def run_ai_model_hub_model_benchmarking_validation(experiment_dir: str | None = None) -> Dict[str, Any]:
    from validation.components.ai_model_hub.model_benchmarking_api import (
        run_ai_model_hub_model_benchmarking_validation as run_benchmarking_suite,
    )

    fixture_dir = os.environ.get("AI_MODEL_HUB_BENCHMARKING_FIXTURE_DIR") or None
    return run_benchmarking_suite(
        fixture_dir=fixture_dir,
        experiment_dir=experiment_dir,
    )


def run_ai_model_hub_mobility_benchmarking_validation(experiment_dir: str | None = None) -> Dict[str, Any]:
    from validation.components.ai_model_hub.mobility_benchmarking_api import (
        run_ai_model_hub_mobility_benchmarking_validation as run_mobility_suite,
    )

    fixture_dir = os.environ.get("AI_MODEL_HUB_MOBILITY_FIXTURE_DIR") or None
    return run_mobility_suite(
        fixture_dir=fixture_dir,
        experiment_dir=experiment_dir,
    )


def run_ai_model_hub_component_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    normalized_base_url = (base_url or "").rstrip("/")

    bootstrap_result = run_ai_model_hub_validation(normalized_base_url, experiment_dir=experiment_dir)
    ui_result = run_ai_model_hub_ui_validation(normalized_base_url, experiment_dir=experiment_dir)
    named_suite_results = [
        ("bootstrap", bootstrap_result),
        ("ui", ui_result),
    ]
    if _connector_governance_enabled():
        named_suite_results.append(
            (
                "connector_governance",
                run_ai_model_hub_connector_governance_validation(experiment_dir=experiment_dir),
            )
        )
    if _model_benchmarking_enabled():
        named_suite_results.append(
            (
                "model_benchmarking",
                run_ai_model_hub_model_benchmarking_validation(experiment_dir=experiment_dir),
            )
        )
    if _mobility_benchmarking_enabled():
        named_suite_results.append(
            (
                "mobility_benchmarking",
                run_ai_model_hub_mobility_benchmarking_validation(experiment_dir=experiment_dir),
            )
        )
    suite_results = [suite_result for _, suite_result in named_suite_results]
    catalog = _load_catalog()
    catalog_cases_by_id = {
        case.get("id"): case
        for case in list(catalog.get("pt5_cases") or [])
        + list(catalog.get("functional_use_cases") or [])
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
    pt5_summary = _summarize_cases(pt5_case_results)
    functional_use_case_summary = _summarize_cases(functional_use_case_results)
    support_summary = _summarize_cases(support_checks)
    findings = _build_findings(pt5_case_results, functional_use_case_results, support_checks)
    catalog_alignment = _build_catalog_alignment(
        catalog,
        pt5_case_results,
        functional_use_case_results,
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

    combined_status = "skipped"
    for suite_result in suite_results:
        combined_status = _combine_status(combined_status, suite_result.get("status", "skipped"))

    component_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "base_url": normalized_base_url,
        "timestamp": started_at,
        "status": combined_status,
        "summary": summary,
        "suites": suites,
        "executed_cases": executed_cases,
        "pt5_case_results": pt5_case_results,
        "pt5_cases": pt5_case_results,
        "pt5_summary": pt5_summary,
        "functional_use_case_results": functional_use_case_results,
        "functional_use_cases": functional_use_case_results,
        "functional_use_case_summary": functional_use_case_summary,
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
            "pt5_case_results_json": pt5_cases_path,
            "functional_use_case_results_json": functional_use_case_results_path,
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
