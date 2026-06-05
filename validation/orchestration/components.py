"""Optional component validation helpers for Level 6."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable


def configured_optional_components(deployer_config: dict[str, Any] | None) -> list[str]:
    raw = ((deployer_config or {}).get("COMPONENTS") or "").strip()
    if not raw:
        return []
    return [
        token.strip().lower().replace("_", "-")
        for token in raw.split(",")
        if token.strip()
    ]


def should_run_component_validation(
    components: list[str],
    *,
    env: dict[str, str],
    env_flag_enabled: Callable[[str, bool], bool],
) -> bool:
    if not components:
        return False

    if env.get("LEVEL6_RUN_COMPONENT_VALIDATION") is None:
        return True

    return env_flag_enabled("LEVEL6_RUN_COMPONENT_VALIDATION", True)


@contextmanager
def _component_auxiliary_environment(component_urls: dict[str, str]):
    auxiliary_env = {}
    mapping_editor_url = str(component_urls.get("semantic-virtualization-editor") or "").strip()
    if mapping_editor_url and not os.environ.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL"):
        auxiliary_env["SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL"] = mapping_editor_url

    previous_values = {key: os.environ.get(key) for key in auxiliary_env}
    try:
        os.environ.update(auxiliary_env)
        yield
    finally:
        for key, previous_value in previous_values.items():
            if previous_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous_value


def run_component_validations(
    components: list[str],
    *,
    infer_component_urls: Callable[[list[str]], dict[str, str]],
    run_component_validations_fn: Callable[..., list[dict[str, Any]]],
    experiment_dir: str,
) -> list[dict[str, Any]]:
    if not components:
        return []

    inferred_urls = infer_component_urls(components) or {}
    component_urls = {
        component: url
        for component, url in inferred_urls.items()
        if component in set(components)
    }
    with _component_auxiliary_environment(inferred_urls):
        results = run_component_validations_fn(component_urls, experiment_dir=experiment_dir)
    results = list(results or [])
    resolved_components = {result.get("component") for result in results}
    for component in components:
        if component not in resolved_components:
            results.append(
                {
                    "component": component,
                    "status": "skipped",
                    "reason": "component_url_not_inferred",
                    "timestamp": datetime.now().isoformat(),
                }
            )
    return results
