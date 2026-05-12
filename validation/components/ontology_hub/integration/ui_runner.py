import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib import parse

import requests

from validation.components.ontology_hub.integration.runner import (
    API_SEARCH_PATH,
    API_DOCS_PATH,
    HOME_PATH,
    evaluate_html_page_response,
    evaluate_term_search_response,
)
from validation.components.artifact_cleanup import cleanup_empty_experiment_artifact_dirs
from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime


COMPONENT_KEY = "ontology-hub"
PLAYWRIGHT_CONFIG_RELATIVE = os.path.join("..", "components", "ontology_hub", "integration", "playwright.config.js")
PLAYWRIGHT_WORKDIR = Path(__file__).resolve().parents[2] / "ui"
COMPONENT_UI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EXPERIMENTS_DIR = Path(__file__).resolve().parents[4] / "experiments" / "_standalone"
PLAYWRIGHT_COMMAND_PREFIX = [
    os.path.join(".", "node_modules", ".bin", "playwright"),
    "test",
    "--config",
    PLAYWRIGHT_CONFIG_RELATIVE,
]

UI_CASE_METADATA: Dict[str, Dict[str, Any]] = {
    "OH-LOGIN": {
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "automation_mode": "ui_support",
        "execution_mode": "ui_support",
        "coverage_status": "automated",
        "expected_result": "Acceso autenticado al area de edicion",
        "spec": "oh_login.spec.js",
    },
    "PT5-OH-01": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "functional",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "La ontologia se registra y es visible en el catalogo",
        "spec": "pt5_oh_01_create_vocab.spec.js",
    },
    "PT5-OH-02": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "publication",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "Los cambios en la ontologia se reflejan correctamente",
        "spec": "pt5_oh_02_edit_vocab.spec.js",
    },
    "OH-LIST-SEARCH": {
        "case_group": "support",
        "validation_type": "support",
        "dataspace_dimension": "support",
        "mapping_status": "supporting",
        "automation_mode": "ui_support",
        "execution_mode": "ui_support",
        "coverage_status": "automated",
        "expected_result": "El catalogo publico lista vocabularios y abre un resultado de busqueda",
        "spec": "oh_list_search.spec.js",
    },
    "PT5-OH-09": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "Resultados filtrados correctamente",
        "spec": "pt5_oh_09_filters.spec.js",
    },
    "PT5-OH-10": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "discovery",
        "mapping_status": "partial",
        "automation_mode": "ui_partial",
        "execution_mode": "ui",
        "coverage_status": "partial",
        "expected_result": "Se muestra la version solicitada",
        "spec": "pt5_oh_10_versions.spec.js",
    },
    "PT5-OH-11": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "visualization",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "Metadatos, codigo y graficos visibles",
        "spec": "pt5_oh_11_vocab_detail.spec.js",
    },
    "PT5-OH-12": {
        "case_group": "pt5",
        "validation_type": "functional",
        "dataspace_dimension": "visualization",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "Metricas visibles conforme a lo definido",
        "spec": "pt5_oh_12_statistics.spec.js",
    },
    "PT5-OH-15": {
        "case_group": "pt5",
        "validation_type": "integration",
        "dataspace_dimension": "integration",
        "mapping_status": "mapped",
        "automation_mode": "ui",
        "execution_mode": "ui",
        "coverage_status": "automated",
        "expected_result": "Paridad funcional entre UI y API",
        "spec": "pt5_oh_15_ui_access.spec.js",
    },
}


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _build_ui_artifact_paths(experiment_dir: str | None, *, create: bool = True) -> Dict[str, str]:
    if experiment_dir:
        base_dir = os.path.join(experiment_dir, "components", COMPONENT_KEY, "ui")
    else:
        base_dir = os.path.join(str(DEFAULT_EXPERIMENTS_DIR), "components", COMPONENT_KEY, "ui")

    paths = {
        "base_dir": base_dir,
        "output_dir": os.path.join(base_dir, "test-results"),
        "html_report_dir": os.path.join(base_dir, "playwright-report"),
        "blob_report_dir": os.path.join(base_dir, "blob-report"),
        "json_report_file": os.path.join(base_dir, "results.json"),
        "report_json": os.path.join(base_dir, "ontology_hub_ui_validation.json"),
        "resolved_runtime_json": os.path.join(base_dir, "resolved_runtime.json"),
        "preflight_json": os.path.join(base_dir, "preflight.json"),
    }
    if create:
        for path in paths.values():
            if path.endswith(".json"):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            else:
                os.makedirs(path, exist_ok=True)
    return paths


