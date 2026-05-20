import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from validation.components.artifact_cleanup import cleanup_empty_experiment_artifact_dirs

COMPONENT_KEY = "ai-model-hub"
PLAYWRIGHT_CONFIG_RELATIVE = os.path.join("..", "components", "ai_model_hub", "ui", "playwright.config.js")
PLAYWRIGHT_WORKDIR = Path(__file__).resolve().parents[2] / "ui"
COMPONENT_UI_DIR = Path(__file__).resolve().parent / "ui"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPERIMENTS_DIR = Path(__file__).resolve().parents[3] / "experiments" / "_standalone"
PLAYWRIGHT_COMMAND = [os.path.join(".", "node_modules", ".bin", "playwright"), "test", "--config", PLAYWRIGHT_CONFIG_RELATIVE]
UI_VALIDATION_ENV = "AI_MODEL_HUB_ENABLE_UI_VALIDATION"
BENCHMARKING_UI_DEMO_ENV = "AI_MODEL_HUB_ENABLE_BENCHMARKING_UI_DEMO"

UI_CASE_METADATA: Dict[str, Dict[str, Any]] = {
    "PT5-MH-01": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "access",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "The catalog route and manual request surface are operational",
        "spec": "pt5_mh_01_catalog_access.spec.js",
    },
    "PT5-MH-02": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "publication",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "A provider can create a local model asset with core and advanced DAIMO metadata",
        "spec": "pt5_mh_02_model_registration.spec.js",
    },
    "PT5-MH-03": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "publication",
        "mapping_status": "mapped",
        "automation_mode": "api_ui",
        "execution_mode": "api_ui",
        "coverage_status": "automated",
        "expected_result": "A provider publication becomes visible through the consumer catalog UI",
        "spec": "pt5_mh_03_catalog_publication.spec.js",
    },
    "PT5-MH-04": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "api_ui",
        "execution_mode": "api_ui",
        "coverage_status": "automated",
        "expected_result": "A controlled local model asset is listed correctly in the discovery UI",
        "spec": "pt5_mh_04_model_listing.spec.js",
    },
    "PT5-MH-05": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "api_ui",
        "execution_mode": "api_ui",
        "coverage_status": "automated",
        "expected_result": "Search returns a controlled matching model and excludes a controlled non-matching model",
        "spec": "pt5_mh_05_search.spec.js",
    },
    "PT5-MH-06": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "api_ui",
        "execution_mode": "api_ui",
        "coverage_status": "automated",
        "expected_result": "Filters discriminate a controlled model result set correctly",
        "spec": "pt5_mh_06_filters.spec.js",
    },
    "PT5-MH-07": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "visualization",
        "mapping_status": "mapped",
        "automation_mode": "api_ui",
        "execution_mode": "api_ui",
        "coverage_status": "automated",
        "expected_result": "The detailed model view exposes controlled functional and technical metadata",
        "spec": "pt5_mh_07_model_details.spec.js",
    },
    "PT5-MH-08": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "contracts",
        "mapping_status": "mapped",
        "automation_mode": "api_ui",
        "execution_mode": "api_ui",
        "coverage_status": "automated",
        "expected_result": "The consumer can finalize a contract negotiation and register the resulting agreement",
        "spec": "pt5_mh_08_contract_negotiation.spec.js",
    },
    "PT5-MH-12": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "comparison",
        "mapping_status": "phase_3",
        "automation_mode": "ui_demo",
        "execution_mode": "ui_demo",
        "coverage_status": "automated",
        "expected_result": "Multiple comparable FLARES models can be selected for benchmarking",
        "spec": "pt5_mh_12_15_model_benchmarking_demo.spec.js",
    },
    "PT5-MH-13": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "comparison",
        "mapping_status": "phase_3",
        "automation_mode": "ui_demo",
        "execution_mode": "ui_demo",
        "coverage_status": "automated",
        "expected_result": "Selected models can be executed over the same benchmark inputs",
        "spec": "pt5_mh_12_15_model_benchmarking_demo.spec.js",
    },
    "PT5-MH-14": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "comparison",
        "mapping_status": "phase_3",
        "automation_mode": "ui_demo",
        "execution_mode": "ui_demo",
        "coverage_status": "automated",
        "expected_result": "Comparison metrics are calculated and rendered by the benchmarking UI",
        "spec": "pt5_mh_12_15_model_benchmarking_demo.spec.js",
    },
    "PT5-MH-15": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "comparison",
        "mapping_status": "phase_3",
        "automation_mode": "ui_demo",
        "execution_mode": "ui_demo",
        "coverage_status": "automated",
        "expected_result": "Comparative result tables and the best model summary are visible",
        "spec": "pt5_mh_12_15_model_benchmarking_demo.spec.js",
    },
}


