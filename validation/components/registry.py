"""Shared component validation registry for Level 6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from deployers.shared.lib.components import (
    COMPONENT_CONTRACTS,
    ComponentContract,
    normalize_component_key,
)
from validation.components.ai_model_hub.component_runner import (
    run_ai_model_hub_component_validation,
)
from validation.components.ontology_hub.component_runner import (
    run_ontology_hub_component_validation,
)
from validation.components.semantic_virtualization.component_runner import (
    run_semantic_virtualization_component_validation,
)


ComponentRunner = Callable[[str, str | None], dict]


@dataclass(frozen=True)
class ComponentValidationRegistration:
    component: str
    supported_adapters: tuple[str, ...]
    deployable_adapters: tuple[str, ...]
    deployment_strategy: str
    validation_groups: tuple[str, ...]
    runner: ComponentRunner | None = None


def _validation_registration(
    contract: ComponentContract,
    *,
    runner: ComponentRunner | None,
) -> ComponentValidationRegistration:
    return ComponentValidationRegistration(
        component=contract.component,
        supported_adapters=contract.supported_adapters,
        deployable_adapters=contract.deployable_adapters,
        deployment_strategy=contract.deployment_strategy,
        validation_groups=contract.validation_groups,
        runner=runner,
    )


COMPONENT_REGISTRY: dict[str, ComponentValidationRegistration] = {
    "ontology-hub": _validation_registration(
        COMPONENT_CONTRACTS["ontology-hub"],
        runner=run_ontology_hub_component_validation,
    ),
    "ai-model-hub": _validation_registration(
        COMPONENT_CONTRACTS["ai-model-hub"],
        runner=run_ai_model_hub_component_validation,
    ),
    "semantic-virtualization": _validation_registration(
        COMPONENT_CONTRACTS["semantic-virtualization"],
        runner=run_semantic_virtualization_component_validation,
    ),
}


def get_component_registration(component: str | None) -> ComponentValidationRegistration | None:
    normalized = normalize_component_key(component)
    if not normalized:
        return None
    return COMPONENT_REGISTRY.get(normalized)


def registered_component_runners() -> dict[str, ComponentRunner]:
    return {
        component: registration.runner
        for component, registration in COMPONENT_REGISTRY.items()
        if callable(registration.runner)
    }
