"""Stable infrastructure import path for topology resolution."""

from deployers.shared.lib.topology import (
    LOCAL_TOPOLOGY,
    ROLE_COMMON,
    ROLE_COMPONENTS,
    ROLE_CONNECTORS,
    ROLE_CONSUMER,
    ROLE_OBSERVABILITY,
    ROLE_PROVIDER,
    ROLE_REGISTRATION_SERVICE,
    SUPPORTED_TOPOLOGIES,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    build_topology_profile,
    normalize_topology,
)

__all__ = [
    "LOCAL_TOPOLOGY",
    "ROLE_COMMON",
    "ROLE_COMPONENTS",
    "ROLE_CONNECTORS",
    "ROLE_CONSUMER",
    "ROLE_OBSERVABILITY",
    "ROLE_PROVIDER",
    "ROLE_REGISTRATION_SERVICE",
    "SUPPORTED_TOPOLOGIES",
    "VM_DISTRIBUTED_TOPOLOGY",
    "VM_SINGLE_TOPOLOGY",
    "build_topology_profile",
    "normalize_topology",
]
