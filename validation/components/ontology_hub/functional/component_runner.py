import os
from datetime import datetime
from typing import Any, Dict

from validation.components.ontology_hub.functional.ui_runner import run_ontology_hub_functional_validation

COMPONENT_KEY = "ontology-hub"


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


def run_ontology_hub_component_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    normalized_base_url = (base_url or "").rstrip("/")
    functional_result = run_ontology_hub_functional_validation(normalized_base_url, experiment_dir=experiment_dir)
    pt5_case_results = list(
        functional_result.get("pt5_case_results")
        or functional_result.get("pt5_cases")
        or functional_result.get("executed_cases")
        or []
    )
    pt5_summary = dict(functional_result.get("pt5_summary") or {})
    if not pt5_summary:
        pt5_summary = {
            "total": len(pt5_case_results),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
        }
        for case in pt5_case_results:
            status = ((case.get("evaluation") or {}).get("status") or "skipped").lower()
            if status in pt5_summary:
                pt5_summary[status] += 1

    catalog_alignment = dict(functional_result.get("catalog_alignment") or {})
    if not catalog_alignment:
        catalog_alignment = {
            "source_file": "docs/11_ontology_hub_validation.md",
            "summary": {
                "declared_pt5_cases": len(pt5_case_results),
                "executed_pt5_cases": len(pt5_case_results),
                "uncovered_pt5_cases": 0,
                "declared_support_checks": 0,
                "executed_support_checks": 0,
                "missing_support_checks": 0,
                "executed_pt5_not_in_catalog": 0,
                "executed_support_not_in_catalog": 0,
            },
        }

    component_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "base_url": normalized_base_url,
        "timestamp": started_at,
        "status": functional_result.get("status", "skipped"),
        "reason": functional_result.get("reason"),
        "error": functional_result.get("error"),
        "summary": dict(functional_result.get("summary") or {}),
        "suites": {
            "functional": functional_result,
        },
        "executed_cases": list(functional_result.get("executed_cases") or []),
        "oh_app_traceability": list(functional_result.get("oh_app_traceability") or []),
        "pt5_case_results": pt5_case_results,
        "pt5_cases": pt5_case_results,
        "pt5_summary": pt5_summary,
        "support_checks": [],
        "support_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "evidence_index": list(functional_result.get("evidence_index") or []),
        "findings": [],
        "catalog_alignment": catalog_alignment,
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ontology_hub_functional_component_validation.json")
        pt5_cases_path = os.path.join(component_dir, "ontology_hub_functional_pt5_case_results.json")
        support_checks_path = os.path.join(component_dir, "ontology_hub_functional_support_checks.json")
        evidence_index_path = os.path.join(component_dir, "ontology_hub_functional_evidence_index.json")
        findings_path = os.path.join(component_dir, "ontology_hub_functional_findings.json")
        catalog_alignment_path = os.path.join(component_dir, "ontology_hub_functional_catalog_alignment.json")
        oh_app_traceability_path = os.path.join(component_dir, "ontology_hub_functional_oh_app_pt5_traceability.json")

        _write_json(pt5_cases_path, {"pt5_case_results": component_result["pt5_case_results"], "summary": component_result["pt5_summary"]})
        _write_json(support_checks_path, {"support_checks": [], "summary": component_result["support_summary"]})
        _write_json(findings_path, {"findings": []})
        _write_json(catalog_alignment_path, component_result["catalog_alignment"])
        _write_json(
            oh_app_traceability_path,
            {
                "oh_app_traceability": component_result["oh_app_traceability"],
                "pt5_case_results": component_result["pt5_case_results"],
                "pt5_summary": component_result["pt5_summary"],
            },
        )

        component_result["artifacts"] = {
            "report_json": report_path,
            "functional_report_json": (functional_result.get("artifacts") or {}).get("report_json"),
            "ui_test_results_dir": (functional_result.get("artifacts") or {}).get("test_results_dir"),
            "ui_html_report_dir": (functional_result.get("artifacts") or {}).get("html_report_dir"),
            "ui_blob_report_dir": (functional_result.get("artifacts") or {}).get("blob_report_dir"),
            "ui_json_report_file": (functional_result.get("artifacts") or {}).get("json_report_file"),
            "pt5_case_results_json": pt5_cases_path,
            "support_checks_json": support_checks_path,
            "evidence_index_json": evidence_index_path,
            "findings_json": findings_path,
            "catalog_alignment_json": catalog_alignment_path,
            "oh_app_pt5_traceability_json": oh_app_traceability_path,
        }
        component_result["evidence_index"] = component_result["evidence_index"] + [
            {"scope": "component", "suite": "component", "artifact_name": "report_json", "path": report_path},
            {"scope": "component", "suite": "component", "artifact_name": "pt5_case_results_json", "path": pt5_cases_path},
            {"scope": "component", "suite": "component", "artifact_name": "support_checks_json", "path": support_checks_path},
            {"scope": "component", "suite": "component", "artifact_name": "evidence_index_json", "path": evidence_index_path},
            {"scope": "component", "suite": "component", "artifact_name": "findings_json", "path": findings_path},
            {"scope": "component", "suite": "component", "artifact_name": "catalog_alignment_json", "path": catalog_alignment_path},
            {"scope": "component", "suite": "component", "artifact_name": "oh_app_pt5_traceability_json", "path": oh_app_traceability_path},
        ]
        _write_json(evidence_index_path, {"evidence_index": component_result["evidence_index"]})
        _write_json(report_path, component_result)

    return component_result
