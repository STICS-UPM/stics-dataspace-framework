"""Component validation execution mode helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping


API_ONLY_VALUES = {"api", "api-only", "api_only", "apis", "rest"}


def _component_env_prefix(component: str | None) -> str:
    return str(component or "").strip().upper().replace("-", "_")


def component_adapter_name(env: Mapping[str, str] | None = None) -> str:
    values = env if env is not None else os.environ
    return str(
        values.get("PIONERA_ADAPTER")
        or values.get("AI_MODEL_HUB_COMPONENT_ADAPTER")
        or values.get("UI_ADAPTER")
        or ""
    ).strip().lower()


def component_api_only_enabled(
    env: Mapping[str, str] | None = None,
    *,
    component: str | None = None,
) -> bool:
    values = env if env is not None else os.environ
    component_prefix = _component_env_prefix(component)
    component_env_names = ()
    if component_prefix:
        component_env_names = (
            f"PIONERA_{component_prefix}_COMPONENT_VALIDATION_MODE",
            f"{component_prefix}_COMPONENT_VALIDATION_MODE",
            f"{component_prefix}_VALIDATION_MODE",
        )
    for name in (
        *component_env_names,
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
