import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from validation.components.artifact_cleanup import cleanup_empty_experiment_artifact_dirs
from validation.components.fail_fast import playwright_max_failures_args
from validation.components.ontology_hub.functional.runtime_preparation import (
    prepare_ontology_hub_for_functional,
)
from validation.components.ontology_hub.functional.pt5_traceability import (
    build_functional_catalog_alignment,
    build_oh_app_traceability,
    build_pt5_case_results_from_oh_app,
    summarize_pt5_case_results,
)
from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime

COMPONENT_KEY = "ontology-hub"
PLAYWRIGHT_CONFIG_RELATIVE = os.path.join("..", "components", "ontology_hub", "functional", "playwright.config.js")
PLAYWRIGHT_WORKDIR = Path(__file__).resolve().parents[3] / "ui"
COMPONENT_FUNCTIONAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EXPERIMENTS_DIR = Path(__file__).resolve().parents[4] / "experiments" / "_standalone"
PLAYWRIGHT_COMMAND_PREFIX = [
    os.path.join(".", "node_modules", ".bin", "playwright"),
    "test",
    "--config",
    PLAYWRIGHT_CONFIG_RELATIVE,
]


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _build_artifact_paths(experiment_dir: str | None, *, create: bool = True) -> Dict[str, str]:
    if experiment_dir:
        experiment_path = Path(experiment_dir)
        if not experiment_path.is_absolute():
            experiment_path = PROJECT_ROOT / experiment_path
        base_dir = experiment_path / "components" / COMPONENT_KEY / "functional"
    else:
        base_dir = DEFAULT_EXPERIMENTS_DIR / "components" / COMPONENT_KEY / "functional"

    paths = {
        "base_dir": str(base_dir),
        "output_dir": str(base_dir / "test-results"),
        "html_report_dir": str(base_dir / "playwright-report"),
        "blob_report_dir": str(base_dir / "blob-report"),
        "json_report_file": str(base_dir / "results.json"),
        "report_json": str(base_dir / "ontology_hub_functional_validation.json"),
        "resolved_runtime_json": str(base_dir / "resolved_runtime.json"),
    }
    if create:
        for path in paths.values():
            if path.endswith('.json'):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            else:
                os.makedirs(path, exist_ok=True)
    return paths


def _build_playwright_command(worker_count: int) -> List[str]:
    normalized_workers = worker_count if worker_count > 0 else 1
    grep = (
        os.environ.get("ONTOLOGY_HUB_FUNCTIONAL_GREP")
        or os.environ.get("PIONERA_ONTOLOGY_HUB_FUNCTIONAL_GREP")
        or ""
    ).strip()
    grep_args = ["--grep", grep] if grep else []
    return [
        *PLAYWRIGHT_COMMAND_PREFIX,
        f"--workers={normalized_workers}",
        *grep_args,
        *playwright_max_failures_args(),
    ]


def _functional_run_id(artifact_paths: Dict[str, str]) -> str:
    try:
        experiment_name = Path(artifact_paths["base_dir"]).parents[2].name
    except IndexError:
        experiment_name = Path(artifact_paths["base_dir"]).name
    normalized = re.sub(r"[^A-Za-z0-9]", "-", experiment_name).lower()
    if not re.search(r"[a-z0-9]", normalized):
        return "standalone"
    return normalized[:48]


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
    return (results[-1].get("status") or "skipped").lower()


