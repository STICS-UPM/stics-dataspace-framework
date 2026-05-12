from validation.components.semantic_virtualization.runner import (
    run_semantic_virtualization_validation,
)


def run_semantic_virtualization_component_validation(
    base_url: str,
    experiment_dir: str | None = None,
) -> dict:
    return run_semantic_virtualization_validation(base_url, experiment_dir=experiment_dir)
