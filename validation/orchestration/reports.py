from __future__ import annotations

import atexit
import html
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


EXPERIMENT_PREFIX = "experiment_"
FRAMEWORK_REPORT_DIR = "framework-report"
LOCAL_REPORT_HOST = "127.0.0.1"
WINDOWS_CMD_EXE = Path("/mnt/c/Windows/System32/cmd.exe")
WINDOWS_EXPLORER_EXE = Path("/mnt/c/Windows/explorer.exe")
WINDOWS_POWERSHELL_EXE = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
_REPORT_SERVER_PROCESSES: list[subprocess.Popen] = []


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def experiments_dir(root: str | Path | None = None) -> Path:
    return Path(root or project_root()) / "experiments"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_link(path: str) -> str:
    return quote(path.replace(os.sep, "/"), safe="/._-")


def _display_name_from_path(path: str) -> str:
    parts = [part for part in Path(path).parts if part and part != "playwright-report"]
    if not parts:
        return "Playwright report"
    return " / ".join(parts)


def _timestamp_from_experiment(path: Path, metadata: dict[str, Any]) -> str:
    raw_timestamp = str(metadata.get("timestamp") or "").strip()
    if raw_timestamp:
        return raw_timestamp
    name = path.name
    if name.startswith(EXPERIMENT_PREFIX):
        raw = name[len(EXPERIMENT_PREFIX) :]
        try:
            return datetime.strptime(raw, "%Y-%m-%d_%H-%M-%S").isoformat()
        except ValueError:
            return raw
    return ""


def _metadata_topology(metadata: dict[str, Any]) -> str:
    topology = str(metadata.get("topology") or metadata.get("topology_name") or "").strip()
    return topology or "not recorded"


def _metadata_cluster_runtime(metadata: dict[str, Any]) -> str:
    cluster = str(metadata.get("cluster_runtime") or metadata.get("cluster") or "").strip()
    if cluster:
        return cluster
    environment = str(metadata.get("environment") or "").strip()
    if environment.lower() in {"minikube", "k3s", "kubernetes"}:
        return environment
    return "not recorded"


def _metadata_adapter(metadata: dict[str, Any]) -> str:
    adapter_name = str(metadata.get("adapter_name") or "").strip()
    if adapter_name:
        return adapter_name
    adapter_class = str(metadata.get("adapter") or "").strip()
    known = {
        "EdcAdapter": "edc",
        "InesdataAdapter": "inesdata",
    }
    return known.get(adapter_class, adapter_class or "unknown")


def _sort_key(experiment: dict[str, Any]) -> str:
    return str(experiment.get("timestamp") or experiment.get("name") or "")


def _summarize_status_items(items: list[dict[str, Any]], status_key: str = "status") -> dict[str, int]:
    summary = {"passed": 0, "failed": 0, "skipped": 0, "other": 0, "total": 0}
    for item in items:
        status = str(item.get(status_key) or "").strip().lower()
        summary["total"] += 1
        if status in {"pass", "passed", "ok", "success", "succeeded"}:
            summary["passed"] += 1
        elif status in {"fail", "failed", "error", "terminated"}:
            summary["failed"] += 1
        elif status in {"skip", "skipped"}:
            summary["skipped"] += 1
        else:
            summary["other"] += 1
    return summary


