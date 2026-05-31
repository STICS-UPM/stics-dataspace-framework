import base64
from contextlib import contextmanager
import html
import importlib.util
import json
import os
import re
import shlex
import socket
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import urlparse

import requests
import yaml

from deployers.infrastructure.lib.namespaces import resolve_namespace_profile_plan
from deployers.shared.lib.components import ontology_validator_source_path, patch_ontology_validator_source
from deployers.shared.lib.connectors import (
    normalize_connector_name,
    parse_connector_mapping,
    parse_connector_pairs,
)
from deployers.shared.lib.public_hostnames import resolved_common_service_hostnames
from deployers.shared.lib.remote_k3s_images import remote_k3s_image_import_target
from deployers.shared.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    build_topology_profile,
    normalize_topology,
)
from deployers.shared.lib.vm_distributed_public_access import resolve_vm_distributed_public_urls
from deployers.shared.lib.cluster_runtime import build_cluster_runtime
from .config import INESDataConfigAdapter, InesdataConfig
from runtime_dependencies import ensure_python_requirements


class INESDataConnectorsAdapter:
    """Contains INESData connector lifecycle logic."""

    LEVEL4_LOCAL_IMAGE_TOPOLOGIES = {LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY}

    def __init__(self, run, run_silent, auto_mode_getter, infrastructure_adapter, config_adapter=None, config_cls=None):
        self.run = run
        self.run_silent = run_silent
        self.auto_mode_getter = auto_mode_getter
        self.infrastructure = infrastructure_adapter
        self.config = config_cls or InesdataConfig
        self.config_adapter = config_adapter or INESDataConfigAdapter(self.config)
        self._management_token_cache = {}
        self._vault_management_token_verified = False
        self._bootstrap_runtime_module = None

    def _auto_mode(self):
        return self.auto_mode_getter() if callable(self.auto_mode_getter) else bool(self.auto_mode_getter)

    def _normalized_topology(self):
        return normalize_topology(
            getattr(self.config_adapter, "topology", None)
            or getattr(self, "topology", None)
            or LOCAL_TOPOLOGY
        )

    def _is_local_topology(self):
        return self._normalized_topology() == LOCAL_TOPOLOGY

    def _vm_distributed_role_kubeconfig(self, role):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return ""

        normalized_role = str(role or "common").strip().lower() or "common"
        runtime = self._cluster_runtime()
        key_by_role = {
            "common": "k3s_kubeconfig_common",
            "provider": "k3s_kubeconfig_provider",
            "consumer": "k3s_kubeconfig_consumer",
            "components": "k3s_kubeconfig_components",
        }
        key = key_by_role.get(normalized_role, "k3s_kubeconfig_common")
        return str(runtime.get(key) or runtime.get("k3s_kubeconfig") or "").strip()

    @contextmanager
    def _temporary_kubeconfig_role(self, role):
        normalized_role = str(role or "common").strip().lower() or "common"
        kubeconfig = self._vm_distributed_role_kubeconfig(normalized_role)
        if not kubeconfig:
            yield
            return

        previous_kubeconfig = os.environ.get("KUBECONFIG")
        previous_role = os.environ.get("PIONERA_KUBECONFIG_ROLE")
        os.environ["KUBECONFIG"] = kubeconfig
        os.environ["PIONERA_KUBECONFIG_ROLE"] = normalized_role
        try:
            yield
        finally:
            if previous_kubeconfig is None:
                os.environ.pop("KUBECONFIG", None)
            else:
                os.environ["KUBECONFIG"] = previous_kubeconfig

            if previous_role is None:
                os.environ.pop("PIONERA_KUBECONFIG_ROLE", None)
            else:
                os.environ["PIONERA_KUBECONFIG_ROLE"] = previous_role

    def _connector_kubeconfig_role(self, connector_name):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return "common"

        layout = self._connector_layout_metadata(connector_name)
        for key in ("role", "namespaceRole"):
            role = str(layout.get(key) or "").strip().lower()
            if role in {"provider", "consumer"}:
                return role
        return "common"

    def _vm_distributed_uses_separate_connector_kubeconfigs(self):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return False
        common = self._vm_distributed_role_kubeconfig("common")
        provider = self._vm_distributed_role_kubeconfig("provider")
        consumer = self._vm_distributed_role_kubeconfig("consumer")
        return len({value for value in (common, provider, consumer) if value}) > 1

    @contextmanager
    def _temporary_connector_kubeconfig(self, connector_name):
        with self._temporary_kubeconfig_role(self._connector_kubeconfig_role(connector_name)):
            yield

    @contextmanager
    def _temporary_connector_cleanup_kubeconfig(self, connector_name, kubeconfig_role=None):
        if kubeconfig_role:
            with self._temporary_kubeconfig_role(kubeconfig_role):
                yield
            return
        with self._temporary_connector_kubeconfig(connector_name):
            yield

    def _dataspace_by_name(self, ds_name):
        target = str(ds_name or "").strip()
        if not target:
            return {}
        for dataspace in self.load_dataspace_connectors() or []:
            if str(dataspace.get("name") or "").strip() == target:
                return dataspace
        return {}

    def _namespace_kubeconfig_role(self, namespace, dataspace=None):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return "common"

        target_namespace = str(namespace or "").strip()
        if not target_namespace:
            return "common"

        if dataspace:
            candidate_dataspaces = [dataspace]
        else:
            try:
                candidate_dataspaces = list(self.load_dataspace_connectors() or [])
            except Exception:
                candidate_dataspaces = []

        for current in candidate_dataspaces:
            for roles_key in ("planned_namespace_roles", "namespace_roles"):
                roles = current.get(roles_key) or {}
                provider_namespace = self._namespace_role_value(roles, "provider_namespace")
                consumer_namespace = self._namespace_role_value(roles, "consumer_namespace")
                if target_namespace and target_namespace == provider_namespace:
                    return "provider"
                if target_namespace and target_namespace == consumer_namespace:
                    return "consumer"

            for connector_layout in current.get("connector_details") or []:
                if target_namespace not in {
                    str(connector_layout.get("active_namespace") or "").strip(),
                    str(connector_layout.get("planned_namespace") or "").strip(),
                }:
                    continue
                namespace_role = str(connector_layout.get("namespace_role") or "").strip().lower()
                validation_role = str(
                    connector_layout.get("validation_role")
                    or connector_layout.get("role")
                    or ""
                ).strip().lower()
                if namespace_role in {"provider", "consumer"}:
                    return namespace_role
                if validation_role in {"provider", "consumer"}:
                    return validation_role

        if target_namespace == "provider":
            return "provider"
        if target_namespace == "consumer":
            return "consumer"
        return "common"

    @contextmanager
    def _temporary_namespace_kubeconfig(self, namespace, dataspace=None):
        with self._temporary_kubeconfig_role(
            self._namespace_kubeconfig_role(namespace, dataspace=dataspace)
        ):
            yield

    def _bootstrap_environment_prefix(self):
        return f"PIONERA_TOPOLOGY={shlex.quote(self._normalized_topology())} "

    def _deployer_config_for_local_image_import(self):
        try:
            return dict(self.config_adapter.load_deployer_config() or {})
        except Exception:
            return {}

    def _vm_distributed_remote_image_import_configured(self):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return False
        deployer_config = self._deployer_config_for_local_image_import()
        for role in ("provider", "consumer", "common"):
            if remote_k3s_image_import_target(deployer_config, role=role):
                return True
        return False

    def _remote_image_import_env_prefix_for_namespace(self, namespace, dataspace=None):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return ""
        deployer_config = self._deployer_config_for_local_image_import()
        role = self._namespace_kubeconfig_role(namespace, dataspace=dataspace)
        target = remote_k3s_image_import_target(deployer_config, role=role)
        if not target:
            return ""
        env_prefix = target.render_shell_env_prefix()
        return f"{env_prefix} " if env_prefix else ""

    def _new_level4_connector_manifest_path(self):
        manifest_dir = os.path.join(tempfile.gettempdir(), "inesdata-manifests")
        os.makedirs(manifest_dir, exist_ok=True)
        return os.path.join(manifest_dir, f"images-level4-connectors-{time.time_ns()}.tsv")

    def _prepare_level4_local_connector_images_for_namespaces(self, namespaces):
        normalized_namespaces = []
        seen = set()
        for namespace in namespaces or []:
            normalized = str(namespace or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_namespaces.append(normalized)

        if not normalized_namespaces:
            return True

        if (
            self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY
            and self._vm_distributed_remote_image_import_configured()
            and len(normalized_namespaces) > 1
        ):
            manifest_file = self._new_level4_connector_manifest_path()
            first_namespace = normalized_namespaces[0]
            if not self._maybe_prepare_level4_local_connector_images(
                first_namespace,
                manifest_file=manifest_file,
            ):
                return False
            if not os.path.isfile(manifest_file):
                print(f"Level 4 local connector image manifest was not generated: {manifest_file}")
                return False
            for namespace in normalized_namespaces[1:]:
                if not self._maybe_prepare_level4_local_connector_images(
                    namespace,
                    manifest_file=manifest_file,
                    skip_build=True,
                ):
                    return False
            return True

        for namespace in normalized_namespaces:
            if not self._maybe_prepare_level4_local_connector_images(namespace):
                return False
        return True

    def _resolve_level4_local_image_policy(self, *, mode, label):
        normalized_mode = str(mode or "auto").strip().lower() or "auto"
        topology = self._normalized_topology()
        if topology in self.LEVEL4_LOCAL_IMAGE_TOPOLOGIES:
            return {
                "topology": topology,
                "mode": normalized_mode,
                "prepare_local_images": True,
                "allow_local_image_overrides": True,
                "message": "",
                "error": "",
            }

        if topology == VM_DISTRIBUTED_TOPOLOGY and self._vm_distributed_remote_image_import_configured():
            return {
                "topology": topology,
                "mode": normalized_mode,
                "prepare_local_images": True,
                "allow_local_image_overrides": True,
                "message": (
                    f"Preparing {label} local images for vm-distributed through remote k3s image import."
                ),
                "error": "",
            }

        if normalized_mode == "required":
            supported = ", ".join(sorted(self.LEVEL4_LOCAL_IMAGE_TOPOLOGIES))
            return {
                "topology": topology,
                "mode": normalized_mode,
                "prepare_local_images": False,
                "allow_local_image_overrides": False,
                "message": "",
                "error": (
                    f"{label} local image preparation mode 'required' is only supported in "
                    f"topologies {supported}, or in vm-distributed when "
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT=true and VM_*_SSH_HOST are configured. "
                    f"Configure pullable image references before running Level 4 on topology '{topology}' "
                    "or enable the remote import path."
                ),
            }

        return {
            "topology": topology,
            "mode": normalized_mode,
            "prepare_local_images": False,
            "allow_local_image_overrides": False,
            "message": (
                f"Skipping {label} local image preparation for topology '{topology}'. "
                "Using chart-configured image references."
            ),
            "error": "",
        }

    @staticmethod
    def _is_connector_interface_pod(pod_name):
        """Support both historical '-inteface' and corrected '-interface' suffixes."""
        return "interface" in pod_name or "inteface" in pod_name

    @classmethod
    def _is_connector_runtime_pod(cls, pod_name):
        return pod_name.startswith("conn-") and not cls._is_connector_interface_pod(pod_name)

    @classmethod
    def _connector_name_from_runtime_pod_name(cls, pod_name):
        if not cls._is_connector_runtime_pod(pod_name):
            return ""
        parts = pod_name.rsplit("-", 2)
        if len(parts) == 3:
            return parts[0]
        return pod_name.rsplit("-", 1)[0]

    @staticmethod
    def _fail(message, root_cause=None):
        if root_cause:
            raise RuntimeError(f"{message}. Root cause: {root_cause}")
        raise RuntimeError(message)

    def _dataspace_name(self):
        getter = getattr(self.config, "dataspace_name", None)
        if callable(getter):
            return getter()
        return (getattr(self.config, "DS_NAME", "demo") or "demo").strip() or "demo"

    def _pg_port(self):
        getter = getattr(self.config_adapter, "get_pg_port", None)
        if callable(getter):
            return str(getter())
        return str(getattr(self.config, "PORT_POSTGRES", 5432))

    @staticmethod
    def _first_config_value(config, *keys, default=None):
        for key in keys:
            value = config.get(key)
            if value not in (None, ""):
                return value
        return default

    @classmethod
    def _minio_admin_credentials(cls, config):
        return (
            cls._first_config_value(config, "MINIO_ADMIN_USER", "MINIO_USER", default="admin"),
            cls._first_config_value(config, "MINIO_ADMIN_PASS", "MINIO_PASSWORD", default="aPassword1234"),
        )

    @staticmethod
    def _connector_credentials_missing_requirements(creds_file_path):
        if not os.path.exists(creds_file_path):
            return []

        try:
            with open(creds_file_path, encoding="utf-8") as handle:
                credentials = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return ["valid-json"]

        required = {
            "database": ("name", "user", "passwd"),
            "certificates": ("path", "passwd"),
            "connector_user": ("user", "passwd"),
            "vault": ("path", "token"),
            "minio": ("user", "passwd", "access_key", "secret_key"),
        }
        missing = []
        for section, keys in required.items():
            value = credentials.get(section)
            if not isinstance(value, dict):
                missing.append(section)
                continue
            missing.extend(f"{section}.{key}" for key in keys if not value.get(key))
        return missing

    @staticmethod
    def _reserve_local_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.getsockname()[1]

    @staticmethod
    def _should_attempt_local_fallback(exc):
        if exc is None:
            return False
        message = str(exc).lower()
        return any(
            token in message
            for token in (
                "connection refused",
                "failed to establish a new connection",
                "failed to resolve",
                "name or service not known",
                "nameresolutionerror",
                "temporary failure in name resolution",
                "nodename nor servname provided",
                "max retries exceeded",
                "timed out",
            )
        )

    @staticmethod
    def _is_truthy(value):
        return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}

    def _level4_role_aligned_connector_namespaces_requested(self):
        env_value = os.environ.get("PIONERA_LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES")
        if env_value is not None:
            return self._is_truthy(env_value)

        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        return self._is_truthy(
            deployer_config.get("LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES")
            or deployer_config.get("ROLE_ALIGNED_CONNECTOR_NAMESPACES_LEVEL4")
        )

    def _level4_connector_reconciliation_mode(self):
        raw_value = os.environ.get("PIONERA_LEVEL4_CONNECTOR_RECONCILIATION_MODE")
        if raw_value is None:
            try:
                deployer_config = self.config_adapter.load_deployer_config() or {}
            except Exception:
                deployer_config = {}
            raw_value = (
                deployer_config.get("LEVEL4_CONNECTOR_RECONCILIATION_MODE")
                or "full"
            )
        mode = str(raw_value or "full").strip().lower().replace("_", "-")
        if mode in {"additive", "add-only", "append", "preserve-existing"}:
            return "additive"
        return "full"

    def _allow_connector_port_forward_fallback(self):
        env_value = os.environ.get("PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK")
        if env_value is not None:
            return self._is_truthy(env_value)

        configured_value = None
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        configured_value = (
            deployer_config.get("ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK")
            or deployer_config.get("CONNECTOR_PORT_FORWARD_FALLBACK")
        )
        if configured_value is not None:
            return self._is_truthy(configured_value)

        return self._role_aligned_connector_port_forward_fallback_implicit()

    def _ensure_local_runtime_access_if_required(self):
        if not self._is_local_topology():
            return True
        ensure_local_access = getattr(self.infrastructure, "ensure_local_infra_access", None)
        if not callable(ensure_local_access):
            return True
        return bool(ensure_local_access())

    def _role_aligned_connector_port_forward_fallback_implicit(self):
        if not self._is_local_topology():
            return False
        if os.environ.get("PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK") is not None:
            return False

        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        configured_value = (
            deployer_config.get("ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK")
            or deployer_config.get("CONNECTOR_PORT_FORWARD_FALLBACK")
        )
        if configured_value is not None:
            return False

        try:
            dataspaces = self.load_dataspace_connectors() or []
        except Exception:
            dataspaces = []
        return self._role_aligned_level4_namespaces_active(dataspaces=dataspaces)

    def _connector_public_ingress_stabilization_timeout(self, connector_name):
        if not self._role_aligned_connector_port_forward_fallback_implicit():
            return 0

        current = self._find_dataspace_for_connector(connector_name) or {}
        if not self._role_aligned_level4_namespaces_active(current):
            return 0

        default_namespace = str(
            current.get("namespace")
            or self._default_connector_namespace()
        ).strip() or self._default_connector_namespace()
        target_namespace = str(
            self._connector_target_namespace(connector_name, dataspace=current)
            or default_namespace
        ).strip() or default_namespace
        if target_namespace == default_namespace:
            return 0
        return 60

    def _connector_public_ingress_resync_wait_seconds(self, connector_name):
        if self._connector_public_ingress_stabilization_timeout(connector_name) <= 0:
            return 0
        return 20

    def _trigger_connector_ingress_resync(self, connector_name):
        if not self._is_local_topology():
            return False
        namespace = str(self._connector_target_namespace(connector_name) or "").strip()
        if not namespace:
            return False
        ingress_name = f"{connector_name}-ingress"
        sync_marker = str(int(time.time()))
        with self._temporary_connector_kubeconfig(connector_name):
            result = self.run_silent(
                f"kubectl annotate ingress {ingress_name} -n {namespace} "
                f"validation-environment/forced-sync-at={sync_marker} --overwrite"
            )
        if result is None:
            return False
        print(f"Requesting ingress resynchronization for connector: {connector_name}")
        return True

    def _default_connector_namespace(self):
        namespace_getter = getattr(self.config, "namespace_demo", None)
        if callable(namespace_getter):
            namespace = namespace_getter()
            if namespace:
                return str(namespace).strip()
        return self._dataspace_name()

    def _connector_details_by_name(self, dataspace):
        return {
            entry.get("name"): entry
            for entry in (dataspace.get("connector_details") or [])
            if entry.get("name")
        }

    def _role_aligned_level4_namespaces_active(self, dataspace=None, dataspaces=None):
        if not self._level4_role_aligned_connector_namespaces_requested():
            return False
        all_dataspaces = dataspaces or self.load_dataspace_connectors() or []
        if len(all_dataspaces) != 1:
            return False
        current = dataspace or all_dataspaces[0]
        profile = str(current.get("namespace_profile") or "compact").strip().lower()
        return profile == "role-aligned"

    def _connector_target_namespace(self, connector_name, dataspace=None, dataspaces=None):
        current = dataspace or self._find_dataspace_for_connector(connector_name) or {}
        default_namespace = str(
            current.get("namespace")
            or self._default_connector_namespace()
        ).strip() or self._default_connector_namespace()
        details = self._connector_details_by_name(current).get(connector_name, {})
        active_namespace = str(details.get("active_namespace") or default_namespace).strip() or default_namespace
        planned_namespace = str(details.get("planned_namespace") or active_namespace).strip() or active_namespace
        if self._role_aligned_level4_namespaces_active(current, dataspaces=dataspaces):
            return planned_namespace
        return active_namespace

    def connector_target_namespace(self, connector_name):
        return self._connector_target_namespace(connector_name)

    def build_internal_protocol_address(self, connector_name, port=19194, path="/protocol"):
        current = self._find_dataspace_for_connector(connector_name) or {}
        default_namespace = str(
            current.get("namespace")
            or self._default_connector_namespace()
        ).strip() or self._default_connector_namespace()
        target_namespace = str(
            self._connector_target_namespace(connector_name, dataspace=current)
            or default_namespace
        ).strip() or default_namespace
        if target_namespace and target_namespace != default_namespace:
            hostname = f"{connector_name}.{target_namespace}.svc.cluster.local"
        else:
            hostname = connector_name
        normalized_path = f"/{str(path or '/protocol').lstrip('/')}"
        return f"http://{hostname}:{int(port)}{normalized_path}"

    def _connector_protocol_address_mode(self):
        deployer_config = self.config_adapter.load_deployer_config() or {}
        raw_mode = (
            os.environ.get("PIONERA_CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or os.environ.get("CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or deployer_config.get("PIONERA_CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or deployer_config.get("CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or ""
        )
        mode = str(raw_mode or "").strip().lower()
        if mode in {"public", "external"}:
            return "public"
        if mode in {"internal", "private"}:
            return "internal"
        return "internal"

    def build_protocol_address(self, connector_name, path="/protocol"):
        normalized_path = f"/{str(path or '/protocol').lstrip('/')}"
        if self._connector_protocol_address_mode() == "public":
            return self.build_public_protocol_address(connector_name, path=normalized_path)

        credentials_url = self._connector_access_url(connector_name, "connector_protocol_api")
        if credentials_url:
            return self._normalize_public_url(credentials_url)

        return f"{self.connector_base_url(connector_name).rstrip('/')}{normalized_path}"

    def build_public_protocol_address(self, connector_name, path="/protocol"):
        normalized_path = f"/{str(path or '/protocol').lstrip('/')}"
        credentials_url = self._connector_public_access_url(connector_name, "connector_protocol_api")
        if credentials_url:
            return self._normalize_public_url(credentials_url)
        return f"{self.connector_base_url(connector_name).rstrip('/')}{normalized_path}"

    def _dataspace_connector_target_namespaces(self, dataspace, dataspaces=None):
        connectors = list(dataspace.get("connectors") or [])
        if not connectors:
            return [str(dataspace.get("namespace") or self._default_connector_namespace()).strip() or self._default_connector_namespace()]
        ordered = []
        for connector in connectors:
            namespace = self._connector_target_namespace(
                connector,
                dataspace=dataspace,
                dataspaces=dataspaces,
            )
            if namespace and namespace not in ordered:
                ordered.append(namespace)
        return ordered or [str(dataspace.get("namespace") or self._default_connector_namespace()).strip() or self._default_connector_namespace()]

    def _all_connector_scan_namespaces(self):
        dataspaces = self.load_dataspace_connectors() or []
        ordered = []
        for dataspace in dataspaces:
            for namespace in self._dataspace_connector_target_namespaces(dataspace, dataspaces=dataspaces):
                if namespace not in ordered:
                    ordered.append(namespace)
        return ordered or [self._default_connector_namespace()]

    def _should_sync_vault_token_to_deployer_config(self):
        for resolver_name in ("infrastructure_deployer_config_path", "deployer_config_path"):
            resolver = getattr(self.config, resolver_name, None)
            if callable(resolver) and os.path.exists(resolver()):
                return True
        return False

    @staticmethod
    def _vault_capabilities_allow_management(capabilities):
        capability_set = set(capabilities or [])
        if "root" in capability_set or "sudo" in capability_set:
            return True
        return bool({"create", "update"}.intersection(capability_set)) and "deny" not in capability_set

    @staticmethod
    def _vault_cluster_service_reference(vault_url):
        try:
            parsed = urlparse(vault_url if "://" in vault_url else f"http://{vault_url}")
            port = parsed.port
        except ValueError:
            return None

        hostname = (parsed.hostname or "").strip().lower()
        parts = hostname.split(".")
        if len(parts) < 3 or parts[2] != "svc" or not parts[0] or not parts[1]:
            return None

        if port is None:
            port = 443 if parsed.scheme == "https" else 80

        return {
            "scheme": parsed.scheme or "http",
            "service": parts[0],
            "namespace": parts[1],
            "port": port,
        }

    def _common_services_namespace(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        return str(
            deployer_config.get("COMMON_SERVICES_NAMESPACE")
            or getattr(self.config, "NS_COMMON", "common-srvs")
            or "common-srvs"
        ).strip() or "common-srvs"

    @staticmethod
    def _vault_management_token_paths(ds_name):
        return [
            "sys/policy/inesdata-preflight-secrets-policy",
            "auth/token/create",
            f"secret/data/{ds_name}/inesdata-preflight/public-key",
        ]

    @staticmethod
    def _vault_network_failure_message(stage, exc):
        if stage == "capabilities":
            return f"Vault token capabilities check failed: Vault is not reachable ({exc})"
        return f"Vault token validation failed: Vault is not reachable ({exc})"

    def _verify_vault_management_token_over_http(self, vault_url, vault_token, paths):
        headers = {"X-Vault-Token": vault_token}
        try:
            response = requests.get(
                f"{vault_url}/v1/auth/token/lookup-self",
                headers=headers,
                timeout=5,
                verify=False,
            )
        except requests.RequestException as exc:
            return False, {"stage": "lookup", "exception": exc}

        if response.status_code != 200:
            print(
                "Vault token validation failed: lookup-self returned "
                f"HTTP {response.status_code}. The shared Vault keys artifact may be stale "
                "for the running Vault. Recreate Level 2 common services or restore the "
                "current Vault root token before deploying INESData connectors."
            )
            return False, None

        try:
            response = requests.post(
                f"{vault_url}/v1/sys/capabilities-self",
                headers=headers,
                json={"paths": paths},
                timeout=5,
                verify=False,
            )
        except requests.RequestException as exc:
            return False, {"stage": "capabilities", "exception": exc}

        if response.status_code != 200:
            print(
                "Vault token capabilities check failed: Vault returned "
                f"HTTP {response.status_code}. INESData connector bootstrap requires policy, "
                "token and secret creation permissions."
            )
            return False, None

        try:
            capabilities_payload = response.json()
        except ValueError:
            print("Vault token capabilities check failed: Vault returned an invalid JSON response")
            return False, None

        for path in paths:
            capabilities = capabilities_payload.get(path)
            if capabilities is None:
                capabilities = capabilities_payload.get("capabilities")
            if not self._vault_capabilities_allow_management(capabilities):
                print(
                    "Vault token capabilities check failed: token does not have management "
                    f"permissions for '{path}'. Recreate Level 2 common services or restore "
                    "the current Vault root token before deploying INESData connectors."
                )
                return False, None

        return True, None

    def _verify_vault_management_token_via_port_forward(self, vault_url, vault_token, paths):
        service_ref = self._vault_cluster_service_reference(vault_url)
        if not service_ref:
            return False

        with self._temporary_kubeconfig_role("common"):
            port_forward = self._open_temporary_port_forward(
                service_ref["namespace"],
                service_ref["service"],
                remote_port=service_ref["port"],
            )
        if not port_forward:
            print(
                "Vault token validation fallback failed: could not open a temporary "
                f"port-forward to {service_ref['service']} in namespace {service_ref['namespace']}."
            )
            return False

        local_url = f"{service_ref['scheme']}://127.0.0.1:{port_forward['local_port']}"
        print(
            "Vault is exposed through Kubernetes DNS; retrying token validation through "
            "a temporary local port-forward."
        )
        try:
            validated, network_failure = self._verify_vault_management_token_over_http(
                local_url,
                vault_token,
                paths,
            )
            if network_failure:
                print(
                    self._vault_network_failure_message(
                        network_failure["stage"],
                        network_failure["exception"],
                    )
                )
            return validated
        finally:
            self._close_temporary_port_forward(port_forward)

    def _verify_vault_management_token(self, ds_name=None):
        deployer_config = self.config_adapter.load_deployer_config() or {}
        vault_url = str(
            deployer_config.get("VT_URL") or deployer_config.get("VAULT_URL") or ""
        ).strip().rstrip("/")
        vault_token = str(deployer_config.get("VT_TOKEN") or "").strip()
        if not vault_url or not vault_token:
            print("Vault token validation failed: VT_URL/VT_TOKEN are not defined in deployer.config")
            return False

        ds_name = ds_name or self._dataspace_name()
        paths = self._vault_management_token_paths(ds_name)
        validated, network_failure = self._verify_vault_management_token_over_http(
            vault_url,
            vault_token,
            paths,
        )
        if validated:
            return True

        if network_failure:
            if (
                self._should_attempt_local_fallback(network_failure["exception"])
                and self._vault_cluster_service_reference(vault_url)
                and self._verify_vault_management_token_via_port_forward(vault_url, vault_token, paths)
            ):
                return True
            print(
                self._vault_network_failure_message(
                    network_failure["stage"],
                    network_failure["exception"],
                )
            )
            return False

        return False

    def _start_vault_bootstrap_access(self):
        deployer_config = self.config_adapter.load_deployer_config() or {}
        vault_url = str(
            deployer_config.get("VT_URL") or deployer_config.get("VAULT_URL") or ""
        ).strip().rstrip("/")
        service_ref = self._vault_cluster_service_reference(vault_url)
        if not service_ref:
            return {"vault_url": None, "port_forward": None}

        with self._temporary_kubeconfig_role("common"):
            port_forward = self._open_temporary_port_forward(
                service_ref["namespace"],
                service_ref["service"],
                remote_port=service_ref["port"],
            )
        if not port_forward:
            print(
                "Vault bootstrap fallback failed: could not open a temporary "
                f"port-forward to {service_ref['service']} in namespace {service_ref['namespace']}."
            )
            return None

        local_url = f"{service_ref['scheme']}://127.0.0.1:{port_forward['local_port']}"
        print(
            "Using temporary local Vault port-forward for Level 4 bootstrap commands "
            f"({service_ref['service']}.{service_ref['namespace']}.svc -> {local_url})."
        )
        return {"vault_url": local_url, "port_forward": port_forward}

    def _stop_vault_bootstrap_access(self, bootstrap_access):
        if not bootstrap_access:
            return
        self._close_temporary_port_forward(bootstrap_access.get("port_forward"))

    def _keycloak_admin_url(self, override_url=None):
        if override_url:
            return str(override_url).strip().rstrip("/")

        deployer_config = self.config_adapter.load_deployer_config() or {}
        keycloak_url = str(
            deployer_config.get("KC_MANAGEMENT_URL") or deployer_config.get("KC_URL") or ""
        ).strip()
        if keycloak_url and not keycloak_url.startswith("http"):
            keycloak_url = f"http://{keycloak_url}"
        return keycloak_url.rstrip("/")

    def _vm_distributed_keycloak_admin_port_forward_requested(self):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return False

        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}

        mode = str(deployer_config.get("KEYCLOAK_BOOTSTRAP_ACCESS") or "").strip().lower()
        if mode in {"port-forward", "port_forward", "local-port-forward", "local_port_forward"}:
            return True

        for key in (
            "KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
            "KEYCLOAK_PORT_FORWARD_BOOTSTRAP",
            "FORCE_KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
        ):
            value = deployer_config.get(key)
            if value is not None:
                return self._is_truthy(value)

        return False

    def _vm_distributed_keycloak_admin_needs_port_forward(self):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return False

        if self._vm_distributed_keycloak_admin_port_forward_requested():
            return True

        keycloak_url = self._keycloak_admin_url()
        if not keycloak_url:
            return False

        try:
            parsed = urlparse(keycloak_url)
        except ValueError:
            return False

        hostname = (parsed.hostname or "").strip()
        if not hostname or hostname in {"127.0.0.1", "::1", "localhost"}:
            return False

        try:
            socket.getaddrinfo(hostname, None)
            return False
        except OSError:
            return True

    def _start_keycloak_bootstrap_access(self):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return {"keycloak_url": None, "port_forward": None}

        deployer_config = self.config_adapter.load_deployer_config() or {}
        namespace = self._common_services_namespace()
        pattern = str(
            deployer_config.get("KEYCLOAK_PORT_FORWARD_POD_PATTERN")
            or f"{namespace}-keycloak"
        ).strip()
        try:
            remote_port = int(
                deployer_config.get("KEYCLOAK_PORT_FORWARD_REMOTE_PORT")
                or deployer_config.get("KEYCLOAK_POD_HTTP_PORT")
                or 8080
            )
        except (TypeError, ValueError):
            remote_port = 8080

        with self._temporary_kubeconfig_role("common"):
            port_forward = self._open_temporary_port_forward(
                namespace,
                pattern,
                remote_port=remote_port,
            )

        if not port_forward:
            print(
                "Keycloak bootstrap fallback failed: could not open a temporary "
                f"port-forward to {pattern} in namespace {namespace}."
            )
            return None

        local_url = f"http://127.0.0.1:{port_forward['local_port']}"
        print(
            "Using temporary local Keycloak port-forward for Level 4 bootstrap commands "
            f"({pattern}.{namespace} -> {local_url})."
        )
        return {"keycloak_url": local_url, "port_forward": port_forward}

    def _stop_keycloak_bootstrap_access(self, bootstrap_access):
        if not bootstrap_access:
            return
        self._close_temporary_port_forward(bootstrap_access.get("port_forward"))

    def _start_postgres_bootstrap_access(self):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return {"pg_host": None, "pg_port": None, "port_forward": None}

        if not callable(getattr(self.infrastructure, "port_forward_service", None)):
            return {"pg_host": None, "pg_port": None, "port_forward": None}

        deployer_config = self.config_adapter.load_deployer_config() or {}
        namespace = self._common_services_namespace()
        pattern = str(
            deployer_config.get("POSTGRES_PORT_FORWARD_POD_PATTERN")
            or f"{namespace}-postgresql"
        ).strip()
        try:
            remote_port = int(
                deployer_config.get("POSTGRES_PORT_FORWARD_REMOTE_PORT")
                or deployer_config.get("PG_PORT")
                or 5432
            )
        except (TypeError, ValueError):
            remote_port = 5432

        with self._temporary_kubeconfig_role("common"):
            port_forward = self._open_temporary_port_forward(
                namespace,
                pattern,
                remote_port=remote_port,
            )

        if not port_forward:
            issue = str(getattr(self.infrastructure, "_last_port_forward_error", "") or "").strip()
            detail = f" Last port-forward issue: {issue}" if issue else ""
            print(
                "PostgreSQL bootstrap fallback failed: could not open a temporary "
                f"port-forward to {pattern} in namespace {namespace}.{detail}"
            )
            return None

        local_port = str(port_forward["local_port"])
        print(
            "Using temporary local PostgreSQL port-forward for Level 4 bootstrap commands "
            f"({pattern}.{namespace} -> 127.0.0.1:{local_port})."
        )
        return {"pg_host": "127.0.0.1", "pg_port": local_port, "port_forward": port_forward}

    def _stop_postgres_bootstrap_access(self, bootstrap_access):
        if not bootstrap_access:
            return
        self._close_temporary_port_forward(bootstrap_access.get("port_forward"))

    def _start_level4_connector_bootstrap_access(self):
        vault_bootstrap_access = self._start_vault_bootstrap_access()
        if vault_bootstrap_access is None:
            return None

        postgres_bootstrap_access = self._start_postgres_bootstrap_access()
        if postgres_bootstrap_access is None:
            self._stop_vault_bootstrap_access(vault_bootstrap_access)
            return None

        keycloak_bootstrap_access = {"keycloak_url": None, "port_forward": None}
        if (
            self._vm_distributed_keycloak_admin_needs_port_forward()
            and callable(getattr(self.infrastructure, "port_forward_service", None))
        ):
            keycloak_bootstrap_access = self._start_keycloak_bootstrap_access()
            if keycloak_bootstrap_access is None:
                self._stop_postgres_bootstrap_access(postgres_bootstrap_access)
                self._stop_vault_bootstrap_access(vault_bootstrap_access)
                return None

        return {
            "vault_access": vault_bootstrap_access,
            "postgres_access": postgres_bootstrap_access,
            "keycloak_access": keycloak_bootstrap_access,
            "vault_url": vault_bootstrap_access.get("vault_url"),
            "pg_host": postgres_bootstrap_access.get("pg_host"),
            "pg_port": postgres_bootstrap_access.get("pg_port"),
            "keycloak_url": keycloak_bootstrap_access.get("keycloak_url"),
        }

    def _stop_level4_connector_bootstrap_access(self, bootstrap_access):
        if not bootstrap_access:
            return
        self._stop_keycloak_bootstrap_access(bootstrap_access.get("keycloak_access"))
        self._stop_postgres_bootstrap_access(bootstrap_access.get("postgres_access"))
        self._stop_vault_bootstrap_access(bootstrap_access.get("vault_access"))

    def _ensure_level4_keycloak_ready(self, bootstrap_access, purpose):
        keycloak_url = bootstrap_access.get("keycloak_url") if bootstrap_access else None
        if self.wait_for_keycloak_admin_ready(keycloak_url=keycloak_url):
            return True

        if (
            keycloak_url is None
            and self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY
            and callable(getattr(self.infrastructure, "port_forward_service", None))
        ):
            keycloak_bootstrap_access = self._start_keycloak_bootstrap_access()
            if keycloak_bootstrap_access is not None:
                bootstrap_access["keycloak_access"] = keycloak_bootstrap_access
                bootstrap_access["keycloak_url"] = keycloak_bootstrap_access.get("keycloak_url")
                keycloak_url = bootstrap_access.get("keycloak_url")

        if keycloak_url and self.wait_for_keycloak_admin_ready(keycloak_url=keycloak_url):
            return True

        print(f"Keycloak admin API not ready for connector {purpose}")
        return False

    def _prepare_vault_management_access(self, ds_name=None):
        if self._vault_management_token_verified:
            return True

        if not self._ensure_local_runtime_access_if_required():
            return False

        if not self.infrastructure.ensure_vault_unsealed():
            return False

        if self._should_sync_vault_token_to_deployer_config():
            reconcile_vault_state = getattr(self.infrastructure, "reconcile_vault_state_for_local_runtime", None)
            sync_vault_token = getattr(self.infrastructure, "sync_vault_token_to_deployer_config", None)
            if callable(reconcile_vault_state):
                synchronized = reconcile_vault_state()
            elif callable(sync_vault_token):
                synchronized = sync_vault_token()
            else:
                synchronized = True
            if not synchronized:
                print("Could not synchronize Vault token into deployer.config")
                return False

        if not self._verify_vault_management_token(ds_name=ds_name):
            return False

        self._vault_management_token_verified = True
        return True

    def _connector_runtime_namespace(self, connector_name):
        namespace = self._connector_target_namespace(connector_name)
        if namespace:
            return str(namespace).strip()
        return self._default_connector_namespace()

    def _connector_pod_name(self, connector_name, interface=False, namespace=None):
        namespace = str(namespace or self._connector_runtime_namespace(connector_name) or "").strip()
        if not namespace:
            namespace = self._default_connector_namespace()
        with self._temporary_connector_kubeconfig(connector_name):
            result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")
        if not result:
            return None

        preferred = []
        fallback = []
        for line in result.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue

            pod_name = parts[0]
            status = parts[2]
            if not pod_name.startswith(connector_name):
                continue

            is_interface = self._is_connector_interface_pod(pod_name)
            if interface != is_interface:
                continue

            if status == "Running":
                preferred.append(pod_name)
            else:
                fallback.append(pod_name)

        candidates = preferred or fallback
        return candidates[0] if candidates else None

    def _open_temporary_port_forward(self, namespace, pod_name, remote_port):
        port_forward_service = getattr(self.infrastructure, "port_forward_service", None)
        if not callable(port_forward_service) or not pod_name:
            return None

        local_port = self._reserve_local_port()
        if not port_forward_service(namespace, pod_name, local_port, remote_port, quiet=True):
            return None

        return {
            "namespace": namespace,
            "pod_name": pod_name,
            "local_port": local_port,
            "kubeconfig_role": os.environ.get("PIONERA_KUBECONFIG_ROLE"),
        }

    def _close_temporary_port_forward(self, port_forward_info):
        if not port_forward_info:
            return

        stop_port_forward_service = getattr(self.infrastructure, "stop_port_forward_service", None)
        if callable(stop_port_forward_service):
            with self._temporary_kubeconfig_role(port_forward_info.get("kubeconfig_role")):
                stop_port_forward_service(
                    port_forward_info["namespace"],
                    port_forward_info["pod_name"],
                    quiet=True,
                )

    def _start_connector_interface_fallback(self, connector_name):
        namespace = self._connector_runtime_namespace(connector_name)
        with self._temporary_connector_kubeconfig(connector_name):
            pod_name = self._connector_pod_name(connector_name, interface=True, namespace=namespace)
            if not pod_name:
                return None, None

            port_forward = self._open_temporary_port_forward(
                namespace,
                pod_name,
                remote_port=8080,
            )
        if not port_forward:
            return None, None

        url = f"http://127.0.0.1:{port_forward['local_port']}/inesdata-connector-interface/"
        return url, port_forward

    def _start_connector_management_api_fallback(self, connector_name):
        namespace = self._connector_runtime_namespace(connector_name)
        with self._temporary_connector_kubeconfig(connector_name):
            pod_name = self._connector_pod_name(connector_name, interface=False, namespace=namespace)
            if not pod_name:
                return None, None

            port_forward = self._open_temporary_port_forward(
                namespace,
                pod_name,
                remote_port=19193,
            )
        if not port_forward:
            return None, None

        url = f"http://127.0.0.1:{port_forward['local_port']}/management/v3/assets/request"
        return url, port_forward

    def wait_for_keycloak_admin_ready(self, timeout=120, poll_interval=3, keycloak_url=None):
        print("Waiting for Keycloak admin authentication to become ready...")
        deployer_config = self.config_adapter.load_deployer_config()
        kc_url = self._keycloak_admin_url(keycloak_url)
        kc_user = deployer_config.get("KC_USER")
        kc_password = deployer_config.get("KC_PASSWORD")

        if not kc_url or not kc_user or not kc_password:
            print("Keycloak admin readiness check skipped: KC_MANAGEMENT_URL/KC_URL/KC_USER/KC_PASSWORD missing")
            return False

        token_url = f"{kc_url.rstrip('/')}/realms/master/protocol/openid-connect/token"
        last_issue = None
        start = time.time()

        while time.time() - start <= timeout:
            try:
                response = requests.post(
                    token_url,
                    data={
                        "grant_type": "password",
                        "client_id": "admin-cli",
                        "username": kc_user,
                        "password": kc_password,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=5,
                )
                if response.status_code == 200 and response.json().get("access_token"):
                    print("Keycloak admin authentication is ready")
                    return True
                last_issue = f"HTTP {response.status_code}"
            except Exception as exc:
                last_issue = str(exc)

            time.sleep(poll_interval)

        if last_issue:
            print(f"Keycloak admin authentication did not become ready: {last_issue}")
            print("Check that the Keycloak hostname resolves through the active ingress/minikube tunnel.")
        else:
            print("Keycloak admin authentication did not become ready")
        return False

    def _bootstrap_connector_environment_prefix(
        self,
        vault_url=None,
        keycloak_url=None,
        pg_host=None,
        pg_port=None,
    ):
        prefix = self._bootstrap_environment_prefix()
        if vault_url:
            prefix += f"PIONERA_VT_URL={shlex.quote(str(vault_url).rstrip('/'))} "
        if keycloak_url:
            prefix += f"PIONERA_KC_MANAGEMENT_URL={shlex.quote(str(keycloak_url).rstrip('/'))} "
        if pg_host:
            prefix += f"PIONERA_PG_HOST={shlex.quote(str(pg_host))} "
        if pg_port:
            prefix += f"PIONERA_PG_PORT={shlex.quote(str(pg_port))} "
        return prefix

    def _bootstrap_connector_create_command(
        self,
        python_exec,
        connector_name,
        ds_name,
        vault_url=None,
        keycloak_url=None,
        pg_host=None,
        pg_port=None,
    ):
        return (
            f"{self._bootstrap_connector_environment_prefix(vault_url, keycloak_url, pg_host, pg_port)}{python_exec} "
            f"bootstrap.py connector create {connector_name} {ds_name}"
        )

    def _bootstrap_connector_delete_command(
        self,
        python_exec,
        connector_name,
        ds_name,
        vault_url=None,
        keycloak_url=None,
        pg_host=None,
        pg_port=None,
    ):
        return (
            f"{self._bootstrap_connector_environment_prefix(vault_url, keycloak_url, pg_host, pg_port)}{python_exec} "
            f"bootstrap.py connector delete {connector_name} {ds_name}"
        )

    def validate_connector_name(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError("Connector name must be a non-empty string")

        if len(name) > 20:
            raise ValueError(f"Invalid connector name '{name}'. Maximum length is 20 characters.")

        if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", name):
            raise ValueError(
                f"Invalid connector name '{name}'. Connector names must start with a letter and contain only alphanumeric characters."
            )

    @staticmethod
    def _connector_role_summary(connectors, validation_pairs=None):
        ordered = [connector for connector in connectors or [] if connector]
        first_pair = next(iter(validation_pairs or []), None)
        if first_pair:
            provider = first_pair[0] if first_pair[0] in ordered else None
            consumer = first_pair[1] if first_pair[1] in ordered else None
        else:
            provider = ordered[0] if len(ordered) >= 1 else None
            consumer = ordered[1] if len(ordered) >= 2 else None
        return {
            "provider": provider,
            "consumer": consumer,
            "additional": [
                connector
                for connector in ordered
                if connector not in {provider, consumer}
            ],
        }

    @staticmethod
    def _scoped_deployer_config_value(config, ds_index, suffix, default=""):
        try:
            resolved_index = int(ds_index)
        except (TypeError, ValueError):
            resolved_index = 1
        candidates = []
        if resolved_index >= 1:
            candidates.append(f"DS_{resolved_index}_{suffix}")
        if resolved_index != 1:
            candidates.append(f"DS_1_{suffix}")
        candidates.append(suffix)
        for key in candidates:
            value = str((config or {}).get(key) or "").strip()
            if value:
                return value
        return default

    def _configured_validation_pairs(self, deployer_config, ds_name, ds_index):
        raw_value = (
            self._scoped_deployer_config_value(deployer_config, ds_index, "VALIDATION_PAIR")
            or self._scoped_deployer_config_value(deployer_config, ds_index, "VALIDATION_PAIRS")
        )
        return parse_connector_pairs(raw_value, ds_name)

    def _configured_connector_namespace_overrides(self, deployer_config, ds_name, ds_index, namespace_plan):
        raw_value = self._scoped_deployer_config_value(
            deployer_config,
            ds_index,
            "CONNECTOR_NAMESPACES",
        )
        raw_mapping = parse_connector_mapping(raw_value, ds_name)
        return {
            connector: self._resolve_connector_namespace_override(target, namespace_plan)
            for connector, target in raw_mapping.items()
        }

    def _resolve_connector_namespace_override(self, target, namespace_plan):
        raw_target = str(target or "").strip()
        runtime_roles = namespace_plan["namespace_roles"]
        planned_roles = namespace_plan["planned_namespace_roles"]
        normalized = raw_target.lower().replace("-", "_")
        aliases = {
            "provider": "provider_namespace",
            "provider_namespace": "provider_namespace",
            "consumer": "consumer_namespace",
            "consumer_namespace": "consumer_namespace",
            "registration": "registration_service_namespace",
            "registration_service": "registration_service_namespace",
            "core": "registration_service_namespace",
            "dataspace": "",
            "default": "",
        }
        role_field = aliases.get(normalized)
        if role_field:
            active_namespace = self._namespace_role_value(runtime_roles, role_field)
            planned_namespace = self._namespace_role_value(planned_roles, role_field, active_namespace)
            namespace_role = normalized
        elif role_field == "":
            active_namespace = ""
            planned_namespace = ""
            namespace_role = normalized
        else:
            active_namespace = raw_target
            planned_namespace = raw_target
            namespace_role = "custom"
        return {
            "configured_namespace": raw_target,
            "namespace_role": namespace_role,
            "active_namespace": active_namespace,
            "planned_namespace": planned_namespace,
        }

    @staticmethod
    def _namespace_role_value(roles, key, default=""):
        if hasattr(roles, key):
            value = getattr(roles, key)
        elif isinstance(roles, dict):
            value = roles.get(key)
        else:
            value = None
        return value or default

    @classmethod
    def _namespace_roles_dict(cls, roles):
        if hasattr(roles, "as_dict"):
            return roles.as_dict()
        if isinstance(roles, dict):
            return dict(roles)
        return {
            "registration_service_namespace": cls._namespace_role_value(roles, "registration_service_namespace"),
            "provider_namespace": cls._namespace_role_value(roles, "provider_namespace"),
            "consumer_namespace": cls._namespace_role_value(roles, "consumer_namespace"),
        }

    def _connector_namespace_details(
        self,
        connectors,
        runtime_namespace,
        namespace_plan,
        validation_pairs=None,
        namespace_overrides=None,
    ):
        runtime_roles = namespace_plan["namespace_roles"]
        planned_roles = namespace_plan["planned_namespace_roles"]
        role_summary = self._connector_role_summary(connectors, validation_pairs=validation_pairs)
        namespace_overrides = dict(namespace_overrides or {})
        details = []

        for index, connector in enumerate(connectors or []):
            if connector == role_summary["provider"]:
                role = "provider"
            elif connector == role_summary["consumer"]:
                role = "consumer"
            else:
                role = "additional"

            override = namespace_overrides.get(connector)
            if override:
                namespace_role = override.get("namespace_role") or "custom"
                active_namespace = (
                    override.get("active_namespace")
                    or runtime_namespace
                )
                planned_namespace = (
                    override.get("planned_namespace")
                    or active_namespace
                )
            elif index == 0:
                namespace_role = "provider"
                active_namespace = self._namespace_role_value(runtime_roles, "provider_namespace", runtime_namespace)
                planned_namespace = self._namespace_role_value(planned_roles, "provider_namespace", active_namespace)
            elif index == 1:
                namespace_role = "consumer"
                active_namespace = self._namespace_role_value(runtime_roles, "consumer_namespace", runtime_namespace)
                planned_namespace = self._namespace_role_value(planned_roles, "consumer_namespace", active_namespace)
            else:
                namespace_role = "dataspace"
                active_namespace = runtime_namespace
                planned_namespace = runtime_namespace

            details.append(
                {
                    "name": connector,
                    "role": role,
                    "validation_role": role,
                    "namespace_role": namespace_role,
                    "runtime_namespace": runtime_namespace,
                    "active_namespace": active_namespace,
                    "planned_namespace": planned_namespace,
                    "registration_service_namespace": self._namespace_role_value(
                        runtime_roles,
                        "registration_service_namespace",
                        runtime_namespace,
                    ),
                    "planned_registration_service_namespace": (
                        self._namespace_role_value(
                            planned_roles,
                            "registration_service_namespace",
                            active_namespace,
                        )
                    ),
                }
            )

        return role_summary, details

    def load_dataspace_connectors(self):
        deployer_config = self.config_adapter.load_deployer_config()
        dataspaces = []
        i = 1

        while True:
            ds_name = deployer_config.get(f"DS_{i}_NAME")
            ds_namespace = (deployer_config.get(f"DS_{i}_NAMESPACE") or ds_name or "").strip() or ds_name
            connectors = deployer_config.get(f"DS_{i}_CONNECTORS")

            if not ds_name:
                break

            connector_list = []
            if connectors:
                for connector in connectors.split(","):
                    name = connector.strip()
                    if name:
                        if not name.startswith("conn-"):
                            self.validate_connector_name(name)
                        normalized_name = normalize_connector_name(name, ds_name)
                        if normalized_name and normalized_name not in connector_list:
                            connector_list.append(normalized_name)

            namespace_plan_getter = getattr(self.config_adapter, "namespace_plan_for_dataspace", None)
            if callable(namespace_plan_getter):
                namespace_plan = namespace_plan_getter(
                    ds_name=ds_name,
                    ds_namespace=ds_namespace,
                    ds_index=i,
                )
            else:
                namespace_plan = {
                    "namespace_profile": "compact",
                    "namespace_roles": {
                        "registration_service_namespace": ds_namespace,
                        "provider_namespace": ds_namespace,
                        "consumer_namespace": ds_namespace,
                    },
                    "planned_namespace_roles": {
                        "registration_service_namespace": ds_namespace,
                        "provider_namespace": ds_namespace,
                        "consumer_namespace": ds_namespace,
                    },
                }
            validation_pairs = self._configured_validation_pairs(
                deployer_config,
                ds_name,
                i,
            )
            namespace_overrides = self._configured_connector_namespace_overrides(
                deployer_config,
                ds_name,
                i,
                namespace_plan,
            )
            role_summary, connector_details = self._connector_namespace_details(
                connector_list,
                ds_namespace,
                namespace_plan,
                validation_pairs=validation_pairs,
                namespace_overrides=namespace_overrides,
            )

            dataspaces.append({
                "name": ds_name,
                "namespace": ds_namespace,
                "connectors": connector_list,
                "namespace_profile": namespace_plan["namespace_profile"],
                "namespace_roles": self._namespace_roles_dict(namespace_plan["namespace_roles"]),
                "planned_namespace_roles": self._namespace_roles_dict(namespace_plan["planned_namespace_roles"]),
                "connector_roles": role_summary,
                "connector_details": connector_details,
                "validation_pairs": [
                    {"provider": provider, "consumer": consumer}
                    for provider, consumer in validation_pairs
                ],
            })
            i += 1

        return dataspaces

    @staticmethod
    def _connector_belongs_to_dataspace(connector_name, ds_name):
        suffix = f"-{ds_name}"
        return connector_name.endswith(suffix)

    def _discover_existing_connectors(self, ds_name, namespace, include_runtime_artifacts=True, dataspace=None):
        existing = set()
        current_dataspace = dataspace or self._dataspace_by_name(ds_name)

        if include_runtime_artifacts:
            # Runtime credentials are useful as a fallback signal that a connector was bootstrapped,
            # but they are not namespace-scoped and must not drive role-aligned namespace mapping.
            creds_dir = os.path.join(
                self.config.repo_dir(),
                "deployments",
                "DEV",
                ds_name,
            )
            if os.path.isdir(creds_dir):
                for entry in os.listdir(creds_dir):
                    if not (entry.startswith("credentials-connector-") and entry.endswith(".json")):
                        continue
                    connector = entry[len("credentials-connector-"):-len(".json")]
                    if connector and self._connector_belongs_to_dataspace(connector, ds_name):
                        existing.add(connector)

        with self._temporary_namespace_kubeconfig(namespace, dataspace=current_dataspace):
            # Helm releases-based detection.
            releases = self.run_silent(f"helm list -n {namespace} --no-headers")
            if releases:
                suffix = f"-{ds_name}"
                for line in releases.splitlines():
                    parts = line.split()
                    if not parts:
                        continue
                    release = parts[0]
                    if release.startswith("conn-") and release.endswith(suffix):
                        connector = release[:-len(suffix)]
                        if connector and self._connector_belongs_to_dataspace(connector, ds_name):
                            existing.add(connector)

            # Pod-based detection (best-effort).
            pods = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")
            if pods:
                for line in pods.splitlines():
                    cols = line.split()
                    if not cols:
                        continue
                    pod_name = cols[0]
                    if not pod_name.startswith("conn-"):
                        continue
                    base = pod_name.rsplit("-", 1)[0]
                    if base.endswith("-inteface") or base.endswith("-interface"):
                        base = base.rsplit("-", 1)[0]
                    if base and self._connector_belongs_to_dataspace(base, ds_name):
                        existing.add(base)

        return existing

    def build_connector_hostnames(self, connectors):
        deployer_config = self.config_adapter.load_deployer_config()
        ds_domain = deployer_config.get("DS_DOMAIN_BASE")

        if not ds_domain:
            return []

        return [f"{connector}.{ds_domain}" for connector in connectors]

    def _host_alias_domains_for_dataspace(self, ds_name=None, ds_namespace=None, connector_name=None):
        resolved_name = str(ds_name or "").strip()
        resolved_namespace = str(ds_namespace or "").strip()
        if connector_name and (not resolved_name or not resolved_namespace):
            dataspace = self._find_dataspace_for_connector(connector_name) or {}
            if not resolved_name:
                resolved_name = str(dataspace.get("name") or "").strip()
            if not resolved_namespace:
                resolved_namespace = str(dataspace.get("namespace") or "").strip()

        domains_getter = getattr(self.config_adapter, "host_alias_domains", None)
        if callable(domains_getter):
            return list(
                domains_getter(
                    ds_name=resolved_name or None,
                    ds_namespace=resolved_namespace or None,
                )
                or []
            )

        fallback_getter = getattr(self.config, "host_alias_domains", None)
        if callable(fallback_getter):
            return list(fallback_getter() or [])
        return []

    def update_connector_host_aliases(self, values_file, connectors, connector_name=None, ds_name=None, ds_namespace=None):
        topology = self._normalized_topology()
        if topology == VM_DISTRIBUTED_TOPOLOGY:
            host_aliases = self._vm_distributed_connector_host_aliases(
                connectors,
                connector_name=connector_name,
                ds_name=ds_name,
                ds_namespace=ds_namespace,
            )
            if not host_aliases:
                return

            with open(values_file) as f:
                values = yaml.safe_load(f) or {}

            values["hostAliases"] = host_aliases

            with open(values_file, "w") as f:
                yaml.dump(values, f, sort_keys=False)
            return

        if topology not in {LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY}:
            return

        host_alias_ip = self._connector_host_alias_ip(topology)
        if not host_alias_ip:
            return

        with open(values_file) as f:
            values = yaml.safe_load(f)

        hostnames = self._host_alias_domains_for_dataspace(
            ds_name=ds_name,
            ds_namespace=ds_namespace,
            connector_name=connector_name,
        )
        hostnames.extend(self.build_connector_hostnames(connectors))

        values["hostAliases"] = [{
            "ip": host_alias_ip,
            "hostnames": hostnames
        }]

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    def _vm_distributed_connector_host_aliases(self, connectors, connector_name=None, ds_name=None, ds_namespace=None):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
            profile = build_topology_profile(VM_DISTRIBUTED_TOPOLOGY, deployer_config)
        except Exception:
            return []

        role_addresses = dict(getattr(profile, "role_addresses", {}) or {})
        common_ip = str(
            role_addresses.get("common")
            or role_addresses.get("registration_service")
            or getattr(profile, "default_address", "")
            or ""
        ).strip()
        provider_ip = str(role_addresses.get("provider") or role_addresses.get("connectors") or common_ip).strip()
        consumer_ip = str(role_addresses.get("consumer") or common_ip).strip()
        if not common_ip:
            return []

        resolved_ds_name = str(ds_name or self._dataspace_name()).strip() or self._dataspace_name()
        ds_domain = str(
            deployer_config.get("DS_DOMAIN_BASE")
            or self.config_adapter.ds_domain_base()
            or ""
        ).strip()

        grouped = {}

        def add(ip, hostnames):
            clean_ip = str(ip or "").strip()
            if not clean_ip:
                return
            bucket = grouped.setdefault(clean_ip, [])
            for hostname in hostnames or []:
                clean_hostname = str(hostname or "").strip()
                if clean_hostname and clean_hostname not in bucket:
                    bucket.append(clean_hostname)

        public_urls = resolve_vm_distributed_public_urls(deployer_config)
        common_hostnames = list(resolved_common_service_hostnames(deployer_config).values())
        common_hostnames.extend(
            self._host_alias_domains_for_dataspace(
                ds_name=resolved_ds_name,
                ds_namespace=ds_namespace,
                connector_name=connector_name,
            )
        )
        for url_key in (
            "VM_COMMON_PUBLIC_URL",
            "PUBLIC_PORTAL_BACKEND_PUBLIC_URL",
            "DATASPACE_PUBLIC_PORTAL_BACKEND_URL",
        ):
            public_hostname = urlparse(str(public_urls.get(url_key) or deployer_config.get(url_key) or "")).hostname
            if public_hostname:
                common_hostnames.append(public_hostname)
        if ds_domain:
            common_hostnames.extend(
                [
                    f"{resolved_ds_name}.{ds_domain}",
                    f"backend-{resolved_ds_name}.{ds_domain}",
                    f"registration-service-{resolved_ds_name}.{ds_domain}",
                ]
            )
        common_hostnames.extend(
            [
                f"ontology-hub-{resolved_ds_name}.{ds_domain}",
                f"ai-model-hub-{resolved_ds_name}.{ds_domain}",
                f"semantic-virtualization-{resolved_ds_name}.{ds_domain}",
            ]
        )
        common_hostnames = [
            hostname
            for hostname in common_hostnames
            if hostname and not hostname.endswith(".")
        ]
        add(common_ip, common_hostnames)

        for connector in connectors or []:
            connector_hostname = f"{connector}.{ds_domain}" if ds_domain else ""
            role = self._connector_kubeconfig_role(connector)
            if role == "consumer":
                add(consumer_ip, [connector_hostname, self._public_hostname_for_role("consumer", deployer_config)])
            elif role == "provider":
                add(provider_ip, [connector_hostname, self._public_hostname_for_role("provider", deployer_config)])
            else:
                add(common_ip, [connector_hostname])

        return [
            {"ip": ip, "hostnames": hostnames}
            for ip, hostnames in grouped.items()
            if ip and hostnames
        ]

    @staticmethod
    def _public_hostname_for_role(role, deployer_config):
        normalized_role = str(role or "").strip().lower()
        key_by_role = {
            "provider": "VM_PROVIDER_PUBLIC_URL",
            "consumer": "VM_CONSUMER_PUBLIC_URL",
        }
        raw_url = str((deployer_config or {}).get(key_by_role.get(normalized_role, "")) or "").strip()
        if not raw_url:
            return ""
        parsed = urlparse(raw_url)
        return parsed.hostname or ""

    def _connector_host_alias_ip(self, topology=None):
        normalized_topology = normalize_topology(topology or self._normalized_topology())
        cluster_type = str(self._cluster_runtime().get("cluster_type") or "minikube").strip().lower() or "minikube"
        if normalized_topology == LOCAL_TOPOLOGY or (
            normalized_topology == VM_SINGLE_TOPOLOGY and cluster_type == "minikube"
        ):
            return self.run("minikube ip", capture=True) or self.config.MINIKUBE_IP

        if normalized_topology == VM_SINGLE_TOPOLOGY and cluster_type == "k3s":
            try:
                deployer_config = self.config_adapter.load_deployer_config() or {}
            except Exception:
                deployer_config = {}
            profile = build_topology_profile(VM_SINGLE_TOPOLOGY, deployer_config)
            return str(profile.ingress_external_ip or profile.default_address or "").strip()

        return ""

    def _find_dataspace_for_connector(self, connector_name):
        for dataspace in self.load_dataspace_connectors() or []:
            connectors = dataspace.get("connectors") or []
            if connector_name in connectors:
                return dataspace
        return None

    def _registration_service_hostname_for_connector(self, connector_name):
        dataspace = self._find_dataspace_for_connector(connector_name) or {}
        ds_name = dataspace.get("name") or self._dataspace_name()
        ds_namespace = dataspace.get("namespace") or self.config.namespace_demo()
        connector_details = {
            entry.get("name"): entry
            for entry in (dataspace.get("connector_details") or [])
            if entry.get("name")
        }
        connector_layout = connector_details.get(connector_name, {})
        connector_namespace = (
            self._connector_target_namespace(connector_name, dataspace=dataspace)
            or connector_layout.get("active_namespace")
            or ds_namespace
        )
        hostname_getter = getattr(self.config_adapter, "registration_service_internal_hostname", None)
        if callable(hostname_getter):
            return hostname_getter(
                ds_name=ds_name,
                ds_namespace=ds_namespace,
                connector_namespace=connector_namespace,
            )
        return f"{ds_name}-registration-service:8080"

    def _connector_layout_metadata(self, connector_name, ds_name=None, ds_namespace=None):
        dataspace = self._find_dataspace_for_connector(connector_name) or {}
        namespace_getter = getattr(self.config, "namespace_demo", None)
        if callable(namespace_getter):
            default_namespace = namespace_getter() or self._dataspace_name()
        else:
            default_namespace = self._dataspace_name()
        resolved_name = str(ds_name or dataspace.get("name") or self._dataspace_name()).strip() or self._dataspace_name()
        resolved_namespace = str(
            ds_namespace
            or dataspace.get("namespace")
            or default_namespace
        ).strip() or default_namespace
        connector_details = {
            entry.get("name"): entry
            for entry in (dataspace.get("connector_details") or [])
            if entry.get("name")
        }
        connector_layout = connector_details.get(connector_name, {})
        metadata = {
            "role": connector_layout.get("role") or "",
            "namespaceProfile": dataspace.get("namespace_profile") or "compact",
            "runtimeNamespace": connector_layout.get("runtime_namespace") or resolved_namespace,
            "activeNamespace": connector_layout.get("active_namespace") or resolved_namespace,
            "plannedNamespace": connector_layout.get("planned_namespace") or resolved_namespace,
            "registrationServiceNamespace": (
                connector_layout.get("registration_service_namespace")
                or resolved_namespace
            ),
            "plannedRegistrationServiceNamespace": (
                connector_layout.get("planned_registration_service_namespace")
                or connector_layout.get("registration_service_namespace")
                or resolved_namespace
            ),
        }
        if connector_layout.get("namespace_role"):
            metadata["namespaceRole"] = connector_layout.get("namespace_role")
        return metadata

    def update_connector_service_discovery(self, values_file, connector_name):
        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

        services = values.setdefault("services", {})
        registration_service = services.setdefault("registrationService", {})
        registration_service["hostname"] = self._registration_service_hostname_for_connector(connector_name)

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    @staticmethod
    def _hostname_from_url_or_host(value):
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        try:
            parsed = urlparse(raw_value if "://" in raw_value else f"http://{raw_value}")
        except ValueError:
            return ""
        return (parsed.hostname or "").strip().lower()

    @classmethod
    def _is_cluster_service_reference(cls, value):
        hostname = cls._hostname_from_url_or_host(value)
        if not hostname:
            return False
        return (
            hostname.endswith(".svc")
            or ".svc." in hostname
            or hostname.endswith(".cluster.local")
        )

    @staticmethod
    def _url_with_replaced_host(value, host, default_port=None):
        raw_value = str(value or "").strip()
        if not raw_value or not host:
            return raw_value
        parsed = urlparse(raw_value if "://" in raw_value else f"http://{raw_value}")
        scheme = parsed.scheme or "http"
        port = parsed.port or default_port
        netloc = str(host).strip()
        if port:
            netloc = f"{netloc}:{int(port)}"
        path = parsed.path or ""
        return f"{scheme}://{netloc}{path}"

    def _vm_distributed_common_runtime_host(self, deployer_config):
        for key in ("VM_COMMON_RUNTIME_HOST", "VM_COMMON_IP", "VM_EXTERNAL_IP", "INGRESS_EXTERNAL_IP"):
            value = str((deployer_config or {}).get(key) or "").strip()
            if value:
                return value
        return ""

    def _vm_distributed_public_registration_hostname(self, ds_name, deployer_config):
        configured = str((deployer_config or {}).get("REGISTRATION_SERVICE_HOSTNAME") or "").strip()
        if configured:
            return configured
        ds_domain = str(
            (deployer_config or {}).get("DS_DOMAIN_BASE")
            or self.config_adapter.ds_domain_base()
            or ""
        ).strip()
        if not ds_domain:
            return ""
        return f"registration-service-{ds_name}.{ds_domain}"

    def update_connector_multicluster_common_service_endpoints(self, values_file, connector_name, ds_name=None):
        if not self._vm_distributed_uses_separate_connector_kubeconfigs():
            return

        deployer_config = self.config_adapter.load_deployer_config() or {}
        common_host = self._vm_distributed_common_runtime_host(deployer_config)
        if not common_host:
            return

        resolved_ds_name = str(ds_name or self._dataspace_name()).strip() or self._dataspace_name()
        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

        services = values.setdefault("services", {})
        db = services.setdefault("db", {})
        if self._is_cluster_service_reference(db.get("hostname")):
            db["hostname"] = common_host

        vault = services.setdefault("vault", {})
        if self._is_cluster_service_reference(vault.get("url")):
            vault["url"] = self._url_with_replaced_host(
                vault.get("url"),
                common_host,
                default_port=8200,
            )

        registration_service = services.setdefault("registrationService", {})
        registration_hostname = registration_service.get("hostname")
        if self._is_cluster_service_reference(registration_hostname):
            public_registration_hostname = self._vm_distributed_public_registration_hostname(
                resolved_ds_name,
                deployer_config,
            )
            if public_registration_hostname:
                registration_service["hostname"] = public_registration_hostname

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    @staticmethod
    def _strip_model_observer_api_path(url):
        normalized = str(url or "").strip().rstrip("/")
        suffix = "/api/model-observer"
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)].rstrip("/")
        return normalized

    @staticmethod
    def _url_with_forced_scheme(url, scheme):
        raw_url = str(url or "").strip().rstrip("/")
        if not raw_url:
            return ""
        try:
            parsed = urlparse(raw_url if "://" in raw_url else f"{scheme}://{raw_url}")
        except ValueError:
            return ""
        if not parsed.netloc:
            return ""
        path = (parsed.path or "").rstrip("/")
        return f"{scheme}://{parsed.netloc}{path}"

    def _connector_model_observer_public_url(self, values, ds_name):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}

        explicit_proxy = str(
            deployer_config.get("AI_MODEL_OBSERVER_PROXY_TARGET")
            or deployer_config.get("MODEL_OBSERVER_PROXY_TARGET")
            or ""
        ).strip()
        if explicit_proxy:
            return self._strip_model_observer_api_path(explicit_proxy)

        explicit_api = str(
            deployer_config.get("AI_MODEL_OBSERVER_API_BASE_URL")
            or deployer_config.get("AI_MODEL_HUB_OBSERVER_API_BASE_URL")
            or ""
        ).strip()
        if explicit_api:
            return self._strip_model_observer_api_path(explicit_api)

        if self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY:
            public_urls = resolve_vm_distributed_public_urls(deployer_config)
            backend_url = str(
                deployer_config.get("PUBLIC_PORTAL_BACKEND_PUBLIC_URL")
                or deployer_config.get("DATASPACE_PUBLIC_PORTAL_BACKEND_URL")
                or public_urls.get("PUBLIC_PORTAL_BACKEND_PUBLIC_URL")
                or public_urls.get("DATASPACE_PUBLIC_PORTAL_BACKEND_URL")
                or ""
            ).strip()
            if backend_url:
                return self._strip_model_observer_api_path(backend_url)

        connector = values.get("connector") or {}
        ingress = connector.get("ingress") or {}
        protocol = str(ingress.get("protocol") or "http").strip() or "http"
        hostname = str(ingress.get("hostname") or "").strip()
        if hostname and "." in hostname:
            return f"{protocol}://backend-{ds_name}.{hostname.split('.', 1)[1]}"
        return ""

    def _connector_model_observer_journal_url(self, public_url):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}

        explicit_url = str(
            deployer_config.get("AI_MODEL_OBSERVER_JOURNAL_BASE_URL")
            or deployer_config.get("AI_MODEL_HUB_OBSERVER_JOURNAL_BASE_URL")
            or deployer_config.get("MODEL_OBSERVER_JOURNAL_BASE_URL")
            or ""
        ).strip()
        if explicit_url:
            return self._strip_model_observer_api_path(explicit_url)

        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return ""

        return self._url_with_forced_scheme(
            self._strip_model_observer_api_path(public_url),
            "http",
        )

    def update_connector_model_observer_config(self, values_file, connector_name, ds_name=None, ds_namespace=None):
        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

        resolved_ds_name = str(ds_name or values.get("connector", {}).get("dataspace") or self._dataspace_name()).strip()
        connector_interface = values.setdefault("connectorInterface", {})
        model_observer = connector_interface.setdefault("modelObserver", {})
        public_url = self._connector_model_observer_public_url(values, resolved_ds_name)
        if public_url:
            model_observer["proxyTarget"] = public_url
            model_observer["strapiUrl"] = public_url
            journal_url = self._connector_model_observer_journal_url(public_url)
            if journal_url:
                model_observer["journalBaseUrl"] = journal_url
        else:
            model_observer.setdefault("proxyTarget", "http://127.0.0.1:9")

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    def update_connector_layout_metadata(self, values_file, connector_name):
        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

        connector = values.setdefault("connector", {})
        connector["layout"] = self._connector_layout_metadata(connector_name)

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    def update_connector_node_scheduling(self, values_file, connector_name):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return

        layout = self._connector_layout_metadata(connector_name)
        role = str(layout.get("role") or "").strip().lower()
        node_key_by_role = {
            "provider": "VM_PROVIDER_K8S_NODE",
            "consumer": "VM_CONSUMER_K8S_NODE",
        }
        node_key = node_key_by_role.get(role)
        if not node_key:
            return

        deployer_config = self.config_adapter.load_deployer_config() or {}
        node_name = str(deployer_config.get(node_key) or "").strip()
        if not node_name:
            return

        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

        node_selector = values.setdefault("nodeSelector", {})
        node_selector["kubernetes.io/hostname"] = node_name

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    @staticmethod
    def _public_url_parts(raw_url):
        parsed = urlparse(str(raw_url or "").strip())
        if not parsed.scheme or not parsed.hostname:
            return "", ""
        hostname = parsed.hostname
        if parsed.port:
            hostname = f"{hostname}:{parsed.port}"
        return parsed.scheme, hostname

    @staticmethod
    def _keycloak_public_url_parts(deployer_config):
        public_urls = resolve_vm_distributed_public_urls(deployer_config)
        parsed = urlparse(
            str(
                (deployer_config or {}).get("KEYCLOAK_FRONTEND_URL")
                or (deployer_config or {}).get("KEYCLOAK_PUBLIC_URL")
                or public_urls.get("KEYCLOAK_FRONTEND_URL")
                or public_urls.get("KEYCLOAK_PUBLIC_URL")
                or ""
            ).strip()
        )
        if not parsed.scheme or not parsed.netloc:
            return "", ""
        public_external = parsed.netloc.strip()
        public_path = parsed.path.strip().rstrip("/")
        if public_path:
            public_external = f"{public_external}{public_path}"
        return parsed.scheme, public_external

    def _connector_public_url_for_role(self, role, deployer_config):
        normalized_role = str(role or "").strip().lower()
        if normalized_role == "provider":
            return (
                (deployer_config or {}).get("VM_PROVIDER_PUBLIC_URL")
                or (deployer_config or {}).get("VM_PROVIDER_HTTP_URL")
                or ""
            )
        if normalized_role == "consumer":
            return (
                (deployer_config or {}).get("VM_CONSUMER_PUBLIC_URL")
                or (deployer_config or {}).get("VM_CONSUMER_HTTP_URL")
                or ""
            )
        return ""

    def update_connector_public_ingress_config(self, values_file, connector_name):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return

        deployer_config = self.config_adapter.load_deployer_config() or {}
        layout = self._connector_layout_metadata(connector_name)
        public_url = self._connector_public_url_for_role(layout.get("role"), deployer_config)
        public_protocol, public_hostname = self._public_url_parts(public_url)
        if not public_hostname:
            return

        with open(values_file) as f:
            values = yaml.safe_load(f) or {}

        connector = values.setdefault("connector", {})
        ingress = connector.setdefault("ingress", {})
        services = values.setdefault("services", {})
        keycloak = services.setdefault("keycloak", {})
        keycloak_public_protocol, keycloak_public_external = self._keycloak_public_url_parts(
            deployer_config
        )
        if keycloak_public_protocol:
            keycloak["publicProtocol"] = keycloak_public_protocol
        elif public_protocol:
            keycloak["publicProtocol"] = public_protocol
        if keycloak_public_external:
            keycloak["external"] = keycloak_public_external
        primary_hostname = str(ingress.get("hostname") or "").strip()
        if primary_hostname == public_hostname:
            ingress["publicProtocol"] = public_protocol
            ingress["publicHostname"] = public_hostname
            with open(values_file, "w") as f:
                yaml.dump(values, f, sort_keys=False)
            return

        ingress["publicProtocol"] = public_protocol
        ingress["publicHostname"] = public_hostname
        additional_hosts = ingress.setdefault("additionalHosts", [])
        existing_hosts = {
            str(item.get("hostname") or "").strip().lower()
            for item in additional_hosts
            if isinstance(item, dict)
        }
        if public_hostname.lower() not in existing_hosts:
            additional_hosts.append(
                {
                    "hostname": public_hostname,
                    "rootToInterface": True,
                }
            )

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    def _local_connector_image_override_path(self):
        policy = self._resolve_level4_local_image_policy(
            mode=self._level4_local_images_mode(),
            label="INESData connector",
        )
        if not policy["allow_local_image_overrides"]:
            return None
        override_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "build",
            "local-overrides",
            "connector-local-overrides.yaml",
        )
        if os.path.isfile(override_path) and os.path.getsize(override_path) > 0:
            return override_path
        return None

    def _explicit_connector_image_override_path(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}

        connector_image_name = (
            os.environ.get("PIONERA_INESDATA_CONNECTOR_IMAGE_NAME")
            or os.environ.get("INESDATA_CONNECTOR_IMAGE_NAME")
            or deployer_config.get("INESDATA_CONNECTOR_IMAGE_NAME")
        )
        connector_image_tag = (
            os.environ.get("PIONERA_INESDATA_CONNECTOR_IMAGE_TAG")
            or os.environ.get("INESDATA_CONNECTOR_IMAGE_TAG")
            or deployer_config.get("INESDATA_CONNECTOR_IMAGE_TAG")
        )
        interface_image_name = (
            os.environ.get("PIONERA_INESDATA_CONNECTOR_INTERFACE_IMAGE_NAME")
            or os.environ.get("INESDATA_CONNECTOR_INTERFACE_IMAGE_NAME")
            or deployer_config.get("INESDATA_CONNECTOR_INTERFACE_IMAGE_NAME")
        )
        interface_image_tag = (
            os.environ.get("PIONERA_INESDATA_CONNECTOR_INTERFACE_IMAGE_TAG")
            or os.environ.get("INESDATA_CONNECTOR_INTERFACE_IMAGE_TAG")
            or deployer_config.get("INESDATA_CONNECTOR_INTERFACE_IMAGE_TAG")
        )

        connector_name_present = bool(str(connector_image_name or "").strip())
        connector_tag_present = bool(str(connector_image_tag or "").strip())
        interface_name_present = bool(str(interface_image_name or "").strip())
        interface_tag_present = bool(str(interface_image_tag or "").strip())

        if connector_name_present != connector_tag_present:
            raise RuntimeError(
                "INESData connector image override is incomplete. Set both "
                "PIONERA_INESDATA_CONNECTOR_IMAGE_NAME and PIONERA_INESDATA_CONNECTOR_IMAGE_TAG."
            )

        if interface_name_present != interface_tag_present:
            raise RuntimeError(
                "INESData connector interface image override is incomplete. Set both "
                "PIONERA_INESDATA_CONNECTOR_INTERFACE_IMAGE_NAME and "
                "PIONERA_INESDATA_CONNECTOR_INTERFACE_IMAGE_TAG."
            )

        override = {}
        if connector_name_present and connector_tag_present:
            override["connector"] = {
                "image": {
                    "name": str(connector_image_name).strip(),
                    "tag": str(connector_image_tag).strip(),
                }
            }

        if interface_name_present and interface_tag_present:
            override["connectorInterface"] = {
                "image": {
                    "name": str(interface_image_name).strip(),
                    "tag": str(interface_image_tag).strip(),
                }
            }

        if not override:
            return None

        override_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "build",
            "runtime-overrides",
        )
        os.makedirs(override_dir, exist_ok=True)
        override_path = os.path.join(override_dir, "connector-image-overrides.yaml")
        with open(override_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(override, handle, sort_keys=False)
        return override_path

    def _framework_root_dir(self):
        resolver = getattr(self.config, "script_dir", None)
        if callable(resolver):
            return resolver()
        repo_resolver = getattr(self.config, "repo_dir", None)
        if callable(repo_resolver):
            return os.path.abspath(repo_resolver())
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def _level4_local_images_mode(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        raw_value = (
            os.environ.get("PIONERA_INESDATA_LOCAL_IMAGES_MODE")
            or os.environ.get("INESDATA_LOCAL_IMAGES_MODE")
            or deployer_config.get("INESDATA_LOCAL_IMAGES_MODE")
            or deployer_config.get("LEVEL4_INESDATA_LOCAL_IMAGES_MODE")
            or deployer_config.get("LEVEL4_LOCAL_IMAGES_MODE")
            or "auto"
        )
        mode = str(raw_value or "auto").strip().lower()
        if mode in {"0", "false", "no", "off", "disabled", "disable"}:
            return "disabled"
        if mode in {"1", "true", "yes", "on", "auto", ""}:
            return "auto"
        if mode in {"required", "require", "strict"}:
            return "required"
        print(f"Unknown INESData local images mode '{raw_value}'. Falling back to auto.")
        return "auto"

    def _local_minikube_profile(self):
        env_profile = os.getenv("PIONERA_MINIKUBE_PROFILE") or os.getenv("MINIKUBE_PROFILE")
        if env_profile:
            return env_profile.strip() or "minikube"
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        return str(deployer_config.get("MINIKUBE_PROFILE") or "minikube").strip() or "minikube"

    def _cluster_runtime(self):
        runtime_getter = getattr(self.config_adapter, "cluster_runtime", None)
        if callable(runtime_getter):
            try:
                return dict(runtime_getter() or {})
            except Exception:
                pass
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        return build_cluster_runtime(deployer_config, topology=self._normalized_topology())

    def _ontology_validator_patch_context(self):
        deployer_config = self.config_adapter.load_deployer_config() or {}
        dataspace_name = self.config_adapter.primary_dataspace_name()
        dataspace_namespace = self.config_adapter.primary_dataspace_namespace()
        namespace_plan = resolve_namespace_profile_plan(
            deployer_config,
            dataspace_name=dataspace_name,
            dataspace_namespace=dataspace_namespace,
            common_default=getattr(self.config, "NS_COMMON", "common-srvs"),
            components_default="components",
        )
        return SimpleNamespace(
            dataspace_name=dataspace_name,
            config=deployer_config,
            namespace_roles=namespace_plan["namespace_roles"],
        )

    def _patch_ontology_validator_source_for_level4_build(self, root_dir):
        try:
            return patch_ontology_validator_source(
                self._ontology_validator_patch_context(),
                root_dir,
            )
        except Exception as exc:
            print(f"Ontology validator URL patch skipped: {exc}")
            return False

    def _connector_interface_source_path(self, root_dir, *parts):
        return os.path.join(
            root_dir,
            "adapters",
            "inesdata",
            "sources",
            "inesdata-connector-interface",
            "src",
            *parts,
        )

    @staticmethod
    def _replace_or_append_css_block(source, marker, css_block):
        begin = f"/* {marker}: begin */"
        end = f"/* {marker}: end */"
        block = f"{begin}\n{css_block.rstrip()}\n{end}\n"
        pattern = re.compile(
            rf"\n?/\* {re.escape(marker)}: begin \*/.*?/\* {re.escape(marker)}: end \*/\n?",
            re.DOTALL,
        )
        if pattern.search(source):
            return pattern.sub(f"\n{block}", source)
        suffix = "" if source.endswith("\n") else "\n"
        return f"{source}{suffix}\n{block}"

    @staticmethod
    def _replace_first_literal(source, old, new):
        if old not in source:
            return source
        return source.replace(old, new, 1)

    def _patch_connector_interface_branding_file(self, path, originals, transform):
        if not os.path.isfile(path):
            print(f"Connector interface branding source patch skipped; file not found: {path}")
            return False
        with open(path, "r", encoding="utf-8") as handle:
            original = handle.read()
        updated = transform(original)
        if updated == original:
            return False
        originals[path] = original
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(updated)
        return True

    @staticmethod
    def _branding_asset_filename(raw_name):
        normalized = str(raw_name or "").strip().replace("\\", "/")
        if not normalized or "/" in normalized:
            return ""
        return os.path.basename(normalized)

    def _patch_connector_interface_branding_source_for_level4_build(self, root_dir):
        source_root = self._connector_interface_source_path(root_dir)
        if not os.path.isdir(source_root):
            print(f"Connector interface branding source patch skipped; source root not found: {source_root}")
            return {}

        try:
            bootstrap = self._bootstrap_runtime()
            config = bootstrap.load_effective_deployer_config()
            branding_keys = bootstrap._inesdata_branding_template_keys(config, "connector")
        except Exception as exc:
            print(f"Connector interface branding source patch skipped: {exc}")
            return {}

        brand_name = str(config.get("INESDATA_BRAND_NAME") or "PIONERA").strip() or "PIONERA"
        primary_color = str(config.get("INESDATA_BRAND_PRIMARY_COLOR") or "#025B77").strip() or "#025B77"
        secondary_color = str(config.get("INESDATA_BRAND_SECONDARY_COLOR") or "#2FA0B5").strip() or "#2FA0B5"
        show_menu_text = self._is_truthy(config.get("INESDATA_BRAND_SHOW_MENU_TEXT", "true"))
        local_store_label = str(config.get("INESDATA_LOCAL_STORE_LABEL") or "LocalStore").strip() or "LocalStore"
        footer_text = str(config.get("INESDATA_BRAND_FOOTER_TEXT") or "").strip()
        powered_by_text = str(config.get("INESDATA_BRAND_POWERED_BY_TEXT") or "Powered by:").strip()

        logo_files = [
            self._branding_asset_filename(item)
            for item in str(branding_keys.get("inesdata_brand_logo_files") or "").split(",")
        ]
        logo_files = [item for item in logo_files if item]
        footer_logo_files = [
            self._branding_asset_filename(item)
            for item in str(branding_keys.get("inesdata_brand_footer_logo_files") or "").split(",")
        ]
        footer_logo_files = [item for item in footer_logo_files if item]
        if not footer_logo_files:
            footer_logo_files = logo_files
        powered_by_logo_files = [
            self._branding_asset_filename(item)
            for item in str(branding_keys.get("inesdata_brand_powered_by_logo_files") or "").split(",")
        ]
        powered_by_logo_files = [item for item in powered_by_logo_files if item]
        explicit_powered_by_logo_urls = str(config.get("INESDATA_BRAND_POWERED_BY_LOGO_URLS") or "").strip()
        powered_by_logo_urls_source = explicit_powered_by_logo_urls
        if not powered_by_logo_files and not powered_by_logo_urls_source:
            powered_by_logo_urls_source = str(branding_keys.get("inesdata_brand_powered_by_logo_urls") or "").strip()
        if explicit_powered_by_logo_urls:
            powered_by_logo_files = []
        powered_by_logo_urls = [str(item or "").strip() for item in powered_by_logo_urls_source.split(",")]
        powered_by_logo_urls = [item for item in powered_by_logo_urls if item]

        escaped_brand = html.escape(brand_name, quote=True)
        escaped_local_store = html.escape(local_store_label, quote=True)
        escaped_powered_by_text = html.escape(powered_by_text, quote=False)
        if footer_text:
            escaped_footer_text = html.escape(footer_text, quote=False)
        else:
            escaped_footer_text = f"{escaped_brand} © {{{{ year }}}}"
        primary_css = html.escape(primary_color, quote=True)
        secondary_css = html.escape(secondary_color, quote=True)
        brand_logo = logo_files[0] if logo_files else ""
        brand_logo_html = ""
        if brand_logo:
            brand_logo_html = (
                f'<img class="brand-logo" src="assets/branding/{html.escape(brand_logo, quote=True)}" '
                f'alt="{escaped_brand} logo">'
            )
        if not brand_logo:
            show_menu_text = True
        brand_text_html = f'<span class="brand-name">{escaped_brand}</span>' if show_menu_text else ""

        def footer_logo_class(filename):
            normalized = str(filename or "").lower()
            if "pionera" in normalized:
                return "footer__logo footer__logo--pionera"
            if "funding" in normalized:
                return "footer__logo footer__logo--funding"
            if "oeg" in normalized or "ontology" in normalized:
                return "footer__logo footer__logo--oeg"
            return "footer__logo"

        def powered_by_logo_class(filename_or_url):
            normalized = str(filename_or_url or "").lower()
            if "inesd" in normalized:
                return "footer__logo footer__logo--inesdata"
            return "footer__logo footer__logo--powered-by"

        footer_logos_html = "\n".join(
            f'      <img class="{footer_logo_class(filename)}" '
            f'src="assets/branding/{html.escape(filename, quote=True)}" '
            f'alt="{escaped_brand} branding">'
            for filename in footer_logo_files
        )
        if not footer_logos_html:
            footer_logos_html = f"      <span>{escaped_brand}</span>"
        powered_by_images = [
            (
                f'      <img class="{powered_by_logo_class(filename)}" '
                f'src="assets/branding/{html.escape(filename, quote=True)}" '
                f'alt="{html.escape(os.path.splitext(filename)[0], quote=True)}">'
            )
            for filename in powered_by_logo_files
        ]
        powered_by_images.extend(
            f'      <img class="{powered_by_logo_class(url)}" '
            f'src="{html.escape(url, quote=True)}" alt="{escaped_brand} powered by">'
            for url in powered_by_logo_urls
        )
        powered_by_html = ""
        if powered_by_images:
            powered_by_html = (
                '    <div class="footer__powered-by">\n'
                f"      <span>{escaped_powered_by_text}</span>\n"
                + "\n".join(powered_by_images)
                + "\n"
                "    </div>\n"
            )

        originals = {}
        patched = []

        nav_html = self._connector_interface_source_path(
            root_dir,
            "app",
            "shared",
            "components",
            "navigation",
            "navigation.component.html",
        )
        nav_toolbar = (
            '      <mat-toolbar class="sidenav-toolbar">\n'
            f'        <span class="brand-label">{brand_logo_html}{brand_text_html}</span>\n'
            "      </mat-toolbar>"
        )

        def patch_nav_toolbar(source):
            legacy = "      <mat-toolbar>INESData</mat-toolbar>"
            if legacy in source:
                return source.replace(legacy, nav_toolbar, 1)
            return re.sub(
                r"\s*<mat-toolbar class=\"sidenav-toolbar\">.*?</mat-toolbar>",
                "\n" + nav_toolbar,
                source,
                count=1,
                flags=re.DOTALL,
            )

        if self._patch_connector_interface_branding_file(
            nav_html,
            originals,
            patch_nav_toolbar,
        ):
            patched.append(nav_html)

        nav_scss = self._connector_interface_source_path(
            root_dir,
            "app",
            "shared",
            "components",
            "navigation",
            "navigation.component.scss",
        )
        nav_css = """
.sidenav-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
}

.brand-label {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}

.brand-logo {
  display: block;
  max-width: 170px;
  max-height: 44px;
  object-fit: contain;
}

.brand-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidenav a[mat-list-item] {
  align-items: center;
  display: flex;
  --mdc-list-list-item-one-line-container-height: 42px;
}

.sidenav mat-icon {
  align-items: center;
  display: inline-flex;
  flex: 0 0 24px;
  height: 24px;
  justify-content: center;
  line-height: 24px;
  width: 24px;
}

:host ::ng-deep mat-nav-list .mat-mdc-list-item .mdc-list-item__content {
  align-items: center;
  display: flex;
}

:host ::ng-deep mat-nav-list .mat-mdc-list-item .mdc-list-item__start {
  align-items: center;
  align-self: center;
  display: inline-flex;
  height: 24px;
  justify-content: center;
  margin-bottom: 0;
  margin-top: 0;
  width: 24px;
}
"""
        if self._patch_connector_interface_branding_file(
            nav_scss,
            originals,
            lambda source: self._replace_or_append_css_block(source, "pionera-branding", nav_css),
        ):
            patched.append(nav_scss)

        footer_html = self._connector_interface_source_path(
            root_dir,
            "app",
            "shared",
            "components",
            "footer",
            "footer.component.html",
        )
        footer_source = f"""<div class="footer-container">
  <footer class="footer">
    <div class="footer__logos">
{footer_logos_html}
    </div>
{powered_by_html.rstrip()}
  </footer>

  <div class="footer__company">
    <p>{escaped_footer_text}</p>
  </div>
</div>
"""
        if self._patch_connector_interface_branding_file(footer_html, originals, lambda _source: footer_source):
            patched.append(footer_html)

        footer_scss = self._connector_interface_source_path(
            root_dir,
            "app",
            "shared",
            "components",
            "footer",
            "footer.component.scss",
        )
        footer_css = """
.footer__logos {
  align-items: center;
  display: flex;
  flex-wrap: nowrap;
  gap: clamp(22px, 4vw, 64px);
  justify-content: center;
  min-height: 58px;
  overflow: hidden;
}

.footer__logos img {
  display: block;
  height: auto;
  margin: 0;
  object-fit: contain;
}

.footer__logo {
  height: auto;
  margin: 0;
  object-fit: contain;
}

.footer__logo--pionera {
  max-height: 52px;
  max-width: 190px;
}

.footer__logo--funding {
  max-height: 64px;
  max-width: min(52vw, 760px);
}

.footer__logo--oeg {
  max-height: 56px;
  max-width: 150px;
}

.footer__powered-by {
  align-items: center;
  color: var(--secondary-600);
  display: flex;
  flex-direction: column;
  font-family: "Open Sans", sans-serif;
  font-size: 12px;
  font-weight: 600;
  gap: 2px;
  justify-content: center;
  line-height: 1.2;
  margin: 2px 0 0;
  text-align: center;
}

.footer__logo--inesdata {
  max-height: 28px;
  max-width: 180px;
}
"""
        if self._patch_connector_interface_branding_file(
            footer_scss,
            originals,
            lambda source: self._replace_or_append_css_block(source, "pionera-powered-by-branding", footer_css),
        ):
            patched.append(footer_scss)

        app_module = self._connector_interface_source_path(root_dir, "app", "app.module.ts")
        if self._patch_connector_interface_branding_file(
            app_module,
            originals,
            lambda source: source.replace(
                "{id: DATA_ADDRESS_TYPES.inesDataStore, name: DATA_ADDRESS_TYPES.inesDataStore}",
                f"{{id: DATA_ADDRESS_TYPES.inesDataStore, name: '{escaped_local_store}'}}",
            ),
        ):
            patched.append(app_module)

        ai_model_browser_service = self._connector_interface_source_path(
            root_dir,
            "app",
            "shared",
            "services",
            "ai-model-browser.service.ts",
        )
        if self._patch_connector_interface_branding_file(
            ai_model_browser_service,
            originals,
            lambda source: source.replace("return 'InesDataStore';", f"return '{escaped_local_store}';"),
        ):
            patched.append(ai_model_browser_service)

        styles_scss = self._connector_interface_source_path(root_dir, "styles.scss")

        def patch_styles(source):
            replacements = {
                r"--brand-500:\s*#[0-9A-Fa-f]{3,6};": f"--brand-500: {primary_css};",
                r"--secondary-500:\s*#[0-9A-Fa-f]{3,6};": f"--secondary-500: {secondary_css};",
                r"--secondary-600:\s*#[0-9A-Fa-f]{3,6};": f"--secondary-600: {primary_css};",
                r"--mdc-list-list-item-label-text-color:\s*#[0-9A-Fa-f]{3,6};": f"--mdc-list-list-item-label-text-color: {primary_css};",
                r"--mdc-list-list-item-hover-label-text-color:\s*#[0-9A-Fa-f]{3,6};": f"--mdc-list-list-item-hover-label-text-color: {primary_css};",
                r"--mdc-list-list-item-focus-label-text-color:\s*#[0-9A-Fa-f]{3,6};": f"--mdc-list-list-item-focus-label-text-color: {primary_css};",
                r"--mat-mdc-button-persistent-ripple-color:\s*#[0-9A-Fa-f]{3,6};": f"--mat-mdc-button-persistent-ripple-color: {secondary_css};",
            }
            updated = source
            for pattern, replacement in replacements.items():
                updated = re.sub(pattern, replacement, updated)
            return updated

        if self._patch_connector_interface_branding_file(styles_scss, originals, patch_styles):
            patched.append(styles_scss)

        theme_scss = self._connector_interface_source_path(root_dir, "theme.scss")

        def patch_theme(source):
            replacements = {
                r"500:\s*#[0-9A-Fa-f]{3,6},": f"500: {primary_css},",
                r"600:\s*#[0-9A-Fa-f]{3,6},": f"600: {primary_css},",
                r"\$primary:\s*#[0-9A-Fa-f]{3,6};": f"$primary: {primary_css};",
            }
            updated = source
            for pattern, replacement in replacements.items():
                updated = re.sub(pattern, replacement, updated)
            return updated

        if self._patch_connector_interface_branding_file(theme_scss, originals, patch_theme):
            patched.append(theme_scss)

        index_html = self._connector_interface_source_path(root_dir, "index.html")
        if self._patch_connector_interface_branding_file(
            index_html,
            originals,
            lambda source: self._replace_first_literal(source, "<title>INESData</title>", f"<title>{escaped_brand}</title>"),
        ):
            patched.append(index_html)

        if patched:
            print("Connector interface branding source patch applied for local image build.")
        else:
            print("Connector interface branding source patch did not change any files.")
        return originals

    def _restore_connector_interface_branding_source(self, originals):
        restored = 0
        for path, original_source in (originals or {}).items():
            if not os.path.isfile(path):
                continue
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(original_source)
            restored += 1
        if restored:
            print("Connector interface branding source restored after local image build.")

    def _maybe_prepare_level4_local_connector_images(self, namespace, manifest_file=None, skip_build=False):
        mode = self._level4_local_images_mode()
        policy = self._resolve_level4_local_image_policy(
            mode=mode,
            label="INESData connector",
        )
        if policy["error"]:
            print(policy["error"])
            return False
        if not policy["prepare_local_images"]:
            if policy["message"]:
                print(policy["message"])
            return True
        if policy["message"]:
            print(policy["message"])
        if mode == "disabled":
            print("Level 4 local INESData connector images disabled by configuration.")
            return True
        if skip_build and not manifest_file:
            print("Level 4 connector image reuse requires a manifest file.")
            return False
        if skip_build and manifest_file and not os.path.isfile(manifest_file):
            print(f"Level 4 connector image manifest not found: {manifest_file}")
            return False

        root_dir = self._framework_root_dir()
        adapter_dir = os.path.join(root_dir, "adapters", "inesdata")
        script_path = os.path.join(adapter_dir, "scripts", "local_build_load_deploy.sh")
        source_dirs = [
            os.path.join(adapter_dir, "sources", "inesdata-connector"),
            os.path.join(adapter_dir, "sources", "inesdata-connector-interface"),
        ]
        missing_sources = [path for path in source_dirs if not os.path.isdir(path)]

        if missing_sources:
            detail = ", ".join(os.path.relpath(path, root_dir) for path in missing_sources)
            if mode == "required":
                print(f"Required INESData local connector sources are missing: {detail}")
                return False
            print(f"Skipping Level 4 local connector image preparation; missing sources: {detail}")
            return True

        if not os.path.isfile(script_path):
            detail = os.path.relpath(script_path, root_dir)
            if mode == "required":
                print(f"Required INESData local image workflow script is missing: {detail}")
                return False
            print(f"Skipping Level 4 local connector image preparation; missing script: {detail}")
            return True

        validator_source_path = ontology_validator_source_path(root_dir)
        original_validator_source = None
        if not skip_build and validator_source_path is not None:
            original_validator_source = validator_source_path.read_text(encoding="utf-8")
            self._patch_ontology_validator_source_for_level4_build(root_dir)
        original_connector_interface_sources = {}
        if not skip_build:
            original_connector_interface_sources = self._patch_connector_interface_branding_source_for_level4_build(root_dir)

        platform_dir = self.config.repo_dir()
        cluster_runtime = self._cluster_runtime()
        cluster_type = str(cluster_runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
        env_prefix = self._remote_image_import_env_prefix_for_namespace(namespace)
        command_parts = [
            "bash",
            script_path,
            "--apply",
            "--platform-dir",
            platform_dir,
            "--namespace",
            namespace,
            "--minikube-profile",
            self._local_minikube_profile(),
            "--cluster-runtime",
            cluster_type,
            "--deploy-target",
            "connectors",
            "--skip-deploy",
        ]
        if manifest_file:
            command_parts.extend(["--manifest", manifest_file])
        if skip_build:
            command_parts.append("--skip-build")
        command = " ".join(shlex.quote(part) for part in command_parts)
        command = f"{env_prefix}{command}"

        print("\nPreparing local INESData connector images for Level 4...")
        print(f"Cluster runtime: {cluster_type}")
        if skip_build:
            print("This reuses the existing Level 4 image manifest and imports the same images before Helm deploy.")
        else:
            print("This builds and loads inesdata-connector and inesdata-connector-interface before Helm deploy.")
        try:
            result = self.run(command, check=False)
        finally:
            if validator_source_path is not None and original_validator_source is not None:
                current_source = validator_source_path.read_text(encoding="utf-8")
                if current_source != original_validator_source:
                    validator_source_path.write_text(original_validator_source, encoding="utf-8", newline="\n")
                    print("Ontology validator source restored after local image build.")
            self._restore_connector_interface_branding_source(original_connector_interface_sources)
        if result is None:
            print("Error preparing local INESData connector images for Level 4.")
            return False
        return True

    def get_deployed_connectors(self, namespace):
        return list(self._runtime_connector_pods_by_namespace(namespace).keys())

    def _runtime_connector_rows_by_namespace(self, namespace):
        with self._temporary_namespace_kubeconfig(namespace):
            result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")
        if not result:
            return []

        rows = []
        for line in result.splitlines():
            cols = line.split()
            if not cols:
                continue
            pod_name = cols[0]
            connector = self._connector_name_from_runtime_pod_name(pod_name)
            if not connector:
                continue
            status = cols[2] if len(cols) >= 3 else ""
            rows.append((connector, pod_name, status))

        return rows

    def _runtime_connector_pods_by_namespace(self, namespace):
        connectors = {}
        for connector, pod_name, _status in self._runtime_connector_rows_by_namespace(namespace):
            if connector not in connectors:
                connectors[connector] = pod_name

        return connectors

    def connector_already_exists(self, connector_name, namespace):
        deployed = self.get_deployed_connectors(namespace)
        return connector_name in deployed

    def build_connector_url(self, connector_name):
        if self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY:
            credentials_url = self._connector_public_access_url(connector_name, "connector_interface_login")
            if credentials_url:
                return self._normalize_public_url(credentials_url, trailing_slash=True)
            public_base_url = self._connector_public_base_url(connector_name)
            if public_base_url:
                return f"{public_base_url}/inesdata-connector-interface/"

        ds_domain = self.config_adapter.ds_domain_base()
        if not ds_domain:
            raise ValueError("DS_DOMAIN_BASE not defined in deployer.config")
        return f"http://{connector_name}.{ds_domain}/inesdata-connector-interface/"

    def wait_for_connector_ready(self, connector_name, timeout=300):
        print(f"Waiting for connector to be ready: {connector_name}")
        url = self.build_connector_url(connector_name)
        host = urlparse(url).hostname
        local_fallback = None
        allow_local_fallback = self._allow_connector_port_forward_fallback()
        ingress_stabilization_timeout = self._connector_public_ingress_stabilization_timeout(connector_name)
        ingress_resync_wait = self._connector_public_ingress_resync_wait_seconds(connector_name)
        ingress_resync_deadline = None
        ingress_resync_attempted = False
        if host:
            try:
                socket.gethostbyname(host)
            except OSError as exc:
                if allow_local_fallback:
                    local_url, local_fallback = self._start_connector_interface_fallback(connector_name)
                    if local_url:
                        url = local_url
                    else:
                        print(f"Connector host does not resolve locally: {host} ({exc})")
                        return False
                else:
                    print(f"Connector host does not resolve locally: {host} ({exc})")
                    print("Connector port-forward fallback is disabled; validate the ingress hostname instead.")
                    return False
        start = time.time()
        last_issue = None

        try:
            while True:
                try:
                    response = requests.get(url, timeout=5)
                    if response.status_code in [200, 302]:
                        print(f"Connector ready: {connector_name}")
                        return True
                    last_issue = f"HTTP {response.status_code}"
                    if (
                        allow_local_fallback
                        and not local_fallback
                        and response.status_code in {502, 503, 504}
                    ):
                        if time.time() - start < ingress_stabilization_timeout:
                            time.sleep(3)
                            continue
                        if (
                            ingress_resync_wait > 0
                            and not ingress_resync_attempted
                            and self._trigger_connector_ingress_resync(connector_name)
                        ):
                            ingress_resync_attempted = True
                            ingress_resync_deadline = time.time() + ingress_resync_wait
                            time.sleep(3)
                            continue
                        if ingress_resync_deadline and time.time() < ingress_resync_deadline:
                            time.sleep(3)
                            continue
                        local_url, local_fallback = self._start_connector_interface_fallback(connector_name)
                        if local_url:
                            url = local_url
                            continue
                except Exception as exc:
                    last_issue = str(exc)
                    if (
                        allow_local_fallback
                        and not local_fallback
                        and self._should_attempt_local_fallback(exc)
                    ):
                        local_url, local_fallback = self._start_connector_interface_fallback(connector_name)
                        if local_url:
                            url = local_url
                            continue

                if time.time() - start > timeout:
                    if last_issue:
                        print(f"Timeout waiting for connector: {connector_name} ({last_issue})")
                    else:
                        print(f"Timeout waiting for connector: {connector_name}")
                    return False

                time.sleep(3)
        finally:
            self._close_temporary_port_forward(local_fallback)

    def wait_for_management_api_ready(self, connector_name, timeout=180, poll_interval=3):
        print(f"Waiting for management API to be ready: {connector_name}")
        start = time.time()
        base_url = self.connector_base_url(connector_name)
        url = f"{base_url}/management/v3/assets/request"
        host = urlparse(url).hostname
        allow_local_fallback = self._allow_connector_port_forward_fallback()
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
            },
            "offset": 0,
            "limit": 1,
        }
        last_issue = None
        local_fallback = None
        ingress_stabilization_timeout = self._connector_public_ingress_stabilization_timeout(connector_name)
        ingress_resync_wait = self._connector_public_ingress_resync_wait_seconds(connector_name)
        ingress_resync_deadline = None
        ingress_resync_attempted = False

        if host:
            try:
                socket.gethostbyname(host)
            except OSError as exc:
                if allow_local_fallback:
                    local_url, local_fallback = self._start_connector_management_api_fallback(connector_name)
                    if local_url:
                        url = local_url
                    else:
                        print(f"Connector Management API host does not resolve locally: {host} ({exc})")
                        return False
                else:
                    print(f"Connector Management API host does not resolve locally: {host} ({exc})")
                    print("Connector port-forward fallback is disabled; validate the ingress hostname instead.")
                    return False

        try:
            while time.time() - start <= timeout:
                headers = self.get_management_api_headers(connector_name)
                if not headers:
                    last_issue = "could not obtain management API token"
                    time.sleep(poll_interval)
                    continue

                try:
                    response = requests.post(url, headers=headers, json=payload, timeout=5)
                    if response.status_code == 200:
                        print(f"Management API ready: {connector_name}")
                        return True
                    if response.status_code == 401:
                        last_issue = "HTTP 401"
                        self.invalidate_management_api_token(connector_name)
                        time.sleep(poll_interval)
                        continue
                    last_issue = f"HTTP {response.status_code}"
                    if (
                        allow_local_fallback
                        and not local_fallback
                        and response.status_code in {502, 503, 504}
                    ):
                        if time.time() - start < ingress_stabilization_timeout:
                            time.sleep(poll_interval)
                            continue
                        if (
                            ingress_resync_wait > 0
                            and not ingress_resync_attempted
                            and self._trigger_connector_ingress_resync(connector_name)
                        ):
                            ingress_resync_attempted = True
                            ingress_resync_deadline = time.time() + ingress_resync_wait
                            time.sleep(poll_interval)
                            continue
                        if ingress_resync_deadline and time.time() < ingress_resync_deadline:
                            time.sleep(poll_interval)
                            continue
                        local_url, local_fallback = self._start_connector_management_api_fallback(connector_name)
                        if local_url:
                            url = local_url
                            continue
                except Exception as exc:
                    last_issue = str(exc)
                    if (
                        allow_local_fallback
                        and not local_fallback
                        and self._should_attempt_local_fallback(exc)
                    ):
                        local_url, local_fallback = self._start_connector_management_api_fallback(connector_name)
                        if local_url:
                            url = local_url
                            continue

                time.sleep(poll_interval)
        finally:
            self._close_temporary_port_forward(local_fallback)

        if last_issue:
            print(f"Management API not ready for {connector_name}: {last_issue}")
        else:
            print(f"Management API not ready for {connector_name}")
        return False

    def wait_for_all_connectors(self, connectors):
        print("\nWaiting for all connectors to become ready...\n")
        if self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY:
            return self._vm_distributed_connector_pods_ready(connectors)

        for connector in connectors:
            if not self.wait_for_connector_ready(connector):
                print(f"Connector not ready: {connector}")
                return False

        return True

    def _vm_distributed_connector_pods_ready(self, connectors):
        for connector in connectors:
            namespace = self._connector_runtime_namespace(connector)
            with self._temporary_connector_kubeconfig(connector):
                pods = self.run_silent(f"kubectl get pods -n {shlex.quote(namespace)} --no-headers") or ""

            runtime_running = False
            interface_running = False
            for line in pods.splitlines():
                cols = line.split()
                if len(cols) < 3:
                    continue
                pod_name, status = cols[0], cols[2]
                if not pod_name.startswith(f"{connector}-"):
                    continue
                if self._is_connector_interface_pod(pod_name):
                    interface_running = interface_running or status == "Running"
                else:
                    runtime_running = runtime_running or status == "Running"

            if not runtime_running or not interface_running:
                print(
                    f"Connector pods not ready in vm-distributed: {connector} "
                    f"(runtime={runtime_running}, interface={interface_running})"
                )
                return False

        print("All vm-distributed connector pods are running")
        return True

    def _wait_for_connector_deployments(self, connector_name, namespace=None, timeout=300):
        namespace = namespace or self._default_connector_namespace()
        rollout_waiter = getattr(self.infrastructure, "wait_for_deployment_rollout", None)
        timeout = max(int(timeout or 300), 1)

        with self._temporary_connector_kubeconfig(connector_name):
            if callable(rollout_waiter):
                deployment_targets = [
                    (connector_name, f"connector runtime '{connector_name}'"),
                    (f"{connector_name}-inteface", f"connector interface '{connector_name}'"),
                ]
                for deployment_name, label in deployment_targets:
                    if not rollout_waiter(
                        namespace,
                        deployment_name,
                        timeout_seconds=timeout,
                        label=label,
                    ):
                        if not self._recover_connector_rollout_after_stalled_init(
                            namespace,
                            deployment_name,
                            timeout=timeout,
                            label=label,
                            rollout_waiter=rollout_waiter,
                        ):
                            return False
                return True

            wait_for_namespace_pods = getattr(self.infrastructure, "wait_for_namespace_pods", None)
            if callable(wait_for_namespace_pods):
                return bool(wait_for_namespace_pods(namespace, timeout=timeout))
            return False

    def _connector_rollout_recovery_enabled(self):
        value = os.environ.get("INESDATA_CONNECTOR_ROLLOUT_RECOVERY", "1").strip().lower()
        return value not in {"0", "false", "no", "off"}

    @staticmethod
    def _pod_status_is_recoverable_rollout_stall(status):
        normalized = str(status or "").strip()
        return (
            normalized.startswith("Init:")
            or normalized in {"ContainerCreating", "PodInitializing", "Pending", "Unknown"}
        )

    def _recover_connector_rollout_after_stalled_init(
        self,
        namespace,
        deployment_name,
        *,
        timeout,
        label,
        rollout_waiter,
    ):
        if not self._connector_rollout_recovery_enabled():
            print(f"Automatic connector rollout recovery disabled; not retrying {label}.")
            return False

        selector = f"service={deployment_name}"
        pods_output = self.run_silent(
            f"kubectl get pods -n {shlex.quote(namespace)} "
            f"-l {shlex.quote(selector)} --no-headers"
        )
        stalled_pods = []
        for line in (pods_output or "").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            pod_name, status = parts[0], parts[2]
            if self._pod_status_is_recoverable_rollout_stall(status):
                stalled_pods.append(pod_name)

        if not stalled_pods:
            print(f"No recoverable stalled init pods found for {label}; keeping rollout failure.")
            return False

        print(
            f"Detected stalled init pod(s) for {label}: {', '.join(stalled_pods)}. "
            "Recreating them once before failing Level 4."
        )
        for pod_name in stalled_pods:
            self.run(
                f"kubectl delete pod {shlex.quote(pod_name)} "
                f"-n {shlex.quote(namespace)} --wait=false",
                check=False,
            )

        retry_timeout = max(int(timeout or 300), 300)
        return bool(
            rollout_waiter(
                namespace,
                deployment_name,
                timeout_seconds=retry_timeout,
                label=f"{label} after stalled init pod recovery",
            )
        )

    def load_connector_credentials(self, connector_name):
        creds_file = self.config.connector_credentials_path(connector_name)
        if not os.path.exists(creds_file):
            return None

        try:
            with open(creds_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    @staticmethod
    def _normalize_public_url(url, trailing_slash=False):
        raw_url = str(url or "").strip()
        if not raw_url:
            return ""
        if not raw_url.startswith(("http://", "https://")):
            raw_url = f"http://{raw_url}"
        raw_url = raw_url.rstrip("/")
        if trailing_slash:
            return f"{raw_url}/"
        return raw_url

    def _connector_public_access_url(self, connector_name, key):
        credentials = self.load_connector_credentials(connector_name) or {}
        public_urls = credentials.get("public_access_urls") or {}
        if not isinstance(public_urls, dict):
            return ""
        return str(public_urls.get(key) or "").strip()

    def _connector_access_url(self, connector_name, key):
        credentials = self.load_connector_credentials(connector_name) or {}
        access_urls = credentials.get("access_urls") or {}
        if not isinstance(access_urls, dict):
            return ""
        return str(access_urls.get(key) or "").strip()

    def _connector_public_base_url(self, connector_name):
        if self._normalized_topology() != VM_DISTRIBUTED_TOPOLOGY:
            return ""

        credentials_url = self._connector_public_access_url(connector_name, "connector_ingress")
        if credentials_url:
            return self._normalize_public_url(credentials_url)

        deployer_config = self.config_adapter.load_deployer_config() or {}
        layout = self._connector_layout_metadata(connector_name)
        role = (
            layout.get("namespace_role")
            or layout.get("validation_role")
            or layout.get("role")
            or self._connector_kubeconfig_role(connector_name)
        )
        role_url = self._connector_public_url_for_role(role, deployer_config)
        if role_url:
            return self._normalize_public_url(role_url)

        return ""

    def connector_base_url(self, connector):
        """Build base Management API URL for a connector."""
        public_base_url = self._connector_public_base_url(connector)
        if public_base_url:
            return public_base_url

        domain = self.config.ds_domain_base()

        if not domain:
            raise ValueError("DS_DOMAIN_BASE not defined in deployer.config")

        return f"http://{connector}.{domain}"

    def get_management_api_auth(self, connector):
        """Get authentication credentials for connector management API."""
        creds = self.load_connector_credentials(connector)

        if not creds or "connector_user" not in creds:
            return None

        return (
            creds["connector_user"]["user"],
            creds["connector_user"]["passwd"]
        )

    @staticmethod
    def _keycloak_realm_url(base_url, dataspace):
        normalized_base = INESDataConnectorsAdapter._normalize_public_url(base_url)
        if not normalized_base:
            return ""
        normalized_dataspace = str(dataspace or "").strip().strip("/")
        if not normalized_dataspace:
            return normalized_base
        realm_suffix = f"/realms/{normalized_dataspace}"
        if normalized_base.endswith(realm_suffix):
            return normalized_base
        return f"{normalized_base}{realm_suffix}"

    def _keycloak_token_url(self):
        deployer_config = self.config_adapter.load_deployer_config()
        keycloak_url = ""
        if self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY:
            keycloak_url = (
                deployer_config.get("KEYCLOAK_FRONTEND_URL")
                or deployer_config.get("KEYCLOAK_PUBLIC_URL")
                or ""
            )
        keycloak_url = keycloak_url or deployer_config.get("KC_INTERNAL_URL") or deployer_config.get("KC_URL")
        if not keycloak_url:
            return None
        realm_url = self._keycloak_realm_url(keycloak_url, self._dataspace_name())
        return f"{realm_url}/protocol/openid-connect/token"

    def get_management_api_token(self, connector):
        """Get a Bearer token for the connector management user."""
        if connector in self._management_token_cache:
            return self._management_token_cache[connector]

        auth = self.get_management_api_auth(connector)
        token_url = self._keycloak_token_url()
        if not auth or not token_url:
            return None

        try:
            response = requests.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": "dataspace-users",
                    "username": auth[0],
                    "password": auth[1],
                    "scope": "openid profile email",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            if response.status_code != 200:
                return None
            token = response.json().get("access_token")
            if token:
                self._management_token_cache[connector] = token
            return token
        except Exception:
            return None

    def invalidate_management_api_token(self, connector):
        self._management_token_cache.pop(connector, None)

    def get_management_api_headers(self, connector):
        """Build bearer-authenticated headers for the connector Management API."""
        token = self.get_management_api_token(connector)
        if not token:
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def asset_exists(self, connector, asset_id):
        headers = self.get_management_api_headers(connector)
        if not headers:
            return False

        base_url = self.connector_base_url(connector)
        url = f"{base_url}/management/v3/assets/{asset_id}"

        try:
            response = requests.get(url, headers=headers, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def policy_exists(self, connector, policy_id):
        headers = self.get_management_api_headers(connector)
        if not headers:
            return False

        base_url = self.connector_base_url(connector)
        url = f"{base_url}/management/v3/policydefinitions/{policy_id}"

        try:
            response = requests.get(url, headers=headers, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def contract_definition_exists(self, connector, contract_id):
        headers = self.get_management_api_headers(connector)
        if not headers:
            return False

        base_url = self.connector_base_url(connector)
        url = f"{base_url}/management/v3/contractdefinitions/{contract_id}"

        try:
            response = requests.get(url, headers=headers, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def delete_asset(self, connector, asset_id):
        headers = self.get_management_api_headers(connector)
        if not headers:
            return False

        base_url = self.connector_base_url(connector)
        url = f"{base_url}/management/v3/assets/{asset_id}"

        try:
            response = requests.delete(url, headers=headers, timeout=5)
            return response.status_code in (200, 204, 404)
        except Exception:
            return False

    def delete_policy(self, connector, policy_id):
        headers = self.get_management_api_headers(connector)
        if not headers:
            return False

        base_url = self.connector_base_url(connector)
        url = f"{base_url}/management/v3/policydefinitions/{policy_id}"

        try:
            response = requests.delete(url, headers=headers, timeout=5)
            return response.status_code in (200, 204, 404)
        except Exception:
            return False

    def delete_contract_definition(self, connector, contract_id):
        headers = self.get_management_api_headers(connector)
        if not headers:
            return False

        base_url = self.connector_base_url(connector)
        url = f"{base_url}/management/v3/contractdefinitions/{contract_id}"

        try:
            response = requests.delete(url, headers=headers, timeout=5)
            return response.status_code in (200, 204, 404)
        except Exception:
            return False

    def cleanup_test_entities(self, connector):
        """Clean up common validation test entities to keep tests idempotent."""
        test_entities = {
            "assets": [
                "test-asset-1",
                "test-asset-2",
                "asset-1",
                "asset-2",
                "test-document",
                "asset-test"
            ],
            "policies": [
                "test-policy-1",
                "test-policy-2",
                "policy-1",
                "policy-2",
                "use-eu",
                "policy-test"
            ],
            "contracts": [
                "test-contract-1",
                "test-contract-2",
                "contract-1",
                "contract-2",
                "contract-definition-1",
                "contract-test"
            ]
        }

        print(f"Cleaning up test entities from {connector}...")

        headers = self.get_management_api_headers(connector)
        if not headers:
            print(f"  Unable to authenticate against Management API for {connector}")
            print(f"Cleanup completed for {connector}\n")
            return

        for contract_id in test_entities["contracts"]:
            if self.delete_contract_definition(connector, contract_id):
                print(f"  Deleted contract definition: {contract_id}")
            else:
                print(f"  Could not delete contract definition: {contract_id}")

        for policy_id in test_entities["policies"]:
            if self.delete_policy(connector, policy_id):
                print(f"  Deleted policy: {policy_id}")
            else:
                print(f"  Could not delete policy: {policy_id}")

        for asset_id in test_entities["assets"]:
            if self.delete_asset(connector, asset_id):
                print(f"  Deleted asset: {asset_id}")
            else:
                print(f"  Could not delete asset: {asset_id}")

        print(f"Cleanup completed for {connector}\n")

    def validation_test_entities_absent(self, connector):
        """Return True only if the fixed validation entities are absent."""
        lingering_entities = []

        if self.asset_exists(connector, "asset-test"):
            lingering_entities.append("asset-test")
        if self.policy_exists(connector, "policy-test"):
            lingering_entities.append("policy-test")
        if self.contract_definition_exists(connector, "contract-test"):
            lingering_entities.append("contract-test")

        return len(lingering_entities) == 0, lingering_entities

    def display_connector_summary(self, connector_name):
        deployer_config = self.config_adapter.load_deployer_config()
        ds_domain = deployer_config.get("DS_DOMAIN_BASE")
        domain_base = deployer_config.get("DOMAIN_BASE")
        pg_host, _, _ = self.config_adapter.get_pg_credentials()
        pg_port = self._pg_port()
        minio_hostname = deployer_config.get("MINIO_HOSTNAME")

        if not ds_domain:
            return

        connector_root_url = f"http://{connector_name}.{ds_domain}"
        connector_interface_url = self.build_connector_url(connector_name)
        management_api_url = f"{connector_root_url}/management/v3"
        protocol_api_url = f"{connector_root_url}/protocol"
        creds = self.load_connector_credentials(connector_name)

        print(f"\n{'='*60}")
        print(f"CONNECTOR: {connector_name}")
        print(f"{'='*60}")
        print("\nURLs:")
        print(f"  Connector: {connector_root_url}")
        print(f"  Interface: {connector_interface_url}")
        print(f"  Management API: {management_api_url}")
        print(f"  Protocol API: {protocol_api_url}")

        if creds:
            print("\nConnector Credentials:")
            connector_user = creds.get("connector_user", {})
            print(f"  User: {connector_user.get('user', 'N/A')}")
            print(f"  Password: {'***REDACTED***' if connector_user.get('passwd') else 'N/A'}")

            print("\nDatabase Credentials:")
            db_creds = creds.get("database", {})
            print(f"  Database: {db_creds.get('name', 'N/A')}")
            print(f"  User: {db_creds.get('user', 'N/A')}")
            print(f"  Password: {'***REDACTED***' if db_creds.get('passwd') else 'N/A'}")
            print(f"  Host: {pg_host}")
            print(f"  DSN: postgresql://{pg_host}:{pg_port}/{db_creds.get('name', 'N/A')}")

            print("\nMinIO Credentials:")
            minio_creds = creds.get("minio", {})
            print(f"  User: {minio_creds.get('user', 'N/A')}")
            print(f"  Password: {'***REDACTED***' if minio_creds.get('passwd') else 'N/A'}")
            print(f"  Access Key: {'***REDACTED***' if minio_creds.get('access_key') else 'N/A'}")
            print(f"  Secret Key: {'***REDACTED***' if minio_creds.get('secret_key') else 'N/A'}")
            if minio_hostname:
                print(f"  API URL: http://{minio_hostname}")
            if domain_base:
                print(f"  Console URL: http://console.minio-s3.{domain_base}")

        print(f"\n{'='*60}\n")

    def setup_minio_bucket(self, namespace, ds_name, connector_name, creds_file_path):
        print("\nConfiguring MinIO...")

        deployer_config = self.config_adapter.load_deployer_config() or {}
        minio_endpoint = deployer_config.get("MINIO_ENDPOINT") or "http://127.0.0.1:9000"
        minio_admin_user, minio_admin_pass = self._minio_admin_credentials(deployer_config)

        minio_pod = self.infrastructure.get_pod_by_name(namespace, self.config.service_minio())
        if not minio_pod:
            print(f"Pod {self.config.service_minio()} not found")
            return False

        try:
            with open(creds_file_path) as f:
                creds = json.load(f)
        except FileNotFoundError:
            print(f"File not found: {creds_file_path}")
            return False

        minio_creds = creds.get("minio", {})
        minio_user_password = minio_creds.get("passwd")
        minio_access_key = minio_creds.get("access_key")
        minio_secret_key = minio_creds.get("secret_key")
        if not all([minio_user_password, minio_access_key, minio_secret_key]):
            print(f"MinIO credentials are incomplete in {creds_file_path}")
            return False

        mc = f"kubectl exec -n {namespace} {minio_pod} --"

        alias_result = self.run(
            f"{mc} mc alias set minio {shlex.quote(minio_endpoint)} "
            f"{shlex.quote(minio_admin_user)} {shlex.quote(minio_admin_pass)}",
            check=False,
            silent=True,
        )
        if alias_result is None:
            print(
                "MinIO admin alias could not be configured. "
                "Check MINIO_USER/MINIO_PASSWORD in deployers/infrastructure/deployer.config "
                "and recreate Level 2 if the running MinIO secret is stale."
            )
            return False

        bucket_name = f"{ds_name}-{connector_name}"
        bucket_result = self.run(
            f"{mc} mc mb --ignore-existing {shlex.quote(f'minio/{bucket_name}')}",
            check=False,
        )
        if bucket_result is None:
            print(f"MinIO bucket '{bucket_name}' could not be created or verified")
            return False

        add_user_result = self.run(
            f"{mc} mc admin user add minio {shlex.quote(connector_name)} {shlex.quote(minio_user_password)}",
            capture=True,
            check=False,
            silent=True,
        )
        if add_user_result is None:
            user_info = self.run_silent(
                f"{mc} mc admin user info minio {shlex.quote(connector_name)}"
            )
            if not user_info:
                print(f"MinIO user '{connector_name}' could not be created or verified")
                return False

        svcacct_info = self.run_silent(
            f"{mc} mc admin user svcacct list minio {shlex.quote(connector_name)}"
        )
        if not svcacct_info or minio_access_key not in svcacct_info:
            svcacct_result = self.run(
                f"{mc} mc admin user svcacct add minio {shlex.quote(connector_name)} "
                f"--access-key {shlex.quote(minio_access_key)} --secret-key {shlex.quote(minio_secret_key)}",
                capture=True,
                check=False,
                silent=True,
            )
            if svcacct_result is None:
                svcacct_info = self.run_silent(
                    f"{mc} mc admin user svcacct list minio {shlex.quote(connector_name)}"
                )
                if not svcacct_info or minio_access_key not in svcacct_info:
                    print(f"MinIO service account for '{connector_name}' could not be created or verified")
                    return False

        # Attach S3 policy to connector user (required for upload permissions) - FIX for BUG-001
        policy_name = f"policy-{ds_name}-{connector_name}"
        policy_file_path = os.path.join(
            self.config.repo_dir(),
            "deployments",
            "DEV",
            ds_name,
            f"{policy_name}.json"
        )

        if os.path.exists(policy_file_path):
            try:
                with open(policy_file_path) as f:
                    policy_content = json.load(f)

                policy_path_pod = f"/tmp/{policy_name}.json"

                # Encode policy as base64 and decode in the pod to avoid shell
                # quoting issues and kubectl cp dependency on `tar`.
                policy_b64 = base64.b64encode(json.dumps(policy_content).encode("utf-8")).decode("ascii")
                write_policy_result = self.run(
                    f"{mc} sh -c \"echo '{policy_b64}' | base64 -d > {policy_path_pod}\"",
                    check=False,
                    silent=True,
                )
                if write_policy_result is None:
                    print(f"Could not write MinIO policy file inside pod for '{connector_name}'")
                    return False

                # Create policy in MinIO (idempotent: ignore already-exists error)
                self.run(
                    f"{mc} mc admin policy create minio {shlex.quote(policy_name)} {shlex.quote(policy_path_pod)}",
                    capture=True,
                    check=False,
                    silent=True,
                )

                user_info = self.run_silent(
                    f"{mc} mc admin user info minio {shlex.quote(connector_name)}"
                )
                policy_already_attached = bool(user_info and policy_name in user_info)
                if not policy_already_attached:
                    self.run(
                        f"{mc} mc admin policy attach minio {shlex.quote(policy_name)} "
                        f"--user {shlex.quote(connector_name)}",
                        capture=True,
                        check=False,
                        silent=True,
                    )

                # Verify
                result = self.run_silent(
                    f"{mc} mc admin user info minio {shlex.quote(connector_name)}"
                )
                if result and policy_name in result:
                    if policy_already_attached:
                        print(f"MinIO policy '{policy_name}' already attached to '{connector_name}'")
                    else:
                        print(f"MinIO policy '{policy_name}' attached to '{connector_name}'")
                else:
                    print(f"MinIO policy attach could not be verified for '{connector_name}'")
                    return False
            except (IOError, json.JSONDecodeError) as e:
                print(f"Could not attach MinIO policy: {e}")
                return False
        else:
            print(f"Policy file not found at {policy_file_path}")
            return False

        print("MinIO configured")
        return True

    def ensure_minio_policy_attached(self, connector_name, ds_name=None):
        """Idempotently ensure the S3 policy is attached to a connector MinIO user.

        Safe to call at any level; checks current state before taking action.
        """
        ds_name = ds_name or self._dataspace_name()
        namespace = self.config.NS_COMMON
        policy_name = f"policy-{ds_name}-{connector_name}"

        deployer_config = self.config_adapter.load_deployer_config() or {}
        minio_endpoint = deployer_config.get("MINIO_ENDPOINT") or "http://127.0.0.1:9000"
        minio_admin_user, minio_admin_pass = self._minio_admin_credentials(deployer_config)

        minio_pod = self.infrastructure.get_pod_by_name(namespace, self.config.service_minio())
        if not minio_pod:
            print(f"  MinIO pod not found — skipping policy ensure for {connector_name}")
            return False

        mc = f"kubectl exec -n {namespace} {minio_pod} --"
        alias_result = self.run(
            f"{mc} mc alias set minio {shlex.quote(minio_endpoint)} "
            f"{shlex.quote(minio_admin_user)} {shlex.quote(minio_admin_pass)}",
            check=False,
            silent=True,
        )
        if alias_result is None:
            print(f"  MinIO admin alias could not be configured for {connector_name}")
            return False

        user_info = self.run_silent(f"{mc} mc admin user info minio {shlex.quote(connector_name)}")
        if user_info and policy_name in user_info:
            print(f"  MinIO policy '{policy_name}' already attached to '{connector_name}'")
            return True

        policy_file_path = os.path.join(
            self.config.repo_dir(),
            "deployments",
            "DEV",
            ds_name,
            f"{policy_name}.json",
        )
        if not os.path.exists(policy_file_path):
            print(f"  Warning: policy file not found: {policy_file_path}")
            return False

        try:
            with open(policy_file_path) as f:
                policy_content = json.load(f)
            if not policy_content:
                print(f"  Warning: policy file {policy_file_path} is empty")
                return False

            policy_path_pod = f"/tmp/{policy_name}.json"
            policy_b64 = base64.b64encode(json.dumps(policy_content).encode("utf-8")).decode("ascii")
            write_policy_result = self.run(
                f"{mc} sh -c \"echo '{policy_b64}' | base64 -d > {policy_path_pod}\"",
                check=False,
                silent=True,
            )
            if write_policy_result is None:
                print(f"  Warning: could not write MinIO policy file inside pod for {connector_name}")
                return False
            self.run(
                f"{mc} mc admin policy create minio {shlex.quote(policy_name)} {shlex.quote(policy_path_pod)}",
                capture=True,
                check=False,
                silent=True,
            )
            user_info = self.run_silent(f"{mc} mc admin user info minio {shlex.quote(connector_name)}")
            policy_already_attached = bool(user_info and policy_name in user_info)
            if not policy_already_attached:
                self.run(
                    f"{mc} mc admin policy attach minio {shlex.quote(policy_name)} "
                    f"--user {shlex.quote(connector_name)}",
                    capture=True,
                    check=False,
                    silent=True,
                )

            user_info = self.run_silent(f"{mc} mc admin user info minio {shlex.quote(connector_name)}")
            if user_info and policy_name in user_info:
                if policy_already_attached:
                    print(f"  MinIO policy '{policy_name}' already attached to '{connector_name}'")
                else:
                    print(f"  MinIO policy '{policy_name}' attached to '{connector_name}'")
                return True

            print(f"  Warning: policy attach could not be verified for '{connector_name}'")
            return False
        except (IOError, json.JSONDecodeError) as e:
            print(f"  Warning: could not attach MinIO policy: {e}")
            return False

    def ensure_all_minio_policies(self, connectors):
        """Ensure MinIO S3 policies are attached for every connector in the list."""
        print("\nEnsuring MinIO policies...")
        all_ok = all(self.ensure_minio_policy_attached(c) for c in connectors)
        if all_ok:
            print("All MinIO policies confirmed\n")
        else:
            print("Warning: one or more MinIO policies could not be confirmed\n")
        return all_ok

    def force_clean_postgres_db(self, db_name, db_user, pg_host=None, pg_port=None):
        print(f"\nCleaning PostgreSQL database '{db_name}'...")

        configured_pg_host, pg_user, pg_password = self.config_adapter.get_pg_credentials()
        pg_host = pg_host or configured_pg_host
        pg_port = pg_port or self._pg_port()
        terminate_sql = f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{db_name}';
        """

        cleanup_steps = [
            (
                "terminate active sessions",
                f"PGPASSWORD={shlex.quote(str(pg_password))} psql -h {shlex.quote(str(pg_host))} "
                f"-p {shlex.quote(str(pg_port))} -U {shlex.quote(str(pg_user))} "
                f"-d postgres -c \"{terminate_sql}\"",
            ),
            (
                "drop database",
                f"PGPASSWORD={shlex.quote(str(pg_password))} psql -h {shlex.quote(str(pg_host))} "
                f"-p {shlex.quote(str(pg_port))} -U {shlex.quote(str(pg_user))} "
                f"-d postgres -c \"DROP DATABASE IF EXISTS {db_name};\"",
            ),
            (
                "drop role",
                f"PGPASSWORD={shlex.quote(str(pg_password))} psql -h {shlex.quote(str(pg_host))} "
                f"-p {shlex.quote(str(pg_port))} -U {shlex.quote(str(pg_user))} "
                f"-d postgres -c \"DROP ROLE IF EXISTS {db_user};\"",
            ),
        ]
        max_attempts = 3
        postgres_ready = getattr(self.infrastructure, "ensure_local_infra_access", None)

        for attempt in range(1, max_attempts + 1):
            for label, command in cleanup_steps:
                if self.run(command, check=False, silent=True) is None:
                    print(f"  Warning: PostgreSQL cleanup step failed: {label}")

            database_exists = self._postgres_database_exists(db_name, pg_host, pg_port, pg_user, pg_password)
            role_exists = self._postgres_role_exists(db_user, pg_host, pg_port, pg_user, pg_password)
            if database_exists is False and role_exists is False:
                print("PostgreSQL cleanup complete\n")
                return True

            if attempt >= max_attempts:
                break

            remaining = []
            if database_exists is not False:
                remaining.append(f"database '{db_name}'")
            if role_exists is not False:
                remaining.append(f"role '{db_user}'")
            if remaining:
                print(
                    "  PostgreSQL cleanup not fully applied yet; retrying after infrastructure check: "
                    + ", ".join(remaining)
                )

            if callable(postgres_ready) and not postgres_ready():
                print("  Warning: local PostgreSQL access could not be re-established before retrying cleanup")
            time.sleep(2)

        print(
            "  Warning: PostgreSQL cleanup could not be fully verified for "
            f"database '{db_name}' and role '{db_user}'"
        )
        print("PostgreSQL cleanup complete\n")
        return False

    def _postgres_database_exists(self, db_name, pg_host, pg_port, pg_user, pg_password):
        escaped_name = str(db_name or "").replace("'", "''")
        result = self.run_silent(
            f"PGPASSWORD={shlex.quote(str(pg_password))} psql -h {shlex.quote(str(pg_host))} "
            f"-p {shlex.quote(str(pg_port))} -U {shlex.quote(str(pg_user))} "
            f"-d postgres -t -A -c \"SELECT 1 FROM pg_database WHERE datname = '{escaped_name}';\""
        )
        if result is None:
            return None
        return result.strip() == "1"

    def _postgres_role_exists(self, role_name, pg_host, pg_port, pg_user, pg_password):
        escaped_name = str(role_name or "").replace("'", "''")
        result = self.run_silent(
            f"PGPASSWORD={shlex.quote(str(pg_password))} psql -h {shlex.quote(str(pg_host))} "
            f"-p {shlex.quote(str(pg_port))} -U {shlex.quote(str(pg_user))} "
            f"-d postgres -t -A -c \"SELECT 1 FROM pg_roles WHERE rolname = '{escaped_name}';\""
        )
        if result is None:
            return None
        return result.strip() == "1"

    def _remove_connector_values_file(self, connector_name):
        values_file = self.config.connector_values_file(connector_name)
        if os.path.exists(values_file):
            try:
                os.remove(values_file)
                print(f"Removed stale connector values file: {values_file}")
            except OSError as exc:
                print(f"Warning: could not remove stale values file {values_file}: {exc}")
        return values_file

    def _bootstrap_runtime(self):
        if self._bootstrap_runtime_module is not None:
            return self._bootstrap_runtime_module

        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        bootstrap_path = os.path.join(root_dir, "deployers", "inesdata", "bootstrap.py")
        spec = importlib.util.spec_from_file_location("_pionera_inesdata_bootstrap_runtime", bootstrap_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load INESData bootstrap module from {bootstrap_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._bootstrap_runtime_module = module
        return module

    def _apply_connector_interface_branding_assets(self, connector_name, namespace):
        try:
            bootstrap = self._bootstrap_runtime()
            config = bootstrap.load_effective_deployer_config()
            branding_keys = bootstrap._inesdata_branding_template_keys(config, "connector")
            selected_files = list(branding_keys.get("inesdata_brand_asset_files") or [])
            configmap_name = f"{connector_name}-interface-branding-assets"
            if not selected_files:
                with self._temporary_namespace_kubeconfig(namespace):
                    self.run(
                        f"kubectl delete configmap {shlex.quote(configmap_name)} "
                        f"-n {shlex.quote(namespace)} --ignore-not-found",
                        check=False,
                    )
                return True

            assets = bootstrap._load_branding_assets(config, selected_files)
            manifest = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": configmap_name,
                    "namespace": namespace,
                    "labels": {"service": f"{connector_name}-interface"},
                },
                "binaryData": {
                    str(asset["name"]): str(asset["contentBase64"])
                    for asset in assets
                },
            }

            tmp_path = ""
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                delete=False,
                prefix=f"{connector_name}-branding-",
                suffix=".yaml",
            ) as handle:
                yaml.safe_dump(manifest, handle, sort_keys=False)
                tmp_path = handle.name

            with self._temporary_namespace_kubeconfig(namespace):
                if not self.run_silent(f"kubectl get namespace {shlex.quote(namespace)}"):
                    self.run(f"kubectl create namespace {shlex.quote(namespace)}", check=False)
                print(f"Applying connector interface branding assets: {configmap_name}")
                existing = self.run_silent(
                    f"kubectl get configmap {shlex.quote(configmap_name)} "
                    f"-n {shlex.quote(namespace)} --ignore-not-found"
                )
                action = "replace" if existing else "create"
                return self.run(f"kubectl {action} -f {shlex.quote(tmp_path)}", check=False) is not None
        except Exception as exc:
            print(f"Error applying connector interface branding assets: {exc}")
            return False
        finally:
            if "tmp_path" in locals() and tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _wait_for_connector_pods_deleted(
        self,
        connector_name,
        namespace,
        timeout=60,
        poll_interval=3,
        kubeconfig_role=None,
    ):
        """Wait briefly for a previous connector release to stop holding DB sessions."""
        start = time.time()
        reported_wait = False

        while time.time() - start < timeout:
            with self._temporary_connector_cleanup_kubeconfig(connector_name, kubeconfig_role=kubeconfig_role):
                pods = self.run_silent(f"kubectl get pods -n {namespace} --no-headers") or ""
            connector_pods = [
                line.split()[0]
                for line in pods.splitlines()
                if line.split() and line.split()[0].startswith(f"{connector_name}-")
            ]
            if not connector_pods:
                if reported_wait:
                    print(f"Previous connector pods terminated: {connector_name}")
                return True

            if not reported_wait:
                print(f"Waiting for previous connector pods to terminate: {connector_name}")
                reported_wait = True
            time.sleep(poll_interval)

        print(f"Warning: previous connector pods still visible before cleanup: {connector_name}")
        return False

    def _cleanup_connector_state(
        self,
        connector_name,
        repo_dir,
        ds_name,
        python_exec,
        namespace=None,
        dataspace=None,
        kubeconfig_role=None,
        vault_url=None,
        keycloak_url=None,
        pg_host=None,
        pg_port=None,
    ):
        values_file = self._remove_connector_values_file(connector_name)
        self.invalidate_management_api_token(connector_name)

        print(f"Cleaning connector: {connector_name}")
        release_name = f"{connector_name}-{ds_name}"
        ns = namespace or self.config.namespace_demo()
        effective_kubeconfig_role = kubeconfig_role
        if effective_kubeconfig_role is None and ns:
            effective_kubeconfig_role = self._namespace_kubeconfig_role(ns, dataspace=dataspace)

        with self._temporary_connector_cleanup_kubeconfig(
            connector_name,
            kubeconfig_role=effective_kubeconfig_role,
        ):
            self.run(f"helm uninstall {release_name} -n {ns}", check=False)
            self._wait_for_connector_pods_deleted(
                connector_name,
                ns,
                kubeconfig_role=effective_kubeconfig_role,
            )

        delete_cmd = self._bootstrap_connector_delete_command(
            python_exec,
            connector_name,
            ds_name,
            vault_url=vault_url,
            keycloak_url=keycloak_url,
            pg_host=pg_host,
            pg_port=pg_port,
        )
        self.run(delete_cmd, cwd=repo_dir, check=False)

        connector_db = connector_name.replace("-", "_")
        self.force_clean_postgres_db(
            connector_db,
            connector_db,
            pg_host=pg_host,
            pg_port=pg_port,
        )

        print("Cleaning registration-service database...")
        sql_del = (
            f"DELETE FROM public.edc_participant "
            f"WHERE participant_id = '{connector_name}';"
        )
        configured_pg_host, pg_user, pg_pass = self.config_adapter.get_pg_credentials()
        effective_pg_host = pg_host or configured_pg_host
        effective_pg_port = pg_port or self._pg_port()
        self.run(
            f"PGPASSWORD={shlex.quote(str(pg_pass))} psql -h {shlex.quote(str(effective_pg_host))} "
            f"-p {shlex.quote(str(effective_pg_port))} -U {shlex.quote(str(pg_user))} "
            f'-d {self.config.registration_db_name()} -c "{sql_del}"',
            check=False,
            silent=True,
        )

        return values_file

    def create_connector(self, connector_name, connector_hostnames=None):
        print("\n========================================")
        print("LEVEL 4 - CREATE CONNECTOR")
        print("========================================\n")

        dataspace = self._find_dataspace_for_connector(connector_name) or {}
        repo_dir = self.config.repo_dir()
        ds_name = str(dataspace.get("name") or self._dataspace_name()).strip() or self._dataspace_name()
        ds_namespace = str(dataspace.get("namespace") or self._default_connector_namespace()).strip() or self._default_connector_namespace()
        target_namespace = self._connector_target_namespace(connector_name, dataspace=dataspace)
        python_exec = self.config.python_exec()

        if not os.path.exists(repo_dir):
            print("Repository not found. Run Level 2 first")
            return False

        if not os.path.exists(self.config.venv_path()):
            print("Python environment not found. Run Level 3 first")
            return False

        if not self._prepare_vault_management_access(ds_name=ds_name):
            return False

        vault_bootstrap_access = self._start_vault_bootstrap_access()
        if vault_bootstrap_access is None:
            return False
        vault_bootstrap_url = vault_bootstrap_access.get("vault_url")
        postgres_bootstrap_access = self._start_postgres_bootstrap_access()
        if postgres_bootstrap_access is None:
            self._stop_vault_bootstrap_access(vault_bootstrap_access)
            return False
        postgres_bootstrap_host = postgres_bootstrap_access.get("pg_host")
        postgres_bootstrap_port = postgres_bootstrap_access.get("pg_port")
        keycloak_bootstrap_access = {"keycloak_url": None, "port_forward": None}
        if (
            self._vm_distributed_keycloak_admin_needs_port_forward()
            and callable(getattr(self.infrastructure, "port_forward_service", None))
        ):
            keycloak_bootstrap_access = self._start_keycloak_bootstrap_access()
            if keycloak_bootstrap_access is None:
                self._stop_postgres_bootstrap_access(postgres_bootstrap_access)
                self._stop_vault_bootstrap_access(vault_bootstrap_access)
                return False
        keycloak_bootstrap_url = keycloak_bootstrap_access.get("keycloak_url")

        try:
            if not self.wait_for_keycloak_admin_ready(keycloak_url=keycloak_bootstrap_url):
                if keycloak_bootstrap_url is None and self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY:
                    keycloak_bootstrap_access = self._start_keycloak_bootstrap_access()
                    if keycloak_bootstrap_access is not None:
                        keycloak_bootstrap_url = keycloak_bootstrap_access.get("keycloak_url")
                if not keycloak_bootstrap_url or not self.wait_for_keycloak_admin_ready(
                    keycloak_url=keycloak_bootstrap_url,
                ):
                    print("Keycloak admin API not ready for connector cleanup")
                    return False

            values_file = self._cleanup_connector_state(
                connector_name,
                repo_dir,
                ds_name,
                python_exec,
                namespace=target_namespace,
                vault_url=vault_bootstrap_url,
                keycloak_url=keycloak_bootstrap_url,
                pg_host=postgres_bootstrap_host,
                pg_port=postgres_bootstrap_port,
            )

            if not self.wait_for_keycloak_admin_ready(keycloak_url=keycloak_bootstrap_url):
                print("Keycloak admin API not ready for connector provisioning")
                return False

            print(f"Creating connector {connector_name}...")
            create_cmd = self._bootstrap_connector_create_command(
                python_exec,
                connector_name,
                ds_name,
                vault_url=vault_bootstrap_url,
                keycloak_url=keycloak_bootstrap_url,
                pg_host=postgres_bootstrap_host,
                pg_port=postgres_bootstrap_port,
            )
            create_result = None
            creds_path = self.config.connector_credentials_path(connector_name)
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                create_result = self.run(create_cmd, cwd=repo_dir, check=False)
                missing_credentials = (
                    self._connector_credentials_missing_requirements(creds_path)
                    if create_result is not None
                    else []
                )
                if create_result is not None and not missing_credentials:
                    break
                if missing_credentials:
                    print(
                        "Connector bootstrap produced incomplete credentials "
                        f"({', '.join(missing_credentials)}). Retrying cleanly..."
                    )
                    create_result = None
                if attempt < max_attempts:
                    print(
                        f"Connector creation failed on attempt {attempt}. "
                        "Cleaning partial state and retrying after Keycloak readiness check..."
                    )
                    values_file = self._cleanup_connector_state(
                        connector_name,
                        repo_dir,
                        ds_name,
                        python_exec,
                        namespace=target_namespace,
                        vault_url=vault_bootstrap_url,
                        keycloak_url=keycloak_bootstrap_url,
                        pg_host=postgres_bootstrap_host,
                        pg_port=postgres_bootstrap_port,
                    )
                    if not self.wait_for_keycloak_admin_ready(keycloak_url=keycloak_bootstrap_url):
                        print("Keycloak admin API not ready for connector provisioning retry")
                        return False
                    time.sleep(5)
        finally:
            self._stop_keycloak_bootstrap_access(keycloak_bootstrap_access)
            self._stop_postgres_bootstrap_access(postgres_bootstrap_access)
            self._stop_vault_bootstrap_access(vault_bootstrap_access)

        if create_result is None:
            print("Error: deployment failed")
            return False

        self.invalidate_management_api_token(connector_name)
        if not self.setup_minio_bucket(self.config.NS_COMMON, ds_name, connector_name, creds_path):
            print("Error: MinIO configuration failed")
            return False

        timeout = 10
        start = time.time()

        while not os.path.exists(values_file):
            if time.time() - start > timeout:
                print("Timeout waiting for values file generation")
                return False
            time.sleep(1)

        if not os.path.exists(values_file):
            print("Connector values file not found")
            return False

        connector_hostnames = connector_hostnames or [connector_name]
        self.update_connector_host_aliases(
            values_file,
            connector_hostnames,
            connector_name=connector_name,
            ds_name=ds_name,
            ds_namespace=ds_namespace,
        )
        self.update_connector_service_discovery(values_file, connector_name)
        self.update_connector_multicluster_common_service_endpoints(
            values_file,
            connector_name,
            ds_name=ds_name,
        )
        self.update_connector_layout_metadata(values_file, connector_name)
        self.update_connector_node_scheduling(values_file, connector_name)
        self.update_connector_public_ingress_config(values_file, connector_name)
        self.update_connector_model_observer_config(
            values_file,
            connector_name,
            ds_name=ds_name,
            ds_namespace=ds_namespace,
        )

        release_name = f"{connector_name}-{ds_name}"
        print(f"Deploying connector {connector_name}...")
        values_files = [os.path.basename(values_file)]
        local_image_override = self._local_connector_image_override_path()
        if local_image_override:
            values_files.append(local_image_override)
            print(f"Using local connector image overrides: {local_image_override}")
        explicit_image_override = self._explicit_connector_image_override_path()
        if explicit_image_override:
            values_files.append(explicit_image_override)
            print(f"Using explicit INESData connector image overrides: {explicit_image_override}")

        with self._temporary_connector_kubeconfig(connector_name):
            if not self._apply_connector_interface_branding_assets(connector_name, target_namespace):
                return False

            if not self.infrastructure.deploy_helm_release(
                release_name,
                target_namespace,
                values_files,
                cwd=self.config.connector_dir()
            ):
                print("Error deploying connector")
                return False

            rollout_timeout = max(int(getattr(self.config, "TIMEOUT_POD_WAIT", 120)), 180)
            if not self._wait_for_connector_deployments(
                connector_name,
                namespace=target_namespace,
                timeout=rollout_timeout,
            ):
                print("Timeout waiting for connector deployment rollout")
                return False

        print("\nCONNECTORS CREATED\n")
        return True

    def connector_is_healthy(self, connector_name, namespace):
        with self._temporary_connector_kubeconfig(connector_name):
            result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")
        if not result:
            return False

        for line in result.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            pod_name = parts[0]
            status = parts[2]
            if pod_name.startswith(connector_name):
                if status == "Running":
                    return True
                print(f"Connector pod unhealthy: {pod_name} ({status})")
                return False

        return False

    def connector_database_credentials_valid(self, connector_name):
        creds = self.load_connector_credentials(connector_name)
        if not creds:
            print(f"Connector credentials not found: {connector_name}")
            return False

        db_creds = creds.get("database", {})
        db_name = db_creds.get("name")
        db_user = db_creds.get("user")
        db_password = db_creds.get("passwd")
        pg_host, _, _ = self.config_adapter.get_pg_credentials()
        pg_port = self._pg_port()

        if not db_name or not db_user or not db_password:
            print(f"Incomplete database credentials for connector: {connector_name}")
            return False

        result = self.run_silent(
            f"PGPASSWORD={shlex.quote(str(db_password))} "
            f"psql -h {shlex.quote(str(pg_host))} -p {shlex.quote(str(pg_port))} "
            f"-U {shlex.quote(str(db_user))} -d {shlex.quote(str(db_name))} -t -A -c \"SELECT 1;\""
        )

        if result and result.strip() == "1":
            return True

        print(
            f"Connector database credentials are stale or invalid: {connector_name} "
            f"(database={db_name}, user={db_user})"
        )
        return False

    def validate_connectors_deployment(self, connectors):
        print("\n========================================")
        print("VALIDATING CONNECTOR DEPLOYMENT")
        print("========================================\n")

        namespace_outputs = []
        for namespace in self._all_connector_scan_namespaces():
            with self._temporary_namespace_kubeconfig(namespace):
                pods = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")
            if pods:
                namespace_outputs.append((namespace, pods))
        if not namespace_outputs:
            print("No pods found in namespace")
            return False

        failed = False
        for namespace, pods in namespace_outputs:
            for connector_name, pod_name, status in self._runtime_connector_rows_by_namespace(namespace):
                if status != "Running":
                    print(f"Connector pod not running: {pod_name} ({status}) in namespace {namespace}")
                    failed = True

        if failed:
            print("\nSome connectors are not running\n")
            for namespace, _pods in namespace_outputs:
                with self._temporary_namespace_kubeconfig(namespace):
                    self.run(f"kubectl get pods -n {namespace}", check=False)
            return False

        print("All connector pods are running\n")

        for connector in connectors:
            print(f"Checking HTTP availability: {connector}")
            if not self.wait_for_connector_ready(connector):
                print(f"Connector not reachable: {connector}")
                return False

            print(f"Checking Management API availability: {connector}")
            if not self.wait_for_management_api_ready(connector):
                print(f"Management API not reachable: {connector}")
                return False

        print("\nAll connectors reachable\n")
        return True

    def validate_connectors_with_stabilization(self, connectors, retries=2, wait_seconds=20, backoff_factor=2):
        """Retry connector validation after short stabilization waits with light backoff."""
        if self.validate_connectors_deployment(connectors):
            return True

        retries = max(int(retries or 0), 0)
        current_wait = max(int(wait_seconds or 0), 0)
        backoff_factor = max(int(backoff_factor or 1), 1)

        for attempt in range(1, retries + 1):
            print(
                f"\nConnector validation failed (attempt {attempt}/{retries + 1}). "
                f"Waiting {current_wait}s for stabilization before retry..."
            )
            if current_wait > 0:
                time.sleep(current_wait)
            if self.validate_connectors_deployment(connectors):
                print("Connector validation recovered after stabilization retry.")
                return True
            current_wait *= backoff_factor

        return False

    def show_connector_logs(self):
        connector_pods = []
        seen = set()
        dataspaces = self.load_dataspace_connectors() or []

        for dataspace in dataspaces:
            ds_name = str(dataspace.get("name") or "").strip()
            if not ds_name:
                continue
            for namespace in self._dataspace_connector_target_namespaces(dataspace, dataspaces=dataspaces):
                runtime_pods = self._runtime_connector_pods_by_namespace(namespace)
                if not runtime_pods:
                    continue
                discovered = self._discover_existing_connectors(
                    ds_name,
                    namespace,
                    include_runtime_artifacts=False,
                )
                for connector_name in sorted(discovered):
                    pod_name = runtime_pods.get(connector_name)
                    if not pod_name:
                        continue
                    key = (namespace, connector_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    connector_pods.append((namespace, connector_name, pod_name))

        if not connector_pods:
            for namespace in self._all_connector_scan_namespaces():
                runtime_pods = self._runtime_connector_pods_by_namespace(namespace)
                for connector_name, pod_name in runtime_pods.items():
                    key = (namespace, connector_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    connector_pods.append((namespace, connector_name, pod_name))

        if not connector_pods:
            print("No pods found in namespace")
            return

        print("Available connectors:\n")
        for i, (namespace, connector_name, pod_name) in enumerate(connector_pods, 1):
            print(f"{i} - {connector_name} ({namespace}) -> {pod_name}")

        choice = input("\nSelect connector for logs (number): ")
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(connector_pods):
            print("Invalid selection")
            return

        selected_namespace, _selected_connector, selected_pod = connector_pods[int(choice) - 1]
        follow = input("Follow logs in real-time? (Y/N): ").strip().upper()

        if follow == "Y":
            with self._temporary_namespace_kubeconfig(selected_namespace):
                self.run(f"kubectl logs -f {selected_pod} -n {selected_namespace}", check=False)
        else:
            with self._temporary_namespace_kubeconfig(selected_namespace):
                self.run(f"kubectl logs {selected_pod} -n {selected_namespace}", check=False)

    def deploy_connectors(self):
        print("\n========================================")
        print("DEPLOY CONNECTORS FROM CONFIG")
        print("========================================\n")

        repo_dir = self.config.repo_dir()
        python_exec = self.config.python_exec()

        if not os.path.exists(repo_dir):
            print("Repository not found. Run Level 2 first")
            return []

        if not os.path.exists(self.config.venv_path()):
            print("Python environment not found. Run Level 3 first")
            return []

        print("Ensuring INESData Python dependencies...")
        ensure_python_requirements(
            python_exec,
            self.config.repo_requirements_path(),
            label="INESData runtime",
        )

        dataspaces = self.load_dataspace_connectors()
        if not dataspaces:
            print("No dataspaces defined in deployer.config")
            return []

        first_namespace = dataspaces[0].get("namespace") or self.config.namespace_demo()
        local_image_namespaces = [first_namespace]
        if self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY:
            local_image_namespaces = []
            seen_namespaces = set()
            for ds in dataspaces:
                for target_namespace in self._dataspace_connector_target_namespaces(ds, dataspaces=dataspaces):
                    normalized_namespace = str(target_namespace or "").strip()
                    if not normalized_namespace or normalized_namespace in seen_namespaces:
                        continue
                    seen_namespaces.add(normalized_namespace)
                    local_image_namespaces.append(normalized_namespace)
            if not local_image_namespaces:
                local_image_namespaces = [first_namespace]

        if not self._prepare_level4_local_connector_images_for_namespaces(local_image_namespaces):
            return []

        all_connectors = set()
        infra_ready = False
        vault_ready = False
        reconciliation_mode = self._level4_connector_reconciliation_mode()
        if reconciliation_mode == "additive":
            print("Level 4 connector reconciliation mode: additive (existing connectors are preserved)")

        for ds in dataspaces:
            ds_name = ds["name"]
            namespace = ds["namespace"]
            connectors = ds["connectors"]
            target_namespaces = self._dataspace_connector_target_namespaces(ds, dataspaces=dataspaces)

            print(f"\nDataspace: {ds_name}")
            print(f"Namespace: {namespace}")
            if self._role_aligned_level4_namespaces_active(ds, dataspaces=dataspaces):
                print(f"Target connector namespaces: {target_namespaces}")
            print(f"Connectors defined: {connectors}\n")

            desired = set(connectors or [])
            existing_namespaces = {}
            for target_namespace in target_namespaces:
                for connector_name in self._discover_existing_connectors(
                    ds_name,
                    target_namespace,
                    include_runtime_artifacts=False,
                ):
                    existing_namespaces.setdefault(connector_name, target_namespace)
            stale = sorted(set(existing_namespaces) - desired)
            if stale:
                if reconciliation_mode == "additive":
                    print(
                        f"Preserving connectors not listed in this Level 4 additive run "
                        f"for dataspace '{ds_name}': {stale}"
                    )
                else:
                    print(f"Found stale connectors for dataspace '{ds_name}': {stale}")
                    if not infra_ready:
                        if not self._ensure_local_runtime_access_if_required():
                            return []
                        infra_ready = True
                    if not vault_ready:
                        if not self.infrastructure.ensure_vault_unsealed():
                            return []
                        vault_ready = True
                    if not self._prepare_vault_management_access(ds_name=ds_name):
                        return []
                    cleanup_bootstrap_access = None
                    if self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY:
                        cleanup_bootstrap_access = self._start_level4_connector_bootstrap_access()
                        if cleanup_bootstrap_access is None:
                            return []
                        if not self._ensure_level4_keycloak_ready(cleanup_bootstrap_access, "cleanup"):
                            self._stop_level4_connector_bootstrap_access(cleanup_bootstrap_access)
                            return []
                    try:
                        for stale_connector in stale:
                            stale_namespace = existing_namespaces.get(stale_connector) or namespace
                            cleanup_kwargs = {"namespace": stale_namespace}
                            if cleanup_bootstrap_access:
                                cleanup_kwargs.update(
                                    dataspace=ds,
                                    kubeconfig_role=self._namespace_kubeconfig_role(
                                        stale_namespace,
                                        dataspace=ds,
                                    ),
                                    vault_url=cleanup_bootstrap_access.get("vault_url"),
                                    keycloak_url=cleanup_bootstrap_access.get("keycloak_url"),
                                    pg_host=cleanup_bootstrap_access.get("pg_host"),
                                    pg_port=cleanup_bootstrap_access.get("pg_port"),
                                )
                            self._cleanup_connector_state(
                                stale_connector,
                                repo_dir,
                                ds_name,
                                python_exec,
                                **cleanup_kwargs,
                            )
                    finally:
                        self._stop_level4_connector_bootstrap_access(cleanup_bootstrap_access)

            for connector in connectors:
                all_connectors.add(connector)
                target_namespace = self._connector_target_namespace(
                    connector,
                    dataspace=ds,
                    dataspaces=dataspaces,
                )

                if self.connector_already_exists(connector, target_namespace):
                    if (
                        reconciliation_mode != "additive"
                        and self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY
                    ):
                        print("Recreating connector to ensure a clean vm-distributed Level 4 deployment")
                    elif (
                        self.connector_is_healthy(connector, target_namespace)
                        and self.connector_database_credentials_valid(connector)
                    ):
                        print(f"Connector already running: {connector}")
                        if reconciliation_mode == "additive":
                            print("Preserving existing connector in additive Level 4 mode")
                            continue
                        print("Recreating connector to ensure a clean Level 4 deployment")
                    else:
                        print(
                            f"Connector exists but is unhealthy or stale. Recreating: {connector} "
                            f"in namespace {target_namespace}"
                        )

                print(f"Deploying connector: {connector}")
                values_file = self.config.connector_values_file(connector)
                if not self.create_connector(connector, connectors):
                    print(f"Aborting Level 4 because connector recreation failed: {connector}")
                    return []

                if not os.path.exists(values_file):
                    print(f"Values file not found: {values_file}")
                    return []

        all_connectors = list(all_connectors)
        print("\nAll connectors deployed or already existing\n")
        if self._is_local_topology():
            print("Configuring connector hosts...")
            connector_hosts = self.config_adapter.generate_connector_hosts(all_connectors)
            self.infrastructure.manage_hosts_entries(connector_hosts)
        else:
            print(f"Skipping connector hosts synchronization for topology '{self.config_adapter.topology}'.")
        if not self.wait_for_all_connectors(all_connectors):
            print("Aborting Level 4 because connector interface readiness failed")
            return []
        if self._normalized_topology() == VM_SINGLE_TOPOLOGY and not self.validate_connectors_with_stabilization(
            all_connectors,
            retries=1,
            wait_seconds=30,
        ):
            print("Aborting Level 4 because connector Management API readiness failed")
            return []
        return all_connectors

    def get_cluster_connectors(self):
        connectors = set()
        dataspaces = self.load_dataspace_connectors() or []
        configured_order = []
        validation_order = []

        for dataspace in dataspaces:
            ds_name = str(dataspace.get("name") or "").strip()
            if not ds_name:
                continue
            for pair in dataspace.get("validation_pairs") or []:
                for key in ("provider", "consumer"):
                    connector = pair.get(key) if isinstance(pair, dict) else None
                    if connector and connector not in validation_order:
                        validation_order.append(connector)
                if validation_order:
                    break
            for connector in dataspace.get("connectors") or []:
                if connector and connector not in configured_order:
                    configured_order.append(connector)
            for namespace in self._dataspace_connector_target_namespaces(dataspace, dataspaces=dataspaces):
                connectors.update(
                    self._discover_existing_connectors(
                        ds_name,
                        namespace,
                        include_runtime_artifacts=False,
                    )
                )

        if connectors:
            ordered = [connector for connector in validation_order if connector in connectors]
            ordered.extend(
                connector
                for connector in configured_order
                if connector in connectors and connector not in ordered
            )
            ordered.extend(sorted(connectors - set(ordered)))
            return ordered

        for namespace in self._all_connector_scan_namespaces():
            with self._temporary_namespace_kubeconfig(namespace):
                output = self.run(f"kubectl get pods -n {namespace} --no-headers", capture=True)
            if not output:
                continue
            for line in output.splitlines():
                parts = line.split()
                if not parts:
                    continue
                name = parts[0]
                if self._is_connector_runtime_pod(name):
                    connectors.add("-".join(name.split("-")[:3]))

        return sorted(connectors)

    def describe(self) -> str:
        return "INESDataConnectorsAdapter contains connector logic for INESData."
