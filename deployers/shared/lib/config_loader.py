from __future__ import annotations

import os
import re
from urllib.parse import urlparse


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

COMMON_SERVICE_TOPOLOGY_KEYS = frozenset(
    {
        "DOMAIN_BASE",
        "DS_DOMAIN_BASE",
        "KC_URL",
        "KC_INTERNAL_URL",
        "KC_MANAGEMENT_URL",
        "KEYCLOAK_HOSTNAME",
        "KEYCLOAK_ADMIN_HOSTNAME",
        "KEYCLOAK_FRONTEND_URL",
        "KEYCLOAK_PUBLIC_URL",
        "MINIO_ENDPOINT",
        "MINIO_HOSTNAME",
        "MINIO_CONSOLE_HOSTNAME",
        "MINIO_API_PUBLIC_URL",
        "MINIO_CONSOLE_PUBLIC_URL",
        "MINIO_PUBLIC_URL",
        "PUBLIC_HOSTNAME",
        "PUBLIC_HOSTNAME_PROVIDER",
        "PUBLIC_HOSTNAME_CONSUMER",
        "TOPOLOGY",
    }
)

KUBERNETES_WORKLOAD_TOPOLOGY_KEYS = frozenset(
    {
        "DATABASE_HOSTNAME",
        "VAULT_URL",
    }
)

VM_SERVICE_TOPOLOGY_KEYS = frozenset(
    {
        "VT_URL",
    }
)

AI_MODEL_HUB_MODEL_SERVER_TOPOLOGY_KEYS = frozenset(
    {
        "AI_MODEL_HUB_MODEL_SERVER_MODE",
        "LEVEL5_AI_MODEL_HUB_MODEL_SERVER_MODE",
        "MODEL_SERVER_MODE",
        "AI_MODEL_HUB_MODEL_SERVER_IMAGE",
        "MODEL_SERVER_IMAGE",
        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR",
        "MODEL_SERVER_SOURCE_DIR",
        "AI_MODEL_HUB_REAL_MODEL_SERVER_SOURCE_DIR",
        "AI_MODEL_HUB_USE_CASE_MODEL_SERVER_SOURCE_DIR",
        "MODEL_SERVER_REAL_SOURCE_DIR",
        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY",
        "AI_MODEL_HUB_USE_CASE_MODEL_SERVER_REPOSITORY",
        "AI_MODEL_HUB_REAL_MODEL_SERVER_REPOSITORY",
        "MODEL_SERVER_SOURCE_REPOSITORY",
        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF",
        "MODEL_SERVER_SOURCE_REF",
        "AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH",
        "MODEL_SERVER_MANIFEST_PATH",
        "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH",
        "MODEL_SERVER_READINESS_PATH",
        "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT",
        "MODEL_SERVER_CONTAINER_PORT",
        "AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE",
        "MODEL_SERVER_DOCKER_BASE_IMAGE",
        "AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP",
        "MODEL_SERVER_UVICORN_APP",
        "AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY",
        "MODEL_SERVER_IMAGE_PULL_POLICY",
        "AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES",
        "MODEL_SERVER_COPY_EXCLUDES",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
        "MODEL_SERVER_PUBLIC_URL",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL",
        "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH",
        "MODEL_SERVER_PUBLIC_PATH",
        "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
        "MODEL_SERVER_CONNECTOR_BASE_URL",
        "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL",
        "MODEL_SERVER_CONNECTOR_URL",
    }
)

