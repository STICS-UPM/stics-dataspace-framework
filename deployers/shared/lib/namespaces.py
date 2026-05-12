from __future__ import annotations

from typing import Any

from .contracts import NamespaceRoles


COMPACT_NAMESPACE_PROFILE = "compact"
ROLE_ALIGNED_NAMESPACE_PROFILE = "role-aligned"
SUPPORTED_NAMESPACE_PROFILES = (
    COMPACT_NAMESPACE_PROFILE,
    ROLE_ALIGNED_NAMESPACE_PROFILE,
)


def normalize_namespace_profile(value: Any) -> str:
    normalized = str(value or COMPACT_NAMESPACE_PROFILE).strip().lower().replace("_", "-")
    if normalized in {"", COMPACT_NAMESPACE_PROFILE}:
        return COMPACT_NAMESPACE_PROFILE
    if normalized in {"role-aligned", "rolealigned", "aligned", "roles"}:
        return ROLE_ALIGNED_NAMESPACE_PROFILE
    return COMPACT_NAMESPACE_PROFILE


def resolve_namespace_profile_plan(
    config: dict[str, Any] | None,
    *,
    dataspace_name: str,
    dataspace_namespace: str,
    common_default: str = "common-srvs",
    components_default: str = "components",
) -> dict[str, Any]:
    payload = dict(config or {})
    profile = normalize_namespace_profile(payload.get("NAMESPACE_PROFILE"))
    execution_roles = _build_compact_namespace_roles(
        payload,
        dataspace_name=dataspace_name,
        dataspace_namespace=dataspace_namespace,
        common_default=common_default,
        components_default=components_default,
    )
    if profile == ROLE_ALIGNED_NAMESPACE_PROFILE:
        planned_roles = _build_role_aligned_namespace_roles(
            payload,
            dataspace_name=dataspace_name,
            dataspace_namespace=dataspace_namespace,
            common_default=common_default,
            components_default=components_default,
        )
        # Phase 2 activates the Level 3 / registration-service namespace while
        # keeping provider and consumer on the compact runtime layout until
        # Level 4 is migrated safely.
        execution_roles = NamespaceRoles.from_mapping(
            {
                **execution_roles.as_dict(),
                "registration_service_namespace": planned_roles.registration_service_namespace,
            }
        )
    else:
        planned_roles = execution_roles
    return {
        "namespace_profile": profile,
        "namespace_roles": execution_roles,
        "planned_namespace_roles": planned_roles,
    }


def _build_compact_namespace_roles(
    config: dict[str, Any],
    *,
    dataspace_name: str,
    dataspace_namespace: str,
    common_default: str,
    components_default: str,
) -> NamespaceRoles:
    namespace = str(dataspace_namespace or dataspace_name or "").strip()
    return NamespaceRoles.from_mapping(
        {
            "common_services_namespace": config.get("COMMON_SERVICES_NAMESPACE") or common_default,
            "components_namespace": config.get("COMPONENTS_NAMESPACE") or components_default,
            "registration_service_namespace": config.get("DS_1_REGISTRATION_NAMESPACE") or namespace,
            "provider_namespace": config.get("DS_1_PROVIDER_NAMESPACE") or namespace,
            "consumer_namespace": config.get("DS_1_CONSUMER_NAMESPACE") or namespace,
            "observability_namespace": config.get("OBSERVABILITY_NAMESPACE") or None,
        }
    )


def _build_role_aligned_namespace_roles(
    config: dict[str, Any],
    *,
    dataspace_name: str,
    dataspace_namespace: str,
    common_default: str,
    components_default: str,
) -> NamespaceRoles:
    base_name = str(dataspace_name or dataspace_namespace or "dataspace").strip() or "dataspace"
    return NamespaceRoles.from_mapping(
        {
            "common_services_namespace": config.get("COMMON_SERVICES_NAMESPACE") or common_default,
            "components_namespace": config.get("COMPONENTS_NAMESPACE") or components_default,
            "registration_service_namespace": config.get("DS_1_REGISTRATION_NAMESPACE") or f"{base_name}-core",
            "provider_namespace": config.get("DS_1_PROVIDER_NAMESPACE") or f"{base_name}-provider",
            "consumer_namespace": config.get("DS_1_CONSUMER_NAMESPACE") or f"{base_name}-consumer",
            "observability_namespace": config.get("OBSERVABILITY_NAMESPACE") or None,
        }
    )