def _ui_validation_enabled() -> bool:
    raw_value = os.environ.get(UI_VALIDATION_ENV)
    if raw_value is None:
        return True
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _component_dir(experiment_dir: str | None) -> str | None:
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, "components", COMPONENT_KEY)
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _build_ui_artifact_paths(experiment_dir: str | None, *, create: bool = True) -> Dict[str, str]:
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
        "html_report_dir": str(base_dir / "playwright-report"),
        "blob_report_dir": str(base_dir / "blob-report"),
        "json_report_file": str(base_dir / "results.json"),
        "report_json": str(base_dir / "ai_model_hub_ui_validation.json"),
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
    return (results[-1].get("status") or "skipped").lower()


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


def _build_ui_evidence_index(
    executed_cases: List[Dict[str, Any]],
    artifact_paths: Dict[str, str],
) -> List[Dict[str, Any]]:
    evidence_index: List[Dict[str, Any]] = [
        {
            "scope": "suite",
            "suite": "ui",
            "artifact_name": "report_json",
            "path": artifact_paths["report_json"],
        },
        {
            "scope": "suite",
            "suite": "ui",
            "artifact_name": "json_report_file",
            "path": artifact_paths["json_report_file"],
        },
        {
            "scope": "suite",
            "suite": "ui",
            "artifact_name": "html_report_dir",
            "path": artifact_paths["html_report_dir"],
        },
        {
            "scope": "suite",
            "suite": "ui",
            "artifact_name": "blob_report_dir",
            "path": artifact_paths["blob_report_dir"],
        },
        {
            "scope": "suite",
            "suite": "ui",
            "artifact_name": "test_results_dir",
            "path": artifact_paths["output_dir"],
        },
    ]

    for case in executed_cases:
        for attachment in (case.get("response") or {}).get("attachments") or []:
            evidence_index.append(
                {
                    "scope": "case",
                    "suite": "ui",
                    "test_case_id": case.get("test_case_id"),
                    "case_group": case.get("case_group"),
                    "artifact_name": attachment.get("name", ""),
                    "content_type": attachment.get("content_type", ""),
                    "path": attachment.get("path", ""),
                }
            )
    return evidence_index


def _extract_executed_cases(report_payload: Dict[str, Any], base_url: str) -> List[Dict[str, Any]]:
    executed_cases: List[Dict[str, Any]] = []
    for spec in _iter_specs(report_payload.get("suites") or []):
        title = spec.get("title") or ""
        case_id = title.split(":", 1)[0].strip()
        metadata = UI_CASE_METADATA.get(case_id)
        if not metadata:
            continue
        status = _spec_result_status(spec)
        executed_cases.append(
            _build_case_result(
                case_id=case_id,
                title=title,
                metadata=metadata,
                status=status,
                base_url=base_url,
                attachments=_attachments_from_spec(spec),
            )
        )
    return executed_cases


def _empty_summary() -> Dict[str, int]:
    return {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }


def _disabled_suite_result(base_url: str, experiment_dir: str | None) -> Dict[str, Any]:
    artifact_paths = _build_ui_artifact_paths(experiment_dir)
    suite_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "ui",
        "status": "skipped",
        "reason": "ui_validation_disabled",
        "timestamp": datetime.now().isoformat(),
        "base_url": (base_url or "").rstrip("/"),
        "summary": _empty_summary(),
        "executed_cases": [],
        "pt5_cases": [],
        "support_checks": [],
        "pt5_summary": _empty_summary(),
        "support_summary": _empty_summary(),
        "evidence_index": [],
        "playwright_config": PLAYWRIGHT_CONFIG_RELATIVE,
        "specs": [metadata["spec"] for metadata in UI_CASE_METADATA.values()],
        "exit_code": None,
        "error": None,
        "artifacts": {
            "report_json": artifact_paths["report_json"],
            "test_results_dir": artifact_paths["output_dir"],
            "html_report_dir": artifact_paths["html_report_dir"],
            "blob_report_dir": artifact_paths["blob_report_dir"],
            "json_report_file": artifact_paths["json_report_file"],
        },
    }
    _write_json(artifact_paths["report_json"], suite_result)
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=PROJECT_ROOT / "experiments")
    return suite_result


