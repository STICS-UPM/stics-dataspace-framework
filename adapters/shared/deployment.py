from contextlib import contextmanager
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import requests
import yaml

from adapters.shared.config import resolve_shared_level3_bootstrap_runtime
from deployers.shared.lib.cluster_runtime import build_cluster_runtime
from deployers.shared.lib.connectors import parse_connector_list
from deployers.shared.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    build_topology_profile,
    normalize_topology,
)
from deployers.shared.lib.vm_distributed_public_access import resolve_vm_distributed_public_urls
from runtime_dependencies import ensure_python_requirements


class SharedDataspaceDeploymentAdapter:
    """Neutral Level 3 deployment flow reused by multiple adapters."""

    def __init__(self, run, run_silent, auto_mode_getter, infrastructure_adapter, config_adapter, config_cls):
        self.run = run
        self.run_silent = run_silent
        self.auto_mode_getter = auto_mode_getter
        self.infrastructure = infrastructure_adapter
        self.config = config_cls
        self.config_adapter = config_adapter

    def _auto_mode(self):
        return self.auto_mode_getter() if callable(self.auto_mode_getter) else bool(self.auto_mode_getter)

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

    def _dataspace_namespace(self):
        namespace_getter = getattr(self.config, "namespace_demo", None)
        if callable(namespace_getter):
            namespace = namespace_getter()
            if namespace:
                return namespace
        return self._dataspace_name()

    def _registration_service_namespace(self):
        config_namespace_getter = getattr(self.config, "registration_service_namespace", None)
        if callable(config_namespace_getter):
            namespace = config_namespace_getter()
            if namespace:
                return str(namespace).strip()
        namespace_getter = getattr(self.config_adapter, "primary_registration_service_namespace", None)
        if callable(namespace_getter):
            try:
                namespace = namespace_getter()
            except Exception:
                namespace = None
            if namespace:
                return str(namespace).strip()
        return self._dataspace_namespace()

    def _common_services_namespace(self):
        return str(getattr(self.config, "NS_COMMON", "common-srvs") or "common-srvs").strip() or "common-srvs"

    def _public_portal_namespace(self):
        return self._registration_service_namespace()

    def _public_portal_enabled(self):
        enabled_getter = getattr(self.config, "deploy_public_portal_with_dataspace", None)
        if not callable(enabled_getter):
            return False
        return bool(enabled_getter())

    def _dataspace_runtime_dir(self):
        bootstrap_runtime = resolve_shared_level3_bootstrap_runtime(self.config) or {}
        if bootstrap_runtime.get("runtime_dir"):
            return bootstrap_runtime["runtime_dir"]
        return os.path.join(self.config.repo_dir(), "deployments", "DEV", self._dataspace_name())

    def _normalized_topology(self):
        topology = normalize_topology(
            getattr(self.config_adapter, "topology", None)
            or getattr(self, "topology", None)
            or os.environ.get("PIONERA_TOPOLOGY")
            or LOCAL_TOPOLOGY
        )
        return topology

    def _bootstrap_environment_prefix(self, pg_host=None, pg_port=None):
        prefix = f"PIONERA_TOPOLOGY={shlex.quote(self._normalized_topology())} "
        if pg_host:
            prefix += f"PIONERA_PG_HOST={shlex.quote(str(pg_host))} "
        if pg_port:
            prefix += f"PIONERA_PG_PORT={shlex.quote(str(pg_port))} "
        return prefix

    @contextmanager
    def _temporary_level3_postgres_environment(self, pg_host=None, pg_port=None):
        updates = {}
        if pg_host:
            updates["PIONERA_PG_HOST"] = str(pg_host)
        if pg_port:
            updates["PIONERA_PG_PORT"] = str(pg_port)

        previous = {key: os.environ.get(key) for key in updates}
        try:
            for key, value in updates.items():
                os.environ[key] = value
            yield
        finally:
            for key, old_value in previous.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value

    @staticmethod
    def _normalized_http_url(value):
        normalized = str(value or "").strip().rstrip("/")
        if not normalized:
            return ""
        if not normalized.startswith(("http://", "https://")):
            normalized = f"http://{normalized}"
        return normalized

    @staticmethod
    def _public_url_host_path(value):
        normalized = str(value or "").strip().rstrip("/")
        if not normalized:
            return "", ""
        parsed = urlparse(normalized)
        host = parsed.hostname or ""
        path = (parsed.path or "").rstrip("/")
        return host, path

    def _keycloak_runtime_url(self, config):
        public_urls = resolve_vm_distributed_public_urls(config or {})
        for raw_url in (
            (config or {}).get("KC_MANAGEMENT_URL"),
            (config or {}).get("KEYCLOAK_FRONTEND_URL"),
            (config or {}).get("KEYCLOAK_PUBLIC_URL"),
            public_urls.get("KEYCLOAK_FRONTEND_URL"),
            public_urls.get("KEYCLOAK_PUBLIC_URL"),
            (config or {}).get("KC_INTERNAL_URL"),
            (config or {}).get("KC_URL"),
        ):
            normalized = self._normalized_http_url(raw_url)
            if normalized:
                return normalized
        return ""

    def _bootstrap_dataspace_command(self, action, dataspace=None, pg_host=None, pg_port=None):
        runtime = resolve_shared_level3_bootstrap_runtime(self.config) or {}
        command_getter = runtime.get("bootstrap_dataspace_command")
        resolved_dataspace = dataspace or self._dataspace_name()
        if callable(command_getter):
            return command_getter(action, dataspace=resolved_dataspace)
        return (
            f"{self._bootstrap_environment_prefix(pg_host=pg_host, pg_port=pg_port)}"
            f"{shlex.quote(self.config.python_exec())} bootstrap.py "
            f"dataspace {shlex.quote(str(action))} {shlex.quote(str(resolved_dataspace))}"
        )

    def _adapter_name(self):
        adapter_name_getter = getattr(self.config, "adapter_name", None)
        if callable(adapter_name_getter):
            adapter_name = adapter_name_getter()
            if adapter_name:
                return str(adapter_name).strip().lower()
        return str(getattr(self.config, "ADAPTER_NAME", "inesdata") or "inesdata").strip().lower()

    def _safe_remove_runtime_dir(self, runtime_dir):
        if not runtime_dir:
            return False

        script_dir_getter = getattr(self.config, "script_dir", None)
        if not callable(script_dir_getter):
            return False

        deployments_root = os.path.abspath(
            os.path.join(script_dir_getter(), "deployers", self._adapter_name(), "deployments")
        )
        runtime_root = os.path.abspath(runtime_dir)
        if runtime_root == deployments_root or not runtime_root.startswith(deployments_root + os.sep):
            print(f"Skipping runtime cleanup outside managed deployments root: {runtime_dir}")
            return False

        if os.path.exists(runtime_root):
            shutil.rmtree(runtime_root)
            print(f"Removed generated dataspace runtime artifacts: {runtime_root}")
            return True
        return False

    def _validate_recreate_namespace(self, namespace):
        normalized = str(namespace or "").strip()
        forbidden = {
            "",
            "default",
            "kube-system",
            "kube-public",
            "kube-node-lease",
            "components",
            str(getattr(self.config, "NS_COMMON", "common-srvs") or "common-srvs").strip(),
        }
        if normalized in forbidden:
            raise RuntimeError(
                f"Refusing to recreate dataspace in protected namespace '{normalized}'. "
                "Use an isolated dataspace namespace."
            )
        return normalized

    def _wait_for_namespace_deleted(self, namespace, timeout=120, poll_interval=3):
        deadline = time.time() + timeout
        namespace_q = shlex.quote(namespace)
        while time.time() <= deadline:
            output = self.run_silent(f"kubectl get namespace {namespace_q} --no-headers")
            if not output:
                return True
            time.sleep(poll_interval)
        return False

    def build_recreate_dataspace_plan(self):
        ds_name = self._dataspace_name()
        namespace = self._registration_service_namespace()
        helm_releases = [self.config.helm_release_rs()]
        public_portal_release_getter = getattr(self.config, "helm_release_public_portal", None)
        if self._public_portal_enabled() and callable(public_portal_release_getter):
            helm_releases.append(public_portal_release_getter())
        return {
            "status": "planned",
            "adapter": self._adapter_name(),
            "dataspace": ds_name,
            "namespace": namespace,
            "runtime_dir": self._dataspace_runtime_dir(),
            "helm_releases": helm_releases,
            "actions": [
                "uninstall_dataspace_helm_releases",
                "delete_dataspace_namespace",
                "delete_dataspace_bootstrap_state",
                "remove_generated_runtime_artifacts",
                "run_level_3_again",
            ],
            "preserves_shared_services": True,
            "shared_services_namespace": getattr(self.config, "NS_COMMON", "common-srvs"),
            "invalidates_level_4_connectors": True,
        }

    def _cleanup_dataspace_before_recreate(self):
        ds_name = self._dataspace_name()
        namespace = self._validate_recreate_namespace(self._registration_service_namespace())
        helm_releases = [self.config.helm_release_rs()]
        public_portal_release_getter = getattr(self.config, "helm_release_public_portal", None)
        if self._public_portal_enabled() and callable(public_portal_release_getter):
            helm_releases.append(public_portal_release_getter())
        bootstrap_runtime = resolve_shared_level3_bootstrap_runtime(self.config) or {}
        repo_dir = bootstrap_runtime.get("repo_dir") or self.config.repo_dir()
        runtime_dir = self._dataspace_runtime_dir()

        print("\nCleaning existing dataspace Kubernetes resources...")
        for helm_release in helm_releases:
            self.run(
                f"helm uninstall {shlex.quote(helm_release)} -n {shlex.quote(namespace)}",
                check=False,
            )
        self.run(
            f"kubectl delete namespace {shlex.quote(namespace)} --ignore-not-found=true",
            check=False,
        )
        if not self._wait_for_namespace_deleted(namespace):
            raise RuntimeError(f"Timed out waiting for namespace '{namespace}' to be deleted")

        print("\nCleaning existing dataspace bootstrap state...")
        bootstrap_script = bootstrap_runtime.get("bootstrap_script") or os.path.join(repo_dir, "bootstrap.py")
        if os.path.exists(bootstrap_script):
            self.run(
                self._bootstrap_dataspace_command("delete", dataspace=ds_name),
                cwd=repo_dir,
                check=False,
            )
        else:
            print(f"Bootstrap script not found at {bootstrap_script}; skipping bootstrap delete.")

        self._safe_remove_runtime_dir(runtime_dir)

    def recreate_dataspace(self, confirm_dataspace=None):
        ds_name = self._dataspace_name()
        if str(confirm_dataspace or "").strip() != ds_name:
            raise RuntimeError(
                f"Dataspace recreation requires explicit confirmation with the exact dataspace name '{ds_name}'."
            )

        plan = self.build_recreate_dataspace_plan()
        print("\n========================================")
        print("RECREATE DATASPACE")
        print("========================================")
        print(f"Adapter: {plan['adapter']}")
        print(f"Dataspace: {plan['dataspace']}")
        print(f"Namespace: {plan['namespace']}")
        print("Shared services will be preserved.")
        print("Level 4 connectors for this dataspace will be invalidated.\n")

        self._cleanup_dataspace_before_recreate()
        return self.deploy_dataspace()

    def _deployer_config(self):
        load_config = getattr(self.config_adapter, "load_deployer_config", None)
        if callable(load_config):
            try:
                return dict(load_config() or {})
            except Exception:
                return {}
        return {}

    def _cluster_runtime(self, topology):
        runtime_getter = getattr(self.config_adapter, "cluster_runtime", None)
        if callable(runtime_getter):
            try:
                runtime = dict(runtime_getter() or {})
            except Exception:
                runtime = {}
            if runtime:
                return runtime
        return build_cluster_runtime(self._deployer_config(), topology=topology)

    def _vm_distributed_role_kubeconfig(self, role):
        runtime = self._cluster_runtime(VM_DISTRIBUTED_TOPOLOGY)
        normalized_role = str(role or "common").strip().lower() or "common"
        key_by_role = {
            "common": "k3s_kubeconfig_common",
            "provider": "k3s_kubeconfig_provider",
            "consumer": "k3s_kubeconfig_consumer",
            "components": "k3s_kubeconfig_components",
        }
        key = key_by_role.get(normalized_role, "k3s_kubeconfig_common")
        kubeconfig = str(runtime.get(key) or runtime.get("k3s_kubeconfig") or "").strip()
        return os.path.abspath(os.path.expanduser(kubeconfig)) if kubeconfig else ""

    @contextmanager
    def _temporary_kubeconfig_role(self, role):
        kubeconfig = self._vm_distributed_role_kubeconfig(role)
        if not kubeconfig:
            yield
            return

        normalized_role = str(role or "common").strip().lower() or "common"
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

    @staticmethod
    def _reserve_local_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.getsockname()[1]

    def _start_level3_postgres_access(self, topology):
        if normalize_topology(topology) != VM_DISTRIBUTED_TOPOLOGY:
            return {"pg_host": None, "pg_port": None, "port_forward": None}

        port_forward_service = getattr(self.infrastructure, "port_forward_service", None)
        if not callable(port_forward_service):
            print("PostgreSQL Level 3 bootstrap access is not available: port-forward helper is missing.")
            return None

        deployer_config = self._deployer_config()
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

        local_port = self._reserve_local_port()
        with self._temporary_kubeconfig_role("common"):
            opened = port_forward_service(namespace, pattern, local_port, remote_port, quiet=True)

        if not opened:
            issue = str(getattr(self.infrastructure, "_last_port_forward_error", "") or "").strip()
            detail = f" Last port-forward issue: {issue}" if issue else ""
            print(
                "PostgreSQL Level 3 bootstrap access failed: could not open a temporary "
                f"port-forward to {pattern} in namespace {namespace}.{detail}"
            )
            return None

        print(
            "Using temporary local PostgreSQL port-forward for Level 3 bootstrap commands "
            f"({pattern}.{namespace} -> 127.0.0.1:{local_port})."
        )
        return {
            "pg_host": "127.0.0.1",
            "pg_port": str(local_port),
            "port_forward": {
                "namespace": namespace,
                "pattern": pattern,
                "kubeconfig_role": "common",
            },
        }

    def _stop_level3_postgres_access(self, postgres_access):
        port_forward = (postgres_access or {}).get("port_forward")
        if not port_forward:
            return

        stop_port_forward_service = getattr(self.infrastructure, "stop_port_forward_service", None)
        if not callable(stop_port_forward_service):
            return

        with self._temporary_kubeconfig_role(port_forward.get("kubeconfig_role") or "common"):
            stop_port_forward_service(
                port_forward["namespace"],
                port_forward["pattern"],
                quiet=True,
            )

    @staticmethod
    def _env_flag_enabled(name, default=True):
        raw_value = str(os.environ.get(name, "")).strip().lower()
        if not raw_value:
            return default
        return raw_value not in {"0", "false", "no", "off", "disabled"}

    @staticmethod
    def _k3s_image_pull_timeout_seconds():
        raw_value = str(os.environ.get("PIONERA_K3S_IMAGE_PULL_TIMEOUT", "1800")).strip()
        try:
            timeout = int(raw_value)
        except ValueError:
            timeout = 1800
        return max(timeout, 60)

    def _should_prepull_level3_images(self, topology):
        normalized_topology = normalize_topology(topology)
        if normalized_topology != VM_SINGLE_TOPOLOGY:
            return False
        if not self._env_flag_enabled("PIONERA_K3S_LEVEL3_IMAGE_PREPULL", default=True):
            return False
        cluster_type = str(
            self._cluster_runtime(normalized_topology).get("cluster_type") or "minikube"
        ).strip().lower()
        return cluster_type == "k3s"

    @staticmethod
    def _nested_dict_value(values, path):
        current = values
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @classmethod
    def _image_reference_from_values(cls, values, image_path):
        image_values = cls._nested_dict_value(values, image_path)
        if not isinstance(image_values, dict):
            return ""
        image_name = str(image_values.get("name") or "").strip()
        image_tag = str(image_values.get("tag") or "").strip()
        if not image_name:
            return ""
        if not image_tag:
            return image_name
        return f"{image_name}:{image_tag}"

    @classmethod
    def _level3_image_references_from_values_file(cls, values_file):
        try:
            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle) or {}
        except OSError as exc:
            raise RuntimeError(f"Could not read Level 3 values file '{values_file}': {exc}") from exc
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Could not parse Level 3 values file '{values_file}': {exc}") from exc

        image_paths = [
            ("registration", "image"),
            ("backend", "image"),
            ("frontend", "image"),
        ]
        images = []
        for image_path in image_paths:
            image = cls._image_reference_from_values(values, image_path)
            if image and image not in images:
                images.append(image)
        return images

    def _prepull_k3s_image(self, image, timeout_seconds):
        print(f"Pre-pulling Level 3 image into k3s: {image}")
        try:
            result = subprocess.run(
                ["sudo", "-n", "k3s", "crictl", "pull", image],
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Timed out after {timeout_seconds}s while pre-pulling Level 3 image '{image}' into k3s. "
                "Check registry connectivity, image availability, and node disk space."
            ) from exc

        if result.returncode == 0:
            return

        root_cause = (result.stderr or result.stdout or "").strip() or f"crictl exited with code {result.returncode}"
        if self._can_prompt_for_sudo_password() and self._sudo_failure_needs_password(root_cause):
            print("Level 3 k3s image pre-pull needs sudo password; retrying with an interactive prompt.")
            try:
                retry = subprocess.run(
                    ["sudo", "k3s", "crictl", "pull", image],
                    text=True,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Timed out after {timeout_seconds}s while pre-pulling Level 3 image '{image}' into k3s. "
                    "Check registry connectivity, image availability, and node disk space."
                ) from exc
            if retry.returncode == 0:
                return
            root_cause = f"interactive sudo retry exited with code {retry.returncode}"

        self._fail(
            f"Could not pre-pull Level 3 image '{image}' into k3s",
            root_cause=root_cause,
        )

    def _can_prompt_for_sudo_password(self):
        return (not self._auto_mode()) and getattr(sys.stdin, "isatty", lambda: False)()

    @staticmethod
    def _sudo_failure_needs_password(message):
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        markers = (
            "a password is required",
            "password is required",
            "a terminal is required",
            "no tty present",
            "no password was provided",
        )
        return any(marker in normalized for marker in markers)

    def _prepull_level3_k3s_images_if_needed(self, topology, values_files):
        if not self._should_prepull_level3_images(topology):
            return

        images = []
        for values_file in values_files:
            for image in self._level3_image_references_from_values_file(values_file):
                if image not in images:
                    images.append(image)

        if not images:
            print("No Level 3 images were found in Helm values; skipping k3s image pre-pull.")
            return

        timeout_seconds = self._k3s_image_pull_timeout_seconds()
        print("\nPreparing Level 3 container images for k3s before Helm deployment...")
        for image in images:
            self._prepull_k3s_image(image, timeout_seconds)
        print("Level 3 k3s image pre-pull completed.")

    def _prepare_level3_local_dataspace_images(self, *, topology, namespace, dataspace):
        del topology, namespace, dataspace
        return True

    def _level3_local_dataspace_images_prepared(self):
        return False

    def _level3_registration_values_files(self, values_file):
        return values_file

    def _level3_public_portal_values_files(self, values_file):
        return values_file

    def _host_alias_ip_for_topology(self, topology):
        normalized_topology = normalize_topology(topology)
        cluster_type = str(self._cluster_runtime(normalized_topology).get("cluster_type") or "minikube").strip().lower()
        if normalized_topology == LOCAL_TOPOLOGY or cluster_type == "minikube":
            return self.run("minikube ip", capture=True) or getattr(self.config, "MINIKUBE_IP", "")

        if normalized_topology == VM_SINGLE_TOPOLOGY and cluster_type == "k3s":
            profile = build_topology_profile(VM_SINGLE_TOPOLOGY, self._deployer_config())
            return str(profile.ingress_external_ip or profile.default_address or "").strip()

        if normalized_topology == VM_DISTRIBUTED_TOPOLOGY and cluster_type == "k3s":
            profile = build_topology_profile(VM_DISTRIBUTED_TOPOLOGY, self._deployer_config())
            return str(profile.ingress_external_ip or profile.default_address or "").strip()

        return ""

    def update_helm_values_with_host_aliases(self, values_file, minikube_ip=None, topology=None):
        host_alias_ip = minikube_ip or self._host_alias_ip_for_topology(
            topology
            or getattr(self.config_adapter, "topology", None)
            or getattr(self, "topology", None)
            or LOCAL_TOPOLOGY
        )
        if not host_alias_ip:
            self._fail(
                "Could not resolve registration-service hostAliases IP",
                root_cause="check topology address and cluster runtime configuration",
            )

        with open(values_file) as f:
            values = yaml.safe_load(f)

        host_alias_domains = getattr(self.config_adapter, "host_alias_domains", None)
        if callable(host_alias_domains):
            hostnames = host_alias_domains(
                ds_name=self._dataspace_name(),
                ds_namespace=self._dataspace_namespace(),
            )
        else:
            hostnames = self.config.host_alias_domains()

        values["hostAliases"] = [{
            "ip": host_alias_ip,
            "hostnames": hostnames
        }]

        with open(values_file, "w") as f:
            yaml.dump(values, f, sort_keys=False)

    @staticmethod
    def _ensure_nested_dict(parent, key):
        value = parent.get(key)
        if isinstance(value, dict):
            return value
        value = {}
        parent[key] = value
        return value

    @staticmethod
    def _namespace_role_value(roles, field, default=""):
        if isinstance(roles, dict):
            return str(roles.get(field) or default or "").strip()
        return str(getattr(roles, field, default) or default or "").strip()

    def _dataspace_index(self, ds_name, ds_namespace):
        index_getter = getattr(self.config_adapter, "dataspace_index", None)
        if callable(index_getter):
            try:
                return int(index_getter(ds_name, ds_namespace))
            except (TypeError, ValueError):
                return 1
        return 1

    def _configured_dataspace_connector_names(self, ds_name=None, ds_namespace=None):
        config = self._deployer_config()
        resolved_ds_name = str(ds_name or self._dataspace_name()).strip() or self._dataspace_name()
        resolved_ds_namespace = str(ds_namespace or self._dataspace_namespace()).strip() or self._dataspace_namespace()
        ds_index = self._dataspace_index(resolved_ds_name, resolved_ds_namespace)
        raw_connectors = str(config.get(f"DS_{ds_index}_CONNECTORS") or "").strip()
        if not raw_connectors and ds_index != 1:
            raw_connectors = str(config.get("DS_1_CONNECTORS") or "").strip()

        return parse_connector_list(raw_connectors, resolved_ds_name)

    def _connector_namespace_for_public_portal(self, connector_name, ds_name=None, ds_namespace=None):
        resolved_ds_name = str(ds_name or self._dataspace_name()).strip() or self._dataspace_name()
        resolved_ds_namespace = str(ds_namespace or self._dataspace_namespace()).strip() or self._dataspace_namespace()
        ds_index = self._dataspace_index(resolved_ds_name, resolved_ds_namespace)
        namespace_plan_getter = getattr(self.config_adapter, "namespace_plan_for_dataspace", None)
        if not callable(namespace_plan_getter):
            return resolved_ds_namespace

        try:
            namespace_plan = namespace_plan_getter(
                ds_name=resolved_ds_name,
                ds_namespace=resolved_ds_namespace,
                ds_index=ds_index,
            )
        except Exception:
            return resolved_ds_namespace

        runtime_roles = namespace_plan.get("namespace_roles", {}) if isinstance(namespace_plan, dict) else {}
        provider_namespace = self._namespace_role_value(
            runtime_roles,
            "provider_namespace",
            resolved_ds_namespace,
        )
        del connector_name
        return provider_namespace or resolved_ds_namespace

    def _public_portal_connector_url(self, connector_name, port, ds_name=None, ds_namespace=None):
        portal_namespace = self._public_portal_namespace()
        connector_namespace = self._connector_namespace_for_public_portal(
            connector_name,
            ds_name=ds_name,
            ds_namespace=ds_namespace,
        )
        hostname = connector_name
        if connector_namespace and portal_namespace and connector_namespace != portal_namespace:
            hostname = f"{connector_name}.{connector_namespace}.svc.cluster.local"
        return f"http://{hostname}:{int(port)}"

    @staticmethod
    def _values_file_contains(values_file, token):
        try:
            with open(values_file, encoding="utf-8") as handle:
                return token in handle.read()
        except OSError:
            return False

    def update_public_portal_connector_endpoints(
        self,
        values_file,
        connector_name=None,
        ds_name=None,
        ds_namespace=None,
    ):
        with open(values_file, encoding="utf-8") as handle:
            values = yaml.safe_load(handle) or {}

        dataspace = values.get("dataspace") if isinstance(values.get("dataspace"), dict) else {}
        resolved_ds_name = str(ds_name or dataspace.get("name") or self._dataspace_name()).strip() or self._dataspace_name()
        resolved_ds_namespace = str(ds_namespace or self._dataspace_namespace()).strip() or self._dataspace_namespace()
        connectors = self._configured_dataspace_connector_names(resolved_ds_name, resolved_ds_namespace)
        resolved_connector = str(connector_name or (connectors[0] if connectors else "")).strip()
        if not resolved_connector:
            return False

        backend = self._ensure_nested_dict(values, "backend")
        catalog = self._ensure_nested_dict(backend, "catalog")
        vocabularies = self._ensure_nested_dict(backend, "vocabularies")
        catalog["connector"] = self._public_portal_connector_url(
            resolved_connector,
            19193,
            ds_name=resolved_ds_name,
            ds_namespace=resolved_ds_namespace,
        )
        vocabularies["connector"] = self._public_portal_connector_url(
            resolved_connector,
            19196,
            ds_name=resolved_ds_name,
            ds_namespace=resolved_ds_namespace,
        )

        with open(values_file, "w", encoding="utf-8") as handle:
            yaml.safe_dump(values, handle, sort_keys=False)
        return True

    def deploy_public_portal_if_configured(self, *, topology, update_minikube_host_aliases=True):
        if not self._public_portal_enabled():
            return False

        ensure_values_file = getattr(self.config, "ensure_public_portal_values_file", None)
        values_file_getter = getattr(self.config, "public_portal_values_file", None)
        values_file = (
            ensure_values_file(refresh=True)
            if callable(ensure_values_file)
            else values_file_getter()
            if callable(values_file_getter)
            else ""
        )
        if not values_file or not os.path.exists(values_file):
            self._fail("Public portal values file not found")

        if not self.update_public_portal_connector_endpoints(values_file):
            print("\nSkipping public portal deployment: no connector is configured for this dataspace.")
            return False

        if update_minikube_host_aliases:
            self.update_helm_values_with_host_aliases(values_file, topology=topology)

        if self._values_file_contains(values_file, "CHANGEME"):
            self._fail(
                "Public portal values still contain CHANGEME placeholders",
                root_cause="connector endpoints could not be reconciled from deployer.config",
            )

        public_portal_values_files = self._level3_public_portal_values_files(values_file)

        chart_dir_getter = getattr(self.config, "public_portal_dir", None)
        release_getter = getattr(self.config, "helm_release_public_portal", None)
        if not callable(chart_dir_getter) or not callable(release_getter):
            self._fail("Public portal deployment helpers are not available")

        chart_dir = chart_dir_getter()
        if not os.path.exists(chart_dir):
            self._fail("Public portal chart directory not found", root_cause=chart_dir)

        if not self._level3_local_dataspace_images_prepared():
            self._prepull_level3_k3s_images_if_needed(topology, [values_file])

        print("\nDeploying public portal...")
        if not self.infrastructure.deploy_helm_release(
            release_getter(),
            self._public_portal_namespace(),
            public_portal_values_files,
            cwd=chart_dir,
            timeout_seconds=300,
        ):
            self._fail("Error deploying public portal")
        if normalize_topology(topology) == VM_DISTRIBUTED_TOPOLOGY:
            self._sync_vm_distributed_public_portal_backend_path_ingress()
        return True

    def _vm_distributed_public_portal_backend_path_ingress(self):
        config = self._deployer_config()
        resolved = {**config, **resolve_vm_distributed_public_urls(config)}
        public_url = (
            resolved.get("PUBLIC_PORTAL_BACKEND_PUBLIC_URL")
            or resolved.get("DATASPACE_PUBLIC_PORTAL_BACKEND_URL")
            or ""
        )
        host, path = self._public_url_host_path(public_url)
        if not host or path in {"", "/"}:
            return None

        ds_name = self._dataspace_name()
        namespace = self._public_portal_namespace()
        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": f"{ds_name}-public-portal-backend-public-path",
                "namespace": namespace,
                "annotations": {
                    "nginx.ingress.kubernetes.io/use-regex": "true",
                    "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
                },
                "labels": {
                    "app.kubernetes.io/managed-by": "validation-environment",
                    "app.kubernetes.io/part-of": "vm-distributed",
                    "app.kubernetes.io/route-kind": "public-path",
                },
            },
            "spec": {
                "ingressClassName": "nginx",
                "rules": [
                    {
                        "host": host,
                        "http": {
                            "paths": [
                                {
                                    "path": f"{path}(/|$)(.*)",
                                    "pathType": "ImplementationSpecific",
                                    "backend": {
                                        "service": {
                                            "name": f"{ds_name}-public-portal-backend",
                                            "port": {"number": 1337},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        }

    def _sync_vm_distributed_public_portal_backend_path_ingress(self):
        ingress = self._vm_distributed_public_portal_backend_path_ingress()
        if not ingress:
            print("vm-distributed public portal backend path ingress skipped: no path public URL configured.")
            return {"status": "skipped", "reason": "no-path-public-url"}

        fd, temp_path = tempfile.mkstemp(prefix="pionera-public-portal-backend-ingress-", suffix=".json")
        os.close(fd)
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(ingress, handle)
            with self._temporary_kubeconfig_role("common"):
                if self.run(f"kubectl apply -f {shlex.quote(temp_path)}", check=False) is None:
                    return {"status": "failed", "reason": "kubectl-apply-failed"}
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        route = ingress["spec"]["rules"][0]
        path = route["http"]["paths"][0]["path"]
        print(f"vm-distributed public portal backend path ingress synchronized: {route['host']}{path}")
        return {"status": "synced", "host": route["host"], "path": path}

    @staticmethod
    def _print_unique_lines(output):
        previous = None
        for line in output.splitlines():
            line = line.rstrip()
            if not line or line == previous:
                continue
            print(line)
            previous = line

    @staticmethod
    def _sql_literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    @staticmethod
    def _sql_identifier(value):
        return '"' + str(value).replace('"', '""') + '"'

    def _postgres_runtime(self, pg_host=None, pg_port=None):
        credentials_getter = getattr(self.config_adapter, "get_pg_credentials", None)
        if not callable(credentials_getter):
            return None

        configured_pg_host, pg_user, pg_password = credentials_getter()
        port_getter = getattr(self.config_adapter, "get_pg_port", None)
        configured_pg_port = port_getter() if callable(port_getter) else "5432"
        return {
            "host": str(pg_host or configured_pg_host or "localhost"),
            "port": str(pg_port or configured_pg_port or "5432"),
            "user": str(pg_user or "postgres"),
            "password": str(pg_password or ""),
        }

    def _run_postgres_admin_query(self, sql_text, pg_host=None, pg_port=None):
        runtime = self._postgres_runtime(pg_host=pg_host, pg_port=pg_port)
        if not runtime:
            self._fail("PostgreSQL cleanup is not configured for Level 3")

        env = os.environ.copy()
        env["PGPASSWORD"] = runtime["password"]
        return subprocess.run(
            [
                "psql",
                "-h",
                runtime["host"],
                "-p",
                runtime["port"],
                "-U",
                runtime["user"],
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
                "-c",
                sql_text,
            ],
            text=True,
            capture_output=True,
            env=env,
        )

    def _postgres_cleanup_residual_state(self, database_name, database_user, pg_host=None, pg_port=None):
        checks = [
            (
                "database",
                f"SELECT 1 FROM pg_database WHERE datname = {self._sql_literal(database_name)};",
            ),
            (
                "role",
                f"SELECT 1 FROM pg_roles WHERE rolname = {self._sql_literal(database_user)};",
            ),
        ]
        residual = []
        for label, sql_text in checks:
            result = self._run_postgres_admin_query(sql_text, pg_host=pg_host, pg_port=pg_port)
            if result.returncode != 0:
                root_cause = (result.stderr or result.stdout or "").strip() or f"psql exited with code {result.returncode}"
                self._fail("Could not verify PostgreSQL cleanup state", root_cause=root_cause)
            if result.stdout.strip():
                residual.append(label)
        return residual

    def _cleanup_postgres_database_and_role_directly(self, database_name, database_user, pg_host=None, pg_port=None):
        statements = [
            (
                "terminate active sessions",
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                f"WHERE datname = {self._sql_literal(database_name)} "
                "AND pid <> pg_backend_pid();",
            ),
            (
                "drop database",
                f"DROP DATABASE IF EXISTS {self._sql_identifier(database_name)};",
            ),
            (
                "drop role",
                f"DROP ROLE IF EXISTS {self._sql_identifier(database_user)};",
            ),
        ]
        for label, sql_text in statements:
            result = self._run_postgres_admin_query(sql_text, pg_host=pg_host, pg_port=pg_port)
            if result.returncode != 0:
                root_cause = (result.stderr or result.stdout or "").strip() or f"psql exited with code {result.returncode}"
                self._fail(
                    f"PostgreSQL cleanup failed while trying to {label}",
                    root_cause=root_cause,
                )

    def _cleanup_level3_postgres_state(self, database_name, database_user, label, pg_host=None, pg_port=None):
        connectors = getattr(self, "connectors_adapter", None)
        cleanup_getter = getattr(connectors, "force_clean_postgres_db", None)
        if callable(cleanup_getter):
            if pg_host or pg_port:
                try:
                    cleanup_getter(database_name, database_user, pg_host=pg_host, pg_port=pg_port)
                except TypeError as exc:
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    cleanup_getter(database_name, database_user)
            else:
                cleanup_getter(database_name, database_user)

        residual = self._postgres_cleanup_residual_state(
            database_name,
            database_user,
            pg_host=pg_host,
            pg_port=pg_port,
        )
        if not residual:
            return

        print(
            f"PostgreSQL cleanup for {label} left residual state "
            f"({', '.join(residual)}). Reconciling directly..."
        )
        self._cleanup_postgres_database_and_role_directly(
            database_name,
            database_user,
            pg_host=pg_host,
            pg_port=pg_port,
        )
        residual = self._postgres_cleanup_residual_state(
            database_name,
            database_user,
            pg_host=pg_host,
            pg_port=pg_port,
        )
        if residual:
            self._fail(
                f"PostgreSQL cleanup did not remove previous {label} state",
                root_cause=f"{', '.join(residual)} still present for {database_name}/{database_user}",
            )

    def wait_for_keycloak_admin_ready(self, kc_url, kc_user, kc_password, timeout=120, poll_interval=3):
        print("Waiting for Keycloak admin authentication to become ready...")
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

    def restart_registration_service(self):
        deployment_name = f"{self._dataspace_name()}-registration-service"
        namespace = self._registration_service_namespace()

        print("\nRestarting registration-service deployment to pick up the recreated database credentials...")
        if self.run(
            f"kubectl rollout restart deployment/{deployment_name} -n {namespace}",
            check=False,
        ) is None:
            self._fail("Could not restart registration-service deployment")

        rollout_output = self.run(
            f"kubectl rollout status deployment/{deployment_name} -n {namespace} --timeout=180s",
            capture=True,
            check=False,
        )
        if rollout_output is None:
            self._fail("registration-service deployment did not finish rolling out")
        self._print_unique_lines(rollout_output)

    def _show_minikube_tunnel_prompt(self):
        print("-------------------------------------------------")
        print("MINIKUBE TUNNEL REQUIRED")
        print()
        print("Open a new terminal and run:")
        print()
        print("minikube tunnel")
        print()
        print("The tunnel must remain active during the dataspace deployment.")
        print("When logs start appearing in the tunnel terminal, Linux may require your password")
        print("even if no explicit prompt is shown. Type your password there and press ENTER.")
        print()
        print("Return to this terminal and press ENTER to continue after starting the tunnel.")
        print("-------------------------------------------------\n")

        if not self._auto_mode():
            input()
        else:
            print("[AUTO_MODE] Skipping tunnel confirmation\n")

    def _deploy_dataspace_runtime(
        self,
        *,
        topology=LOCAL_TOPOLOGY,
        require_tunnel_prompt=True,
        update_minikube_host_aliases=True,
    ):
        self.infrastructure.announce_level(3, "DATASPACE")
        normalized_topology = normalize_topology(topology)
        self.topology = normalized_topology

        if require_tunnel_prompt:
            self._show_minikube_tunnel_prompt()
        else:
            print(
                f"Topology '{normalized_topology}' uses an existing cluster ingress. "
                "Skipping Minikube tunnel prompt.\n"
            )

        bootstrap_runtime = resolve_shared_level3_bootstrap_runtime(self.config) or {}
        repo_dir = bootstrap_runtime.get("repo_dir") or self.config.repo_dir()
        ds_name = self._dataspace_name()
        python_exec = bootstrap_runtime.get("python_exec") or self.config.python_exec()

        if not os.path.exists(repo_dir):
            self._fail("Repository not found. Run Level 2 first")

        requires_local_runtime_access = normalized_topology == LOCAL_TOPOLOGY

        if requires_local_runtime_access and not self.infrastructure.ensure_local_infra_access():
            self._fail("Local access to PostgreSQL/Vault is not available")

        if not self.infrastructure.ensure_vault_unsealed():
            self._fail("Vault is not initialized or unsealed")

        reconcile_vault_state = getattr(self.infrastructure, "reconcile_vault_state_for_local_runtime", None)
        if requires_local_runtime_access and callable(reconcile_vault_state) and not reconcile_vault_state():
            self._fail("Vault token could not be synchronized with the shared local runtime")

        sync_common_credentials = getattr(self.infrastructure, "sync_common_credentials_from_kubernetes", None)
        if callable(sync_common_credentials):
            sync_common_credentials()

        print("Verifying Keycloak access...")
        deployer_config = self.config_adapter.load_deployer_config()
        kc_runtime_url = self._keycloak_runtime_url(deployer_config)
        kc_user = deployer_config.get("KC_USER")
        kc_password = deployer_config.get("KC_PASSWORD")

        if not kc_runtime_url:
            self._fail(
                "Keycloak URL not defined in deployer.config",
                root_cause=(
                    "set KC_MANAGEMENT_URL, KEYCLOAK_FRONTEND_URL, KEYCLOAK_PUBLIC_URL, "
                    "KC_INTERNAL_URL or KC_URL, then rerun Level 3"
                ),
            )
        if not kc_user or not kc_password:
            self._fail("KC_USER/KC_PASSWORD not defined in deployer.config")

        try:
            response = requests.get(f"{kc_runtime_url}/realms/master", timeout=5)
            if response.status_code not in (200, 302):
                self._fail(
                    "Keycloak not ready",
                    root_cause=(
                        f"unexpected HTTP status {response.status_code} from "
                        f"{kc_runtime_url}/realms/master"
                    ),
                )
        except Exception:
            self._fail("Keycloak not accessible. Verify ingress hostname resolution")

        if not self.wait_for_keycloak_admin_ready(kc_runtime_url, kc_user, kc_password):
            self._fail("Keycloak admin API not ready", root_cause="admin authentication did not succeed in time")

        if not os.path.exists(self.config.venv_path()):
            print("Creating Python environment...")
            self.run("python3 -m venv .venv", cwd=repo_dir)

        runtime_label = getattr(self.config, "RUNTIME_LABEL", "dataspace")
        quiet_requirements = bool(getattr(self.config, "QUIET_REQUIREMENTS_INSTALL", False))
        print(f"Ensuring {runtime_label} Python dependencies...")
        ensure_python_requirements(
            python_exec,
            bootstrap_runtime.get("requirements_path") or self.config.repo_requirements_path(),
            label=f"{runtime_label} runtime",
            quiet=quiet_requirements,
        )

        postgres_access = self._start_level3_postgres_access(normalized_topology)
        if postgres_access is None:
            self._fail(
                "PostgreSQL access is not available for Level 3",
                root_cause="could not create a temporary PostgreSQL port-forward for vm-distributed",
            )
        postgres_host = postgres_access.get("pg_host")
        postgres_port = postgres_access.get("pg_port")

        try:
            print("Cleaning previous databases...")
            self._cleanup_level3_postgres_state(
                self.config.registration_db_name(),
                self.config.registration_db_user(),
                "registration-service",
                pg_host=postgres_host,
                pg_port=postgres_port,
            )
            self._cleanup_level3_postgres_state(
                self.config.webportal_db_name(),
                self.config.webportal_db_user(),
                "web portal",
                pg_host=postgres_host,
                pg_port=postgres_port,
            )

            print("Creating dataspace...")
            quiet_deployer_output = bool(getattr(self.config, "QUIET_SENSITIVE_DEPLOYER_OUTPUT", False))
            create_result = self.run(
                self._bootstrap_dataspace_command(
                    "create",
                    dataspace=ds_name,
                    pg_host=postgres_host,
                    pg_port=postgres_port,
                ),
                cwd=repo_dir,
                capture=quiet_deployer_output,
                silent=quiet_deployer_output,
            )
            if create_result is None:
                self._fail("Error creating dataspace")
            if quiet_deployer_output:
                print("Dataspace bootstrap completed; sensitive deployer output suppressed")
        finally:
            self._stop_level3_postgres_access(postgres_access)

        ensure_values_file = getattr(self.config, "ensure_registration_values_file", None)
        values_file = (
            ensure_values_file(refresh=True)
            if callable(ensure_values_file)
            else self.config.registration_values_file()
        )
        if not os.path.exists(values_file):
            self._fail("Registration service values file not found")

        if not self._prepare_level3_local_dataspace_images(
            topology=normalized_topology,
            namespace=self._registration_service_namespace(),
            dataspace=ds_name,
        ):
            self._fail("Error preparing local Level 3 dataspace images")

        registration_values_files = self._level3_registration_values_files(values_file)

        if update_minikube_host_aliases:
            self.update_helm_values_with_host_aliases(values_file, topology=normalized_topology)

        if not self._level3_local_dataspace_images_prepared():
            self._prepull_level3_k3s_images_if_needed(normalized_topology, [values_file])

        print("\nDeploying registration-service...")
        if not self.infrastructure.deploy_helm_release(
            self.config.helm_release_rs(),
            self._registration_service_namespace(),
            registration_values_files,
            cwd=self.config.registration_service_dir()
        ):
            self._fail("Error deploying registration-service")

        self.restart_registration_service()
        public_portal_deployed = self.deploy_public_portal_if_configured(
            topology=normalized_topology,
            update_minikube_host_aliases=update_minikube_host_aliases,
        )

        if not self.infrastructure.wait_for_dataspace_level3_pods(
            self._registration_service_namespace(),
            dataspace_name=ds_name,
            include_public_portal=public_portal_deployed,
        ):
            self._fail("Timeout waiting for dataspace pods")

        readiness_postgres_access = self._start_level3_postgres_access(normalized_topology)
        if readiness_postgres_access is None:
            self._fail(
                "PostgreSQL access is not available for Level 3 readiness verification",
                root_cause="could not create a temporary PostgreSQL port-forward for vm-distributed",
            )
        try:
            with self._temporary_level3_postgres_environment(
                readiness_postgres_access.get("pg_host"),
                readiness_postgres_access.get("pg_port"),
            ):
                dataspace_ready, root_cause = self.infrastructure.verify_dataspace_ready_for_level4()
        finally:
            self._stop_level3_postgres_access(readiness_postgres_access)
        if not dataspace_ready:
            self._fail("Level 3 did not leave the dataspace ready for Level 4", root_cause=root_cause)

        self.infrastructure.complete_level(3)
        print("Next step: run Level 4 to deploy or update the connectors for this dataspace.")

    def deploy_dataspace(self):
        return self._deploy_dataspace_runtime()

    def deploy_dataspace_for_topology(self, topology=LOCAL_TOPOLOGY):
        normalized_topology = normalize_topology(topology)
        if normalized_topology == LOCAL_TOPOLOGY:
            return self.deploy_dataspace()
        if normalized_topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
            raise RuntimeError(
                f"Level 3 deploy_dataspace_for_topology() is not implemented for topology "
                f"'{normalized_topology}' yet."
            )
        result = self._deploy_dataspace_runtime(
            topology=normalized_topology,
            require_tunnel_prompt=False,
            update_minikube_host_aliases=normalized_topology in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY},
        )
        if normalized_topology == VM_DISTRIBUTED_TOPOLOGY:
            sync_routing = getattr(self.infrastructure, "sync_vm_distributed_routing", None)
            if callable(sync_routing):
                sync_routing()
        return result
