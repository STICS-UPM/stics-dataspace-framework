from __future__ import annotations

import atexit
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from validation.orchestration.suite_taxonomy import (
    classify_playwright_spec,
    classify_suite_artifact,
    suite_sort_key,
    summarize_group_taxonomy,
)


EXPERIMENT_PREFIX = "experiment_"
FRAMEWORK_REPORT_DIR = "framework-report"
LOCAL_REPORT_HOST = "127.0.0.1"
WINDOWS_CMD_EXE = Path("/mnt/c/Windows/System32/cmd.exe")
WINDOWS_EXPLORER_EXE = Path("/mnt/c/Windows/explorer.exe")
WINDOWS_POWERSHELL_EXE = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
_REPORT_SERVER_PROCESSES: list[subprocess.Popen] = []
LEVEL6_CONSOLE_LOG_FILENAME = "level6_console.log"
NEWMAN_CONSOLE_LOG_FILENAME = "newman_console.log"
KAFKA_CONSOLE_LOG_FILENAME = "kafka_console.log"
CONSOLE_LOG_ARTIFACTS = (
    {
        "filename": LEVEL6_CONSOLE_LOG_FILENAME,
        "title": "Level 6 console log",
    },
    {
        "filename": NEWMAN_CONSOLE_LOG_FILENAME,
        "title": "Newman interoperability console log",
    },
    {
        "filename": KAFKA_CONSOLE_LOG_FILENAME,
        "title": "Kafka interoperability console log",
    },
)
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
ANSI_SGR_RE = re.compile(r"\x1B\[([0-9;]*)m")
PLAYWRIGHT_TEST_BEGIN_RE = re.compile(r"^\s*›\s+(?P<title>.+?)\s*$")
PLAYWRIGHT_TEST_END_RE = re.compile(r"^\s*(?:✓|✗|-)\s+(?P<title>.+?)\s*$")
DASHBOARD_SUITE_HEADER_RE = re.compile(
    r"^\s*(?:Suite|Group|Component suite|Component API suite|Component Playwright suite|"
    r"Interoperability(?: [^:]+)? suite):\s+.+"
)
DASHBOARD_STATUS_PREFIX_RE = re.compile(
    r"^(?P<control>(?:\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]))*)"
    r"(?P<indent>\s*)(?P<icon>✓|✗|-|›)(?P<spacing>\s+)(?P<text>.+)$"
)
ANSI_HAS_SGR_RE = re.compile(r"\x1B\[[0-9;]*m")
ANSI_FG_CLASSES = {
    30: "ansi-fg-black",
    31: "ansi-fg-red",
    32: "ansi-fg-green",
    33: "ansi-fg-yellow",
    34: "ansi-fg-blue",
    35: "ansi-fg-magenta",
    36: "ansi-fg-cyan",
    37: "ansi-fg-white",
    90: "ansi-fg-bright-black",
    91: "ansi-fg-bright-red",
    92: "ansi-fg-bright-green",
    93: "ansi-fg-bright-yellow",
    94: "ansi-fg-bright-blue",
    95: "ansi-fg-bright-magenta",
    96: "ansi-fg-bright-cyan",
    97: "ansi-fg-bright-white",
}
ANSI_BG_CLASSES = {
    40: "ansi-bg-black",
    41: "ansi-bg-red",
    42: "ansi-bg-green",
    43: "ansi-bg-yellow",
    44: "ansi-bg-blue",
    45: "ansi-bg-magenta",
    46: "ansi-bg-cyan",
    47: "ansi-bg-white",
    100: "ansi-bg-bright-black",
    101: "ansi-bg-bright-red",
    102: "ansi-bg-bright-green",
    103: "ansi-bg-bright-yellow",
    104: "ansi-bg-bright-blue",
    105: "ansi-bg-bright-magenta",
    106: "ansi-bg-bright-cyan",
    107: "ansi-bg-bright-white",
}


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


