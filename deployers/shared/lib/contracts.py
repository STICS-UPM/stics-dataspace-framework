from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NamespaceRoles:
    common_services_namespace: str = "common-srvs"
    components_namespace: str = "components"
    registration_service_namespace: str = ""
    provider_namespace: str = ""
    consumer_namespace: str = ""
    observability_namespace: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None = None, **overrides: Any) -> "NamespaceRoles":
        payload = dict(data or {})
        payload.update({key: value for key, value in overrides.items() if value is not None})
        return cls(
            common_services_namespace=str(payload.get("common_services_namespace", "common-srvs") or "common-srvs"),
            components_namespace=str(payload.get("components_namespace", "components") or "components"),
            registration_service_namespace=str(payload.get("registration_service_namespace", "") or ""),
            provider_namespace=str(payload.get("provider_namespace", "") or ""),
            consumer_namespace=str(payload.get("consumer_namespace", "") or ""),
            observability_namespace=payload.get("observability_namespace"),
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "common_services_namespace": self.common_services_namespace,
            "components_namespace": self.components_namespace,
            "registration_service_namespace": self.registration_service_namespace,
            "provider_namespace": self.provider_namespace,
            "consumer_namespace": self.consumer_namespace,
            "observability_namespace": self.observability_namespace,
        }


@dataclass(slots=True)
class ValidationProfile:
    adapter: str
    newman_enabled: bool = True
    test_data_cleanup_enabled: bool = False
    playwright_enabled: bool = False
    playwright_config: str | None = None
    component_validation_enabled: bool = False
    component_groups: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None = None, **overrides: Any) -> "ValidationProfile":
        payload = dict(data or {})
        payload.update({key: value for key, value in overrides.items() if value is not None})
        groups = payload.get("component_groups") or []
        return cls(
            adapter=str(payload.get("adapter", "") or ""),
            newman_enabled=bool(payload.get("newman_enabled", True)),
            test_data_cleanup_enabled=bool(payload.get("test_data_cleanup_enabled", False)),
            playwright_enabled=bool(payload.get("playwright_enabled", False)),
            playwright_config=payload.get("playwright_config"),
            component_validation_enabled=bool(payload.get("component_validation_enabled", False)),
            component_groups=list(groups),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "newman_enabled": self.newman_enabled,
            "test_data_cleanup_enabled": self.test_data_cleanup_enabled,
            "playwright_enabled": self.playwright_enabled,
            "playwright_config": self.playwright_config,
            "component_validation_enabled": self.component_validation_enabled,
            "component_groups": list(self.component_groups),
        }


@dataclass(slots=True)
class TopologyProfile:
    name: str = "local"
    default_address: str = "127.0.0.1"
    role_addresses: dict[str, str] = field(default_factory=dict)
    ingress_external_ip: str = ""
    routing_mode: str = "host"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None = None, **overrides: Any) -> "TopologyProfile":
        payload = dict(data or {})
        payload.update({key: value for key, value in overrides.items() if value is not None})
        role_addresses = payload.get("role_addresses") or {}
        return cls(
            name=str(payload.get("name", "local") or "local"),
            default_address=str(payload.get("default_address", "127.0.0.1") or "127.0.0.1"),
            role_addresses={
                str(key): str(value)
                for key, value in dict(role_addresses).items()
                if str(key or "").strip() and str(value or "").strip()
            },
            ingress_external_ip=str(payload.get("ingress_external_ip", "") or ""),
            routing_mode=str(payload.get("routing_mode", "host") or "host"),
        )

    def address_for(self, role: str, fallback: str | None = None) -> str:
        role_name = str(role or "").strip()
        if role_name and role_name in self.role_addresses:
            return self.role_addresses[role_name]
        return str(fallback or self.default_address or "127.0.0.1").strip() or "127.0.0.1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "default_address": self.default_address,
            "role_addresses": dict(self.role_addresses),
            "ingress_external_ip": self.ingress_external_ip,
            "routing_mode": self.routing_mode,
        }


@dataclass(slots=True)
class DeploymentContext:
    deployer: str
    topology: str
    environment: str
    dataspace_name: str
    ds_domain_base: str
    connectors: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    namespace_profile: str = "compact"
    namespace_roles: NamespaceRoles = field(default_factory=NamespaceRoles)
    planned_namespace_roles: NamespaceRoles = field(default_factory=NamespaceRoles)
    topology_profile: TopologyProfile = field(default_factory=TopologyProfile)
    runtime_dir: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None = None, **overrides: Any) -> "DeploymentContext":
        payload = dict(data or {})
        payload.update({key: value for key, value in overrides.items() if value is not None})
        namespace_roles = payload.get("namespace_roles")
        if isinstance(namespace_roles, NamespaceRoles):
            resolved_roles = namespace_roles
        else:
            resolved_roles = NamespaceRoles.from_mapping(namespace_roles or {})
        planned_namespace_roles = payload.get("planned_namespace_roles")
        if isinstance(planned_namespace_roles, NamespaceRoles):
            resolved_planned_roles = planned_namespace_roles
        else:
            resolved_planned_roles = NamespaceRoles.from_mapping(planned_namespace_roles or resolved_roles.as_dict())
        topology_profile = payload.get("topology_profile")
        if isinstance(topology_profile, TopologyProfile):
            resolved_topology_profile = topology_profile
        else:
            resolved_topology_profile = TopologyProfile.from_mapping(
                topology_profile or {"name": payload.get("topology", "local")}
            )
        return cls(
            deployer=str(payload.get("deployer", "") or ""),
            topology=str(payload.get("topology", "local") or "local"),
            environment=str(payload.get("environment", "DEV") or "DEV"),
            dataspace_name=str(payload.get("dataspace_name", "") or ""),
            ds_domain_base=str(payload.get("ds_domain_base", "") or ""),
            connectors=list(payload.get("connectors") or []),
            components=list(payload.get("components") or []),
            namespace_profile=str(payload.get("namespace_profile", "compact") or "compact"),
            namespace_roles=resolved_roles,
            planned_namespace_roles=resolved_planned_roles,
            topology_profile=resolved_topology_profile,
            runtime_dir=str(payload.get("runtime_dir", "") or ""),
            config=dict(payload.get("config") or {}),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "deployer": self.deployer,
            "topology": self.topology,
            "environment": self.environment,
            "dataspace_name": self.dataspace_name,
            "ds_domain_base": self.ds_domain_base,
            "connectors": list(self.connectors),
            "components": list(self.components),
            "namespace_profile": self.namespace_profile,
            "namespace_roles": self.namespace_roles.as_dict(),
            "planned_namespace_roles": self.planned_namespace_roles.as_dict(),
            "topology_profile": self.topology_profile.as_dict(),
            "runtime_dir": self.runtime_dir,
            "config": dict(self.config),
        }