COMPONENT_IMAGE_TOPOLOGY_KEYS = frozenset(
    {
        "COMPONENTS_IMAGE_PULL_POLICY",
        "ONTOLOGY_HUB_IMAGE_REF",
        "ONTOLOGY_HUB_PREBUILT_IMAGE_REF",
        "ONTOLOGY_HUB_PREBUILT_IMAGE",
        "ONTOLOGY_HUB_IMAGE_REPOSITORY",
        "ONTOLOGY_HUB_PREBUILT_IMAGE_REPOSITORY",
        "ONTOLOGY_HUB_IMAGE_TAG",
        "ONTOLOGY_HUB_PREBUILT_IMAGE_TAG",
        "ONTOLOGY_HUB_IMAGE_PULL_POLICY",
        "ONTOLOGY_HUB_PREBUILT_IMAGE_PULL_POLICY",
        "AI_MODEL_HUB_IMAGE_REF",
        "AI_MODEL_HUB_PREBUILT_IMAGE_REF",
        "AI_MODEL_HUB_PREBUILT_IMAGE",
        "AI_MODEL_HUB_IMAGE_REPOSITORY",
        "AI_MODEL_HUB_PREBUILT_IMAGE_REPOSITORY",
        "AI_MODEL_HUB_IMAGE_TAG",
        "AI_MODEL_HUB_PREBUILT_IMAGE_TAG",
        "AI_MODEL_HUB_IMAGE_PULL_POLICY",
        "AI_MODEL_HUB_PREBUILT_IMAGE_PULL_POLICY",
        "SEMANTIC_VIRTUALIZATION_IMAGE_REF",
        "SEMANTIC_VIRTUALIZATION_PREBUILT_IMAGE_REF",
        "SEMANTIC_VIRTUALIZATION_PREBUILT_IMAGE",
        "SEMANTIC_VIRTUALIZATION_IMAGE_REPOSITORY",
        "SEMANTIC_VIRTUALIZATION_PREBUILT_IMAGE_REPOSITORY",
        "SEMANTIC_VIRTUALIZATION_IMAGE_TAG",
        "SEMANTIC_VIRTUALIZATION_PREBUILT_IMAGE_TAG",
        "SEMANTIC_VIRTUALIZATION_IMAGE_PULL_POLICY",
        "SEMANTIC_VIRTUALIZATION_PREBUILT_IMAGE_PULL_POLICY",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PREBUILT_IMAGE_REF",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PREBUILT_IMAGE",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REPOSITORY",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PREBUILT_IMAGE_REPOSITORY",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_TAG",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PREBUILT_IMAGE_TAG",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_PULL_POLICY",
        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PREBUILT_IMAGE_PULL_POLICY",
        "SEMANTIC_VIRTUALIZATION_EDITOR_IMAGE_REF",
        "SEMANTIC_VIRTUALIZATION_EDITOR_PREBUILT_IMAGE_REF",
        "SEMANTIC_VIRTUALIZATION_EDITOR_PREBUILT_IMAGE",
        "SEMANTIC_VIRTUALIZATION_EDITOR_IMAGE_REPOSITORY",
        "SEMANTIC_VIRTUALIZATION_EDITOR_PREBUILT_IMAGE_REPOSITORY",
        "SEMANTIC_VIRTUALIZATION_EDITOR_IMAGE_TAG",
        "SEMANTIC_VIRTUALIZATION_EDITOR_PREBUILT_IMAGE_TAG",
        "SEMANTIC_VIRTUALIZATION_EDITOR_IMAGE_PULL_POLICY",
        "SEMANTIC_VIRTUALIZATION_EDITOR_PREBUILT_IMAGE_PULL_POLICY",
    }
)

IMAGE_BUILD_POLICY_TOPOLOGY_KEYS = frozenset(
    {
        "LEVEL4_LOCAL_IMAGES_MODE",
        "LEVEL4_INESDATA_LOCAL_IMAGES_MODE",
        "INESDATA_LOCAL_IMAGES_MODE",
        "LEVEL4_EDC_LOCAL_IMAGES_MODE",
        "EDC_LOCAL_IMAGES_MODE",
        "LEVEL5_AUTO_BUILD_LOCAL_IMAGES",
        "LEVEL6_AUTO_BUILD_LOCAL_IMAGES",
        "LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE",
        "LEVEL6_ASSUME_LOCAL_IMAGES_AVAILABLE",
    }
)

KAFKA_TOPOLOGY_KEYS = frozenset(
    {
        "KAFKA_PROVISIONER",
        "KAFKA_K8S_NAMESPACE",
        "KAFKA_K8S_SERVICE_NAME",
        "KAFKA_K8S_EXTERNAL_SERVICE_TYPE",
        "KAFKA_K8S_NODEPORT",
        "KAFKA_K8S_LOCAL_PORT",
        "KAFKA_CLUSTER_ADVERTISED_HOST",
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_CLUSTER_BOOTSTRAP_SERVERS",
        "KAFKA_EDC_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS",
        "KAFKA_EDC_CONSUMER_POLL_TIMEOUT_SECONDS",
        "KAFKA_EDC_KUBERNETES_EXEC_TIMEOUT_SECONDS",
        "KAFKA_EDC_KUBERNETES_EXEC_SCAN_MAX_MESSAGES",
        "KAFKA_EDC_KUBERNETES_EXEC_USE_TOPIC_OFFSETS",
        "KAFKA_EDC_LATE_PROBE_CONFIRMATION_SECONDS",
        "KAFKA_EDC_LATE_TRANSFER_CONFIRMATION_SECONDS",
        "KAFKA_EDC_MESSAGE_COUNT",
        "KAFKA_EDC_PAIR_ATTEMPTS",
        "KAFKA_EDC_PAIR_RETRY_SECONDS",
        "KAFKA_EDC_PRE_RUN_SETTLE_SECONDS",
        "KAFKA_EDC_STABILIZATION_GROUP_WAIT_SECONDS",
        "KAFKA_EDC_STABILIZATION_PROBE_TIMEOUT_SECONDS",
        "KAFKA_EDC_STARTUP_GRACE_SECONDS",
        "KAFKA_EDC_VALIDATION_BACKEND",
    }
)

