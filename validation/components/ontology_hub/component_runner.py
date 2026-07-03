import os
from datetime import datetime
from typing import Any, Dict, List

from validation.components.artifact_contract import attach_component_artifact_manifest
from validation.components.console_output import print_component_case_results, print_component_suite_header
from validation.components.execution_mode import component_api_only_enabled
from validation.components.fail_fast import component_fail_fast_enabled
from validation.components.ontology_hub.functional.component_runner import (
    run_ontology_hub_component_validation as run_ontology_hub_functional_component_validation,
)
from validation.components.ontology_hub.integration.component_runner import (
    run_ontology_hub_component_validation as run_ontology_hub_integration_component_validation,
)


COMPONENT_KEY = "ontology-hub"
PHASE_LABELS = {
    "functional": "Ontology Hub functional",
    "integration": "Ontology Hub API integration",
}
PHASE_CHANNELS = {
    "functional": "playwright",
    "integration": "api",
}
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


def _combine_status(statuses: List[str]) -> str:
    combined = "skipped"
    for status in statuses:
        normalized = (status or "skipped").lower()
        if STATUS_PRIORITY.get(normalized, 0) > STATUS_PRIORITY.get(combined, 0):
            combined = normalized
    return combined


def _summarize_cases(cases: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"total": len(cases), "passed": 0, "failed": 0, "skipped": 0}
    for case in cases:
        status = ((case.get("evaluation") or {}).get("status") or "skipped").lower()
        if status in summary:
            summary[status] += 1
    return summary


