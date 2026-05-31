import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from validation.components.artifact_cleanup import cleanup_empty_experiment_artifact_dirs
from validation.components.fail_fast import playwright_max_failures_args


COMPONENT_KEY = "semantic-virtualization"
SUITE_NAME = "ui"
PLAYWRIGHT_CONFIG_RELATIVE = os.path.join("..", "components", "semantic_virtualization", "ui", "playwright.config.js")
PLAYWRIGHT_WORKDIR = Path(__file__).resolve().parents[2] / "ui"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPERIMENTS_DIR = PROJECT_ROOT / "experiments" / "_standalone"
PLAYWRIGHT_COMMAND = [os.path.join(".", "node_modules", ".bin", "playwright"), "test", "--config", PLAYWRIGHT_CONFIG_RELATIVE]
UI_VALIDATION_ENV = "SEMANTIC_VIRTUALIZATION_ENABLE_UI_VALIDATION"
MAPPING_EDITOR_ENV = "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI"


def _playwright_command() -> List[str]:
    return [*PLAYWRIGHT_COMMAND, *playwright_max_failures_args()]


UI_CASE_METADATA: Dict[str, Dict[str, Any]] = {
    "SV-UI-01": {
        "case_group": "support",
        "validation_type": "functional",
        "dataspace_dimension": "browser_reachability",
        "mapping_status": "supporting",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The Semantic Virtualization root is reachable from a browser.",
        "spec": "sv_ui_01_browser_reachability.spec.js",
    },
    "SV-UI-02": {
        "case_group": "support",
        "validation_type": "functional",
        "dataspace_dimension": "capabilities",
        "mapping_status": "supporting",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The Semantic Virtualization OpenAPI document is available as machine-readable JSON.",
        "spec": "sv_ui_01_browser_reachability.spec.js",
    },
    "SV-UI-03": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "semantic_query",
        "mapping_status": "phase_1",
        "automation_mode": "ui_api",
        "execution_mode": "ui_api",
        "coverage_status": "automated",
        "expected_result": "The query endpoint is reachable from Playwright.",
        "spec": "sv_ui_01_browser_reachability.spec.js",
    },
    "PT5-VS-07": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "mapping_editor",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor exposes a visual mapping representation.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
    "PT5-VS-08": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "mapping_editor",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor can launch a mapping execution flow.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
    "SV-UI-04": {
        "case_group": "support",
        "validation_type": "functional",
        "dataspace_dimension": "mapping_editor",
        "mapping_status": "supporting",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor exposes ontology import and exploration panels.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
    "SV-UI-05": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "mapping_authoring",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor supports a non-destructive mapping authoring path.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
    "SV-UI-06": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "mapping_materialisation",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor exposes export and materialisation checkpoints.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
    "SV-UI-07": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "mapping_export",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor manages namespaces and exports a mapping.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
    "SV-UI-08": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "source_and_ontology_import",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor imports ontology and data source fixtures.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
    "SV-UI-10": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "ontology_lens",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The mapping editor explores a non-empty mapping with ontology lens.",
        "spec": "sv_ui_02_mapping_editor.spec.js",
    },
}


def _ui_validation_enabled() -> bool:
    raw_value = os.environ.get(UI_VALIDATION_ENV)
    if raw_value is None:
        return True
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _build_artifact_paths(experiment_dir: str | None, *, create: bool = True) -> Dict[str, str]:
    if experiment_dir:
        experiment_path = Path(experiment_dir)
        if not experiment_path.is_absolute():
            experiment_path = PROJECT_ROOT / experiment_path
        base_dir = experiment_path / "components" / COMPONENT_KEY / "ui"
    else:
        base_dir = DEFAULT_EXPERIMENTS_DIR / "components" / COMPONENT_KEY / "ui"

    paths = {
        "base_dir": str(base_dir),
        "output_dir": str(base_dir / "test-results"),
        "test_results_dir": str(base_dir / "test-results"),
        "html_report_dir": str(base_dir / "playwright-report"),
        "blob_report_dir": str(base_dir / "blob-report"),
        "json_report_file": str(base_dir / "results.json"),
        "report_json": str(base_dir / "semantic_virtualization_ui_validation.json"),
    }
    if create:
        for path in paths.values():
            if path.endswith(".json"):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            else:
                os.makedirs(path, exist_ok=True)
    return paths


