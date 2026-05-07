from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComponentContract:
    component: str
    supported_adapters: tuple[str, ...]
    deployable_adapters: tuple[str, ...]
    deployment_strategy: str
    validation_groups: tuple[str, ...]


_COMPONENT_ALIASES = {
    "ontology_hub": "ontology-hub",
    "ai_model_hub": "ai-model-hub",
    "semantic_virtualization": "semantic-virtualization",
    "semantic_virtualizer": "semantic-virtualization",
    "virtualizer": "semantic-virtualization",
}


COMPONENT_CONTRACTS: dict[str, ComponentContract] = {
    "ontology-hub": ComponentContract(
        component="ontology-hub",
        supported_adapters=("inesdata", "edc"),
        deployable_adapters=("inesdata",),
        deployment_strategy="shared-chart-active-adapter",
        validation_groups=("ontology-hub",),
    ),
    "ai-model-hub": ComponentContract(
        component="ai-model-hub",
        supported_adapters=("inesdata", "edc"),
        deployable_adapters=("inesdata",),
        deployment_strategy="shared-chart-active-adapter",
        validation_groups=("ai-model-hub",),
    ),
    "semantic-virtualization": ComponentContract(
        component="semantic-virtualization",
        supported_adapters=("inesdata", "edc"),
        deployable_adapters=("inesdata",),
        deployment_strategy="shared-chart-active-adapter",
        validation_groups=("semantic-virtualization",),
    ),
}


def component_values_file_candidates(chart_dir: str, ds_name: str, namespace: str) -> list[str]:
    return [
        f"{chart_dir}/values-{ds_name}.yaml",
        f"{chart_dir}/values-{namespace}.yaml",
        f"{chart_dir}/values.yaml",
    ]


def normalize_component_key(component: str | None) -> str:
    normalized = str(component or "").strip().lower().replace("_", "-")
    if not normalized:
        return ""
    return _COMPONENT_ALIASES.get(normalized, normalized)


def get_component_contract(component: str | None) -> ComponentContract | None:
    normalized = normalize_component_key(component)
    if not normalized:
        return None
    return COMPONENT_CONTRACTS.get(normalized)


def strip_url_scheme(host_or_url: str | None) -> str:
    value = str(host_or_url or "").strip().rstrip("/")
    if value.startswith("http://"):
        return value[len("http://"):]
    if value.startswith("https://"):
        return value[len("https://"):]
    return value


def configured_component_host(
    component: str | None,
    deployer_config: dict[str, Any] | None,
    *,
    dataspace_name: str = "",
) -> str:
    normalized = normalize_component_key(component)
    if not normalized:
        return ""

    config = dict(deployer_config or {})
    env_key = normalized.upper().replace("-", "_")
    explicit = (
        config.get(f"{env_key}_HOST")
        or config.get(f"{env_key}_HOSTNAME")
        or config.get(f"{env_key}_URL")
    )
    explicit_host = strip_url_scheme(explicit)
    if explicit_host:
        return explicit_host

    if normalized in {"ontology-hub", "ai-model-hub", "semantic-virtualization"}:
        ds_domain = str(config.get("DS_DOMAIN_BASE") or "").strip()
        ds_name = str(dataspace_name or "").strip()
        if ds_domain and ds_name:
            return f"{normalized}-{ds_name}.{ds_domain}"

    return ""


def infer_component_hostname(
    component: str | None,
    values: dict[str, Any] | None,
    deployer_config: dict[str, Any] | None,
    *,
    dataspace_name: str = "",
) -> str | None:
    normalized = normalize_component_key(component)
    if not normalized:
        return None

    configured_host = configured_component_host(
        normalized,
        deployer_config,
        dataspace_name=dataspace_name,
    )
    if configured_host:
        return configured_host

    payload = dict(values or {})
    ingress = payload.get("ingress") or {}
    if not bool(ingress.get("enabled")):
        return None

    host = str(ingress.get("host") or "").strip()
    if host:
        return host

    ds_name = str(dataspace_name or "").strip()
    ds_domain = str((deployer_config or {}).get("DS_DOMAIN_BASE") or "").strip()
    if ds_name and ds_domain:
        return f"{normalized}-{ds_name}.{ds_domain}"

    return None