def _summary_count(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _summary_status(summary: dict[str, Any], fallback: Any = None) -> str:
    """Return the dashboard status implied by test counters."""

    normalized_fallback = str(fallback or "").strip().lower()
    if normalized_fallback in {"failed", "fail", "error", "terminated"}:
        return "failed"

    failed = _summary_count(summary, "failed")
    skipped = _summary_count(summary, "skipped")
    other = _summary_count(summary, "other")
    total = _summary_count(summary, "total")

    if failed:
        return "failed"
    if skipped:
        return "skipped"
    if other:
        return "partial"
    if total:
        return "passed"
    return normalized_fallback or "unknown"


def _with_suite_taxonomy(suite: dict[str, Any]) -> dict[str, Any]:
    if suite.get("audit_suite") and suite.get("audit_group"):
        return suite
    taxonomy = classify_suite_artifact(
        kind=suite.get("kind"),
        title=suite.get("title"),
        artifacts=list(suite.get("artifacts") or []),
    )
    return {**suite, **taxonomy}


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
        "status": _summary_status(summary),
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
                "title": str(payload.get("display_name") or payload.get("component") or path.parent.name),
                "status": _summary_status(summary, payload.get("status")),
                "summary": {
                    "total": summary.get("total", 0),
                    "passed": summary.get("passed", 0),
                    "failed": summary.get("failed", 0),
                    "skipped": summary.get("skipped", 0),
                },
                "phase_execution_channels": payload.get("phase_execution_channels"),
                "suite_execution_channels": payload.get("suite_execution_channels"),
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
                "status": _summary_status(summary, payload.get("status")),
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
        relative_parent = _relative(path.parent, experiment_path)
        stats = _playwright_stats(payload, source_path=relative_parent)
        taxonomy = summarize_group_taxonomy(list(stats.get("groups") or []))
        summaries.append(
            {
                "kind": "playwright-json",
                "title": _display_name_from_path(relative_parent),
                "status": _summary_status(stats),
                "summary": stats,
                "artifacts": [_relative(path, experiment_path)],
                **taxonomy,
            }
        )
    return summaries


def _playwright_status_bucket(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"expected", "passed"}:
        return "passed"
    if normalized in {"unexpected", "failed", "timedout", "interrupted"}:
        return "failed"
    if normalized in {"skipped"}:
        return "skipped"
    return "other"


def _increment_playwright_stats(stats: dict[str, int], status: str) -> None:
    stats["total"] += 1
    stats[_playwright_status_bucket(status)] += 1


def _playwright_stats(payload: dict[str, Any], *, source_path: str = "") -> dict[str, Any]:
    stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "other": 0}
    group_stats: dict[tuple[str, str], dict[str, Any]] = {}

    def group_for_spec(spec: dict[str, Any], suite_file: str | None) -> dict[str, Any]:
        spec_file = spec.get("file") or suite_file or spec.get("title") or source_path
        taxonomy = classify_playwright_spec(spec_file, source_path=source_path)
        key = (taxonomy["audit_suite"], taxonomy["audit_group"])
        if key not in group_stats:
            group_stats[key] = {
                **taxonomy,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "other": 0,
            }
        return group_stats[key]

    def walk_suite(suite: dict[str, Any], suite_file: str | None = None) -> None:
        current_suite_file = suite.get("file") or suite_file or suite.get("title")
        for spec in suite.get("specs") or []:
            if not isinstance(spec, dict):
                continue
            spec_group = group_for_spec(spec, current_suite_file)
            for test in spec.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                status = str(test.get("status") or "").strip().lower()
                _increment_playwright_stats(stats, status)
                _increment_playwright_stats(spec_group, status)
        for child in suite.get("suites") or []:
            if isinstance(child, dict):
                walk_suite(child, current_suite_file)

    for suite in payload.get("suites") or []:
        if isinstance(suite, dict):
            walk_suite(suite)
    stats["groups"] = sorted(group_stats.values(), key=suite_sort_key)
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
        *[artifact["filename"] for artifact in CONSOLE_LOG_ARTIFACTS],
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
        *[artifact["filename"] for artifact in CONSOLE_LOG_ARTIFACTS],
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