def _iter_specs(suites: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for suite in suites or []:
        for child_suite in suite.get("suites") or []:
            yield from _iter_specs([child_suite])
        for spec in suite.get("specs") or []:
            yield spec


def _spec_result_status(spec: Dict[str, Any]) -> str:
    tests = spec.get("tests") or []
    if not tests:
        return "skipped"
    results = tests[0].get("results") or []
    if not results:
        return "skipped"
    return str(results[-1].get("status") or "skipped").lower()


def _attachments_from_spec(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    tests = spec.get("tests") or []
    if not tests:
        return []
    results = tests[0].get("results") or []
    if not results:
        return []
    return [
        {
            "name": attachment.get("name", ""),
            "content_type": attachment.get("contentType", ""),
            "path": attachment.get("path", ""),
        }
        for attachment in results[-1].get("attachments") or []
    ]


def _build_case_result(
    *,
    case_id: str,
    title: str,
    metadata: Dict[str, Any],
    status: str,
    base_url: str,
    attachments: List[Dict[str, str]],
) -> Dict[str, Any]:
    description = title.split(":", 1)[1].strip() if ":" in title else title
    return {
        "test_case_id": case_id,
        "description": description,
        "type": "ui",
        "case_group": metadata["case_group"],
        "validation_type": metadata["validation_type"],
        "dataspace_dimension": metadata["dataspace_dimension"],
        "mapping_status": metadata["mapping_status"],
        "automation_mode": metadata["automation_mode"],
        "execution_mode": metadata["execution_mode"],
        "coverage_status": metadata["coverage_status"],
        "source_suite": SUITE_NAME,
        "request": {
            "runner": "playwright",
            "spec": metadata["spec"],
            "base_url": base_url,
        },
        "response": {
            "status": status,
            "attachments": attachments,
        },
        "evaluation": {
            "status": status,
            "assertions": [],
        },
        "expected_result": metadata["expected_result"],
    }


def _extract_executed_cases(report_payload: Dict[str, Any], base_url: str) -> List[Dict[str, Any]]:
    executed_cases: List[Dict[str, Any]] = []
    for spec in _iter_specs(report_payload.get("suites") or []):
        title = str(spec.get("title") or "")
        case_id = title.split(":", 1)[0].strip()
        metadata = UI_CASE_METADATA.get(case_id)
        if not metadata:
            continue
        executed_cases.append(
            _build_case_result(
                case_id=case_id,
                title=title,
                metadata=metadata,
                status=_spec_result_status(spec),
                base_url=base_url,
                attachments=_attachments_from_spec(spec),
            )
        )
    return executed_cases


def _summary_from_report(report_payload: Dict[str, Any]) -> Dict[str, int]:
    stats = report_payload.get("stats") or {}
    return {
        "total": int(stats.get("expected", 0))
        + int(stats.get("unexpected", 0))
        + int(stats.get("flaky", 0))
        + int(stats.get("skipped", 0)),
        "passed": int(stats.get("expected", 0)),
        "failed": int(stats.get("unexpected", 0)) + int(stats.get("flaky", 0)),
        "skipped": int(stats.get("skipped", 0)),
    }


def _empty_summary() -> Dict[str, int]:
    return {"total": 0, "passed": 0, "failed": 0, "skipped": 0}


def _summarize_cases(cases: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"total": len(cases), "passed": 0, "failed": 0, "skipped": 0}
    for case in cases:
        status = ((case.get("evaluation") or {}).get("status") or "").lower()
        if status in summary:
            summary[status] += 1
    return summary


def _evidence_index(executed_cases: List[Dict[str, Any]], artifact_paths: Dict[str, str]) -> List[Dict[str, Any]]:
    evidence = [
        {"scope": "suite", "suite": SUITE_NAME, "artifact_name": "report_json", "path": artifact_paths["report_json"]},
        {
            "scope": "suite",
            "suite": SUITE_NAME,
            "artifact_name": "json_report_file",
            "path": artifact_paths["json_report_file"],
        },
        {
            "scope": "suite",
            "suite": SUITE_NAME,
            "artifact_name": "html_report_dir",
            "path": artifact_paths["html_report_dir"],
        },
    ]
    for case in executed_cases:
        for attachment in (case.get("response") or {}).get("attachments") or []:
            evidence.append(
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": case.get("test_case_id"),
                    "case_group": case.get("case_group"),
                    "artifact_name": attachment.get("name", ""),
                    "content_type": attachment.get("content_type", ""),
                    "path": attachment.get("path", ""),
                }
            )
    return evidence


def _disabled_suite_result(base_url: str, experiment_dir: str | None) -> Dict[str, Any]:
    artifact_paths = _build_artifact_paths(experiment_dir)
    suite_result = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "status": "skipped",
        "reason": "ui_validation_disabled",
        "timestamp": datetime.now().isoformat(),
        "base_url": (base_url or "").rstrip("/"),
        "summary": _empty_summary(),
        "executed_cases": [],
        "pt5_case_results": [],
        "pt5_cases": [],
        "support_checks": [],
        "pt5_summary": _empty_summary(),
        "support_summary": _empty_summary(),
        "evidence_index": [],
        "playwright_config": PLAYWRIGHT_CONFIG_RELATIVE,
        "specs": [metadata["spec"] for metadata in UI_CASE_METADATA.values()],
        "exit_code": None,
        "error": None,
        "artifacts": artifact_paths,
    }
    with open(artifact_paths["report_json"], "w", encoding="utf-8") as handle:
        json.dump(suite_result, handle, indent=2, ensure_ascii=False)
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=PROJECT_ROOT / "experiments")
    return suite_result


