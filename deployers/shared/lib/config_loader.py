from __future__ import annotations

import os
import re


_DATASPACE_SLOT_PATTERN = re.compile(r"^DS_(\d+)_([A-Z0-9_]+)$")


INFRASTRUCTURE_MANAGED_KEYS = frozenset(
    {
        "KC_URL",
        "KC_INTERNAL_URL",
        "KC_MANAGEMENT_URL",
        "KEYCLOAK_FRONTEND_URL",
        "KEYCLOAK_PUBLIC_URL",
        "KC_USER",
        "KC_PASSWORD",
        "PG_HOST",
        "PG_PORT",
        "PG_USER",
        "PG_PASSWORD",
        "VT_URL",
        "VT_TOKEN",
        "MINIO_ENDPOINT",
        "MINIO_API_PUBLIC_URL",
        "MINIO_CONSOLE_PUBLIC_URL",
        "MINIO_PUBLIC_URL",
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
            "VM_SINGLE_LOCAL_KUBECONFIG",
            "VM_SINGLE_REMOTE_KUBECONFIG",
            "VM_SINGLE_K3S_TUNNEL_MODE",
            "VM_SINGLE_K3S_API_LOCAL_PORT",
            "VM_SINGLE_K3S_API_REMOTE_PORT",
            "MINIKUBE_DRIVER",
            "MINIKUBE_CPUS",
            "MINIKUBE_MEMORY",
            "MINIKUBE_PROFILE",
            "VM_SSH_USER",
            "VM_SINGLE_SSH_HOST",
            "VM_SINGLE_SSH_PORT",
            "VM_SINGLE_SSH_USER",
            "VM_SINGLE_SSH_IDENTITY_FILE",
            "VM_SINGLE_SSH_BOOTSTRAP_MODE",
            "VM_SINGLE_SSH_KEY_COMMENT",
            "VM_SINGLE_SSH_MANAGED_MARKER",
            "VM_SINGLE_SSH_KNOWN_HOSTS_STRATEGY",
            "VM_SINGLE_LEVEL_EXECUTION_MODE",
            "VM_SINGLE_REMOTE_PYTHON",
            "VM_SINGLE_REMOTE_WORKDIR",
            "VM_SINGLE_WORKSPACE_SYNC",
            "VM_SINGLE_WORKSPACE_SYNC_DELETE",
            "VM_SINGLE_WORKSPACE_SYNC_EXCLUDES",
            "VM_SINGLE_HTTP_URL",
            "VM_REMOTE_WORKDIR",
            "SSH_ACCESS_MODE",
            "SSH_BASTION_HOST",
            "SSH_BASTION_PORT",
            "SSH_BASTION_USER",
            "SSH_BASTION_IDENTITY_FILE",
            "SSH_IDENTITY_FILE",
            "SSH_CONNECT_TIMEOUT_SECONDS",
        }
    ),
    "vm-distributed": frozenset(
        {
            "VM_EXTERNAL_IP",
            "VM_COMMON_IP",
            "VM_DATASPACE_IP",
            "VM_PROVIDER_IP",
            "VM_CONSUMER_IP",
            "VM_PROVIDER_K8S_NODE",
            "VM_CONSUMER_K8S_NODE",
            "VM_CONNECTORS_IP",
            "VM_COMPONENTS_IP",
            "VM_OBSERVABILITY_IP",
            "VM_SSH_USER",
            "INGRESS_EXTERNAL_IP",
            "CLUSTER_TYPE",
            "K3S_KUBECONFIG",
            "K3S_KUBECONFIG_COMMON",
            "K3S_KUBECONFIG_PROVIDER",
            "K3S_KUBECONFIG_CONSUMER",
            "K3S_KUBECONFIG_COMPONENTS",
            "K3S_INSTALL_EXEC",
            "K3S_SERVICE_NAME",
            "K3S_INGRESS_CONTROLLER",
            "K3S_INGRESS_SERVICE_TYPE",
            "K3S_INGRESS_HTTP_NODEPORT",
            "K3S_REPAIR_ON_LEVEL1",
            "K3S_WRITE_KUBECONFIG_MODE",
            "KEYCLOAK_BOOTSTRAP_ACCESS",
            "KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
            "KEYCLOAK_PORT_FORWARD_BOOTSTRAP",
            "FORCE_KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
            "KEYCLOAK_FRONTEND_URL",
            "KEYCLOAK_PUBLIC_URL",
            "VM_PUBLIC_PROXY_IP",
            "TOPOLOGY_ROUTING_MODE",
            "VM_PROVIDER_CONNECTORS",
            "VM_CONSUMER_CONNECTORS",
            "VM_PROVIDER_INGRESS_HTTP_PORT",
            "VM_CONSUMER_INGRESS_HTTP_PORT",
            "VM_PROVIDER_INGRESS_NODEPORT",
            "VM_CONSUMER_INGRESS_NODEPORT",
            "CONNECTOR_PROTOCOL_ADDRESS_MODE",
            "DATABASE_HOSTNAME",
            "VAULT_URL",
            "VT_URL",
            "PIONERA_LEVEL6_MINIO_ENDPOINT",
            "MINIO_API_PUBLIC_URL",
            "MINIO_CONSOLE_PUBLIC_URL",
            "MINIO_PUBLIC_URL",
            "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES_ENABLED",
            "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES",
            "COMPONENTS_PUBLIC_BASE_URL",
            "COMPONENTS_PUBLIC_PATH_REWRITE",
            "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
            "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
            "MODEL_SERVER_CONNECTOR_BASE_URL",
            "AI_MODEL_OBSERVER_JOURNAL_BASE_URL",
            "AI_MODEL_HUB_OBSERVER_JOURNAL_BASE_URL",
            "MODEL_OBSERVER_JOURNAL_BASE_URL",
            "ONTOLOGY_HUB_PUBLIC_URL",
            "ONTOLOGY_HUB_SELF_HOST_URL",
            "ONTOLOGY_HUB_INTERNAL_SELF_HOST_URL",
            "AI_MODEL_HUB_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
            "SSH_BASTION_HOST",
            "SSH_BASTION_PORT",
            "SSH_BASTION_USER",
            "SSH_BASTION_IDENTITY_FILE",
            "SSH_IDENTITY_FILE",
            "SSH_ACCESS_MODE",
            "SSH_CONNECT_TIMEOUT_SECONDS",
            "VM_DISTRIBUTED_EXECUTION_HOST",
            "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH",
            "VM_DISTRIBUTED_INFER_LOCAL_WORKDIR",
            "VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE",
            "VM_DISTRIBUTED_KUBECONFIG_DIR",
            "VM_DISTRIBUTED_KUBECONFIG_SYNC",
            "VM_DISTRIBUTED_REMOTE_KUBECONFIG",
            "VM_COMMON_REMOTE_KUBECONFIG",
            "VM_PROVIDER_REMOTE_KUBECONFIG",
            "VM_CONSUMER_REMOTE_KUBECONFIG",
            "VM_COMPONENTS_REMOTE_KUBECONFIG",
            "VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY",
            "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE",
            "VM_DISTRIBUTED_SSH_KEY_COMMENT",
            "VM_DISTRIBUTED_SSH_MANAGED_MARKER",
            "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
            "VM_DISTRIBUTED_DEPLOYMENT_MODE",
            "VM_DISTRIBUTED_PREFLIGHT_DRY_RUN",
            "VM_DISTRIBUTED_K3S_TUNNEL_MODE",
            "VM_DISTRIBUTED_K3S_API_REMOTE_PORT",
            "VM_DISTRIBUTED_K3S_TUNNEL_RECREATE",
            "VM_COMMON_K3S_API_LOCAL_PORT",
            "VM_PROVIDER_K3S_API_LOCAL_PORT",
            "VM_CONSUMER_K3S_API_LOCAL_PORT",
            "VM_COMPONENTS_K3S_API_LOCAL_PORT",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY",
            "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE",
            "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP",
            "VM_DISTRIBUTED_SSH_IDENTITY_FILE",
            "VM_REMOTE_WORKDIR",
            "VM_COMMON_REMOTE_WORKDIR",
            "VM_PROVIDER_REMOTE_WORKDIR",
            "VM_CONSUMER_REMOTE_WORKDIR",
            "VM_COMMON_PUBLIC_URL",
            "VM_PROVIDER_PUBLIC_URL",
            "VM_CONSUMER_PUBLIC_URL",
            "VM_COMMON_HTTP_URL",
            "VM_PROVIDER_HTTP_URL",
            "VM_CONSUMER_HTTP_URL",
            "VM_COMMON_SSH_HOST",
            "VM_COMMON_SSH_PORT",
            "VM_COMMON_SSH_USER",
            "VM_COMMON_SSH_IDENTITY_FILE",
            "VM_COMPONENTS_SSH_HOST",
            "VM_COMPONENTS_SSH_PORT",
            "VM_COMPONENTS_SSH_USER",
            "VM_COMPONENTS_SSH_IDENTITY_FILE",
            "VM_PROVIDER_SSH_HOST",
            "VM_PROVIDER_SSH_PORT",
            "VM_PROVIDER_SSH_USER",
            "VM_PROVIDER_SSH_IDENTITY_FILE",
            "VM_CONSUMER_SSH_HOST",
            "VM_CONSUMER_SSH_PORT",
            "VM_CONSUMER_SSH_USER",
            "VM_CONSUMER_SSH_IDENTITY_FILE",
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