def _strip_ansi_sequences(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def _plain_console_line(value: str) -> str:
    line = _strip_ansi_sequences(value)
    line = line.replace("\r", "").replace("\b", "")
    return re.sub(r"\s+", " ", line).strip()


def _playwright_progress_title(line: str) -> str | None:
    match = PLAYWRIGHT_TEST_BEGIN_RE.match(_plain_console_line(line))
    if not match:
        return None
    return match.group("title").strip()


def _playwright_result_title(line: str) -> str | None:
    match = PLAYWRIGHT_TEST_END_RE.match(_plain_console_line(line))
    if not match:
        return None
    return match.group("title").strip()


def _dashboard_line_has_sgr(line: str) -> bool:
    return bool(ANSI_HAS_SGR_RE.search(line))


def _dashboard_is_component_suite_header(line: str) -> bool:
    plain = _plain_console_line(line)
    return plain.startswith(("Component suite:", "Component API suite:", "Component Playwright suite:"))


def _dashboard_is_interoperability_suite_header(line: str) -> bool:
    plain = _plain_console_line(line)
    return plain.startswith(("Interoperability ", "Interoperability suite:"))


def _dashboard_is_interoperability_suite_footer(line: str) -> bool:
    return _plain_console_line(line).startswith("End interoperability suite:")


def _dashboard_is_suite_header(line: str) -> bool:
    return bool(DASHBOARD_SUITE_HEADER_RE.match(_plain_console_line(line)))


def _dashboard_has_result_prefix(line: str) -> bool:
    return bool(DASHBOARD_STATUS_PREFIX_RE.match(_plain_console_line(line)))


def _dashboard_component_headers_to_hide(lines: list[str]) -> set[int]:
    hidden: set[int] = set()
    component_header_indices = [
        index for index, line in enumerate(lines) if _dashboard_is_component_suite_header(line)
    ]
    for position, index in enumerate(component_header_indices):
        next_index = component_header_indices[position + 1] if position + 1 < len(component_header_indices) else len(lines)
        block = lines[index + 1 : next_index]
        plain_header = _plain_console_line(lines[index])
        has_artifact_suite_header = any(_plain_console_line(line).startswith("Suite:") for line in block)
        has_direct_result = any(_dashboard_has_result_prefix(line) for line in block)
        if not has_direct_result:
            hidden.add(index)
        elif has_artifact_suite_header and plain_header.startswith("Component suite:"):
            hidden.add(index)
    return hidden


def _dashboard_colorize_plain_line(line: str) -> str:
    """Apply stable dashboard colors when a raw console line has no SGR color."""
    if not line or _dashboard_line_has_sgr(line):
        return line

    plain = _plain_console_line(line)
    if not plain:
        return line

    if (
        _dashboard_is_component_suite_header(plain)
        or _dashboard_is_interoperability_suite_header(plain)
        or plain == "Component validation summary"
    ):
        return f"\033[33;1m{line}\033[0m"

    if plain.startswith("Components:"):
        if " failed" in plain and not re.search(r"\b0 failed\b", plain):
            return f"\033[31m{line}\033[0m"
        if " skipped" in plain and not re.search(r"\b0 skipped\b", plain):
            return f"\033[33m{line}\033[0m"
        return f"\033[32m{line}\033[0m"

    if DASHBOARD_SUITE_HEADER_RE.match(plain):
        return f"\033[36;1m{line}\033[0m"

    status_match = DASHBOARD_STATUS_PREFIX_RE.match(line)
    if not status_match:
        return line

    icon = status_match.group("icon")
    color = {
        "✓": "32",
        "✗": "31",
        "-": "33",
        "›": "36",
    }.get(icon)
    if not color:
        return line
    return (
        f"{status_match.group('control')}{status_match.group('indent')}\033[{color}m{icon}\033[0m"
        f"{status_match.group('spacing')}{status_match.group('text')}"
    )


def _dashboard_console_content(value: str) -> tuple[str, int]:
    """Return a complete static rendering of the console log for audit review."""
    if not value:
        return value, 0

    project_root_prefix = f"{project_root().as_posix().rstrip('/')}/"
    normalized = value.replace("\r", "\n")
    raw_lines = normalized.split("\n")
    hidden_component_headers = _dashboard_component_headers_to_hide(raw_lines)
    completed_titles = {
        title
        for title in (_playwright_result_title(line) for line in raw_lines)
        if title
    }
    rendered_lines: list[str] = []
    hidden_progress_lines = 0

    for index, line in enumerate(raw_lines):
        line = line.replace(project_root_prefix, "")
        if _dashboard_is_interoperability_suite_footer(line):
            continue

        if index in hidden_component_headers:
            continue

        progress_title = _playwright_progress_title(line)
        if progress_title and progress_title in completed_titles:
            hidden_progress_lines += 1
            continue

        colored_line = _dashboard_colorize_plain_line(line)
        if _dashboard_is_suite_header(line) and rendered_lines and rendered_lines[-1] != "":
            rendered_lines.append("")
        rendered_lines.append(colored_line)

    return "\n".join(rendered_lines), hidden_progress_lines


def _ansi_style_classes(style: dict[str, Any]) -> list[str]:
    classes = []
    if style.get("bold"):
        classes.append("ansi-bold")
    if style.get("dim"):
        classes.append("ansi-dim")
    if style.get("underline"):
        classes.append("ansi-underline")
    fg_class = style.get("fg")
    bg_class = style.get("bg")
    if fg_class:
        classes.append(fg_class)
    if bg_class:
        classes.append(bg_class)
    return classes


def _ansi_256_to_hex(value: int) -> str | None:
    palette = [
        "#000000",
        "#800000",
        "#008000",
        "#808000",
        "#000080",
        "#800080",
        "#008080",
        "#c0c0c0",
        "#808080",
        "#ff0000",
        "#00ff00",
        "#ffff00",
        "#0000ff",
        "#ff00ff",
        "#00ffff",
        "#ffffff",
    ]
    if 0 <= value < len(palette):
        return palette[value]
    if 16 <= value <= 231:
        value -= 16
        red = value // 36
        green = (value % 36) // 6
        blue = value % 6
        levels = [0, 95, 135, 175, 215, 255]
        return f"#{levels[red]:02x}{levels[green]:02x}{levels[blue]:02x}"
    if 232 <= value <= 255:
        level = 8 + (value - 232) * 10
        return f"#{level:02x}{level:02x}{level:02x}"
    return None


def _ansi_style_attribute(style: dict[str, Any]) -> str:
    declarations = []
    if style.get("fg_rgb"):
        declarations.append(f"color: {style['fg_rgb']}")
    if style.get("bg_rgb"):
        declarations.append(f"background-color: {style['bg_rgb']}")
    return "; ".join(declarations)


def _apply_ansi_sgr(style: dict[str, Any], params: list[int]) -> None:
    if not params:
        params = [0]
    index = 0
    while index < len(params):
        code = params[index]
        if code == 0:
            style.clear()
        elif code == 1:
            style["bold"] = True
        elif code == 2:
            style["dim"] = True
        elif code == 4:
            style["underline"] = True
        elif code in {22, 21}:
            style.pop("bold", None)
            style.pop("dim", None)
        elif code == 24:
            style.pop("underline", None)
        elif code == 39:
            style.pop("fg", None)
            style.pop("fg_rgb", None)
        elif code == 49:
            style.pop("bg", None)
            style.pop("bg_rgb", None)
        elif code in ANSI_FG_CLASSES:
            style["fg"] = ANSI_FG_CLASSES[code]
            style.pop("fg_rgb", None)
        elif code in ANSI_BG_CLASSES:
            style["bg"] = ANSI_BG_CLASSES[code]
            style.pop("bg_rgb", None)
        elif code in {38, 48}:
            target = "fg_rgb" if code == 38 else "bg_rgb"
            class_target = "fg" if code == 38 else "bg"
            if index + 2 < len(params) and params[index + 1] == 5:
                color = _ansi_256_to_hex(params[index + 2])
                if color:
                    style[target] = color
                    style.pop(class_target, None)
                index += 2
            elif index + 4 < len(params) and params[index + 1] == 2:
                red, green, blue = params[index + 2 : index + 5]
                if all(0 <= item <= 255 for item in (red, green, blue)):
                    style[target] = f"#{red:02x}{green:02x}{blue:02x}"
                    style.pop(class_target, None)
                index += 4
        index += 1


def _ansi_to_html(value: str) -> str:
    if not value:
        return ""
    parts: list[str] = []
    style: dict[str, Any] = {}
    span_open = False
    cursor = 0

    def close_span() -> None:
        nonlocal span_open
        if span_open:
            parts.append("</span>")
            span_open = False

    def open_span() -> None:
        nonlocal span_open
        classes = _ansi_style_classes(style)
        style_attribute = _ansi_style_attribute(style)
        if classes or style_attribute:
            attributes = []
            if classes:
                attributes.append(f"class='{' '.join(classes)}'")
            if style_attribute:
                attributes.append(f"style='{html.escape(style_attribute, quote=True)}'")
            parts.append(f"<span {' '.join(attributes)}>")
            span_open = True

    for match in ANSI_ESCAPE_RE.finditer(value):
        parts.append(html.escape(value[cursor : match.start()]))
        sequence = match.group(0)
        sgr_match = ANSI_SGR_RE.fullmatch(sequence)
        if sgr_match:
            close_span()
            params = [int(item) for item in sgr_match.group(1).split(";") if item != ""]
            _apply_ansi_sgr(style, params)
            open_span()
        cursor = match.end()

    parts.append(html.escape(value[cursor:]))
    close_span()
    return "".join(parts)


def _line_count(value: str) -> int:
    if not value:
        return 0
    return value.count("\n") + (0 if value.endswith("\n") else 1)


def _read_console_log_summary(experiment_path: Path, filename: str, title: str) -> dict[str, Any] | None:
    path = experiment_path / filename
    if not path.is_file():
        return None
    try:
        raw_content = path.read_text(encoding="utf-8", errors="replace")
        size_bytes = path.stat().st_size
    except OSError:
        return None
    content = _strip_ansi_sequences(raw_content)
    return {
        "title": title,
        "path": filename,
        "content": content,
        "ansi_content": raw_content,
        "line_count": _line_count(content),
        "size_bytes": size_bytes,
    }


def _console_log_summaries(experiment_path: Path) -> list[dict[str, Any]]:
    logs = []
    for artifact in CONSOLE_LOG_ARTIFACTS:
        summary = _read_console_log_summary(
            experiment_path,
            artifact["filename"],
            artifact["title"],
        )
        if summary:
            logs.append(summary)
    return logs


def _console_log_summary(experiment_path: Path) -> dict[str, Any] | None:
    logs = _console_log_summaries(experiment_path)
    return logs[0] if logs else None


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
    suites = [_with_suite_taxonomy(suite) for suite in suites]

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
    console_logs = _console_log_summaries(experiment_path)
    if console_logs:
        report_kinds.append("Console")

    result = "No failed suites detected"
    if any(str(suite.get("status")).lower() in {"failed", "error"} for suite in suites):
        result = "Issues detected"
    elif any(str(suite.get("status")).lower() in {"warning", "warning-existing"} for suite in suites):
        result = "Warnings detected"
    elif any(str(suite.get("status")).lower() in {"skipped", "partial"} for suite in suites):
        result = "Partial"
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
        "console_log": console_logs[0] if console_logs else None,
        "console_logs": console_logs,
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
    elif normalized in {"warning", "warning-existing", "warnings detected", "partial"}:
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
    console_log_html = _render_console_log(experiment)
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
    main {{ width: min(100%, 1680px); margin: 0 auto; padding: 32px clamp(16px, 2vw, 36px) 72px; }}
    header {{ margin-bottom: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 2.4rem; letter-spacing: 0; }}
    h2 {{ margin: 32px 0 14px; font-size: 1.35rem; }}
    h3 {{ margin: 18px 0 10px; font-size: 1.02rem; }}
    p {{ color: var(--muted); margin: 0; }}
    a {{ color: var(--accent); font-weight: 700; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
    .card, .section {{
      background: rgba(255, 250, 240, 0.92);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 14px 32px rgba(24, 33, 47, 0.08);
    }}
    .card {{ padding: 16px; }}
    .card span {{ display: block; color: var(--muted); font-size: 0.85rem; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 1.05rem; overflow-wrap: anywhere; }}
    .section {{ overflow-x: auto; padding: 20px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.95rem; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 11px 8px; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; }}
    .badge {{ border-radius: 999px; display: inline-block; font-size: 0.8rem; font-weight: 800; padding: 4px 9px; }}
    .ok {{ background: #dcfae6; color: var(--ok); }}
    .warn {{ background: #fef0c7; color: var(--warn); }}
    .fail {{ background: #fee4e2; color: var(--fail); }}
    .neutral {{ background: #eef2f6; color: var(--neutral); }}
    .links {{ display: grid; gap: 10px; }}
    .link-card {{ background: #ffffffb8; border: 1px solid var(--line); border-radius: 8px; padding: 13px 14px; }}
    .small {{ color: var(--muted); font-size: 0.87rem; }}
    code {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 2px 6px; }}
    .console-meta {{ align-items: center; display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; margin-bottom: 12px; }}
    .console-log {{
      background: #101318;
      border: 1px solid #252c36;
      border-radius: 10px;
      color: #d7dde8;
      font: 0.86rem/1.5 "Cascadia Mono", "Consolas", "Menlo", monospace;
      margin: 0;
      min-height: 96px;
      overflow: visible;
      overflow-wrap: anywhere;
      padding: 16px;
      tab-size: 2;
      white-space: pre-wrap;
      width: 100%;
    }}
    .ansi-bold {{ font-weight: 800; }}
    .ansi-dim {{ opacity: 0.72; }}
    .ansi-underline {{ text-decoration: underline; }}
    .ansi-fg-black {{ color: #101318; }}
    .ansi-fg-red {{ color: #ff6b6b; }}
    .ansi-fg-green {{ color: #6ee7a8; }}
    .ansi-fg-yellow {{ color: #f8d66d; }}
    .ansi-fg-blue {{ color: #7fb4ff; }}
    .ansi-fg-magenta {{ color: #f0a6ff; }}
    .ansi-fg-cyan {{ color: #67e8f9; }}
    .ansi-fg-white {{ color: #f2f4f7; }}
    .ansi-fg-bright-black {{ color: #98a2b3; }}
    .ansi-fg-bright-red {{ color: #ff8787; }}
    .ansi-fg-bright-green {{ color: #86efac; }}
    .ansi-fg-bright-yellow {{ color: #fde68a; }}
    .ansi-fg-bright-blue {{ color: #93c5fd; }}
    .ansi-fg-bright-magenta {{ color: #f5b8ff; }}
    .ansi-fg-bright-cyan {{ color: #a5f3fc; }}
    .ansi-fg-bright-white {{ color: #ffffff; }}
    .ansi-bg-black {{ background: #101318; }}
    .ansi-bg-red {{ background: #7f1d1d; }}
    .ansi-bg-green {{ background: #14532d; }}
    .ansi-bg-yellow {{ background: #713f12; }}
    .ansi-bg-blue {{ background: #1e3a8a; }}
    .ansi-bg-magenta {{ background: #581c87; }}
    .ansi-bg-cyan {{ background: #164e63; }}
    .ansi-bg-white {{ background: #f2f4f7; color: #101318; }}
    .ansi-bg-bright-black {{ background: #344054; }}
    .ansi-bg-bright-red {{ background: #b42318; }}
    .ansi-bg-bright-green {{ background: #027a48; }}
    .ansi-bg-bright-yellow {{ background: #b54708; }}
    .ansi-bg-bright-blue {{ background: #175cd3; }}
    .ansi-bg-bright-magenta {{ background: #9e77ed; }}
    .ansi-bg-bright-cyan {{ background: #0891b2; }}
    .ansi-bg-bright-white {{ background: #ffffff; color: #101318; }}
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
    <h2>Console logs</h2>
    {console_log_html}
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
        taxonomy = classify_suite_artifact(
            kind="playwright-report",
            title=report.get("title"),
            artifacts=[report.get("index") or report.get("path") or ""],
        )
        audit_context = html.escape(f"{taxonomy['audit_suite']} / {taxonomy['audit_group']}")
        items.append(
            f"<div class='link-card'><a href='{href}'>Open {title}</a>"
            f"<div class='small'>{audit_context} · {path}</div></div>"
        )
    return "<div class='links'>" + "\n".join(items) + "</div>"


def _render_suite_summaries(experiment: dict[str, Any]) -> str:
    suites = experiment.get("suites") or []
    if not suites:
        return "<p>No suite summaries were detected. Raw artifacts may still be available below.</p>"
    rows = []
    for suite in sorted(suites, key=suite_sort_key):
        audit_suite = html.escape(str(suite.get("audit_suite") or "Unclassified"))
        audit_group = html.escape(str(suite.get("audit_group") or "Review"))
        title = html.escape(str(suite.get("title") or suite.get("kind") or "suite"))
        status = _badge(suite.get("status"))
        details = html.escape(_suite_details(suite))
        artifact_links = ", ".join(
            f"<a href='../{_safe_link(str(path))}'>{html.escape(Path(str(path)).name)}</a>"
            for path in suite.get("artifacts") or []
        )
        rows.append(
            f"<tr><td>{audit_suite}</td><td>{audit_group}</td><td>{title}</td>"
            f"<td>{status}</td><td>{details}</td><td>{artifact_links}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Audit suite</th><th>Group</th><th>Artifact suite</th>"
        "<th>Status</th><th>Summary</th><th>Artifacts</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )


def _format_execution_channels(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    labels = []
    for phase, channels in value.items():
        if isinstance(channels, str):
            channel_values = [channels]
        elif isinstance(channels, (list, tuple, set)):
            channel_values = list(channels)
        else:
            channel_values = []
        clean_channels = [
            str(channel).strip()
            for channel in channel_values
            if str(channel or "").strip()
        ]
        if not clean_channels:
            continue
        display = ", ".join(
            channel.upper() if channel.lower() == "api" else channel.title()
            for channel in clean_channels
        )
        labels.append(f"{phase}: {display}")
    return "; ".join(labels)


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
        details = (
            f"Total: {summary.get('total', 0)}, passed: {summary.get('passed', 0)}, "
            f"failed: {summary.get('failed', 0)}, skipped: {summary.get('skipped', 0)}."
        )
        channel_details = _format_execution_channels(suite.get("phase_execution_channels"))
        if channel_details:
            details += f" Channels: {channel_details}."
        groups = list(summary.get("groups") or [])
        if kind == "playwright-json" and groups:
            group_labels = [
                f"{group.get('audit_group')}: {group.get('passed', 0)}/{group.get('total', 0)} passed"
                for group in groups
            ]
            details += f" Groups: {'; '.join(group_labels)}."
        return details
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


def _render_single_console_log(console_log: dict[str, Any]) -> str:
    title = str(console_log.get("title") or "Console log")
    content = str(console_log.get("content") or "")
    if not content:
        content = "(empty console log)"
    ansi_content = str(console_log.get("ansi_content") or content)
    path = str(console_log.get("path") or LEVEL6_CONSOLE_LOG_FILENAME)
    line_count = int(console_log.get("line_count") or 0)
    size_bytes = int(console_log.get("size_bytes") or 0)
    dashboard_content, hidden_progress_lines = _dashboard_console_content(ansi_content)
    dashboard_line_count = _line_count(_strip_ansi_sequences(dashboard_content))
    meta = f"{dashboard_line_count} displayed lines, raw: {line_count} lines, {size_bytes} bytes"
    if hidden_progress_lines:
        suffix = "line" if hidden_progress_lines == 1 else "lines"
        meta += f"; hidden {hidden_progress_lines} transient Playwright start {suffix}"
    rendered_content = _ansi_to_html(dashboard_content)
    return (
        f"<h3>{html.escape(title)}</h3>"
        "<div class='console-meta'>"
        f"<span class='small'>{html.escape(meta)}</span>"
        f"<a href='../{_safe_link(path)}'>Open raw {html.escape(Path(path).name)}</a>"
        "</div>"
        f"<pre class='console-log'>{rendered_content}</pre>"
    )


def _render_console_log(experiment: dict[str, Any]) -> str:
    console_logs = list(experiment.get("console_logs") or [])
    if not console_logs and experiment.get("console_log"):
        console_logs = [experiment["console_log"]]
    if not console_logs:
        return "<p>No console log was detected for this experiment.</p>"
    return "\n".join(_render_single_console_log(console_log) for console_log in console_logs)


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


def wsl_file_url_for_path(path: str | os.PathLike[str]) -> str | None:
    distro_name = (
        os.environ.get("PIONERA_WSL_DISTRO_NAME")
        or os.environ.get("WSL_DISTRO_NAME")
        or ""
    ).strip()
    if not distro_name:
        return None

    absolute_path = os.path.abspath(os.fspath(path))
    if not absolute_path.startswith("/"):
        return None

    encoded_distro = quote(distro_name, safe="")
    encoded_path = "/".join(quote(part, safe="") for part in absolute_path.split("/") if part)
    return f"file://wsl.localhost/{encoded_distro}/{encoded_path}"


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
