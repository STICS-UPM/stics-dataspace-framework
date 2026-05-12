from __future__ import annotations

from typing import Any

from .contracts import TopologyProfile


LOCAL_TOPOLOGY = "local"
VM_SINGLE_TOPOLOGY = "vm-single"
VM_DISTRIBUTED_TOPOLOGY = "vm-distributed"
SUPPORTED_TOPOLOGIES = (LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY)

ROLE_COMMON = "common"
ROLE_REGISTRATION_SERVICE = "registration_service"
ROLE_PROVIDER = "provider"
ROLE_CONSUMER = "consumer"
ROLE_CONNECTORS = "connectors"
ROLE_COMPONENTS = "components"
ROLE_OBSERVABILITY = "observability"


def normalize_topology(value: Any) -> str:
    topology = str(value or LOCAL_TOPOLOGY).strip().lower()
    return topology or LOCAL_TOPOLOGY


def build_topology_profile(topology: str = LOCAL_TOPOLOGY, config: dict[str, Any] | None = None) -> TopologyProfile:
    resolved_topology = normalize_topology(topology)
    if resolved_topology not in SUPPORTED_TOPOLOGIES:
        supported = ", ".join(SUPPORTED_TOPOLOGIES)
        raise ValueError(f"Unsupported topology '{resolved_topology}'. Supported topologies: {supported}")

    values = dict(config or {})
    routing_mode = _first_config_value(values, "TOPOLOGY_ROUTING_MODE", "ROUTING_MODE") or "host"

    if resolved_topology == LOCAL_TOPOLOGY:
        local_address = _first_topology_address_value(values, "LOCAL_HOSTS_ADDRESS", "HOSTS_ADDRESS") or "127.0.0.1"
        return TopologyProfile(
            name=resolved_topology,
            default_address=local_address,
            ingress_external_ip=_first_topology_address_value(
                values, "LOCAL_INGRESS_EXTERNAL_IP", "INGRESS_EXTERNAL_IP"
            ),
            routing_mode=routing_mode,
        )

    if resolved_topology == VM_SINGLE_TOPOLOGY:
        address = _first_topology_address_value(
            values,
            "VM_SINGLE_ADDRESS",
            "VM_SINGLE_IP",
            "VM_EXTERNAL_IP",
            "HOSTS_ADDRESS",
            "INGRESS_EXTERNAL_IP",
        )
        if not address:
            raise ValueError(
                "Topology 'vm-single' requires VM_EXTERNAL_IP, VM_SINGLE_IP, "
                "VM_SINGLE_ADDRESS, HOSTS_ADDRESS, or INGRESS_EXTERNAL_IP."
            )
        return TopologyProfile(
            name=resolved_topology,
            default_address=address,
            role_addresses=_same_address_for_all_roles(address),
            ingress_external_ip=_first_topology_address_value(values, "INGRESS_EXTERNAL_IP", "VM_INGRESS_EXTERNAL_IP")
            or address,
            routing_mode=routing_mode,
        )

    shared_address = _first_topology_address_value(values, "VM_EXTERNAL_IP", "HOSTS_ADDRESS", "INGRESS_EXTERNAL_IP")
    role_addresses = {
        ROLE_COMMON: _first_topology_address_value(values, "VM_COMMON_IP", "VM_COMMON_ADDRESS") or shared_address,
        ROLE_REGISTRATION_SERVICE: (
            _first_topology_address_value(
                values, "VM_DATASPACE_IP", "VM_DATASPACE_ADDRESS", "VM_REGISTRATION_SERVICE_IP"
            )
            or shared_address
        ),
        ROLE_PROVIDER: _first_topology_address_value(values, "VM_PROVIDER_IP", "VM_PROVIDER_ADDRESS") or shared_address,
        ROLE_CONSUMER: _first_topology_address_value(values, "VM_CONSUMER_IP", "VM_CONSUMER_ADDRESS")
        or shared_address,
        ROLE_CONNECTORS: _first_topology_address_value(values, "VM_CONNECTORS_IP", "VM_CONNECTORS_ADDRESS")
        or shared_address,
        ROLE_COMPONENTS: _first_topology_address_value(values, "VM_COMPONENTS_IP", "VM_COMPONENTS_ADDRESS")
        or shared_address,
        ROLE_OBSERVABILITY: _first_topology_address_value(values, "VM_OBSERVABILITY_IP", "VM_OBSERVABILITY_ADDRESS")
        or shared_address,
    }
    role_addresses = {
        role: address
        for role, address in role_addresses.items()
        if str(address or "").strip()
    }
    if not role_addresses:
        raise ValueError(
            "Topology 'vm-distributed' requires VM_EXTERNAL_IP/HOSTS_ADDRESS or role-specific "
            "addresses such as VM_COMMON_IP, VM_PROVIDER_IP, VM_CONSUMER_IP, or VM_COMPONENTS_IP."
        )
    default_address = shared_address or next(iter(role_addresses.values()))
    return TopologyProfile(
        name=resolved_topology,
        default_address=default_address,
        role_addresses=role_addresses,
        ingress_external_ip=_first_topology_address_value(values, "INGRESS_EXTERNAL_IP", "VM_INGRESS_EXTERNAL_IP")
        or default_address,
        routing_mode=routing_mode,
    )


def _same_address_for_all_roles(address: str) -> dict[str, str]:
    return {
        ROLE_COMMON: address,
        ROLE_REGISTRATION_SERVICE: address,
        ROLE_PROVIDER: address,
        ROLE_CONSUMER: address,
        ROLE_CONNECTORS: address,
        ROLE_COMPONENTS: address,
        ROLE_OBSERVABILITY: address,
    }


def _first_config_value(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = config.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _first_topology_address_value(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(config.get(key) or "").strip()
        if not value:
            continue
        if value.upper() in {"X", "AUTO", "REPLACE_ME"}:
            continue
        return value
    return ""
