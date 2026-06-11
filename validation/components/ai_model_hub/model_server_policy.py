from __future__ import annotations

import os
from typing import Any, Mapping

from deployers.shared.lib import ai_model_hub_model_server as model_server_config


LOCAL_TOPOLOGY = "local"

FALSE_LIKE_VALUES = {"0", "false", "no", "n", "off", "disabled", "disable", "none", "skip"}
TRUE_LIKE_VALUES = {"1", "true", "yes", "y", "on", "enabled", "enable"}

MODEL_SERVER_ENABLED_KEYS = (
    "AI_MODEL_HUB_MODEL_SERVER_ENABLED",
    "LEVEL5_AI_MODEL_HUB_MODEL_SERVER_ENABLED",
)
MODEL_SERVER_MODE_KEYS = (
    "AI_MODEL_HUB_MODEL_SERVER_MODE",
    "LEVEL5_AI_MODEL_HUB_MODEL_SERVER_MODE",
    "MODEL_SERVER_MODE",
)
MODEL_SERVER_URL_KEYS = (
    "AI_MODEL_HUB_MODEL_EXECUTION_MODEL_URL",
    "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_URL",
    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
    "MODEL_SERVER_CONNECTOR_BASE_URL",
    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL",
    "MODEL_SERVER_CONNECTOR_URL",
    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
    "MODEL_SERVER_PUBLIC_URL",
    "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL",
    "UI_AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL",
    "AI_MODEL_HUB_MODEL_SERVER_BASE_URL",
    "MODEL_SERVER_BASE_URL",
    "UI_AI_MODEL_HUB_MODEL_SERVER_BASE_URL",
    "UI_AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
)


def _first_non_empty(values: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(values.get(key) or "").strip()
        if value:
            return value
    return ""


def _merged_values(
    config: Mapping[str, Any] | None = None,
    environ: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = dict(environ or os.environ)
    values.update(dict(config or {}))
    return values


def false_like(value: Any) -> bool:
    return str(value or "").strip().lower() in FALSE_LIKE_VALUES


def true_like(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUE_LIKE_VALUES


def configured_model_server_mode(
    config: Mapping[str, Any] | None = None,
    environ: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    values = _merged_values(config, environ)
    raw_mode = _first_non_empty(values, *MODEL_SERVER_MODE_KEYS)
    if not raw_mode:
        return "", ""
    if false_like(raw_mode):
        return "disabled", raw_mode
    return model_server_config.normalize_model_server_mode(raw_mode), raw_mode


def configured_model_server_enabled(
    config: Mapping[str, Any] | None = None,
    environ: Mapping[str, Any] | None = None,
) -> tuple[bool | None, str]:
    values = _merged_values(config, environ)
    raw_enabled = _first_non_empty(values, *MODEL_SERVER_ENABLED_KEYS)
    if not raw_enabled:
        return None, ""
    if false_like(raw_enabled):
        return False, raw_enabled
    if true_like(raw_enabled):
        return True, raw_enabled
    return False, raw_enabled


def explicit_model_server_url_configured(
    config: Mapping[str, Any] | None = None,
    environ: Mapping[str, Any] | None = None,
) -> bool:
    values = _merged_values(config, environ)
    return bool(_first_non_empty(values, *MODEL_SERVER_URL_KEYS))


def model_server_validation_state(
    config: Mapping[str, Any] | None = None,
    *,
    topology: str | None = None,
    environ: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    values = _merged_values(config, environ)
    normalized_topology = str(
        topology
        or values.get("AI_MODEL_HUB_MODEL_SERVER_TOPOLOGY")
        or values.get("AI_MODEL_HUB_MODEL_EXECUTION_TOPOLOGY")
        or values.get("PIONERA_TOPOLOGY")
        or values.get("INESDATA_TOPOLOGY")
        or values.get("TOPOLOGY")
        or LOCAL_TOPOLOGY
    ).strip().lower() or LOCAL_TOPOLOGY
    mode, raw_mode = configured_model_server_mode(values, {})
    enabled_flag, raw_enabled = configured_model_server_enabled(values, {})
    has_explicit_url = explicit_model_server_url_configured(values, {})

    if enabled_flag is False:
        enabled = False
        reason = f"AI Model Hub model-server disabled by configuration ({raw_enabled})"
    elif mode == "disabled":
        enabled = False
        reason = f"AI Model Hub model-server mode disables validation ({raw_mode})"
    elif enabled_flag is True:
        enabled = True
        reason = ""
    elif has_explicit_url:
        enabled = True
        reason = ""
    elif normalized_topology == LOCAL_TOPOLOGY:
        enabled = False
        reason = (
            "local topology does not deploy AI Model Hub model-server by default; "
            "enable AI_MODEL_HUB_MODEL_SERVER_ENABLED=true to run mock or real endpoint checks"
        )
    else:
        enabled = True
        reason = ""

    if enabled and not mode:
        mode = "mock" if enabled_flag is True and normalized_topology == LOCAL_TOPOLOGY else "external"
    if not enabled and not mode:
        mode = "disabled"

    return {
        "enabled": enabled,
        "mode": mode,
        "configured_mode": raw_mode,
        "enabled_flag": enabled_flag,
        "configured_enabled": raw_enabled,
        "has_explicit_url": has_explicit_url,
        "topology": normalized_topology,
        "skip_reason": reason,
    }


def model_server_execution_labels(mode: str | None) -> tuple[str, str]:
    normalized_mode = model_server_config.normalize_model_server_mode(mode or "external")
    if normalized_mode == "mock":
        return "api_mock_model_server", "automated_mock_model_server"
    if normalized_mode == "combined":
        return "api_combined_model_server", "automated_combined_model_server"
    if normalized_mode in {"use-cases", "external"}:
        return "api_model_server", "automated_real_model_server"
    return "api_model_server", "automated_model_server"
