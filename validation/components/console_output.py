from __future__ import annotations

import os
import sys
from typing import Any, Iterable, Mapping


STATUS_ICONS = {
    "passed": ("✓", "32"),
    "success": ("✓", "32"),
    "failed": ("✗", "31"),
    "error": ("✗", "31"),
    "skipped": ("-", "33"),
    "pending": ("-", "33"),
}
CHANNEL_LABELS = {
    "api": "API",
    "playwright": "Playwright",
}
COMPONENT_LABELS = {
    "ontology-hub": "Ontology Hub",
    "ai-model-hub": "AI Model Hub",
    "semantic-virtualization": "Semantic Virtualization",
}
PHASE_TYPE_LABELS = {
    "preflight": "Non-functional",
    "functional": "Functional",
    "integration": "Integration",
    "interoperability": "Interoperability",
}
STATUS_LABELS = {
    "passed": "passed",
    "success": "passed",
    "failed": "failed",
    "error": "failed",
    "skipped": "skipped",
    "pending": "skipped",
}
DEFAULT_TEST_INDENT = "  "
HEADER_COLOR = "33;1"
INTEROPERABILITY_COLOR = HEADER_COLOR


def _supports_color(stream=None) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    stream = stream or sys.stdout
    return bool(os.environ.get("FORCE_COLOR") or getattr(stream, "isatty", lambda: False)())


def _color(value: str, code: str, *, stream=None) -> str:
    if not _supports_color(stream=stream):
        return value
    return f"\033[{code}m{value}\033[0m"


def _case_status(case: Mapping[str, Any]) -> str:
    evaluation = case.get("evaluation") if isinstance(case.get("evaluation"), Mapping) else {}
    return str(
        evaluation.get("status")
        or case.get("status")
        or case.get("result")
        or "skipped"
    ).strip().lower()


def _case_label(case: Mapping[str, Any]) -> str:
    case_id = str(case.get("test_case_id") or case.get("case_id") or case.get("id") or "").strip()
    title = str(
        case.get("description")
        or case.get("expected_result")
        or case.get("name")
        or case.get("title")
        or ""
    ).strip()
    if case_id and title:
        normalized_title = title.lower()
        if normalized_title.startswith(case_id.lower()):
            return title
        return f"{case_id}: {title}"
    return case_id or title or "Unnamed component test"


def print_component_suite_header(title: str, channel: str | None = None) -> None:
    channel_key = str(channel or "").strip().lower()
    channel_label = CHANNEL_LABELS.get(channel_key)
    prefix = f"Component {channel_label} suite" if channel_label else "Component suite"
    print(f"\n{_color(f'{prefix}: {title}', HEADER_COLOR)}")


def print_interoperability_suite_header(title: str, channel: str | None = None) -> None:
    channel_value = str(channel or "").strip()
    channel_label = f" {channel_value}" if channel_value else ""
    print(f"\n{_color(f'Interoperability{channel_label} suite: {title}', INTEROPERABILITY_COLOR)}")


def _component_label(component: Any) -> str:
    key = str(component or "").strip()
    return COMPONENT_LABELS.get(key, key.replace("-", " ").title() or "Unknown component")


def _phase_type(phase: Any) -> str:
    phase_key = str(phase or "").strip().lower()
    return PHASE_TYPE_LABELS.get(phase_key, "Component")