def _attachments_from_spec(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    tests = spec.get("tests") or []
    if not tests:
        return []
    results = tests[0].get("results") or []
    if not results:
        return []
    attachments = results[-1].get("attachments") or []
    return [
        {
            "name": attachment.get("name", ""),
            "content_type": attachment.get("contentType", ""),
            "path": attachment.get("path", ""),
        }
        for attachment in attachments
    ]


def _build_case_result(*, case_id: str, title: str, status: str, base_url: str, spec_file: str, attachments: List[Dict[str, str]]) -> Dict[str, Any]:
    description = title.split(":", 1)[1].strip() if ":" in title else title
    return {
        "test_case_id": case_id,
        "description": description,
        "type": "ui",
        "case_group": "oh_app",
        "validation_type": "functional",
        "dataspace_dimension": "functional",
        "mapping_status": "mapped",
        "automation_mode": "ui_functional",
        "execution_mode": "ui_functional",
        "coverage_status": "automated",
        "request": {
            "runner": "playwright",
            "spec": spec_file,
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
        "expected_result": description,
    }


def _extract_executed_cases(report_payload: Dict[str, Any], base_url: str) -> List[Dict[str, Any]]:
    executed_cases: List[Dict[str, Any]] = []
    for spec in _iter_specs(report_payload.get("suites") or []):
        title = spec.get("title") or ""
        case_id = title.split(":", 1)[0].strip()
        if not case_id.startswith("OH-APP-"):
            continue
        spec_file = spec.get("file") or spec.get("location", {}).get("file") or ""
        executed_cases.append(
            _build_case_result(
                case_id=case_id,
                title=title,
                status=_spec_result_status(spec),
                base_url=base_url,
                spec_file=os.path.basename(spec_file),
                attachments=_attachments_from_spec(spec),
            )
        )
    return executed_cases


def _build_evidence_index(executed_cases: List[Dict[str, Any]], artifact_paths: Dict[str, str]) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = [
        {"scope": "suite", "suite": "functional", "artifact_name": "report_json", "path": artifact_paths["report_json"]},
        {"scope": "suite", "suite": "functional", "artifact_name": "json_report_file", "path": artifact_paths["json_report_file"]},
        {"scope": "suite", "suite": "functional", "artifact_name": "html_report_dir", "path": artifact_paths["html_report_dir"]},
        {"scope": "suite", "suite": "functional", "artifact_name": "blob_report_dir", "path": artifact_paths["blob_report_dir"]},
        {"scope": "suite", "suite": "functional", "artifact_name": "test_results_dir", "path": artifact_paths["output_dir"]},
        {"scope": "suite", "suite": "functional", "artifact_name": "resolved_runtime_json", "path": artifact_paths["resolved_runtime_json"]},
    ]
    for case in executed_cases:
        for attachment in (case.get("response") or {}).get("attachments") or []:
            evidence_index.append(
                {
                    "scope": "case",
                    "suite": "functional",
                    "test_case_id": case.get("test_case_id"),
                    "artifact_name": attachment.get("name", ""),
                    "content_type": attachment.get("content_type", ""),
                    "path": attachment.get("path", ""),
                }
            )
    return evidence_index


def _prepare_functional_runtime(runtime: Dict[str, Any]) -> tuple[bool, Dict[str, str] | None]:
    try:
        prepared = bool(prepare_ontology_hub_for_functional(runtime))
    except Exception as exc:  # pragma: no cover - defensive preparation guard
        return False, {"type": type(exc).__name__, "message": str(exc)}

    if not prepared:
        return False, {
            "type": "RuntimePreparationError",
            "message": "Ontology Hub functional preparation did not complete successfully.",
        }
    return True, None


def run_ontology_hub_functional_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    runtime = resolve_ontology_hub_runtime(base_url=base_url)
    normalized_base_url = runtime["baseUrl"]
    artifact_paths = _build_artifact_paths(experiment_dir)
    _write_json(artifact_paths["resolved_runtime_json"], runtime)

    prepared, preparation_error = _prepare_functional_runtime(runtime)
    if not prepared:
        suite_result: Dict[str, Any] = {
            "component": COMPONENT_KEY,
            "suite": "functional",
            "status": "failed",
            "timestamp": started_at,
            "base_url": normalized_base_url,
            "runtime": runtime,
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "executed_cases": [],
            "oh_app_traceability": [],
            "pt5_case_results": [],
            "pt5_cases": [],
            "support_checks": [],
            "pt5_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "support_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
            "catalog_alignment": build_functional_catalog_alignment(
                executed_cases=[],
                pt5_case_results=[],
            ),
            "evidence_index": _build_evidence_index([], artifact_paths),
            "playwright_config": PLAYWRIGHT_CONFIG_RELATIVE,
            "playwright_command": _build_playwright_command(1),
            "exit_code": None,
            "reason": "functional_preparation_failed",
            "error": preparation_error,
            "artifacts": {
                "report_json": artifact_paths["report_json"],
                "resolved_runtime_json": artifact_paths["resolved_runtime_json"],
                "test_results_dir": artifact_paths["output_dir"],
                "html_report_dir": artifact_paths["html_report_dir"],
                "blob_report_dir": artifact_paths["blob_report_dir"],
                "json_report_file": artifact_paths["json_report_file"],
            },
        }
        _write_json(artifact_paths["report_json"], suite_result)
        cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=PROJECT_ROOT / "experiments")
        return suite_result

    env = {
        **os.environ,
        "ONTOLOGY_HUB_BASE_URL": normalized_base_url,
        "ONTOLOGY_HUB_RUNTIME_FILE": artifact_paths["resolved_runtime_json"],
        "ONTOLOGY_HUB_FUNCTIONAL_RUN_ID": _functional_run_id(artifact_paths),
        "ONTOLOGY_HUB_COMPONENTS_NAMESPACE": str(runtime.get("componentsNamespace") or "components"),
        "ONTOLOGY_HUB_UI_EXPECT_TIMEOUT_MS": str(runtime.get("uiExpectTimeoutMs") or 15000),
        "ONTOLOGY_HUB_UI_ACTION_TIMEOUT_MS": str(runtime.get("uiActionTimeoutMs") or 15000),
        "ONTOLOGY_HUB_UI_NAVIGATION_TIMEOUT_MS": str(runtime.get("uiNavigationTimeoutMs") or 15000),
        "ONTOLOGY_HUB_UI_READY_TIMEOUT_MS": str(runtime.get("uiReadyTimeoutMs") or 15000),
        "ONTOLOGY_HUB_UI_WORKERS": "1",
        "PLAYWRIGHT_OUTPUT_DIR": artifact_paths["output_dir"],
        "PLAYWRIGHT_HTML_REPORT_DIR": artifact_paths["html_report_dir"],
        "PLAYWRIGHT_BLOB_REPORT_DIR": artifact_paths["blob_report_dir"],
        "PLAYWRIGHT_JSON_REPORT_FILE": artifact_paths["json_report_file"],
        "PIONERA_PLAYWRIGHT_SUITE_NAME": "Ontology Hub functional",
        "NODE_TLS_REJECT_UNAUTHORIZED": "0",
    }

    error = None
    exit_code = None
    status = "skipped"
    reason = None
    try:
        result = subprocess.run(_build_playwright_command(1), cwd=str(PLAYWRIGHT_WORKDIR), env=env)
        exit_code = result.returncode
        status = "passed" if result.returncode == 0 else "failed"
    except OSError as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        status = "failed"
        reason = "playwright_runtime_unavailable"

    if os.path.exists(artifact_paths["json_report_file"]):
        with open(artifact_paths["json_report_file"], "r", encoding="utf-8") as handle:
            report_payload = json.load(handle)
        stats = report_payload.get("stats") or {}
        summary = {
            "total": int(stats.get("expected", 0)) + int(stats.get("unexpected", 0)) + int(stats.get("flaky", 0)) + int(stats.get("skipped", 0)),
            "passed": int(stats.get("expected", 0)),
            "failed": int(stats.get("unexpected", 0)) + int(stats.get("flaky", 0)),
            "skipped": int(stats.get("skipped", 0)),
        }
        executed_cases = _extract_executed_cases(report_payload, normalized_base_url)
        if summary["failed"] > 0:
            status = "failed"
        elif summary["passed"] > 0:
            status = "passed"
        elif summary["skipped"] == summary["total"] and summary["total"] > 0:
            status = "skipped"
    else:
        executed_cases = []
        summary = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
        if error is None:
            reason = "no_playwright_results_generated"

    evidence_index = _build_evidence_index(executed_cases, artifact_paths)
    pt5_case_results = build_pt5_case_results_from_oh_app(executed_cases) if executed_cases else []
    pt5_summary = summarize_pt5_case_results(pt5_case_results)
    oh_app_traceability = build_oh_app_traceability(executed_cases)
    catalog_alignment = build_functional_catalog_alignment(
        executed_cases=executed_cases,
        pt5_case_results=pt5_case_results,
    )
    suite_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "functional",
        "status": status,
        "timestamp": started_at,
        "base_url": normalized_base_url,
        "runtime": runtime,
        "summary": summary,
        "executed_cases": executed_cases,
        "oh_app_traceability": oh_app_traceability,
        "pt5_case_results": pt5_case_results,
        "pt5_cases": pt5_case_results,
        "support_checks": [],
        "pt5_summary": pt5_summary,
        "support_summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "catalog_alignment": catalog_alignment,
        "evidence_index": evidence_index,
        "playwright_config": PLAYWRIGHT_CONFIG_RELATIVE,
        "playwright_command": _build_playwright_command(1),
        "exit_code": exit_code,
        "reason": reason,
        "error": error,
        "artifacts": {
            "report_json": artifact_paths["report_json"],
            "resolved_runtime_json": artifact_paths["resolved_runtime_json"],
            "test_results_dir": artifact_paths["output_dir"],
            "html_report_dir": artifact_paths["html_report_dir"],
            "blob_report_dir": artifact_paths["blob_report_dir"],
            "json_report_file": artifact_paths["json_report_file"],
        },
    }
    _write_json(artifact_paths["report_json"], suite_result)
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=PROJECT_ROOT / "experiments")
    return suite_result