def run_ai_model_hub_ui_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    normalized_base_url = (base_url or "").rstrip("/")
    if not _ui_validation_enabled():
        return _disabled_suite_result(normalized_base_url, experiment_dir)

    started_at = datetime.now().isoformat()
    artifact_paths = _build_ui_artifact_paths(experiment_dir)
    env = {
        **os.environ,
        "AI_MODEL_HUB_BASE_URL": normalized_base_url,
        BENCHMARKING_UI_DEMO_ENV: os.environ.get(BENCHMARKING_UI_DEMO_ENV, "1"),
        "PLAYWRIGHT_OUTPUT_DIR": artifact_paths["output_dir"],
        "PLAYWRIGHT_HTML_REPORT_DIR": artifact_paths["html_report_dir"],
        "PLAYWRIGHT_BLOB_REPORT_DIR": artifact_paths["blob_report_dir"],
        "PLAYWRIGHT_JSON_REPORT_FILE": artifact_paths["json_report_file"],
        "PIONERA_PLAYWRIGHT_SUITE_NAME": "AI Model Hub functional",
        "PLAYWRIGHT_INTERACTION_MARKERS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKERS", "1"),
        "PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS": os.environ.get("PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS", "350"),
    }

    error = None
    exit_code = None
    status = "skipped"
    try:
        result = subprocess.run(
            PLAYWRIGHT_COMMAND,
            cwd=str(PLAYWRIGHT_WORKDIR),
            env=env,
        )
        exit_code = result.returncode
        status = "passed" if result.returncode == 0 else "failed"
    except OSError as exc:
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }

    if os.path.exists(artifact_paths["json_report_file"]):
        with open(artifact_paths["json_report_file"], "r", encoding="utf-8") as handle:
            report_payload = json.load(handle)
        stats = report_payload.get("stats") or {}
        summary = {
            "total": int(stats.get("expected", 0))
            + int(stats.get("unexpected", 0))
            + int(stats.get("flaky", 0))
            + int(stats.get("skipped", 0)),
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
        total_cases = len(UI_CASE_METADATA)
        summary = {
            "total": total_cases,
            "passed": 0,
            "failed": 0 if status == "skipped" else total_cases,
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

    pt5_cases = list(executed_cases)
    support_checks: List[Dict[str, Any]] = []
    pt5_summary = {
        "total": len(pt5_cases),
        "passed": sum(1 for case in pt5_cases if ((case.get("evaluation") or {}).get("status") or "").lower() == "passed"),
        "failed": sum(1 for case in pt5_cases if ((case.get("evaluation") or {}).get("status") or "").lower() == "failed"),
        "skipped": sum(1 for case in pt5_cases if ((case.get("evaluation") or {}).get("status") or "").lower() == "skipped"),
    }
    support_summary = _empty_summary()
    evidence_index = _build_ui_evidence_index(executed_cases, artifact_paths)

    suite_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "ui",
        "status": status,
        "timestamp": started_at,
        "base_url": normalized_base_url,
        "summary": summary,
        "executed_cases": executed_cases,
        "pt5_cases": pt5_cases,
        "support_checks": support_checks,
        "pt5_summary": pt5_summary,
        "support_summary": support_summary,
        "evidence_index": evidence_index,
        "playwright_config": PLAYWRIGHT_CONFIG_RELATIVE,
        "specs": [metadata["spec"] for metadata in UI_CASE_METADATA.values()],
        "exit_code": exit_code,
        "error": error,
        "artifacts": {
            "report_json": artifact_paths["report_json"],
            "test_results_dir": artifact_paths["output_dir"],
            "html_report_dir": artifact_paths["html_report_dir"],
            "blob_report_dir": artifact_paths["blob_report_dir"],
            "json_report_file": artifact_paths["json_report_file"],
        },
    }
    _write_json(artifact_paths["report_json"], suite_result)
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=PROJECT_ROOT / "experiments")
    return suite_result
