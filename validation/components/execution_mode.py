"""Component validation execution mode helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping


API_ONLY_VALUES = {"api", "api-only", "api_only", "apis", "rest"}


def component_adapter_name(env: Mapping[str, str] | None = None) -> str:
    values = env if env is not None else os.environ
    return str(
        values.get("PIONERA_ADAPTER")
        or values.get("AI_MODEL_HUB_COMPONENT_ADAPTER")
        or values.get("UI_ADAPTER")
        or ""
    ).strip().lower()


def component_api_only_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    for name in (
        "PIONERA_COMPONENT_VALIDATION_MODE",
        "LEVEL6_COMPONENT_VALIDATION_MODE",
        "COMPONENT_VALIDATION_MODE",
    ):
        raw_value = values.get(name)
        if raw_value is not None:
            return str(raw_value).strip().lower().replace("-", "_") in {
                value.replace("-", "_") for value in API_ONLY_VALUES
            }
    return False
