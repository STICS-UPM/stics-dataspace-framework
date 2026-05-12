import json
from datetime import datetime
from typing import Dict, List

from validation.components.registry import (
    ComponentRunner,
    get_component_registration,
    registered_component_runners,
)


COMPONENT_RUNNERS: Dict[str, ComponentRunner] = registered_component_runners()


def run_component_validations(component_urls: Dict[str, str], experiment_dir: str | None = None) -> List[dict]:
    results: List[dict] = []
    for component, base_url in sorted((component_urls or {}).items()):
        registration = get_component_registration(component)
        runner = COMPONENT_RUNNERS.get(component)
        if runner is None:
            results.append(
                {
                    "component": component,
                    "base_url": base_url,
                    "status": "skipped",
                    "reason": "no_validator_registered",
                    "supported_adapters": list(registration.supported_adapters) if registration else [],
                    "timestamp": datetime.now().isoformat(),
                }
            )
            continue

        try:
            results.append(runner(base_url, experiment_dir=experiment_dir))
        except Exception as exc:  # pragma: no cover - defensive integration guard
            results.append(
                {
                    "component": component,
                    "base_url": base_url,
                    "status": "failed",
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "timestamp": datetime.now().isoformat(),
                }
            )
    return results


def summarize_component_results(component_results: List[dict]) -> dict:
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }
    for result in component_results or []:
        summary["total"] += 1
        status = (result.get("status") or "").lower()
        if status in summary:
            summary[status] += 1
    return summary


def dumps_component_results(component_results: List[dict]) -> str:
    return json.dumps(component_results or [], indent=2, ensure_ascii=False)