def run_semantic_virtualization_ui_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    normalized_base_url = (base_url or "").rstrip("/")
    if not _ui_validation_enabled():
        return _disabled_suite_result(normalized_base_url, experiment_dir)

    started_at = datetime.now().isoformat()
    artifact_paths = _build_artifact_paths(experiment_dir)
    env = {
        **os.environ,
        "SEMANTIC_VIRTUALIZATION_BASE_URL": normalized_base_url,
        MAPPING_EDITOR_ENV: os.environ.get(MAPPING_EDITOR_ENV, "1"),
        "PLAYWRIGHT_OUTPUT_DIR": artifact_paths["output_dir"],
        "PLAYWRIGHT_HTML_REPORT_DIR": artifact_paths["html_report_dir"],
        "PLAYWRIGHT_BLOB_REPORT_DIR": artifact_paths["blob_report_dir"],
        "PLAYWRIGHT_JSON_REPORT_FILE": artifact_paths["json_report_file"],
        "PIONERA_PLAYWRIGHT_SUITE_NAME": "Virtualizador functional",
        "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
        "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
    }

    error = None
    exit_code = None
    status = "skipped"
    try:
        completed = subprocess.run(_playwright_command(), cwd=str(PLAYWRIGHT_WORKDIR), env=env)
        exit_code = completed.returncode
        status = "passed" if completed.returncode == 0 else "failed"
    except OSError as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        status = "failed"

    if os.path.exists(artifact_paths["json_report_file"]):
        with open(artifact_paths["json_report_file"], "r", encoding="utf-8") as handle:
            report_payload = json.load(handle)
        summary = _summary_from_report(report_payload)
        executed_cases = _extract_executed_cases(report_payload, normalized_base_url)
        if summary["failed"] > 0:
            status = "failed"
        elif summary["passed"] > 0:
            status = "passed"
        elif summary["skipped"] == summary["total"] and summary["total"] > 0:
            status = "skipped"
    else:
        total_cases = len(UI_CASE_METADATA)
        summary = {
            "total": total_cases,
            "passed": 0,
            "failed": total_cases if status == "failed" else 0,
            "skipped": total_cases if status == "skipped" else 0,
        }
        executed_cases = [
            _build_case_result(
                case_id=case_id,
                title=case_id,
                metadata=metadata,
                status=status,
                base_url=normalized_base_url,
                attachments=[],
            )
            for case_id, metadata in UI_CASE_METADATA.items()
        ]

    pt5_cases = [case for case in executed_cases if case.get("case_group") == "pt5"]
    support_checks = [case for case in executed_cases if case.get("case_group") == "support"]
    evidence_index = _evidence_index(executed_cases, artifact_paths)
    suite_result = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "status": status,
        "timestamp": started_at,
        "base_url": normalized_base_url,
        "summary": summary,
        "executed_cases": executed_cases,
        "pt5_case_results": pt5_cases,
        "pt5_cases": pt5_cases,
        "support_checks": support_checks,
        "pt5_summary": _summarize_cases(pt5_cases),
        "support_summary": _summarize_cases(support_checks),
        "evidence_index": evidence_index,
        "playwright_config": PLAYWRIGHT_CONFIG_RELATIVE,
        "specs": [metadata["spec"] for metadata in UI_CASE_METADATA.values()],
        "exit_code": exit_code,
        "error": error,
        "artifacts": artifact_paths,
    }
    with open(artifact_paths["report_json"], "w", encoding="utf-8") as handle:
        json.dump(suite_result, handle, indent=2, ensure_ascii=False)
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=PROJECT_ROOT / "experiments")
    return suite_result