def _summary_value(summary: Mapping[str, Any] | None, key: str) -> int:
    if not isinstance(summary, Mapping):
        return 0
    try:
        return int(summary.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _normalized_status(status: Any) -> str:
    return STATUS_LABELS.get(str(status or "").strip().lower(), str(status or "unknown").strip().lower() or "unknown")


def _status_label(status: Any) -> tuple[str, str]:
    normalized = _normalized_status(status)
    icon, color = STATUS_ICONS.get(normalized, ("?", "36"))
    raw = f"{icon} {normalized}"
    return raw, _color(raw, color)


def _format_channels(channels: Any) -> str:
    if isinstance(channels, str):
        candidates = [channels]
    elif isinstance(channels, Iterable):
        candidates = [str(channel) for channel in channels]
    else:
        candidates = []
    labels = []
    for channel in candidates:
        channel_key = channel.strip().lower()
        if not channel_key:
            continue
        labels.append(CHANNEL_LABELS.get(channel_key, channel_key.replace("-", " ").title()))
    return ", ".join(dict.fromkeys(labels)) or "n/a"


def _phase_channels(component_result: Mapping[str, Any], phase: str, phase_result: Mapping[str, Any]) -> str:
    phase_channels = component_result.get("phase_execution_channels")
    if isinstance(phase_channels, Mapping) and phase in phase_channels:
        return _format_channels(phase_channels.get(phase))

    explicit_channel = phase_result.get("execution_channel")
    if explicit_channel:
        return _format_channels(explicit_channel)

    suite_channels = []
    suites = phase_result.get("suites")
    if isinstance(suites, Mapping):
        for suite_result in suites.values():
            if isinstance(suite_result, Mapping):
                suite_channels.append(suite_result.get("execution_channel") or "unknown")
    return _format_channels(suite_channels)


def _component_summary_rows(component_results: Iterable[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for component_result in component_results or []:
        if not isinstance(component_result, Mapping):
            continue
        component = _component_label(component_result.get("component"))
        phases = component_result.get("phases")
        if isinstance(phases, Mapping) and phases:
            phase_order = list(component_result.get("phase_order") or phases.keys())
            for phase in phase_order:
                phase_result = phases.get(phase)
                if not isinstance(phase_result, Mapping):
                    continue
                summary = phase_result.get("summary") if isinstance(phase_result.get("summary"), Mapping) else {}
                status = phase_result.get("status")
                if not summary and _normalized_status(status) == "failed":
                    summary = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
                status_raw, status_rendered = _status_label(status)
                rows.append(
                    {
                        "component": component,
                        "type": _phase_type(phase),
                        "channel": _phase_channels(component_result, str(phase), phase_result),
                        "total": str(_summary_value(summary, "total")),
                        "passed": str(_summary_value(summary, "passed")),
                        "failed": str(_summary_value(summary, "failed")),
                        "skipped": str(_summary_value(summary, "skipped")),
                        "status": status_raw,
                        "status_rendered": status_rendered,
                    }
                )
            continue

        summary = component_result.get("summary") if isinstance(component_result.get("summary"), Mapping) else {}
        status = component_result.get("status")
        if not summary and _normalized_status(status) == "failed":
            summary = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
        status_raw, status_rendered = _status_label(status)
        rows.append(
            {
                "component": component,
                "type": "Component",
                "channel": _format_channels(component_result.get("execution_channel")),
                "total": str(_summary_value(summary, "total")),
                "passed": str(_summary_value(summary, "passed")),
                "failed": str(_summary_value(summary, "failed")),
                "skipped": str(_summary_value(summary, "skipped")),
                "status": status_raw,
                "status_rendered": status_rendered,
            }
        )
    return rows


def _fit(value: Any, width: int) -> str:
    text = str(value or "")
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return f"{text[: width - 3]}..."


def _print_table_row(cells: list[tuple[str, str]], widths: list[int]) -> None:
    parts = []
    for (raw_value, rendered_value), width in zip(cells, widths):
        raw = _fit(raw_value, width)
        rendered = rendered_value if raw == raw_value else raw
        parts.append(f"{rendered}{' ' * max(width - len(raw), 0)}")
    print(f"  {'  '.join(parts)}")


def print_component_case_result(case: Mapping[str, Any], *, indent: str = DEFAULT_TEST_INDENT) -> None:
    status = _case_status(case)
    icon, color = STATUS_ICONS.get(status, ("-", "33"))
    print(f"{indent}{_color(icon, color)} {_case_label(case)}")


def print_component_case_results(cases: Iterable[Mapping[str, Any]] | None, *, indent: str = DEFAULT_TEST_INDENT) -> None:
    for case in cases or []:
        print_component_case_result(case, indent=indent)


def print_component_validation_summary(component_results: Iterable[Mapping[str, Any]] | None) -> None:
    component_result_list = list(component_results or [])
    rows = _component_summary_rows(component_result_list)
    if not rows:
        return

    print(f"\n{_color('Component validation summary', HEADER_COLOR)}\n")
    columns = [
        ("component", "Component", 25),
        ("type", "Type", 16),
        ("channel", "Channel", 17),
        ("total", "Total", 5),
        ("passed", "Pass", 5),
        ("failed", "Fail", 5),
        ("skipped", "Skip", 5),
        ("status", "Status", 10),
    ]
    widths = [
        min(max(len(header), *(len(str(row.get(key, ""))) for row in rows)), max_width)
        for key, header, max_width in columns
    ]
    header_cells = [
        (header, _color(_fit(header, width), "36;1"))
        for (_, header, _), width in zip(columns, widths)
    ]
    _print_table_row(header_cells, widths)
    _print_table_row([("-" * width, _color("-" * width, "36")) for width in widths], widths)
    for row in rows:
        cells = []
        for key, _, _ in columns:
            raw = str(row.get(key, ""))
            rendered = str(row.get(f"{key}_rendered") or raw)
            cells.append((raw, rendered))
        _print_table_row(cells, widths)

    statuses = [_normalized_status(result.get("status")) for result in component_result_list if isinstance(result, Mapping)]
    total = len(statuses)
    passed = sum(1 for status in statuses if status == "passed")
    failed = sum(1 for status in statuses if status == "failed")
    skipped = sum(1 for status in statuses if status == "skipped")
    overall_status = "failed" if failed else "skipped" if skipped else "passed"
    label_color = {"passed": "32", "failed": "31", "skipped": "33"}.get(overall_status, "36")
    failed_color = "31" if failed else "32"
    skipped_color = "33"
    print(
        "\n"
        f"{_color('Components:', label_color)} "
        f"{_color(f'{passed}/{total} passed', '32')}, "
        f"{_color(f'{failed} failed', failed_color)}, "
        f"{_color(f'{skipped} skipped', skipped_color)}"
    )