def _summary_from_phases(phases: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    summary = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    for phase_result in phases.values():
        phase_summary = phase_result.get("summary") or {}
        for key in summary:
            summary[key] += int(phase_summary.get(key, 0) or 0)
    return summary


def _phase_label(phase: str) -> str:
    return PHASE_LABELS.get(phase, f"Ontology Hub {phase}")


def _phase_failure_result(phase: str, exc: Exception) -> Dict[str, Any]:
    return {
        "component": COMPONENT_KEY,
        "suite": phase,
        "display_name": _phase_label(phase),
        "status": "failed",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "executed_cases": [],
        "pt5_case_results": [],
        "pt5_cases": [],
        "support_checks": [],
        "evidence_index": [],
        "findings": [
            {
                "scope": phase,
                "status": "failed",
                "assertions": [f"{type(exc).__name__}: {exc}"],
            }
        ],
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def _tag_phase(cases: List[Dict[str, Any]], phase: str) -> List[Dict[str, Any]]:
    tagged_cases: List[Dict[str, Any]] = []
    for case in cases:
        tagged = dict(case)
        tagged["source_phase"] = phase
        tagged.setdefault("source_suite", case.get("source_suite") or case.get("suite") or phase)
        tagged_cases.append(tagged)
    return tagged_cases


def _aggregate_pt5_cases(phases: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    aggregated: Dict[str, Dict[str, Any]] = {}
    for phase, phase_result in phases.items():
        for case in _tag_phase(
            list(phase_result.get("pt5_case_results") or phase_result.get("pt5_cases") or []),
            phase,
        ):
            case_id = str(case.get("test_case_id") or "")
            if not case_id:
                continue
            status = ((case.get("evaluation") or {}).get("status") or "skipped").lower()
            if case_id not in aggregated:
                aggregated[case_id] = case
                aggregated[case_id]["source_phases"] = [phase]
                continue

            current = aggregated[case_id]
            current_status = ((current.get("evaluation") or {}).get("status") or "skipped").lower()
            if STATUS_PRIORITY.get(status, 0) > STATUS_PRIORITY.get(current_status, 0):
                merged = case
                merged["source_phases"] = list(current.get("source_phases") or [])
                current = merged
                aggregated[case_id] = current
            if phase not in current.get("source_phases", []):
                current.setdefault("source_phases", []).append(phase)
    return sorted(aggregated.values(), key=lambda case: str(case.get("test_case_id") or ""))


def _collect_phase_artifacts(phases: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    artifacts: Dict[str, Any] = {"phase_artifacts": {}}
    for phase, phase_result in phases.items():
        phase_artifacts = dict(phase_result.get("artifacts") or {})
        artifacts["phase_artifacts"][phase] = phase_artifacts
        report_path = phase_artifacts.get("report_json")
        if report_path:
            artifacts[f"{phase}_report_json"] = report_path
    return artifacts


def run_ontology_hub_component_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    normalized_base_url = (base_url or "").rstrip("/")
    phases: Dict[str, Dict[str, Any]] = {}
    api_only = component_api_only_enabled(component=COMPONENT_KEY)

    phase_runners = [
        ("functional", run_ontology_hub_functional_component_validation),
        ("integration", run_ontology_hub_integration_component_validation),
    ]
    if api_only:
        phase_runners = [
            (phase, runner)
            for phase, runner in phase_runners
            if PHASE_CHANNELS.get(phase) == "api"
        ]
    for phase, runner in phase_runners:
        print_component_suite_header(_phase_label(phase), PHASE_CHANNELS.get(phase))
        try:
            phases[phase] = runner(normalized_base_url, experiment_dir=experiment_dir)
            phases[phase].setdefault("display_name", _phase_label(phase))
            phases[phase].setdefault("phase", phase)
            phases[phase].setdefault("execution_channel", PHASE_CHANNELS.get(phase))
            if PHASE_CHANNELS.get(phase) == "api":
                print_component_case_results(phases[phase].get("executed_cases") or [])
        except Exception as exc:  # pragma: no cover - defensive integration guard
            phases[phase] = _phase_failure_result(phase, exc)
            phases[phase].setdefault("execution_channel", PHASE_CHANNELS.get(phase))
        if component_fail_fast_enabled() and str(phases[phase].get("status") or "").lower() == "failed":
            break

    executed_cases = [
        case
        for phase, phase_result in phases.items()
        for case in _tag_phase(list(phase_result.get("executed_cases") or []), phase)
    ]
    pt5_case_results = _aggregate_pt5_cases(phases)
    support_checks = [
        case
        for phase, phase_result in phases.items()
        for case in _tag_phase(list(phase_result.get("support_checks") or []), phase)
    ]
    evidence_index = [
        {**evidence, "source_phase": phase}
        for phase, phase_result in phases.items()
        for evidence in list(phase_result.get("evidence_index") or [])
    ]
    findings = [
        {**finding, "source_phase": phase}
        for phase, phase_result in phases.items()
        for finding in list(phase_result.get("findings") or [])
    ]

    component_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "base_url": normalized_base_url,
        "timestamp": started_at,
        "status": _combine_status([phase_result.get("status", "skipped") for phase_result in phases.values()]),
        "summary": _summary_from_phases(phases),
        "validation_mode": "api" if api_only else "mixed",
        "phase_order": [phase for phase, _ in phase_runners],
        "phase_display_names": {phase: _phase_label(phase) for phase in phases},
        "phase_execution_channels": {
            phase: [PHASE_CHANNELS.get(phase, "unknown")]
            for phase in phases
        },
        "phases": phases,
        "suites": phases,
        "executed_cases": executed_cases,
        "oh_app_traceability": list((phases.get("functional") or {}).get("oh_app_traceability") or []),
        "pt5_case_results": pt5_case_results,
        "pt5_cases": pt5_case_results,
        "pt5_summary": _summarize_cases(pt5_case_results),
        "support_checks": support_checks,
        "support_summary": _summarize_cases(support_checks),
        "evidence_index": evidence_index,
        "findings": findings,
        "catalog_alignment": {
            "phases": {
                phase: phase_result.get("catalog_alignment")
                for phase, phase_result in phases.items()
                if phase_result.get("catalog_alignment")
            }
        },
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ontology_hub_component_validation.json")
        pt5_cases_path = os.path.join(component_dir, "ontology_hub_pt5_case_results.json")
        support_checks_path = os.path.join(component_dir, "ontology_hub_support_checks.json")
        evidence_index_path = os.path.join(component_dir, "ontology_hub_evidence_index.json")
        findings_path = os.path.join(component_dir, "ontology_hub_findings.json")
        catalog_alignment_path = os.path.join(component_dir, "ontology_hub_catalog_alignment.json")

        artifacts = _collect_phase_artifacts(phases)
        artifacts.update(
            {
                "report_json": report_path,
                "pt5_case_results_json": pt5_cases_path,
                "support_checks_json": support_checks_path,
                "evidence_index_json": evidence_index_path,
                "findings_json": findings_path,
                "catalog_alignment_json": catalog_alignment_path,
            }
        )
        component_result["artifacts"] = artifacts
        component_result["evidence_index"] = evidence_index + [
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
            {
                "scope": "component",
                "suite": "component",
                "artifact_name": "catalog_alignment_json",
                "path": catalog_alignment_path,
            },
        ]
        attach_component_artifact_manifest(component_result, component_dir)

        _write_json(pt5_cases_path, {"pt5_case_results": pt5_case_results, "summary": component_result["pt5_summary"]})
        _write_json(support_checks_path, {"support_checks": support_checks, "summary": component_result["support_summary"]})
        _write_json(findings_path, {"findings": findings})
        _write_json(catalog_alignment_path, component_result["catalog_alignment"])
        _write_json(evidence_index_path, {"evidence_index": component_result["evidence_index"]})
        _write_json(report_path, component_result)

    return component_result