def _build_playwright_command(worker_count: int) -> List[str]:
    normalized_workers = worker_count if worker_count > 0 else 1
    return [*PLAYWRIGHT_COMMAND_PREFIX, f"--workers={normalized_workers}"]


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


def _filter_case_group(executed_cases: List[Dict[str, Any]], case_group: str) -> List[Dict[str, Any]]:
    return [case for case in executed_cases if case.get("case_group") == case_group]


def _summarize_case_list(executed_cases: List[Dict[str, Any]]) -> Dict[str, int]:
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
        {
            "scope": "suite",
            "suite": "ui",
            "artifact_name": "resolved_runtime_json",
            "path": artifact_paths["resolved_runtime_json"],
        },
        {
            "scope": "suite",
            "suite": "ui",
            "artifact_name": "preflight_json",
            "path": artifact_paths["preflight_json"],
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


def _probe_request_failure(probe_id: str, url: str, blocking: bool, exc: Exception) -> Dict[str, Any]:
    return {
        "id": probe_id,
        "url": url,
        "blocking": blocking,
        "status": "failed",
        "http_status": None,
        "content_type": "",
        "assertions": [f"Probe failed: {exc}"],
    }


def _run_html_probe(
    *,
    probe_id: str,
    url: str,
    required_markers: List[str],
    blocking: bool,
    timeout: int,
) -> Dict[str, Any]:
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return _probe_request_failure(probe_id, url, blocking, exc)

    evaluation = evaluate_html_page_response(
        response.status_code,
        response.headers.get("Content-Type", ""),
        response.text,
        required_markers=required_markers,
    )
    return {
        "id": probe_id,
        "url": url,
        "blocking": blocking,
        **evaluation,
    }


_LOGIN_FORM_ACTION_RE = re.compile(r"<form[^>]+action=[\"']([^\"']+)[\"']", re.IGNORECASE)
_LOGIN_CSRF_RE = re.compile(
    r"<input[^>]+name=[\"']_csrf[\"'][^>]+value=[\"']([^\"']*)[\"']",
    re.IGNORECASE,
)


def _extract_login_form_action(body_text: str) -> str:
    match = _LOGIN_FORM_ACTION_RE.search(body_text or "")
    if not match:
        return "/edition/session"
    return match.group(1).strip() or "/edition/session"


def _extract_login_csrf(body_text: str) -> str:
    match = _LOGIN_CSRF_RE.search(body_text or "")
    if not match:
        return ""
    return match.group(1).strip()


def _run_edition_auth_probe(runtime: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    base_url = runtime["baseUrl"]
    login_url = f"{base_url}/edition/login"
    session = requests.Session()

    try:
        login_response = session.get(login_url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        probe = _probe_request_failure("edition_authentication", login_url, True, exc)
        probe["fatal"] = True
        return probe

    login_evaluation = evaluate_html_page_response(
        login_response.status_code,
        login_response.headers.get("Content-Type", ""),
        login_response.text,
        required_markers=["email", "password", "log in it"],
    )
    if login_evaluation["status"] != "passed":
        return {
            "id": "edition_authentication",
            "url": login_url,
            "blocking": True,
            "fatal": True,
            **login_evaluation,
        }

    payload = {
        "email": runtime["adminEmail"],
        "password": runtime["adminPassword"],
    }
    csrf_token = _extract_login_csrf(login_response.text)
    if csrf_token:
        payload["_csrf"] = csrf_token

    submit_url = parse.urljoin(base_url.rstrip("/") + "/", _extract_login_form_action(login_response.text))
    try:
        auth_response = session.post(
            submit_url,
            data=payload,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        probe = _probe_request_failure("edition_authentication", submit_url, True, exc)
        probe["fatal"] = True
        return probe

    body_text = auth_response.text or ""
    normalized_body = body_text.lower()
    final_url = auth_response.url or submit_url
    success = any(
        marker in normalized_body
        for marker in [
            "logout",
            "profile",
            "createvocab",
            'title="edition"',
            "href=\"/edition/\"",
            "href=\"/edition/lov/\"",
        ]
    )

    assertions: List[str] = []
    status = "passed"
    if auth_response.status_code != 200:
        status = "failed"
        assertions.append(f"Expected HTTP 200 after login, got HTTP {auth_response.status_code}")
    if "invalid email or password." in normalized_body:
        status = "failed"
        assertions.append(
            "Las credenciales configuradas para Ontology Hub no son validas. "
            "Revisa ONTOLOGY_HUB_ADMIN_EMAIL y ONTOLOGY_HUB_ADMIN_PASSWORD."
        )
    elif final_url.rstrip("/").endswith("/edition/login") and not success:
        status = "failed"
        assertions.append(
            "El login volvio a /edition/login sin exponer el area de edicion esperada."
        )
    elif not success:
        status = "failed"
        assertions.append(
            "La autenticacion no mostro los marcadores esperados del area de edicion "
            "(Logout, Profile o createVocab)."
        )

    return {
        "id": "edition_authentication",
        "url": submit_url,
        "final_url": final_url,
        "blocking": True,
        "fatal": True,
        "status": status,
        "http_status": auth_response.status_code,
        "content_type": auth_response.headers.get("Content-Type", ""),
        "assertions": assertions,
        "body_excerpt": body_text[:500],
    }


def _run_search_api_probe(runtime: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    query = {
        "q": runtime["expectedSearchTerm"],
        "type": "class",
    }
    url = f"{runtime['baseUrl']}{API_SEARCH_PATH}?{parse.urlencode(query)}"
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return _probe_request_failure("search_api", url, True, exc)

    evaluation = evaluate_term_search_response(
        response.status_code,
        response.headers.get("Content-Type", ""),
        response.text,
        expected_query=runtime["expectedSearchTerm"],
        expected_vocab=runtime["expectedVocabularyPrefix"],
    )
    return {
        "id": "search_api",
        "url": url,
        "blocking": False,
        **evaluation,
    }


def _run_ui_preflight(runtime: Dict[str, Any]) -> Dict[str, Any]:
    timeout = runtime["preflightTimeout"]
    base_url = runtime["baseUrl"]
    probes = [
        _run_html_probe(
            probe_id="home_page",
            url=f"{base_url}{HOME_PATH}",
            required_markers=["/dataset/api", "/dataset/vocabs"],
            blocking=True,
            timeout=timeout,
        ),
        _run_html_probe(
            probe_id="catalog_page",
            url=f"{base_url}/dataset/vocabs",
            required_markers=["search for a vocabulary"],
            blocking=True,
            timeout=timeout,
        ),
        _run_html_probe(
            probe_id="api_docs",
            url=f"{base_url}{API_DOCS_PATH}",
            required_markers=["/api/v2/term/search"],
            blocking=True,
            timeout=timeout,
        ),
        _run_html_probe(
            probe_id="edition_login",
            url=f"{base_url}/edition/login",
            required_markers=["email", "password", "log in it"],
            blocking=True,
            timeout=timeout,
        ),
        _run_edition_auth_probe(runtime, timeout),
        _run_html_probe(
            probe_id="vocabulary_detail",
            url=f"{base_url}/dataset/vocabs/{runtime['expectedVocabularyPrefix']}",
            required_markers=["metadata"],
            blocking=False,
            timeout=timeout,
        ),
        _run_search_api_probe(runtime, timeout),
    ]
    blocking_failures = [probe["id"] for probe in probes if probe.get("blocking") and probe["status"] != "passed"]
    fatal_failures = [probe["id"] for probe in probes if probe.get("fatal") and probe["status"] != "passed"]
    ready = not blocking_failures
    return {
        "status": "passed" if ready else "failed",
        "ready": ready,
        "strict": runtime["strictPreflight"],
        "shouldRunPlaywright": not fatal_failures and (ready or not runtime["strictPreflight"]),
        "blocking_failures": blocking_failures,
        "fatal_failures": fatal_failures,
        "probes": probes,
    }


def run_ontology_hub_ui_validation(base_url: str, experiment_dir: str | None = None) -> Dict[str, Any]:
    started_at = datetime.now().isoformat()
    runtime = resolve_ontology_hub_runtime(base_url=base_url)
    normalized_base_url = runtime["baseUrl"]
    artifact_paths = _build_ui_artifact_paths(experiment_dir)
    _write_json(artifact_paths["resolved_runtime_json"], runtime)

    preflight = _run_ui_preflight(runtime)
    _write_json(artifact_paths["preflight_json"], preflight)

    env = {
        **os.environ,
        "ONTOLOGY_HUB_BASE_URL": normalized_base_url,
        "ONTOLOGY_HUB_RUNTIME_FILE": artifact_paths["resolved_runtime_json"],
        "ONTOLOGY_HUB_UI_WORKERS": str(runtime["uiWorkers"]),
        "PLAYWRIGHT_OUTPUT_DIR": artifact_paths["output_dir"],
        "PLAYWRIGHT_HTML_REPORT_DIR": artifact_paths["html_report_dir"],
        "PLAYWRIGHT_BLOB_REPORT_DIR": artifact_paths["blob_report_dir"],
        "PLAYWRIGHT_JSON_REPORT_FILE": artifact_paths["json_report_file"],
    }

    error = None
    exit_code = None
    status = "skipped"
    try:
        if not preflight["shouldRunPlaywright"]:
            failed_ids = ", ".join(preflight["blocking_failures"]) or "unknown"
            raise RuntimeError(f"Ontology Hub UI preflight failed: {failed_ids}")
        result = subprocess.run(
            _build_playwright_command(runtime["uiWorkers"]),
            cwd=str(PLAYWRIGHT_WORKDIR),
            env=env,
        )
        exit_code = result.returncode
        status = "passed" if result.returncode == 0 else "failed"
    except (OSError, RuntimeError) as exc:
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        status = "failed" if preflight["status"] == "failed" else "skipped"

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

    pt5_cases = _filter_case_group(executed_cases, "pt5")
    support_checks = _filter_case_group(executed_cases, "support")
    pt5_summary = _summarize_case_list(pt5_cases)
    support_summary = _summarize_case_list(support_checks)
    evidence_index = _build_ui_evidence_index(executed_cases, artifact_paths)

    suite_result: Dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": "ui",
        "status": status,
        "timestamp": started_at,
        "base_url": normalized_base_url,
        "runtime": runtime,
        "preflight": preflight,
        "summary": summary,
        "executed_cases": executed_cases,
        "pt5_cases": pt5_cases,
        "support_checks": support_checks,
        "pt5_summary": pt5_summary,
        "support_summary": support_summary,
        "evidence_index": evidence_index,
        "playwright_config": PLAYWRIGHT_CONFIG_RELATIVE,
        "playwright_command": _build_playwright_command(runtime["uiWorkers"]),
        "specs": [metadata["spec"] for metadata in UI_CASE_METADATA.values()],
        "exit_code": exit_code,
        "error": error,
        "artifacts": {
            "report_json": artifact_paths["report_json"],
            "resolved_runtime_json": artifact_paths["resolved_runtime_json"],
            "preflight_json": artifact_paths["preflight_json"],
            "test_results_dir": artifact_paths["output_dir"],
            "html_report_dir": artifact_paths["html_report_dir"],
            "blob_report_dir": artifact_paths["blob_report_dir"],
            "json_report_file": artifact_paths["json_report_file"],
        },
    }
    _write_json(artifact_paths["report_json"], suite_result)
    cleanup_empty_experiment_artifact_dirs(artifact_paths, experiments_root=PROJECT_ROOT / "experiments")
    return suite_result