def _summarize_newman(experiment_path: Path) -> dict[str, Any] | None:
    test_results = _read_json(experiment_path / "test_results.json")
    newman_results_path = experiment_path / "newman_results.json"
    newman_results = _read_json(newman_results_path)
    report_files = sorted((experiment_path / "newman_reports").glob("**/*.json"))

    if not isinstance(test_results, list) and not newman_results_path.exists() and not report_files:
        return None

    assertions = _summarize_status_items(test_results if isinstance(test_results, list) else [])
    checks = []
    if isinstance(newman_results, list):
        for item in newman_results:
            if isinstance(item, dict) and isinstance(item.get("checks"), list):
                checks.extend(check for check in item["checks"] if isinstance(check, dict))

    passed_checks = sum(1 for check in checks if check.get("ok") is True)
    failed_checks = sum(1 for check in checks if check.get("ok") is False)
    return {
        "kind": "newman",
        "title": "Newman",
        "status": "failed" if assertions["failed"] or failed_checks else "passed",
        "assertions": assertions,
        "checks": {
            "total": len(checks),
            "passed": passed_checks,
            "failed": failed_checks,
        },
        "report_files": len(report_files),
        "artifacts": [
            _relative(path, experiment_path)
            for path in (experiment_path / "newman_results.json", experiment_path / "test_results.json")
            if path.exists()
        ],
    }


def _summarize_kafka(experiment_path: Path) -> dict[str, Any] | None:
    candidates = [
        experiment_path / "kafka_transfer_results.json",
        experiment_path / "kafka_edc_results.json",
    ]
    artifacts = [path for path in candidates if path.exists()]
    transfer_files = sorted((experiment_path / "kafka_transfer").glob("*.json"))
    if not artifacts and not transfer_files:
        return None

    records: list[dict[str, Any]] = []
    for path in artifacts:
        payload = _read_json(path)
        if isinstance(payload, list):
            records.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            raw_results = payload.get("results")
            if isinstance(raw_results, list):
                records.extend(item for item in raw_results if isinstance(item, dict))

    summary = _summarize_status_items(records)
    latencies = []
    throughputs = []
    for record in records:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        latency = metrics.get("average_latency_ms", record.get("average_latency_ms"))
        throughput = metrics.get("throughput_messages_per_second", record.get("throughput_messages_per_second"))
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))
        if isinstance(throughput, (int, float)):
            throughputs.append(float(throughput))

    return {
        "kind": "kafka",
        "title": "Kafka transfer",
        "status": "failed" if summary["failed"] else "passed",
        "summary": summary,
        "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "average_throughput": round(sum(throughputs) / len(throughputs), 2) if throughputs else None,
        "transfer_files": len(transfer_files),
        "artifacts": [_relative(path, experiment_path) for path in artifacts],
    }


def _summarize_local_stability(experiment_path: Path) -> dict[str, Any] | None:
    path = experiment_path / "local_stability_postflight.json"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    comparison_warnings = comparison.get("warnings") if isinstance(comparison.get("warnings"), list) else []
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    snapshot_warnings = snapshot.get("warnings") if isinstance(snapshot.get("warnings"), list) else []
    blocking = payload.get("blocking_issues") if isinstance(payload.get("blocking_issues"), list) else []
    display_status = str(comparison.get("status") or "unknown")
    if display_status == "warning" and not comparison_warnings and snapshot_warnings:
        display_status = "warning-existing"
    return {
        "kind": "stability",
        "title": "Local stability postflight",
        "status": display_status,
        "warnings": len(comparison_warnings),
        "snapshot_warnings": len(snapshot_warnings),
        "blocking_issues": len(blocking),
        "node_not_ready_delta": comparison.get("node_not_ready_delta"),
        "artifacts": [_relative(path, experiment_path)],
    }


def _summarize_une_0087(experiment_path: Path) -> dict[str, Any] | None:
    path = experiment_path / "une_0087_alignment.json"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    statuses = summary.get("statuses") if isinstance(summary.get("statuses"), dict) else {}
    artifacts = [_relative(path, experiment_path)]
    markdown_path = experiment_path / "une_0087_alignment.md"
    if markdown_path.exists():
        artifacts.append(_relative(markdown_path, experiment_path))
    total = int(summary.get("total_criteria") or 0)
    not_covered = int(statuses.get("not_covered") or 0)
    partially_covered = int(statuses.get("partially_covered") or 0)
    status = "covered" if total and not not_covered and not partially_covered else "partial"
    return {
        "kind": "une-0087",
        "title": "UNE 0087 alignment",
        "status": status,
        "summary": {
            "total": total,
            "covered": int(statuses.get("covered") or 0),
            "partially_covered": partially_covered,
            "not_covered": not_covered,
            "not_applicable": int(statuses.get("not_applicable") or 0),
        },
        "certification_claim": bool(payload.get("certification_claim")),
        "artifacts": artifacts,
    }