INESDATA_CONNECTOR_IMAGE_TOPOLOGY_KEYS = frozenset(
    {
        "INESDATA_CONNECTOR_IMAGE_NAME",
        "INESDATA_CONNECTOR_IMAGE_TAG",
        "INESDATA_CONNECTOR_INTERFACE_IMAGE_NAME",
        "INESDATA_CONNECTOR_INTERFACE_IMAGE_TAG",
    }
)

EDC_IMAGE_TOPOLOGY_KEYS = frozenset(
    {
        "EDC_CONNECTOR_IMAGE_NAME",
        "EDC_CONNECTOR_IMAGE_TAG",
        "EDC_DASHBOARD_IMAGE_NAME",
        "EDC_DASHBOARD_IMAGE_TAG",
        "EDC_DASHBOARD_PROXY_IMAGE_NAME",
        "EDC_DASHBOARD_PROXY_IMAGE_TAG",
    }
)

EDC_RUNTIME_TOPOLOGY_KEYS = frozenset(
    {
        "EDC_SQL_SCHEMA_AUTOCREATE",
    }
)

TOPOLOGY_OVERLAY_KEYS = {
    "local": frozenset(
        {
            "PG_HOST",
            "VT_URL",
            "LOCAL_HOSTS_ADDRESS",
            "LOCAL_INGRESS_EXTERNAL_IP",
            "LOCAL_RESOURCE_PROFILE",
            "CLUSTER_TYPE",
            "MINIKUBE_DRIVER",
            "MINIKUBE_CPUS",
            "MINIKUBE_MEMORY",
            "MINIKUBE_PROFILE",
        }
    )
    | COMMON_SERVICE_TOPOLOGY_KEYS
    | KUBERNETES_WORKLOAD_TOPOLOGY_KEYS,
    "vm-single": frozenset(
        {
            "VM_EXTERNAL_IP",
            "VM_COMMON_IP",
            "VM_DATASPACE_IP",
            "VM_CONNECTORS_IP",
            "VM_COMPONENTS_IP",
            "INGRESS_EXTERNAL_IP",
            "FRAMEWORK_EXECUTION_MODE",
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
            "VM_SINGLE_REMOTE_IMAGE_IMPORT",
            "VM_SINGLE_REMOTE_IMAGE_IMPORT_COMMAND",
            "VM_SINGLE_REMOTE_IMAGE_IMPORT_DIR",
            "VM_SINGLE_REMOTE_IMAGE_IMPORT_INTERACTIVE",
            "VM_SINGLE_REMOTE_IMAGE_IMPORT_TTY",
            "VM_SINGLE_REMOTE_IMAGE_PRUNE",
            "VM_SINGLE_REMOTE_IMAGE_PRUNE_KEEP",
            "VM_SINGLE_K3S_LEVEL3_IMAGE_PREPULL",
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
            "VM_SINGLE_PUBLIC_URL",
            "VM_SINGLE_HTTP_URL",
            "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX",
            "VM_REMOTE_WORKDIR",
            "SSH_ACCESS_MODE",
            "SSH_BASTION_HOST",
            "SSH_BASTION_PORT",
            "SSH_BASTION_USER",
            "SSH_BASTION_IDENTITY_FILE",
            "SSH_IDENTITY_FILE",
            "SSH_CONNECT_TIMEOUT_SECONDS",
            "COMPONENTS_PUBLIC_BASE_URL",
            "COMPONENTS_PUBLIC_PATH_REWRITE",
            "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
            "AI_MODEL_OBSERVER_JOURNAL_BASE_URL",
            "AI_MODEL_HUB_OBSERVER_JOURNAL_BASE_URL",
            "MODEL_OBSERVER_JOURNAL_BASE_URL",
            "ONTOLOGY_HUB_PUBLIC_URL",
            "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_ENABLED",
            "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_SIZE",
            "ONTOLOGY_HUB_SELF_HOST_URL",
            "ONTOLOGY_HUB_INTERNAL_SELF_HOST_URL",
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME",
            "ONTOLOGY_HUB_SELF_HOST_NAMESPACE",
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT",
            "ONTOLOGY_HUB_SELF_HOST_PORT",
            "ONTOLOGY_HUB_SERVICE_NAME",
            "ONTOLOGY_HUB_SERVICE_NAMESPACE",
            "ONTOLOGY_HUB_SERVICE_PORT",
            "AI_MODEL_HUB_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_HOST",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NAMESPACE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_NAME",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_TYPE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NODE_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_MODE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_LOCAL_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_REMOTE_HOST",
        }
    )
    | COMMON_SERVICE_TOPOLOGY_KEYS
    | KUBERNETES_WORKLOAD_TOPOLOGY_KEYS
    | VM_SERVICE_TOPOLOGY_KEYS
    | AI_MODEL_HUB_MODEL_SERVER_TOPOLOGY_KEYS
    | COMPONENT_IMAGE_TOPOLOGY_KEYS
    | IMAGE_BUILD_POLICY_TOPOLOGY_KEYS
    | INESDATA_CONNECTOR_IMAGE_TOPOLOGY_KEYS
    | EDC_IMAGE_TOPOLOGY_KEYS
    | EDC_RUNTIME_TOPOLOGY_KEYS,
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
            "VM_PUBLIC_PROXY_IP",
            "TOPOLOGY_ROUTING_MODE",
            "VM_PROVIDER_CONNECTORS",
            "VM_CONSUMER_CONNECTORS",
            "VM_PROVIDER_INGRESS_HTTP_PORT",
            "VM_CONSUMER_INGRESS_HTTP_PORT",
            "VM_PROVIDER_INGRESS_NODEPORT",
            "VM_CONSUMER_INGRESS_NODEPORT",
            "CONNECTOR_PROTOCOL_ADDRESS_MODE",
            "PIONERA_LEVEL6_MINIO_ENDPOINT",
            "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES_ENABLED",
            "MINIO_CONSOLE_PUBLIC_ROOT_ALIASES",
            "COMPONENTS_PUBLIC_BASE_URL",
            "COMPONENTS_PUBLIC_PATH_REWRITE",
            "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
            "AI_MODEL_OBSERVER_JOURNAL_BASE_URL",
            "AI_MODEL_HUB_OBSERVER_JOURNAL_BASE_URL",
            "MODEL_OBSERVER_JOURNAL_BASE_URL",
            "ONTOLOGY_HUB_PUBLIC_URL",
            "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_ENABLED",
            "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_SIZE",
            "ONTOLOGY_HUB_SELF_HOST_URL",
            "ONTOLOGY_HUB_INTERNAL_SELF_HOST_URL",
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME",
            "ONTOLOGY_HUB_SELF_HOST_NAMESPACE",
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT",
            "ONTOLOGY_HUB_SELF_HOST_PORT",
            "ONTOLOGY_HUB_SERVICE_NAME",
            "ONTOLOGY_HUB_SERVICE_NAMESPACE",
            "ONTOLOGY_HUB_SERVICE_PORT",
            "AI_MODEL_HUB_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_HOST",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NAMESPACE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_NAME",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_TYPE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NODE_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_MODE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_LOCAL_PORT",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_REMOTE_HOST",
            "SSH_BASTION_HOST",
            "SSH_BASTION_PORT",
            "SSH_BASTION_USER",
            "SSH_BASTION_IDENTITY_FILE",
            "SSH_IDENTITY_FILE",
            "SSH_ACCESS_MODE",
            "SSH_CONNECT_TIMEOUT_SECONDS",
            "FRAMEWORK_EXECUTION_MODE",
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
            "VM_DISTRIBUTED_REMOTE_NGINX_INTERACTIVE",
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
            "VM_COMMON_SSH_ACCESS_MODE",
            "VM_COMMON_SSH_BASTION_HOST",
            "VM_COMMON_SSH_BASTION_PORT",
            "VM_COMMON_SSH_BASTION_USER",
            "VM_COMMON_SSH_BASTION_IDENTITY_FILE",
            "VM_COMPONENTS_SSH_HOST",
            "VM_COMPONENTS_SSH_PORT",
            "VM_COMPONENTS_SSH_USER",
            "VM_COMPONENTS_SSH_IDENTITY_FILE",
            "VM_COMPONENTS_SSH_ACCESS_MODE",
            "VM_COMPONENTS_SSH_BASTION_HOST",
            "VM_COMPONENTS_SSH_BASTION_PORT",
            "VM_COMPONENTS_SSH_BASTION_USER",
            "VM_COMPONENTS_SSH_BASTION_IDENTITY_FILE",
            "VM_PROVIDER_SSH_HOST",
            "VM_PROVIDER_SSH_PORT",
            "VM_PROVIDER_SSH_USER",
            "VM_PROVIDER_SSH_IDENTITY_FILE",
            "VM_PROVIDER_SSH_ACCESS_MODE",
            "VM_PROVIDER_SSH_BASTION_HOST",
            "VM_PROVIDER_SSH_BASTION_PORT",
            "VM_PROVIDER_SSH_BASTION_USER",
            "VM_PROVIDER_SSH_BASTION_IDENTITY_FILE",
            "VM_CONSUMER_SSH_HOST",
            "VM_CONSUMER_SSH_PORT",
            "VM_CONSUMER_SSH_USER",
            "VM_CONSUMER_SSH_IDENTITY_FILE",
            "VM_CONSUMER_SSH_ACCESS_MODE",
            "VM_CONSUMER_SSH_BASTION_HOST",
            "VM_CONSUMER_SSH_BASTION_PORT",
            "VM_CONSUMER_SSH_BASTION_USER",
            "VM_CONSUMER_SSH_BASTION_IDENTITY_FILE",
        }
    )
    | COMMON_SERVICE_TOPOLOGY_KEYS
    | KUBERNETES_WORKLOAD_TOPOLOGY_KEYS
    | VM_SERVICE_TOPOLOGY_KEYS
    | AI_MODEL_HUB_MODEL_SERVER_TOPOLOGY_KEYS
    | COMPONENT_IMAGE_TOPOLOGY_KEYS
    | IMAGE_BUILD_POLICY_TOPOLOGY_KEYS
    | KAFKA_TOPOLOGY_KEYS
    | INESDATA_CONNECTOR_IMAGE_TOPOLOGY_KEYS
    | EDC_IMAGE_TOPOLOGY_KEYS
    | EDC_RUNTIME_TOPOLOGY_KEYS,
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


