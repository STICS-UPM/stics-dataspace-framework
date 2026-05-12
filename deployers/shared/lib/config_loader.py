from __future__ import annotations

import os
import re


_DATASPACE_SLOT_PATTERN = re.compile(r"^DS_(\d+)_([A-Z0-9_]+)$")


INFRASTRUCTURE_MANAGED_KEYS = frozenset(
    {
        "KC_URL",
        "KC_INTERNAL_URL",
        "KC_USER",
        "KC_PASSWORD",
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
        "VT_URL",
        "VT_TOKEN",
        "MINIO_ENDPOINT",
        "MINIO_USER",
        "MINIO_PASSWORD",
        "MINIO_ADMIN_USER",
        "MINIO_ADMIN_PASS",
    }
)

TOPOLOGY_OVERLAY_KEYS = {
    "local": frozenset(
        {
            "PG_HOST",
            "VT_URL",
            "MINIO_ENDPOINT",
            "LOCAL_HOSTS_ADDRESS",
            "LOCAL_INGRESS_EXTERNAL_IP",
            "LOCAL_RESOURCE_PROFILE",
            "CLUSTER_TYPE",
            "MINIKUBE_DRIVER",
            "MINIKUBE_CPUS",
            "MINIKUBE_MEMORY",
            "MINIKUBE_PROFILE",
        }
    ),
    "vm-single": frozenset(
        {
            "VM_EXTERNAL_IP",
            "VM_COMMON_IP",
            "VM_DATASPACE_IP",
            "VM_CONNECTORS_IP",
            "VM_COMPONENTS_IP",
            "INGRESS_EXTERNAL_IP",
            "CLUSTER_TYPE",
            "K3S_KUBECONFIG",
            "K3S_INSTALL_EXEC",
            "K3S_SERVICE_NAME",
            "K3S_INGRESS_CONTROLLER",
            "K3S_INGRESS_SERVICE_TYPE",
            "K3S_REPAIR_ON_LEVEL1",
            "K3S_WRITE_KUBECONFIG_MODE",
            "MINIKUBE_DRIVER",
            "MINIKUBE_CPUS",
            "MINIKUBE_MEMORY",
            "MINIKUBE_PROFILE",
        }
    ),
    "vm-distributed": frozenset(
        {
            "VM_EXTERNAL_IP",
            "VM_COMMON_IP",
            "VM_DATASPACE_IP",
            "VM_PROVIDER_IP",
            "VM_CONSUMER_IP",
            "VM_CONNECTORS_IP",
            "VM_COMPONENTS_IP",
            "VM_OBSERVABILITY_IP",
            "INGRESS_EXTERNAL_IP",
            "CLUSTER_TYPE",
            "K3S_KUBECONFIG",
            "K3S_INSTALL_EXEC",
            "K3S_SERVICE_NAME",
            "K3S_INGRESS_CONTROLLER",
            "K3S_INGRESS_SERVICE_TYPE",
            "K3S_REPAIR_ON_LEVEL1",
            "K3S_WRITE_KUBECONFIG_MODE",
        }
    ),
}

TOPOLOGY_KEY_TARGETS: dict[str, tuple[str, ...]] = {}
for _topology_name, _keys in TOPOLOGY_OVERLAY_KEYS.items():
    for _key_name in _keys:
        TOPOLOGY_KEY_TARGETS.setdefault(_key_name, tuple())
        TOPOLOGY_KEY_TARGETS[_key_name] = tuple(
            sorted(set(TOPOLOGY_KEY_TARGETS[_key_name]).union({_topology_name}))
        )


def load_deployer_config(path: str) -> dict[str, str]:
    """Load a deployer.config file using a simple KEY=VALUE format."""
    config: dict[str, str] = {}
    if not path or not os.path.isfile(path):
        return config

    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    return config


def apply_pionera_environment_overrides(config: dict[str, str]) -> dict[str, str]:
    """Apply PIONERA_* environment variables as highest-priority overrides."""

    for env_key, env_value in os.environ.items():
        if not env_key.startswith("PIONERA_"):
            continue
        override_key = env_key[len("PIONERA_"):].strip()
        if not override_key or env_value in (None, ""):
            continue
        config[override_key] = env_value
    return config


def topology_overlay_config_path(path: str, topology: str | None = None) -> str:
    """Return the optional topology overlay path that accompanies a deployer.config file."""

    normalized_topology = str(topology or "").strip().lower()
    if not path or not normalized_topology:
        return ""
    return os.path.join(os.path.dirname(path), "topologies", f"{normalized_topology}.config")


def resolve_deployer_config_layer_paths(path: str, topology: str | None = None) -> list[str]:
    """Expand a deployer.config path with its optional topology overlay."""

    if not path:
        return []
    resolved_paths = [path]
    overlay_path = topology_overlay_config_path(path, topology)
    if overlay_path:
        resolved_paths.append(overlay_path)
    return resolved_paths


def detect_topology_key_migration_warnings(path: str) -> list[dict[str, object]]:
    """Report topology-scoped keys that still live in the shared base config."""

    warnings: list[dict[str, object]] = []
    if not path or not os.path.isfile(path):
        return warnings

    config = load_deployer_config(path)
    for key in sorted(config):
        target_topologies = list(TOPOLOGY_KEY_TARGETS.get(key, ()))
        if not target_topologies:
            continue
        value = str(config.get(key) or "").strip()
        if value == "":
            continue
        overlay_paths = [
            topology_overlay_config_path(path, topology_name)
            for topology_name in target_topologies
        ]
        warnings.append(
            {
                "key": key,
                "value": value,
                "base_path": path,
                "target_topologies": target_topologies,
                "recommended_overlay_paths": overlay_paths,
            }
        )
    return warnings


def load_layered_deployer_config(
    paths: list[str] | tuple[str, ...],
    *,
    defaults: dict[str, str] | None = None,
    apply_environment: bool = True,
    protected_keys: set[str] | frozenset[str] | None = None,
    topology: str | None = None,
) -> dict[str, str]:
    """Load deployer configuration as defaults < files in order < PIONERA_*."""

    config: dict[str, str] = dict(defaults or {})
    protected = set(protected_keys or [])
    for path in paths:
        for resolved_path in resolve_deployer_config_layer_paths(path, topology):
            layer = load_deployer_config(resolved_path)
            for key, value in layer.items():
                if key in protected and key in config:
                    continue
                config[key] = value
    if apply_environment:
        apply_pionera_environment_overrides(config)
    return config


def iter_dataspace_slots(config: dict[str, str] | None) -> list[dict[str, str]]:
    """Group DS_<n>_* keys by slot while keeping the raw values untouched."""
    slots: dict[str, dict[str, str]] = {}
    for key, value in (config or {}).items():
        match = _DATASPACE_SLOT_PATTERN.match(key)
        if not match:
            continue
        slot_id, field_name = match.groups()
        slot = slots.setdefault(slot_id, {"slot": slot_id})
        slot[field_name] = value

    def _sort_key(item: dict[str, str]) -> int:
        try:
            return int(item["slot"])
        except (KeyError, TypeError, ValueError):
            return 0

    return [slots[key] for key in sorted(slots, key=lambda value: int(value))]