def _summarize_components(experiment_path: Path) -> list[dict[str, Any]]:
    results = []
    for path in sorted((experiment_path / "components").glob("*/*_component_validation.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        results.append(
            {
                "kind": "component",
                "title": str(payload.get("component") or path.parent.name),
                "status": str(payload.get("status") or "unknown"),
                "summary": {
                    "total": summary.get("total", 0),
                    "passed": summary.get("passed", 0),
                    "failed": summary.get("failed", 0),
                    "skipped": summary.get("skipped", 0),
                },
                "artifacts": [_relative(path, experiment_path)],
            }
        )
    return results


def _component_validation_components(experiment_path: Path) -> set[str]:
    components = set()
    for path in sorted((experiment_path / "components").glob("*/*_component_validation.json")):
        components.add(path.parent.name)
    return components


def _component_report_json_paths(experiment_path: Path) -> list[Path]:
    paths = []
    component_summaries = _component_validation_components(experiment_path)
    for path in sorted((experiment_path / "components").glob("*/*/*.json")):
        if path.name in {"results.json", "metadata.json"} or path.name.endswith("_component_validation.json"):
            continue
        if "test-results" in path.parts or "playwright-report" in path.parts or "node_modules" in path.parts:
            continue
        relative_parts = path.relative_to(experiment_path).parts
        if len(relative_parts) < 4:
            continue
        component = relative_parts[1]
        if component in component_summaries:
            continue
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        if not isinstance(payload.get("summary"), dict):
            continue
        if not str(payload.get("status") or "").strip():
            continue
        paths.append(path)
    return paths


def _summarize_component_report_json(experiment_path: Path) -> list[dict[str, Any]]:
    summaries = []
    for path in _component_report_json_paths(experiment_path):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        relative_parts = path.relative_to(experiment_path).parts
        component = str(payload.get("component") or relative_parts[1])
        suite = str(payload.get("suite") or relative_parts[2])
        summaries.append(
            {
                "kind": "component-report",
                "title": f"{component} / {suite}",
                "status": str(payload.get("status") or "unknown"),
                "summary": {
                    "total": summary.get("total", 0),
                    "passed": summary.get("passed", 0),
                    "failed": summary.get("failed", 0),
                    "skipped": summary.get("skipped", 0),
                },
                "artifacts": [_relative(path, experiment_path)],
            }
        )
    return summaries


def _summarize_playwright_json(experiment_path: Path) -> list[dict[str, Any]]:
    summaries = []
    component_summaries = _component_validation_components(experiment_path)
    for path in sorted(experiment_path.glob("**/results.json")):
        if "node_modules" in path.parts:
            continue
        relative_parts = path.relative_to(experiment_path).parts
        if len(relative_parts) >= 3 and relative_parts[0] == "components" and relative_parts[1] in component_summaries:
            continue
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        stats = _playwright_stats(payload)
        summaries.append(
            {
                "kind": "playwright-json",
                "title": _display_name_from_path(_relative(path.parent, experiment_path)),
                "status": "failed" if stats["failed"] else "passed",
                "summary": stats,
                "artifacts": [_relative(path, experiment_path)],
            }
        )
    return summaries


def _playwright_stats(payload: dict[str, Any]) -> dict[str, int]:
    stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "other": 0}

    def walk_suite(suite: dict[str, Any]) -> None:
        for spec in suite.get("specs") or []:
            if not isinstance(spec, dict):
                continue
            for test in spec.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                status = str(test.get("status") or "").strip().lower()
                stats["total"] += 1
                if status in {"expected", "passed"}:
                    stats["passed"] += 1
                elif status in {"unexpected", "failed", "timedout", "interrupted"}:
                    stats["failed"] += 1
                elif status in {"skipped"}:
                    stats["skipped"] += 1
                else:
                    stats["other"] += 1
        for child in suite.get("suites") or []:
            if isinstance(child, dict):
                walk_suite(child)

    for suite in payload.get("suites") or []:
        if isinstance(suite, dict):
            walk_suite(suite)
    return stats