def pionera_environment_override_keys() -> set[str]:
    """Return config keys provided through PIONERA_* environment variables."""

    keys: set[str] = set()
    for env_key, env_value in os.environ.items():
        if not env_key.startswith("PIONERA_"):
            continue
        override_key = env_key[len("PIONERA_"):].strip()
        if not override_key or env_value in (None, ""):
            continue
        keys.add(override_key)
    return keys


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


def apply_topology_runtime_defaults(
    config: dict[str, str],
    topology: str | None = None,
    protected_keys: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    """Fill runtime defaults that depend on the selected topology."""

    protected = set(protected_keys or [])
    common_namespace = str(config.get("COMMON_SERVICES_NAMESPACE") or "common-srvs").strip() or "common-srvs"

    if "DATABASE_HOSTNAME" not in protected and not str(config.get("DATABASE_HOSTNAME") or "").strip():
        config["DATABASE_HOSTNAME"] = f"common-srvs-postgresql.{common_namespace}.svc"

    vault_service_url = f"http://common-srvs-vault.{common_namespace}.svc:8200"
    if "VAULT_URL" not in protected and _is_blank_or_loopback_url(config.get("VAULT_URL")):
        config["VAULT_URL"] = vault_service_url

    normalized_topology = str(topology or "").strip().lower()
    if normalized_topology:
        config["TOPOLOGY"] = normalized_topology
    if normalized_topology not in {"vm-single", "vm-distributed"}:
        return config

    if "VT_URL" not in protected and _is_blank_or_loopback_url(config.get("VT_URL")):
        config["VT_URL"] = vault_service_url

    return config


def _is_blank_or_loopback_url(value: str | None) -> bool:
    raw_value = str(value or "").strip()
    if not raw_value:
        return True
    try:
        parsed = urlparse(raw_value if "://" in raw_value else f"http://{raw_value}")
    except ValueError:
        return False
    hostname = (parsed.hostname or "").strip().lower()
    return hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


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
    environment_override_keys = set()
    if apply_environment:
        environment_override_keys = pionera_environment_override_keys()
        apply_pionera_environment_overrides(config)
    apply_topology_runtime_defaults(config, topology, protected_keys=environment_override_keys)
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
