"""Common artifact contract for component validation reports."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List


ARTIFACT_MANIFEST_FILENAME = "artifact_manifest.json"
ARTIFACT_CONTRACT_SCHEMA = "pionera.validation.component-artifacts.v1"
MINIMAL_COMPONENT_ARTIFACTS = (
    "report_json",
    "artifact_manifest_json",
    "evidence_index_json",
    "findings_json",
)


def _safe_len(value: Any) -> int:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 0


def _summary(payload: Dict[str, Any] | None) -> Dict[str, int]:
    raw_summary = (payload or {}).get("summary") or {}
    return {
        "total": int(raw_summary.get("total", 0) or 0),
        "passed": int(raw_summary.get("passed", 0) or 0),
        "failed": int(raw_summary.get("failed", 0) or 0),
        "skipped": int(raw_summary.get("skipped", 0) or 0),
    }


def _artifact_paths(artifacts: Dict[str, Any] | None) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for name, path in sorted((artifacts or {}).items()):
        if isinstance(path, str) and path:
            normalized[name] = path
    return normalized


def _suite_record(name: str, suite_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": name,
        "suite": suite_result.get("suite") or name,
        "display_name": suite_result.get("display_name") or suite_result.get("suite_label") or name,
        "status": suite_result.get("status") or "skipped",
        "summary": _summary(suite_result),
        "artifact_keys": sorted(_artifact_paths(suite_result.get("artifacts")).keys()),
        "evidence_count": _safe_len(suite_result.get("evidence_index")),
        "executed_cases_count": _safe_len(suite_result.get("executed_cases") or suite_result.get("test_cases")),
        "pt5_cases_count": _safe_len(suite_result.get("pt5_case_results") or suite_result.get("pt5_cases")),
        "support_checks_count": _safe_len(suite_result.get("support_checks")),
        "findings_count": _safe_len(suite_result.get("findings")),
    }


def _phase_record(name: str, phase_result: Dict[str, Any]) -> Dict[str, Any]:
    suite_records: List[Dict[str, Any]] = []
    suites = phase_result.get("suites") or {}
    if isinstance(suites, dict):
        suite_records = [
            _suite_record(suite_name, suite_result)
            for suite_name, suite_result in sorted(suites.items())
            if isinstance(suite_result, dict)
        ]
    return {
        "name": name,
        "display_name": phase_result.get("display_name") or phase_result.get("suite_label") or name,
        "status": phase_result.get("status") or "skipped",
        "summary": _summary(phase_result),
        "suites": suite_records,
    }


def _phase_records(component_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    phases = component_result.get("phases") or {}
    if not isinstance(phases, dict):
        return []

    phase_order: Iterable[str] = component_result.get("phase_order") or phases.keys()
    records: List[Dict[str, Any]] = []
    seen = set()
    for phase_name in phase_order:
        if phase_name in seen:
            continue
        phase_result = phases.get(phase_name)
        if isinstance(phase_result, dict):
            records.append(_phase_record(str(phase_name), phase_result))
            seen.add(phase_name)
    for phase_name, phase_result in sorted(phases.items()):
        if phase_name not in seen and isinstance(phase_result, dict):
            records.append(_phase_record(str(phase_name), phase_result))
    return records


def build_component_artifact_manifest(component_result: Dict[str, Any]) -> Dict[str, Any]:
    artifacts = _artifact_paths(component_result.get("artifacts"))
    missing_minimal_artifacts = [
        artifact_name for artifact_name in MINIMAL_COMPONENT_ARTIFACTS if artifact_name not in artifacts
    ]
    return {
        "schema": ARTIFACT_CONTRACT_SCHEMA,
        "generated_at": datetime.now().isoformat(),
        "component": component_result.get("component"),
        "status": component_result.get("status") or "skipped",
        "summary": _summary(component_result),
        "phase_order": list(component_result.get("phase_order") or []),
        "phases": _phase_records(component_result),
        "artifacts": artifacts,
        "minimal_artifacts": list(MINIMAL_COMPONENT_ARTIFACTS),
        "missing_minimal_artifacts": missing_minimal_artifacts,
        "evidence_count": _safe_len(component_result.get("evidence_index")),
        "findings_count": _safe_len(component_result.get("findings")),
    }


def attach_component_artifact_manifest(
    component_result: Dict[str, Any],
    component_dir: str,
) -> str:
    manifest_path = os.path.join(component_dir, ARTIFACT_MANIFEST_FILENAME)
    component_result.setdefault("artifacts", {})["artifact_manifest_json"] = manifest_path
    evidence_entry = {
        "scope": "component",
        "suite": "component",
        "artifact_name": "artifact_manifest_json",
        "path": manifest_path,
    }
    evidence_index = component_result.setdefault("evidence_index", [])
    if not any(
        item.get("artifact_name") == "artifact_manifest_json" and item.get("path") == manifest_path
        for item in evidence_index
        if isinstance(item, dict)
    ):
        evidence_index.append(evidence_entry)

    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(build_component_artifact_manifest(component_result), handle, indent=2, ensure_ascii=False)
    return manifest_path