def _discover_playwright_reports(experiment_path: Path) -> list[dict[str, str]]:
    reports = []
    for index_path in sorted(experiment_path.glob("**/playwright-report/index.html")):
        relative_parent = _relative(index_path.parent, experiment_path)
        reports.append(
            {
                "kind": "playwright",
                "title": _display_name_from_path(relative_parent),
                "path": relative_parent,
                "index": _relative(index_path, experiment_path),
            }
        )
    return reports


def _artifact_links(experiment_path: Path) -> list[dict[str, str]]:
    names = [
        "metadata.json",
        "local_capacity_preflight.json",
        "local_stability_preflight.json",
        "local_stability_postflight.json",
        "newman_results.json",
        "test_results.json",
        "kafka_transfer_results.json",
        "kafka_edc_results.json",
        "aggregated_metrics.json",
        "une_0087_alignment.json",
        "une_0087_alignment.md",
    ]
    artifacts = [
        {"title": name, "path": name}
        for name in names
        if (experiment_path / name).exists()
    ]
    for path in sorted(experiment_path.glob("components/*/*_component_validation.json")):
        rel = _relative(path, experiment_path)
        artifacts.append({"title": rel, "path": rel})
    for path in _component_report_json_paths(experiment_path):
        rel = _relative(path, experiment_path)
        artifacts.append({"title": rel, "path": rel})
    return artifacts


def _has_report_artifacts(experiment_path: Path) -> bool:
    standard_artifacts = {
        "local_capacity_preflight.json",
        "local_stability_preflight.json",
        "local_stability_postflight.json",
        "newman_results.json",
        "test_results.json",
        "kafka_transfer_results.json",
        "kafka_edc_results.json",
        "aggregated_metrics.json",
        "une_0087_alignment.json",
        "une_0087_alignment.md",
    }
    if any((experiment_path / name).exists() for name in standard_artifacts):
        return True
    if any(experiment_path.glob("components/*/*_component_validation.json")):
        return True
    if _component_report_json_paths(experiment_path):
        return True
    if any(experiment_path.glob("**/results.json")):
        return True
    if any(experiment_path.glob("**/playwright-report/index.html")):
        return True
    return False


