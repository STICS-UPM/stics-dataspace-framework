"""Fail-fast helpers shared by Level 6 component validation runners."""

from __future__ import annotations

import os
from collections.abc import Mapping


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def component_fail_fast_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return component_fail_fast_enabled_from_stop_flag(values)


def playwright_max_failures_args(env: Mapping[str, str] | None = None) -> list[str]:
    values = env if env is not None else os.environ
    for name in ("PIONERA_PLAYWRIGHT_MAX_FAILURES", "PLAYWRIGHT_MAX_FAILURES"):
        raw_value = values.get(name)
        if raw_value is None:
            continue
        try:
            count = int(str(raw_value).strip())
        except ValueError:
            count = 1 if str(raw_value).strip() else 0
        if count > 0:
            return ["--max-failures", str(count)]

    if component_fail_fast_enabled_from_stop_flag(values):
        return ["--max-failures", "1"]
    return []


def component_fail_fast_enabled_from_stop_flag(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    for name in (
        "PIONERA_LEVEL6_STOP_ON_PLAYWRIGHT_FAILURE",
        "LEVEL6_STOP_ON_PLAYWRIGHT_FAILURE",
    ):
        if _truthy(values.get(name)):
            return True
    return False