def resolve_component_release_name(
    component: str | None,
    *,
    dataspace_name: str = "",
    registration_service_release_name: str = "",
    public_portal_release_name: str = "",
) -> str:
    normalized = normalize_component_key(component)
    ds_name = str(dataspace_name or "").strip()
    if not normalized:
        return ds_name
    if normalized == "registration-service" and registration_service_release_name:
        return str(registration_service_release_name).strip()
    if normalized == "public-portal":
        if public_portal_release_name:
            return str(public_portal_release_name).strip()
        if ds_name:
            return f"{ds_name}-dataspace-pp"
    if ds_name:
        return f"{ds_name}-{normalized}"
    return normalized


def configured_optional_components(config: dict[str, Any] | None) -> list[str]:
    raw = str((config or {}).get("COMPONENTS", "") or "").strip()
    if not raw:
        return []

    components: list[str] = []
    seen: set[str] = set()
    for token in raw.split(","):
        normalized = normalize_component_key(token)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        components.append(normalized)
    return components


def components_for_adapter(
    config: dict[str, Any] | None,
    adapter: str,
    *,
    deployable_only: bool = True,
) -> list[str]:
    adapter_name = str(adapter or "").strip().lower()
    resolved: list[str] = []
    for component in configured_optional_components(config):
        contract = get_component_contract(component)
        if contract is None:
            continue
        adapters = contract.deployable_adapters if deployable_only else contract.supported_adapters
        if adapter_name in adapters:
            resolved.append(component)
    return resolved


def component_validation_groups(components: list[str] | tuple[str, ...] | None) -> list[str]:
    groups: list[str] = []
    seen: set[str] = set()
    for component in list(components or []):
        contract = get_component_contract(component)
        if contract is None:
            continue
        for group in contract.validation_groups:
            if group in seen:
                continue
            seen.add(group)
            groups.append(group)
    return groups


def summarize_components_for_adapter(config: dict[str, Any] | None, adapter: str) -> dict[str, list[str]]:
    adapter_name = str(adapter or "").strip().lower()
    configured = configured_optional_components(config)
    deployable: list[str] = []
    pending_support: list[str] = []
    unsupported: list[str] = []
    unknown: list[str] = []

    for component in configured:
        contract = get_component_contract(component)
        if contract is None:
            unknown.append(component)
            continue
        if adapter_name in contract.deployable_adapters:
            deployable.append(component)
            continue
        if adapter_name in contract.supported_adapters:
            pending_support.append(component)
            continue
        unsupported.append(component)

    return {
        "configured": configured,
        "deployable": deployable,
        "pending_support": pending_support,
        "unsupported": unsupported,
        "unknown": unknown,
    }


def build_component_preview(
    *,
    configured: list[str] | tuple[str, ...] | None,
    deployable: list[str] | tuple[str, ...] | None,
    pending_support: list[str] | tuple[str, ...] | None,
    unsupported: list[str] | tuple[str, ...] | None,
    unknown: list[str] | tuple[str, ...] | None,
    inferred_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    configured_values = [str(value or "").strip() for value in (configured or []) if str(value or "").strip()]
    deployable_values = [str(value or "").strip() for value in (deployable or []) if str(value or "").strip()]
    pending_values = [str(value or "").strip() for value in (pending_support or []) if str(value or "").strip()]
    unsupported_values = [str(value or "").strip() for value in (unsupported or []) if str(value or "").strip()]
    unknown_values = [str(value or "").strip() for value in (unknown or []) if str(value or "").strip()]
    urls = dict(inferred_urls or {})

    if not configured_values:
        return {
            "status": "not-applicable",
            "action": "skip",
            "components": [],
            "configured": [],
            "deployable": [],
            "pending_support": [],
            "unsupported": [],
            "unknown": [],
        }

    component_entries: list[dict[str, Any]] = []
    deployable_set = set(deployable_values)
    pending_set = set(pending_values)
    unsupported_set = set(unsupported_values)
    for component in configured_values:
        if component in deployable_set:
            component_status = "planned"
        elif component in pending_set:
            component_status = "pending-support"
        elif component in unsupported_set:
            component_status = "unsupported"
        else:
            component_status = "unknown"
        component_entries.append(
            {
                "name": component,
                "url": urls.get(component),
                "status": component_status,
            }
        )

    if deployable_values:
        status = "planned"
        action = "deploy_components"
    elif pending_values:
        status = "pending-support"
        action = "skip"
    elif unsupported_values or unknown_values:
        status = "unsupported"
        action = "skip"
    else:
        status = "not-applicable"
        action = "skip"

    return {
        "status": status,
        "action": action,
        "components": component_entries,
        "configured": configured_values,
        "deployable": deployable_values,
        "pending_support": pending_values,
        "unsupported": unsupported_values,
        "unknown": unknown_values,
    }