def _is_reportable_experiment_path(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.name.startswith(EXPERIMENT_PREFIX):
        return True
    if path.name.startswith("_"):
        return False
    return (path / "metadata.json").is_file() and _has_report_artifacts(path)


def inspect_experiment(path: str | Path) -> dict[str, Any]:
    experiment_path = Path(path)
    metadata = _read_json(experiment_path / "metadata.json")
    metadata = metadata if isinstance(metadata, dict) else {}

    suites = []
    for summary in (
        _summarize_newman(experiment_path),
        _summarize_kafka(experiment_path),
        _summarize_local_stability(experiment_path),
        _summarize_une_0087(experiment_path),
    ):
        if summary:
            suites.append(summary)
    suites.extend(_summarize_components(experiment_path))
    suites.extend(_summarize_component_report_json(experiment_path))
    suites.extend(_summarize_playwright_json(experiment_path))

    playwright_reports = _discover_playwright_reports(experiment_path)
    report_kinds = []
    if playwright_reports:
        report_kinds.append("Playwright")
    if any(suite.get("kind") == "newman" for suite in suites):
        report_kinds.append("Newman")
    if any(suite.get("kind") == "kafka" for suite in suites):
        report_kinds.append("Kafka")
    if any(suite.get("kind") in {"component", "component-report"} for suite in suites):
        report_kinds.append("Components")
    if any(suite.get("kind") == "stability" for suite in suites):
        report_kinds.append("Stability")
    if any(suite.get("kind") == "une-0087" for suite in suites):
        report_kinds.append("UNE 0087")

    result = "No failed suites detected"
    if any(str(suite.get("status")).lower() in {"failed", "error"} for suite in suites):
        result = "Issues detected"
    elif any(str(suite.get("status")).lower() in {"warning", "warning-existing"} for suite in suites):
        result = "Warnings detected"
    elif not suites and not playwright_reports:
        result = "Partial"

    return {
        "name": experiment_path.name,
        "path": str(experiment_path),
        "timestamp": _timestamp_from_experiment(experiment_path, metadata),
        "adapter": _metadata_adapter(metadata),
        "adapter_class": str(metadata.get("adapter") or "").strip(),
        "topology": _metadata_topology(metadata),
        "cluster_runtime": _metadata_cluster_runtime(metadata),
        "result": result,
        "reports": report_kinds,
        "playwright_reports": playwright_reports,
        "suites": suites,
        "artifacts": _artifact_links(experiment_path),
    }


def discover_report_experiments(root: str | Path | None = None) -> list[dict[str, Any]]:
    base = experiments_dir(root)
    if not base.is_dir():
        return []
    experiments = [
        inspect_experiment(path)
        for path in sorted(base.iterdir())
        if _is_reportable_experiment_path(path)
    ]
    return sorted(experiments, key=_sort_key, reverse=True)


def format_report_experiment_summary(experiment: dict[str, Any]) -> list[str]:
    reports = ", ".join(experiment.get("reports") or []) or "none detected"
    return [
        f"{experiment.get('name')}",
        f"    Adapter: {experiment.get('adapter') or 'unknown'}",
        f"    Topology: {experiment.get('topology') or 'unknown'}",
        f"    Cluster runtime: {experiment.get('cluster_runtime') or 'unknown'}",
        f"    Dashboard status: {experiment.get('result') or 'unknown'}",
        f"    Reports: {reports}",
    ]


def build_experiment_dashboard(experiment: dict[str, Any]) -> Path:
    experiment_path = Path(str(experiment["path"]))
    report_dir = experiment_path / FRAMEWORK_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    index_path = report_dir / "index.html"
    index_path.write_text(_render_dashboard_html(experiment), encoding="utf-8")
    return index_path


def _badge(status: Any) -> str:
    normalized = str(status or "unknown").strip().lower()
    if normalized in {"succeeded", "passed", "success", "covered", "no failed suites detected"}:
        css = "ok"
    elif normalized in {"warning", "warning-existing", "warnings detected"}:
        css = "warn"
    elif normalized in {"failed", "error", "issues detected"}:
        css = "fail"
    else:
        css = "neutral"
    display = "existing warning" if normalized == "warning-existing" else str(status or "unknown")
    return f'<span class="badge {css}">{html.escape(display)}</span>'


def _render_dashboard_html(experiment: dict[str, Any]) -> str:
    title = html.escape(str(experiment.get("name") or "experiment"))
    cards = [
        ("Adapter", experiment.get("adapter")),
        ("Topology", experiment.get("topology")),
        ("Cluster runtime", experiment.get("cluster_runtime")),
        ("Timestamp", experiment.get("timestamp")),
        ("Dashboard status", experiment.get("result")),
    ]
    cards_html = "\n".join(
        f"<article class='card'><span>{html.escape(label)}</span><strong>{html.escape(str(value or 'unknown'))}</strong></article>"
        for label, value in cards
    )
    playwright_html = _render_playwright_links(experiment)
    suites_html = _render_suite_summaries(experiment)
    artifacts_html = _render_artifact_links(experiment)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} - Framework report</title>
  <style>
    :root {{
      --ink: #18212f;
      --muted: #667085;
      --paper: #f7f4ee;
      --panel: #fffaf0;
      --line: #dccfb9;
      --ok: #0f7a55;
      --warn: #a15c00;
      --fail: #b42318;
      --neutral: #475467;
      --accent: #145c66;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Aptos", "Segoe UI", sans-serif;
      background: radial-gradient(circle at top left, #e8f3ef, transparent 32rem), var(--paper);
      color: var(--ink);
      line-height: 1.5;
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 40px 24px 72px; }}
    header {{ margin-bottom: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(2rem, 4vw, 3.4rem); letter-spacing: -0.04em; }}
    h2 {{ margin: 32px 0 14px; font-size: 1.35rem; }}
    p {{ color: var(--muted); margin: 0; }}
    a {{ color: var(--accent); font-weight: 700; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
    .card, .section {{
      background: rgba(255, 250, 240, 0.92);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 14px 32px rgba(24, 33, 47, 0.08);
    }}
    .card {{ padding: 16px; }}
    .card span {{ display: block; color: var(--muted); font-size: 0.85rem; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 1.05rem; overflow-wrap: anywhere; }}
    .section {{ padding: 20px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.95rem; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 11px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; }}
    .badge {{ border-radius: 999px; display: inline-block; font-size: 0.8rem; font-weight: 800; padding: 4px 9px; }}
    .ok {{ background: #dcfae6; color: var(--ok); }}
    .warn {{ background: #fef0c7; color: var(--warn); }}
    .fail {{ background: #fee4e2; color: var(--fail); }}
    .neutral {{ background: #eef2f6; color: var(--neutral); }}
    .links {{ display: grid; gap: 10px; }}
    .link-card {{ background: #ffffffb8; border: 1px solid var(--line); border-radius: 14px; padding: 13px 14px; }}
    .small {{ color: var(--muted); font-size: 0.87rem; }}
    code {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 2px 6px; }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>{title}</h1>
    <p>Framework validation dashboard. Local, read-only entry point for this experiment.</p>
  </header>
  <section class="cards">{cards_html}</section>
  <section class="section">
    <h2>Playwright reports</h2>
    {playwright_html}
  </section>
  <section class="section">
    <h2>Suite summaries</h2>
    {suites_html}
  </section>
  <section class="section">
    <h2>Raw artifacts</h2>
    {artifacts_html}
  </section>
  <p class="small">Security note: this dashboard is generated from local artifacts and must be served on <code>127.0.0.1</code>.</p>
</main>
</body>
</html>
"""


def _render_playwright_links(experiment: dict[str, Any]) -> str:
    reports = experiment.get("playwright_reports") or []
    if not reports:
        return "<p>No Playwright HTML reports were detected for this experiment.</p>"
    items = []
    for report in reports:
        href = "../" + _safe_link(str(report.get("index") or ""))
        title = html.escape(str(report.get("title") or "Playwright report"))
        path = html.escape(str(report.get("path") or ""))
        items.append(f"<div class='link-card'><a href='{href}'>Open {title}</a><div class='small'>{path}</div></div>")
    return "<div class='links'>" + "\n".join(items) + "</div>"


def _render_suite_summaries(experiment: dict[str, Any]) -> str:
    suites = experiment.get("suites") or []
    if not suites:
        return "<p>No suite summaries were detected. Raw artifacts may still be available below.</p>"
    rows = []
    for suite in suites:
        title = html.escape(str(suite.get("title") or suite.get("kind") or "suite"))
        status = _badge(suite.get("status"))
        details = html.escape(_suite_details(suite))
        artifact_links = ", ".join(
            f"<a href='../{_safe_link(str(path))}'>{html.escape(Path(str(path)).name)}</a>"
            for path in suite.get("artifacts") or []
        )
        rows.append(f"<tr><td>{title}</td><td>{status}</td><td>{details}</td><td>{artifact_links}</td></tr>")
    return "<table><thead><tr><th>Suite</th><th>Status</th><th>Summary</th><th>Artifacts</th></tr></thead><tbody>" + "\n".join(rows) + "</tbody></table>"


def _suite_details(suite: dict[str, Any]) -> str:
    kind = suite.get("kind")
    if kind == "newman":
        assertions = suite.get("assertions") or {}
        checks = suite.get("checks") or {}
        return (
            f"Assertions: {assertions.get('passed', 0)} passed, {assertions.get('failed', 0)} failed. "
            f"Checks: {checks.get('passed', 0)} passed, {checks.get('failed', 0)} failed. "
            f"Report files: {suite.get('report_files', 0)}."
        )
    if kind == "kafka":
        summary = suite.get("summary") or {}
        latency = suite.get("average_latency_ms")
        throughput = suite.get("average_throughput")
        metrics = []
        if latency is not None:
            metrics.append(f"avg latency {latency} ms")
        if throughput is not None:
            metrics.append(f"avg throughput {throughput} msg/s")
        suffix = f" ({', '.join(metrics)})" if metrics else ""
        return f"Transfers: {summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed{suffix}."
    if kind in {"component", "component-report", "playwright-json"}:
        summary = suite.get("summary") or {}
        return (
            f"Total: {summary.get('total', 0)}, passed: {summary.get('passed', 0)}, "
            f"failed: {summary.get('failed', 0)}, skipped: {summary.get('skipped', 0)}."
        )
    if kind == "stability":
        snapshot_warnings = suite.get("snapshot_warnings", 0)
        return (
            f"New warnings: {suite.get('warnings', 0)}, existing snapshot warnings: {snapshot_warnings}, "
            f"blocking issues: {suite.get('blocking_issues', 0)}, "
            f"NodeNotReady delta: {suite.get('node_not_ready_delta', 0)}."
        )
    if kind == "une-0087":
        summary = suite.get("summary") or {}
        claim = "yes" if suite.get("certification_claim") else "no"
        return (
            f"Criteria: {summary.get('covered', 0)} covered, "
            f"{summary.get('partially_covered', 0)} partially covered, "
            f"{summary.get('not_covered', 0)} not covered. "
            f"Formal certification claim: {claim}."
        )
    return "Summary available in linked artifact."


def _render_artifact_links(experiment: dict[str, Any]) -> str:
    artifacts = experiment.get("artifacts") or []
    if not artifacts:
        return "<p>No standard raw artifacts were detected.</p>"
    rows = []
    for artifact in artifacts:
        title = html.escape(str(artifact.get("title") or artifact.get("path") or "artifact"))
        path = str(artifact.get("path") or "")
        rows.append(f"<tr><td><a href='../{_safe_link(path)}'>{title}</a></td><td><code>{html.escape(path)}</code></td></tr>")
    return "<table><thead><tr><th>Artifact</th><th>Path</th></tr></thead><tbody>" + "\n".join(rows) + "</tbody></table>"


def find_free_local_port(host: str = LOCAL_REPORT_HOST) -> int:
    if host != LOCAL_REPORT_HOST:
        raise ValueError("Report servers must bind to 127.0.0.1.")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def wait_for_local_server(host: str, port: int, *, timeout_seconds: float = 5.0) -> bool:
    """Wait until a local report server accepts TCP connections."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _register_report_process(process: subprocess.Popen) -> None:
    _REPORT_SERVER_PROCESSES.append(process)


def _cleanup_report_processes() -> None:
    for process in list(_REPORT_SERVER_PROCESSES):
        if process.poll() is None:
            process.terminate()


atexit.register(_cleanup_report_processes)


def launch_static_report_server(
    directory: str | Path,
    *,
    host: str = LOCAL_REPORT_HOST,
    port: int | None = None,
    subprocess_module=subprocess,
    python_executable: str | None = None,
    wait_for_server=wait_for_local_server,
) -> dict[str, Any]:
    if host != LOCAL_REPORT_HOST:
        raise ValueError("Report servers must bind to 127.0.0.1.")
    directory_path = Path(directory)
    if not directory_path.is_dir():
        raise FileNotFoundError(f"Report directory not found: {directory_path}")
    selected_port = port or find_free_local_port(host)
    command = [
        python_executable or sys.executable,
        "-m",
        "http.server",
        str(selected_port),
        "--bind",
        host,
        "--directory",
        str(directory_path),
    ]
    process = subprocess_module.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _register_report_process(process)
    ready = bool(wait_for_server(host, selected_port))
    return {
        "status": "started",
        "host": host,
        "port": selected_port,
        "url": f"http://{host}:{selected_port}",
        "directory": str(directory_path),
        "pid": getattr(process, "pid", None),
        "command": command,
        "ready": ready,
    }


def launch_playwright_report(
    report_dir: str | Path,
    *,
    root: str | Path | None = None,
    host: str = LOCAL_REPORT_HOST,
    port: int | None = None,
    subprocess_module=subprocess,
    wait_for_server=wait_for_local_server,
) -> dict[str, Any]:
    if host != LOCAL_REPORT_HOST:
        raise ValueError("Playwright reports must bind to 127.0.0.1.")
    report_path = Path(report_dir)
    if not report_path.is_dir() or not (report_path / "index.html").exists():
        raise FileNotFoundError(f"Playwright report not found: {report_path}")
    selected_port = port or find_free_local_port(host)
    cwd = Path(root or project_root()) / "validation" / "ui"
    command = [
        "npx",
        "playwright",
        "show-report",
        str(report_path),
        "--host",
        host,
        "--port",
        str(selected_port),
    ]
    process = subprocess_module.Popen(command, cwd=str(cwd))
    _register_report_process(process)
    ready = bool(wait_for_server(host, selected_port))
    return {
        "status": "started",
        "host": host,
        "port": selected_port,
        "url": f"http://{host}:{selected_port}",
        "directory": str(report_path),
        "pid": getattr(process, "pid", None),
        "command": command,
        "ready": ready,
    }


def try_open_local_url(url: str, *, subprocess_module=subprocess) -> bool:
    return bool(open_local_url(url, subprocess_module=subprocess_module).get("opened"))


def _windows_executable(path: Path) -> str | None:
    return str(path) if path.exists() else None


def _local_url_open_commands(url: str) -> list[dict[str, Any]]:
    commands = []
    wslview = shutil.which("wslview")
    if wslview:
        commands.append({"method": "wslview", "command": [wslview, url]})

    cmd_exe = shutil.which("cmd.exe") or _windows_executable(WINDOWS_CMD_EXE)
    if cmd_exe:
        commands.append({"method": "windows-cmd-start", "command": [cmd_exe, "/c", "start", "", url]})

    powershell = shutil.which("powershell.exe") or _windows_executable(WINDOWS_POWERSHELL_EXE)
    if powershell:
        commands.append(
            {
                "method": "windows-powershell-start-process",
                "command": [powershell, "-NoProfile", "-Command", "Start-Process", url],
            }
        )

    explorer = shutil.which("explorer.exe") or _windows_executable(WINDOWS_EXPLORER_EXE)
    if explorer:
        commands.append({"method": "windows-explorer", "command": [explorer, url]})

    xdg_open = shutil.which("xdg-open")
    if xdg_open:
        commands.append({"method": "xdg-open", "command": [xdg_open, url]})

    return commands


def open_local_url(url: str, *, subprocess_module=subprocess) -> dict[str, Any]:
    """Open a local report URL using the best available desktop bridge."""
    commands = _local_url_open_commands(url)
    if not commands:
        return {
            "opened": False,
            "method": None,
            "reason": "No desktop opener found. Install wslu/wslview or enable Windows interop.",
        }

    errors = []
    for candidate in commands:
        method = candidate["method"]
        command = candidate["command"]
        try:
            subprocess_module.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"opened": True, "method": method, "command": command}
        except Exception as exc:
            errors.append(f"{method}: {exc}")
    return {
        "opened": False,
        "method": None,
        "reason": "; ".join(errors) or "Desktop openers failed.",
    }
