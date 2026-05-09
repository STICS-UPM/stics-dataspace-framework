import json
import os
import shutil
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import requests

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
from tabulate import tabulate

from deployers.infrastructure.lib.public_hostnames import (
    canonical_common_service_config_values,
    canonical_common_service_hostnames,
)
from deployers.shared.lib.cluster_runtime import build_cluster_runtime
from framework.local_capacity import LOCAL_COEXISTENCE_MEMORY_MB, parse_memory_quantity_mb
from .config import INESDataConfigAdapter, InesdataConfig


yaml_ruamel = YAML()
yaml_ruamel.preserve_quotes = True
yaml_ruamel.indent(mapping=2, sequence=4, offset=2)


class INESDataInfrastructureAdapter:
    """Contains INESData infrastructure logic."""

    COMMON_CREDENTIAL_KEYS = (
        "PG_PASSWORD",
        "PG_PORT",
        "KC_USER",
        "KC_PASSWORD",
        "KC_INTERNAL_URL",
        "KC_URL",
        "KEYCLOAK_HOSTNAME",
        "KEYCLOAK_ADMIN_HOSTNAME",
        "MINIO_USER",
        "MINIO_PASSWORD",
        "MINIO_ADMIN_USER",
        "MINIO_ADMIN_PASS",
        "MINIO_HOSTNAME",
        "MINIO_CONSOLE_HOSTNAME",
    )
    POSTGRES_SERVICE_PORT = 5432
    KEYCLOAK_HTTP_COOKIE_ANNOTATION = "nginx.ingress.kubernetes.io/configuration-snippet"
    KEYCLOAK_HTTP_COOKIE_SNIPPET = "proxy_cookie_flags ~ nosecure nosamesite;\n"

    def __init__(self, run, run_silent, auto_mode_getter, config_adapter=None, config_cls=None):
        self.run = run
        self.run_silent = run_silent
        self.auto_mode_getter = auto_mode_getter
        self.config = config_cls or InesdataConfig
        self.config_adapter = config_adapter or INESDataConfigAdapter(self.config)
        self._last_registration_service_liquibase_issue = None
        self._vault_repair_temp_backup = None
        self._announced_levels = set()
        self._completed_levels = set()

    def _auto_mode(self):
        return self.auto_mode_getter() if callable(self.auto_mode_getter) else bool(self.auto_mode_getter)

    def _confirm_interactive(self, prompt, default=False):
        if self._auto_mode() or not getattr(sys.stdin, "isatty", lambda: False)():
            return False
        default_label = "Y/n" if default else "y/N"
        try:
            answer = input(f"{prompt} ({default_label}): ").strip().lower()
        except EOFError:
            return False
        if not answer:
            return bool(default)
        return answer in {"y", "yes", "s", "si", "sí"}

    @staticmethod
    def _fail(message, root_cause=None):
        if root_cause:
            raise RuntimeError(f"{message}. Root cause: {root_cause}")
        raise RuntimeError(message)

    @staticmethod
    def _print_unique_lines(output):
        previous = None
        for line in (output or "").splitlines():
            line = line.rstrip()
            if not line or line == previous:
                continue
            print(line)
            previous = line

    def _dataspace_name(self):
        getter = getattr(self.config, "dataspace_name", None)
        if callable(getter):
            return getter()
        return (getattr(self.config, "DS_NAME", "demo") or "demo").strip() or "demo"

    def _minikube_runtime_config(self):
        getter = getattr(self.config_adapter, "foundation_minikube_runtime", None)
        if callable(getter):
            try:
                runtime = dict(getter() or {})
            except Exception:
                runtime = {}
        else:
            runtime = {}
        if not runtime:
            load_config = getattr(self.config_adapter, "load_deployer_config", None)
            if callable(load_config):
                try:
                    deployer_config = dict(load_config() or {})
                except Exception:
                    deployer_config = {}
                runtime = {
                    "driver": deployer_config.get("MINIKUBE_DRIVER"),
                    "cpus": deployer_config.get("MINIKUBE_CPUS"),
                    "memory": deployer_config.get("MINIKUBE_MEMORY"),
                    "profile": deployer_config.get("MINIKUBE_PROFILE"),
                    "local_resource_profile": deployer_config.get("LOCAL_RESOURCE_PROFILE"),
                }

        topology = str(getattr(self.config_adapter, "topology", "local") or "local").strip().lower()
        default_cpus = 8 if topology == "vm-single" else 4
        default_memory = 24576 if topology == "vm-single" else 12288

        def _default(attr_name, fallback):
            if topology == "vm-single" and attr_name in {"MINIKUBE_CPUS", "MINIKUBE_MEMORY"}:
                return str(fallback)
            value = getattr(self.config, attr_name, fallback)
            normalized = str(value or "").strip()
            return normalized or str(fallback)

        def _positive_int_string(value, fallback):
            fallback_value = str(fallback or "").strip() or "0"
            try:
                parsed = int(str(value or "").strip())
            except (TypeError, ValueError):
                return fallback_value
            if parsed <= 0:
                return fallback_value
            return str(parsed)

        return {
            "driver": str(runtime.get("driver") or _default("MINIKUBE_DRIVER", "docker")).strip() or "docker",
            "cpus": _positive_int_string(runtime.get("cpus"), _default("MINIKUBE_CPUS", default_cpus)),
            "memory": _positive_int_string(runtime.get("memory"), _default("MINIKUBE_MEMORY", default_memory)),
            "profile": str(runtime.get("profile") or _default("MINIKUBE_PROFILE", "minikube")).strip() or "minikube",
            "local_resource_profile": str(runtime.get("local_resource_profile") or "").strip().lower(),
        }

    def _cluster_runtime_config(self):
        getter = getattr(self.config_adapter, "cluster_runtime", None)
        if callable(getter):
            try:
                runtime = dict(getter() or {})
            except Exception:
                runtime = {}
        else:
            runtime = {}
        if not runtime:
            load_config = getattr(self.config_adapter, "load_deployer_config", None)
            if callable(load_config):
                try:
                    deployer_config = dict(load_config() or {})
                except Exception:
                    deployer_config = {}
            else:
                deployer_config = {}
            topology = str(getattr(self.config_adapter, "topology", "local") or "local").strip().lower()
            runtime = build_cluster_runtime(deployer_config, topology=topology)
        return {
            "cluster_type": str(runtime.get("cluster_type") or "minikube").strip().lower() or "minikube",
            "k3s_kubeconfig": str(runtime.get("k3s_kubeconfig") or "/etc/rancher/k3s/k3s.yaml").strip()
            or "/etc/rancher/k3s/k3s.yaml",
            "k3s_install_exec": str(runtime.get("k3s_install_exec") or "--disable=traefik").strip()
            or "--disable=traefik",
            "k3s_service_name": str(runtime.get("k3s_service_name") or "k3s").strip() or "k3s",
            "k3s_ingress_controller": str(runtime.get("k3s_ingress_controller") or "ingress-nginx").strip()
            or "ingress-nginx",
            "k3s_ingress_service_type": str(runtime.get("k3s_ingress_service_type") or "NodePort").strip()
            or "NodePort",
            "k3s_repair_on_level1": str(runtime.get("k3s_repair_on_level1") or "prompt").strip().lower()
            or "prompt",
            "k3s_write_kubeconfig_mode": str(runtime.get("k3s_write_kubeconfig_mode") or "0644").strip()
            or "0644",
        }

    def _is_vm_single_topology(self):
        return str(getattr(self.config_adapter, "topology", "local") or "local").strip().lower() == "vm-single"

    def _common_services_startup_timeout(self):
        baseline = 600 if self._is_vm_single_topology() else 180
        return max(int(getattr(self.config, "TIMEOUT_POD_WAIT", 120)), baseline)

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
        namespace_demo_getter = getattr(self.config, "namespace_demo", None)
        if callable(namespace_demo_getter):
            namespace = namespace_demo_getter()
            if namespace:
                return str(namespace).strip()
        return self._dataspace_name()

    @staticmethod
    def _first_config_value(config, *keys):
        for key in keys:
            value = config.get(key)
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _minio_admin_credentials(cls, config):
        return (
            cls._first_config_value(config, "MINIO_ADMIN_USER", "MINIO_USER"),
            cls._first_config_value(config, "MINIO_ADMIN_PASS", "MINIO_PASSWORD"),
        )

    @staticmethod
    def _truthy_yaml_value(value):
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"true", "yes", "y", "1", "on"}

    @classmethod
    def _plain_http_keycloak_ingress(cls, values):
        keycloak = values.get("keycloak", {}) or {}
        tls_enabled = cls._truthy_yaml_value((keycloak.get("tls", {}) or {}).get("enabled"))
        ingress_tls = cls._truthy_yaml_value((keycloak.get("ingress", {}) or {}).get("tls"))
        admin_ingress_tls = cls._truthy_yaml_value((keycloak.get("adminIngress", {}) or {}).get("tls"))
        return not tls_enabled and not ingress_tls and not admin_ingress_tls

    @classmethod
    def _expected_keycloak_proxy(cls, values):
        if cls._plain_http_keycloak_ingress(values):
            return "none"
        return None

    @classmethod
    def _apply_keycloak_proxy_policy(cls, values):
        expected_proxy = cls._expected_keycloak_proxy(values)
        if expected_proxy:
            keycloak = values.setdefault("keycloak", {})
            keycloak["proxy"] = expected_proxy
            for ingress_key in ("ingress", "adminIngress"):
                ingress = keycloak.setdefault(ingress_key, {})
                annotations = ingress.setdefault("annotations", {})
                annotations[cls.KEYCLOAK_HTTP_COOKIE_ANNOTATION] = LiteralScalarString(
                    cls.KEYCLOAK_HTTP_COOKIE_SNIPPET
                )
        return values

    def announce_level(self, level, title):
        if level in self._announced_levels:
            return
        print("\n========================================")
        print(f"LEVEL {level} - {title}")
        print("========================================\n")
        self._announced_levels.add(level)

    def complete_level(self, level):
        if level in self._completed_levels:
            return
        print(f"\nLEVEL {level} COMPLETE\n")
        self._completed_levels.add(level)

    def ensure_unix_environment(self):
        if os.name == "nt":
            print("Script must run on Linux, macOS, or WSL")
            raise SystemExit(1)

    def is_wsl(self):
        try:
            with open("/proc/version", "r") as f:
                return "microsoft" in f.read().lower()
        except Exception:
            return False

    def ensure_wsl_docker_config(self):
        if not self.is_wsl():
            return True

        docker_config_path = os.path.expanduser("~/.docker/config.json")
        print("\nWSL detected: validating Docker client config...")

        if not os.path.exists(docker_config_path):
            print("Docker config not found. Skipping WSL Docker config adjustment.")
            return True

        try:
            with open(docker_config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError:
            print(f"Docker config is not valid JSON: {docker_config_path}")
            print("Skipping automatic adjustment.")
            return True
        except OSError as e:
            print(f"Could not read Docker config ({docker_config_path}): {e}")
            return True

        if not isinstance(config, dict):
            print(f"Docker config has unexpected format in {docker_config_path}")
            print("Skipping automatic adjustment.")
            return True

        creds_store = str(config.get("credsStore") or "").strip().lower()
        if creds_store not in {"desktop", "desktop.exe"}:
            print("No WSL Docker credsStore adjustment required.")
            return True

        removed_creds_store = config.pop("credsStore", None)
        try:
            with open(docker_config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
                f.write("\n")
        except OSError as e:
            print(f"Could not write Docker config ({docker_config_path}): {e}")
            return False

        print(f"Removed credsStore={removed_creds_store} from {docker_config_path}")
        return True

    def get_hosts_path(self):
        import sys

        if self.is_wsl():
            return "/mnt/c/Windows/System32/drivers/etc/hosts"
        if sys.platform.startswith("linux"):
            return "/etc/hosts"
        if sys.platform == "darwin":
            return "/private/etc/hosts"
        return None

    def manage_hosts_entries(self, desired_entries, header_comment="# Dataspace Local Deployment", auto_confirm=None):
        hosts_path = self.get_hosts_path()

        default_header = "# Dataspace Local Deployment"
        header_comment = (header_comment or default_header).strip() or default_header
        if not header_comment.startswith("#"):
            header_comment = f"# {header_comment}"

        if not hosts_path:
            print("OS not supported for automatic hosts modification")
            return

        print(f"\nHosts file: {hosts_path}")

        try:
            with open(hosts_path, "r") as f:
                content = f.read()
        except PermissionError:
            print("Permission denied reading hosts file")
            return

        lines = content.splitlines()

        def line_matches_entry(line: str, entry: str) -> bool:
            stripped = line.strip()
            if not stripped.startswith(entry):
                return False
            if len(stripped) == len(entry):
                return True
            next_char = stripped[len(entry)]
            return next_char.isspace() or next_char == "#"

        def entry_present(entry: str) -> bool:
            return any(line_matches_entry(line, entry) for line in lines)

        def entry_present_under_header(entry: str, header: str) -> bool:
            current_header = None
            for line in lines:
                if line.lstrip().startswith("#"):
                    current_header = line.strip()
                    continue
                if line_matches_entry(line, entry) and current_header == header:
                    return True
            return False

        existing = [entry for entry in desired_entries if entry_present(entry)]
        missing = [entry for entry in desired_entries if not entry_present(entry)]

        needs_section_migration = False
        if header_comment != default_header:
            for entry in desired_entries:
                if entry_present(entry) and not entry_present_under_header(entry, header_comment):
                    needs_section_migration = True
                    break

        print("\nExisting entries:")
        for entry in existing or ["None"]:
            if entry:
                print(f"  {entry}")

        print("\nMissing entries:")
        for entry in missing or ["None"]:
            if entry:
                print(f"  {entry}")

        if not missing and not needs_section_migration:
            print("\nNo modifications needed to hosts file")
            return

        effective_auto = self._auto_mode() if auto_confirm is None else bool(auto_confirm)

        if effective_auto:
            choice = "Y"
            if self._auto_mode() and auto_confirm is None:
                print("\n[AUTO_MODE] Automatically adding entries to hosts file")
            else:
                print("\nAutomatically adding entries to hosts file")
        else:
            prompt = (
                "\nAdd missing entries to hosts file? (Y/N, default: Y): "
                if missing
                else "\nUpdate hosts section header? (Y/N, default: Y): "
            )
            try:
                choice = (input(prompt).strip().upper() or "Y")
            except EOFError:
                choice = "Y"

        if choice == "S":
            choice = "Y"

        if choice != "Y":
            print("No changes made to hosts file")
            return

        try:
            if needs_section_migration:
                desired_unique = list(dict.fromkeys(desired_entries))
                desired_set = set(desired_unique)

                updated = lines[:]
                i = 0
                while i < len(updated):
                    if updated[i].strip() == default_header:
                        j = i + 1
                        block_entries = []
                        while j < len(updated) and not updated[j].lstrip().startswith("#"):
                            candidate = updated[j].strip()
                            if candidate:
                                block_entries.append(candidate)
                            j += 1

                        if block_entries and all(entry in desired_set for entry in block_entries):
                            updated[i] = header_comment

                        i = j
                        continue

                    i += 1

                cleaned = []
                current_header = None
                for line in updated:
                    if line.lstrip().startswith("#"):
                        current_header = line.strip()
                        cleaned.append(line)
                        continue

                    matched = next(
                        (entry for entry in desired_unique if line_matches_entry(line, entry)),
                        None,
                    )
                    if matched and current_header != header_comment:
                        continue

                    cleaned.append(line)

                present_under_target = set()
                current_header = None
                for line in cleaned:
                    if line.lstrip().startswith("#"):
                        current_header = line.strip()
                        continue
                    if current_header == header_comment:
                        for entry in desired_unique:
                            if line_matches_entry(line, entry):
                                present_under_target.add(entry)

                entries_to_add = [e for e in desired_unique if e not in present_under_target]
                if entries_to_add:
                    header_idx = None
                    for idx in range(len(cleaned) - 1, -1, -1):
                        if cleaned[idx].strip() == header_comment:
                            header_idx = idx
                            break

                    if header_idx is None:
                        if cleaned and cleaned[-1].strip() != "":
                            cleaned.append("")
                        cleaned.append(header_comment)
                        header_idx = len(cleaned) - 1

                    insert_at = len(cleaned)
                    for idx in range(header_idx + 1, len(cleaned)):
                        if cleaned[idx].lstrip().startswith("#"):
                            insert_at = idx
                            break

                    cleaned[insert_at:insert_at] = entries_to_add

                with open(hosts_path, "w") as f:
                    f.write("\n".join(cleaned).rstrip("\n") + "\n")

                print("Hosts file updated successfully")
            else:
                with open(hosts_path, "a") as f:
                    f.write(f"\n{header_comment}\n")
                    for line in missing:
                        f.write(line + "\n")
                print("Entries added successfully")
        except PermissionError:
            print("Permission denied writing to hosts file.")
            if self.is_wsl() and hosts_path.startswith("/mnt/"):
                print("On WSL, the Windows hosts file may require Administrator privileges.")
                print("Edit it from Windows as admin: C:\\Windows\\System32\\drivers\\etc\\hosts")
            else:
                print("Try re-running with sudo.")
        except OSError as exc:
            print(f"Could not write to hosts file: {exc}")

    def deploy_helm_release(
        self,
        release_name,
        namespace,
        values_file="values.yaml",
        cwd=None,
        wait=True,
        timeout_seconds=None,
    ):
        print("Executing helm upgrade --install...")

        if isinstance(values_file, (list, tuple)):
            values_files = [str(path) for path in values_file if str(path).strip()]
        else:
            values_files = [str(values_file)]

        if not values_files:
            values_files = ["values.yaml"]

        values_args = " ".join(
            f"-f {shlex.quote(path)}"
            for path in values_files
        )

        cmd = (
            f"helm upgrade --install {shlex.quote(str(release_name))} . "
            f"-n {shlex.quote(str(namespace))} "
            f"--create-namespace "
            f"{values_args} "
        )
        if not wait:
            cmd += "--wait=false "
        if timeout_seconds:
            cmd += f"--timeout {int(timeout_seconds)}s "

        max_attempts = self._helm_deploy_attempts()
        retry_delay = self._helm_deploy_retry_delay_seconds()
        result = None
        for attempt in range(1, max_attempts + 1):
            result = self.run(cmd, check=False, cwd=cwd)
            if result is not None:
                print("Release deployed successfully")
                return True

            if attempt < max_attempts:
                print(
                    f"Helm deployment failed on attempt {attempt}/{max_attempts}; "
                    f"retrying in {retry_delay}s..."
                )
                if retry_delay > 0:
                    time.sleep(retry_delay)

        print("Helm deployment failed")
        return False

    @staticmethod
    def _positive_int_env(name, default):
        raw_value = str(os.environ.get(name, "") or "").strip()
        if not raw_value:
            return int(default)
        try:
            return max(int(raw_value), 1)
        except ValueError:
            return int(default)

    def _helm_deploy_attempts(self):
        return self._positive_int_env("PIONERA_HELM_DEPLOY_ATTEMPTS", 3)

    @staticmethod
    def _helm_deploy_retry_delay_seconds():
        raw_value = str(
            os.environ.get("PIONERA_HELM_DEPLOY_RETRY_DELAY_SECONDS", "") or ""
        ).strip()
        if not raw_value:
            return 10
        try:
            return max(int(raw_value), 0)
        except ValueError:
            return 10

    def wait_for_deployment_rollout(self, namespace, deployment_name, timeout_seconds=180, label=None):
        namespace = (namespace or "").strip()
        deployment_name = (deployment_name or "").strip()
        if not namespace or not deployment_name:
            return False

        timeout_seconds = max(int(timeout_seconds or 180), 1)
        rollout_label = label or f"deployment/{deployment_name}"
        print(f"Waiting for {rollout_label} rollout...")

        result = self.run(
            f"kubectl rollout status deployment/{shlex.quote(deployment_name)} "
            f"-n {shlex.quote(namespace)} --timeout={timeout_seconds}s",
            capture=True,
            check=False,
        )

        if result is None:
            print(f"Timeout waiting for {rollout_label} rollout")
            self.run(
                f"kubectl get deployment {shlex.quote(deployment_name)} -n {shlex.quote(namespace)}",
                check=False,
            )
            self.run(f"kubectl get pods -n {shlex.quote(namespace)}", check=False)
            return False

        self._print_unique_lines(result)
        return True

    def add_helm_repos(self):
        print("\nAdding Helm repositories...")
        for name, url in self.config.HELM_REPOS.items():
            self.run(f"helm repo add {name} {url}", check=False)
        self.run("helm repo update", check=False)

    def get_pod_by_name(self, namespace, pod_pattern):
        result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")

        if not result:
            return None

        for line in result.splitlines():
            if pod_pattern in line:
                return line.split()[0]

        return None

    def wait_for_pod_running(self, pod_name, namespace, timeout=None):
        timeout = timeout or self.config.TIMEOUT_NAMESPACE
        print(f"Waiting for pod {pod_name} to be running...")
        start = time.time()

        while True:
            result = self.run_silent(f"kubectl get pod {pod_name} -n {namespace} --no-headers")

            if result:
                cols = result.split()
                if len(cols) > 2 and cols[2] == "Running":
                    print(f"Pod {pod_name} is running")
                    return True

            if time.time() - start > timeout:
                print(f"Timeout waiting for pod {pod_name}")
                return False

            time.sleep(1)

    def _is_ignored_transient_hook_pod(self, namespace, pod_name):
        if "keycloak-config-cli" in pod_name:
            return True

        if "minio-post-job" in pod_name:
            return True

        if namespace != "ingress-nginx":
            return False

        return (
            pod_name.startswith("ingress-nginx-admission-create-")
            or pod_name.startswith("ingress-nginx-admission-patch-")
        )

    def wait_for_pods(self, namespace, timeout=None):
        timeout = timeout or self.config.TIMEOUT_POD_WAIT
        print(f"\nWaiting for pods in namespace '{namespace}' to be ready...")
        start_time = time.time()

        while True:
            result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")

            if not result:
                time.sleep(2)
                continue

            all_ready = True
            observed_relevant_pod = False

            for line in result.splitlines():
                columns = line.split()
                name = columns[0]
                ready = columns[1] if len(columns) > 1 else ""
                status = columns[2]

                if self._is_ignored_transient_hook_pod(namespace, name):
                    continue

                if status in ["CrashLoopBackOff", "Error", "ImagePullBackOff"]:
                    print(f"\nPod in error state: {name} ({status})")
                    self.run(f"kubectl get pods -n {namespace}", check=False)
                    return False

                if status == "Completed":
                    continue

                observed_relevant_pod = True

                if status != "Running":
                    all_ready = False
                    continue

                if "/" in ready:
                    ready_current, ready_total = ready.split("/", 1)
                    if ready_current != ready_total:
                        all_ready = False
                        continue

                if not ready:
                    all_ready = False

            if all_ready and observed_relevant_pod:
                print("\nAll pods are running and ready\n")
                self.run(f"kubectl get pods -n {namespace}", check=False)
                return True

            if time.time() - start_time > timeout:
                print("\nTimeout waiting for pods to be ready\n")
                self.run(f"kubectl get pods -n {namespace}", check=False)
                return False

            time.sleep(1)

    def wait_for_namespace_pods(self, namespace, timeout=None):
        timeout = timeout or self.config.TIMEOUT_NAMESPACE
        print(f"\nWaiting for pods in namespace '{namespace}'...")
        start = time.time()

        while True:
            result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")

            if result:
                all_ready = True
                observed_relevant_pod = False
                for line in result.splitlines():
                    columns = line.split()
                    if len(columns) < 3:
                        continue
                    name = columns[0]
                    ready = columns[1] if len(columns) > 1 else ""
                    status = columns[2]

                    if self._is_ignored_transient_hook_pod(namespace, name):
                        continue

                    if status == "Completed":
                        continue

                    if status == "Terminating":
                        continue

                    observed_relevant_pod = True

                    if status != "Running":
                        all_ready = False
                        break

                    if "/" in ready:
                        ready_current, ready_total = ready.split("/", 1)
                        if ready_current != ready_total:
                            all_ready = False
                            break

                if all_ready and observed_relevant_pod:
                    print("\nPods ready:")
                    self.run(f"kubectl get pods -n {namespace}")
                    return True

            if time.time() - start > timeout:
                print("Timeout waiting for pods")
                self.run(f"kubectl get pods -n {namespace}")
                return False

            time.sleep(1)

    def wait_for_dataspace_level3_pods(self, namespace, dataspace_name=None, timeout=None):
        """Wait only for Level 3 dataspace pods.

        A dataspace namespace can already contain Level 4 connector pods from a
        previous run. Level 3 should not fail because those connector pods are
        initializing or unhealthy; connector health belongs to Level 4.
        """
        timeout = timeout or self.config.TIMEOUT_NAMESPACE
        transient_error_grace_seconds = max(
            5,
            min(int(getattr(self.config, "TIMEOUT_PORT", 30)), 15),
        )
        dataspace = str(dataspace_name or namespace or "").strip()
        namespace = str(namespace or "").strip()
        if not namespace:
            return False

        selected_prefixes = []
        if dataspace:
            selected_prefixes.append(f"{dataspace}-registration-service-")
        selected_prefixes.append("registration-service-")

        print(f"\nWaiting for Level 3 dataspace pods in namespace '{namespace}'...")
        start = time.time()
        last_stale_terminal_notice = None
        transient_error_since = {}

        while True:
            now = time.time()
            result = self.run_silent(f"kubectl get pods -n {shlex.quote(namespace)} --no-headers")

            if result:
                selected = []
                ignored = []

                for line in result.splitlines():
                    columns = line.split()
                    if len(columns) < 3:
                        continue
                    name = columns[0]

                    if any(name.startswith(prefix) for prefix in selected_prefixes):
                        selected.append(columns)
                    else:
                        ignored.append(name)

                if selected:
                    all_ready = True
                    ready_running = []
                    fatal_terminal_error = []
                    transient_error = []
                    progressing = []
                    selected_names = set()
                    for columns in selected:
                        name = columns[0]
                        ready = columns[1] if len(columns) > 1 else ""
                        status = columns[2]
                        selected_names.add(name)

                        is_ready = False
                        if status == "Running" and "/" in ready:
                            ready_current, ready_total = ready.split("/", 1)
                            is_ready = ready_current == ready_total
                        elif status == "Running" and ready:
                            is_ready = True

                        if status in ["CrashLoopBackOff", "ImagePullBackOff"]:
                            fatal_terminal_error.append((name, status))
                            all_ready = False
                            continue

                        if status == "Error":
                            transient_error.append((name, status))
                            transient_error_since.setdefault(name, now)
                            all_ready = False
                            continue

                        transient_error_since.pop(name, None)

                        if status != "Running":
                            progressing.append((name, status))
                            all_ready = False
                            continue

                        if is_ready:
                            ready_running.append(name)
                            continue

                        progressing.append((name, status))
                        all_ready = False

                    transient_error_since = {
                        name: first_seen
                        for name, first_seen in transient_error_since.items()
                        if name in selected_names
                    }

                    if all_ready:
                        if ignored:
                            print(
                                "Ignoring non-Level 3 pods while checking dataspace readiness: "
                                + ", ".join(ignored)
                            )
                        print("\nLevel 3 dataspace pods ready:")
                        self.run(f"kubectl get pods -n {shlex.quote(namespace)}", check=False)
                        return True

                    if fatal_terminal_error:
                        name, status = fatal_terminal_error[0]
                        print(f"\nLevel 3 pod in error state: {name} ({status})")
                        self.run(f"kubectl get pods -n {shlex.quote(namespace)}", check=False)
                        return False

                    if transient_error and (ready_running or progressing):
                        stale_terminal_notice = ", ".join(
                            f"{name} ({status})" for name, status in transient_error
                        )
                        if stale_terminal_notice != last_stale_terminal_notice:
                            print(
                                "\nWaiting for stale Level 3 rollout pods to disappear: "
                                f"{stale_terminal_notice}"
                            )
                            last_stale_terminal_notice = stale_terminal_notice
                    elif transient_error:
                        expired_transient_error = [
                            (name, status)
                            for name, status in transient_error
                            if now - transient_error_since.get(name, now)
                            >= transient_error_grace_seconds
                        ]
                        if expired_transient_error:
                            name, status = expired_transient_error[0]
                            print(f"\nLevel 3 pod in error state: {name} ({status})")
                            self.run(f"kubectl get pods -n {shlex.quote(namespace)}", check=False)
                            return False

                        stale_terminal_notice = ", ".join(
                            f"{name} ({status})" for name, status in transient_error
                        )
                        if stale_terminal_notice != last_stale_terminal_notice:
                            print(
                                "\nWaiting for transient Level 3 pod errors to recover: "
                                f"{stale_terminal_notice}"
                            )
                            last_stale_terminal_notice = stale_terminal_notice

            if now - start > timeout:
                print("Timeout waiting for Level 3 dataspace pods")
                self.run(f"kubectl get pods -n {shlex.quote(namespace)}", check=False)
                return False

            time.sleep(1)

    def port_forward_service(self, namespace, pattern, local_port, remote_port, quiet=False, wait_timeout=None):
        pod = self.get_pod_by_name(namespace, pattern)

        if not pod:
            if not quiet:
                print(f"Pod with pattern '{pattern}' not found in {namespace}")
            return False

        self.run(f"pkill -f 'kubectl port-forward {pod}'", check=False, silent=quiet)

        process = subprocess.Popen(
            ["kubectl", "port-forward", pod, "-n", namespace, f"{local_port}:{remote_port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        deadline = time.time() + max(float(wait_timeout or getattr(self.config, "TIMEOUT_PORT", 30)), 1.0)

        while time.time() <= deadline:
            if process.poll() is not None:
                if not quiet:
                    print(f"Port-forward process for '{pod}' exited before local port {local_port} became reachable")
                return False

            if self._port_is_open("127.0.0.1", local_port, connect_timeout=0.25):
                return True

            time.sleep(0.25)

        if not quiet:
            print(f"Timed out waiting for port-forward to '{pod}' on local port {local_port}")
        return False

    def stop_port_forward_service(self, namespace, pattern, quiet=False):
        pod = self.get_pod_by_name(namespace, pattern)
        if not pod:
            return False
        return self.run(f"pkill -f 'kubectl port-forward {pod}'", check=False, silent=quiet) is not None

    @staticmethod
    def _port_is_open(host, port, connect_timeout=0.5):
        connect_timeout = max(min(float(connect_timeout), 2.0), 0.1)
        try:
            with socket.create_connection((host, port), timeout=connect_timeout):
                return True
        except OSError:
            return False

    def _ensure_local_service_access(
        self,
        service_label,
        namespace,
        pattern,
        local_port,
        remote_port,
        quiet=False,
        probe_timeout=None,
        wait_timeout=None,
    ):
        full_timeout = max(int(wait_timeout or getattr(self.config, "TIMEOUT_PORT", 30)), 1)
        probe_timeout = max(min(int(probe_timeout or 3), full_timeout), 1)

        if self.wait_for_port("127.0.0.1", local_port, timeout=probe_timeout):
            if not quiet:
                print(f"{service_label} accessible")
            return True, False

        if not quiet:
            print(f"{service_label} not accessible locally after {probe_timeout}s. Creating port-forward...")

        if not self.port_forward_service(
            namespace,
            pattern,
            local_port,
            remote_port,
            quiet=quiet,
            wait_timeout=full_timeout,
        ):
            if not quiet:
                print(f"Could not establish {service_label} access")
            return False, False

        if not quiet:
            print(f"{service_label} accessible via port-forward")
        return True, True

    def _configured_pg_port(self):
        getter = getattr(self.config_adapter, "get_pg_port", None)
        if callable(getter):
            return str(getter())
        return str(getattr(self.config, "PORT_POSTGRES", 5432))

    def _postgres_connection_works(self, host, port, user, password):
        if not password:
            return False
        result = self.run_silent(
            " ".join(
                [
                    f"PGPASSWORD={shlex.quote(str(password))}",
                    "psql",
                    "-h",
                    shlex.quote(str(host)),
                    "-p",
                    shlex.quote(str(port)),
                    "-U",
                    shlex.quote(str(user)),
                    "-d",
                    "postgres",
                    "-t",
                    "-A",
                    "-c",
                    '"SELECT 1;"',
                ]
            )
        )
        return bool(result and result.strip() == "1")

    def _set_local_pg_port_override(self, port, persist=False):
        os.environ["PIONERA_PG_PORT"] = str(port)
        if persist:
            config_path = self._common_credentials_deployer_config_path()
            try:
                self._write_key_value_updates(config_path, {"PG_PORT": str(port)}, self.COMMON_CREDENTIAL_KEYS)
            except OSError as exc:
                print(f"Warning: could not persist PostgreSQL local port override: {exc}")

    def _wait_for_local_port_closed(self, port, timeout=3):
        deadline = time.time() + max(float(timeout or 3), 0.25)
        while time.time() <= deadline:
            if not self._port_is_open("127.0.0.1", port, connect_timeout=0.25):
                return True
            time.sleep(0.25)
        return False

    def _release_stale_postgres_port_forward(self, local_port):
        """Release only framework-owned PostgreSQL port-forward processes."""
        namespace = str(self.config.NS_COMMON)
        local_port = str(local_port)
        remote_port = str(self.POSTGRES_SERVICE_PORT)

        released = False
        if self.stop_port_forward_service(namespace, "postgresql", quiet=True):
            released = True

        # Covers stale port-forward processes whose pod name is no longer current.
        pattern = (
            f"kubectl port-forward .*postgresql.* -n {namespace} "
            f".*{local_port}:{remote_port}"
        )
        if self.run(f"pkill -f {shlex.quote(pattern)}", check=False, silent=True) is not None:
            released = True

        if released and self._wait_for_local_port_closed(int(local_port), timeout=3):
            return True

        return False

    def _describe_local_port_listener(self, port):
        port = int(port)
        probes = [
            f"ss -ltnp 'sport = :{port}' 2>/dev/null",
            f"lsof -nP -iTCP:{port} -sTCP:LISTEN 2>/dev/null",
        ]
        for command in probes:
            result = self.run_silent(command)
            if result:
                return result.strip()
        return "Port owner details unavailable. Try: ss -ltnp 'sport = :%s'" % port

    def _ensure_local_postgres_access(self, full_timeout, probe_timeout):
        pg_host, pg_user, pg_password = self.config_adapter.get_pg_credentials()
        pg_port = self._configured_pg_port()
        try:
            local_pg_port = int(pg_port)
        except (TypeError, ValueError):
            print(f"Invalid PG_PORT value: {pg_port}")
            return False

        print(
            f"PostgreSQL service port is {self.POSTGRES_SERVICE_PORT}; "
            f"local client port is {local_pg_port}."
        )

        if self.wait_for_port("127.0.0.1", local_pg_port, timeout=probe_timeout):
            if self._postgres_connection_works(pg_host, pg_port, pg_user, pg_password):
                self._set_local_pg_port_override(pg_port)
                print("PostgreSQL accessible")
                return True

            print(
                f"PostgreSQL local port {pg_port} is open but does not authenticate "
                "with framework credentials. Checking for stale framework port-forward..."
            )
            if self._release_stale_postgres_port_forward(local_pg_port):
                print(
                    f"Released stale framework PostgreSQL port-forward on local port {pg_port}."
                )
            elif self.wait_for_port("127.0.0.1", local_pg_port, timeout=1):
                print(
                    f"PostgreSQL local port {pg_port} is occupied by a process that "
                    "is not the framework PostgreSQL port-forward."
                )
                print(self._describe_local_port_listener(local_pg_port))
                print(
                    "Stop that process or free the port manually, then rerun the level. "
                    "The framework did not terminate unknown processes."
                )
                return False

        print(
            f"Creating port-forward 127.0.0.1:{pg_port} -> "
            f"common-srvs-postgresql:{self.POSTGRES_SERVICE_PORT}..."
        )
        self._set_local_pg_port_override(pg_port)

        if not self.port_forward_service(
            self.config.NS_COMMON,
            "postgresql",
            local_pg_port,
            self.POSTGRES_SERVICE_PORT,
            quiet=False,
            wait_timeout=full_timeout,
        ):
            print("Could not establish PostgreSQL access")
            return False

        if not self._postgres_connection_works(pg_host, pg_port, pg_user, pg_password):
            print("PostgreSQL port-forward is active but authentication still fails")
            return False

        print(
            f"PostgreSQL accessible via port-forward "
            f"127.0.0.1:{local_pg_port} -> common-srvs-postgresql:{self.POSTGRES_SERVICE_PORT}"
        )
        return True

    def wait_for_port(self, host, port, timeout=None):
        timeout = timeout or self.config.TIMEOUT_PORT
        start = time.time()

        while True:
            if self._port_is_open(host, port, connect_timeout=0.5):
                return True

            if time.time() - start > timeout:
                return False

            time.sleep(1)

    def wait_for_vault_pod(self, namespace=None, timeout=None):
        namespace = namespace or self.config.NS_COMMON
        timeout = timeout or self.config.TIMEOUT_NAMESPACE
        print("\nWaiting for Vault pod to be created...")
        start = time.time()

        while True:
            pod = self.get_pod_by_name(namespace, "vault")
            if pod:
                print("Vault pod detected")
                return True

            if time.time() - start > timeout:
                print("Timeout waiting for Vault pod")
                return False

            time.sleep(1)

    def wait_for_level2_service_pods(self, namespace=None, timeout=None, require_vault_ready=False):
        namespace = namespace or self.config.NS_COMMON
        timeout = timeout or self.config.TIMEOUT_POD_WAIT
        print(f"\nWaiting for core services in namespace '{namespace}'...")
        start_time = time.time()
        expected_prefixes = (
            "common-srvs-keycloak-",
            "common-srvs-minio-",
            "common-srvs-postgresql-",
            "common-srvs-vault-",
        )
        observed_expected_error = None

        while True:
            result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")

            if result:
                pods = {}
                transient_error = None

                for line in result.splitlines():
                    columns = line.split()
                    if len(columns) < 3:
                        continue

                    name = columns[0]
                    ready = columns[1] if len(columns) > 1 else ""
                    status = columns[2]

                    if self._is_ignored_transient_hook_pod(namespace, name):
                        continue

                    # Ignore completed hook/job pods so they do not replace the
                    # long-lived service pod we actually want to observe.
                    if status == "Completed":
                        continue

                    if status in ["CrashLoopBackOff", "ImagePullBackOff"]:
                        print(f"\nPod in error state: {name} ({status})")
                        self.run(f"kubectl get pods -n {namespace}", check=False)
                        return False

                    is_expected_service_pod = any(name.startswith(prefix) for prefix in expected_prefixes)
                    if status == "Error" and not self._is_ignored_transient_hook_pod(namespace, name):
                        if is_expected_service_pod:
                            observed_expected_error = f"{name} ({status})"
                            continue
                        print(f"\nPod in error state: {name} ({status})")
                        self.run(f"kubectl get pods -n {namespace}", check=False)
                        return False

                    if is_expected_service_pod:
                        pods[name] = {"ready": ready, "status": status}
                    elif status == "Error":
                        transient_error = transient_error or f"{name} ({status})"

                expected = {
                    "keycloak": None,
                    "minio": None,
                    "postgresql": None,
                    "vault": None,
                }
                for name, pod in pods.items():
                    if name.startswith("common-srvs-keycloak-"):
                        expected["keycloak"] = pod
                    elif name.startswith("common-srvs-minio-"):
                        expected["minio"] = pod
                    elif name.startswith("common-srvs-postgresql-"):
                        expected["postgresql"] = pod
                    elif name.startswith("common-srvs-vault-"):
                        expected["vault"] = pod

                def is_ready(pod):
                    if pod is None or pod["status"] != "Running":
                        return False
                    ready = pod.get("ready", "")
                    if "/" not in ready:
                        return False
                    ready_current, ready_total = ready.split("/", 1)
                    return ready_current == ready_total

                all_present = all(expected.values())
                all_ready = all(
                    is_ready(pod)
                    for key, pod in expected.items()
                    if key != "vault" and pod is not None
                )
                if require_vault_ready:
                    vault_running = is_ready(expected["vault"])
                else:
                    vault_running = expected["vault"] is not None and expected["vault"]["status"] == "Running"

                if all_present and all_ready and vault_running:
                    print("\nCore services detected:")
                    self.run(f"kubectl get pods -n {namespace}", check=False)
                    return True

                if transient_error:
                    print(f"Waiting past transient hook state: {transient_error}")
                if observed_expected_error:
                    print(
                        "Observed transient service pod error while the common services cold start "
                        f"was still converging: {observed_expected_error}"
                    )

            if time.time() - start_time > timeout:
                print("\nTimeout waiting for core services\n")
                if observed_expected_error:
                    print(f"Last transient service pod error observed: {observed_expected_error}")
                self.run(f"kubectl get pods -n {namespace}", check=False)
                return False

            time.sleep(1)

    def _run_vault_status_command(self, pod_name, namespace):
        """Return Vault status stdout even when Vault exits non-zero while sealed."""
        command = [
            "kubectl",
            "exec",
            str(pod_name),
            "-n",
            str(namespace),
            "--",
            "vault",
            "status",
            "-format=json",
        ]
        try:
            result = subprocess.run(command, text=True, capture_output=True)
        except Exception as exc:
            return "", f"vault status command failed: {exc}"

        stdout = (result.stdout or "").strip()
        if stdout:
            return stdout, None

        stderr = (result.stderr or "").strip()
        if stderr:
            return "", f"vault status unavailable: {stderr}"
        if result.returncode != 0:
            return "", f"vault status unavailable: exit code {result.returncode}"
        return "", "vault status unavailable"

    def _read_vault_status(self, pod_name, namespace, attempts=10, poll_interval=3):
        attempts = max(1, int(attempts or 1))
        status_error = "vault status unavailable"

        for attempt in range(attempts):
            status_json, status_error = self._run_vault_status_command(pod_name, namespace)
            if status_json:
                try:
                    return json.loads(status_json), None
                except json.JSONDecodeError as exc:
                    return None, f"invalid vault status: {exc}"

            if attempt < attempts - 1:
                time.sleep(poll_interval)

        return None, status_error

    def _vault_root_token_valid(self, pod_name, namespace, root_token):
        if not root_token:
            return False

        token_lookup = self.run_silent(
            f"kubectl exec {pod_name} -n {namespace} -- "
            f"env VAULT_TOKEN={shlex.quote(root_token)} vault token lookup -format=json"
        )
        if not token_lookup:
            return False

        try:
            payload = json.loads(token_lookup)
        except json.JSONDecodeError:
            return False

        return bool(payload.get("data"))

    def setup_vault(self, namespace=None):
        namespace = namespace or self.config.NS_COMMON
        print("\nConfiguring Vault...")

        pod_name = self.get_pod_by_name(namespace, "vault")
        if not pod_name:
            print("Could not detect Vault pod")
            return False

        if not self.wait_for_pod_running(pod_name, namespace):
            return False

        vault_file_path = self.config.vault_keys_path()
        status_data, status_error = self._read_vault_status(pod_name, namespace)
        initialized = False
        sealed = True

        if status_data:
            initialized = status_data.get("initialized", False)
            sealed = status_data.get("sealed", True)
            print(f"Vault status: initialized={initialized}, sealed={sealed}")
        elif os.path.exists(vault_file_path):
            print(f"Vault status temporarily unavailable ({status_error}); reusing existing keys")
            initialized = True
            sealed = True
        else:
            print(f"Could not get Vault status: {status_error}")
            return False

        if not initialized:
            print("Vault not initialized. Running init...")
            init_output = self.run_silent(
                f"kubectl exec {pod_name} -n {namespace} -- "
                "vault operator init -key-shares=1 -key-threshold=1 -format=json"
            )

            if not init_output:
                print("Error: vault operator init failed")
                return False

            os.makedirs(os.path.dirname(vault_file_path), exist_ok=True)
            try:
                with open(vault_file_path, "w") as f:
                    f.write(init_output)
                print("Vault keys file created")
            except IOError as e:
                print(f"Error writing Vault keys: {e}")
                return False
        else:
            print("Vault already initialized")

        if initialized:
            ensure_vault_keys_file = getattr(self.config, "ensure_vault_keys_file", None)
            if callable(ensure_vault_keys_file):
                vault_file_path = ensure_vault_keys_file()

        try:
            with open(vault_file_path, "r") as f:
                keys = json.load(f)
        except FileNotFoundError:
            print("Error: Vault keys file not found")
            return False
        except json.JSONDecodeError:
            print("Error: Vault keys file corrupted")
            return False

        unseal_key = keys.get("unseal_keys_hex", [None])[0]
        root_token = keys.get("root_token")

        if not unseal_key or not root_token:
            print("Error: Invalid keys in Vault keys file")
            return False

        if sealed:
            print("Running unseal...")
            unseal_result = self.run_silent(
                f"kubectl exec {pod_name} -n {namespace} -- vault operator unseal {unseal_key}"
            )
            if not unseal_result:
                print("Error: vault operator unseal failed")
                return False
            print("Vault unsealed")
        else:
            print("Vault already unsealed")

        if not self._vault_root_token_valid(pod_name, namespace, root_token):
            print("Local Vault root token is not valid for the running Vault. Trying automatic reconciliation...")
            if self.reconcile_vault_state_for_local_runtime(pod_name=pod_name, namespace=namespace, quiet=True):
                try:
                    with open(vault_file_path, "r") as f:
                        keys = json.load(f)
                    root_token = keys.get("root_token")
                except (OSError, json.JSONDecodeError):
                    root_token = None

            if not self._vault_root_token_valid(pod_name, namespace, root_token):
                print(
                    "Error: local Vault root token is not valid for the running Vault. "
                    "The Vault persistent state and deployers/shared/common/init-keys-vault.json "
                    "are out of sync. Recreate Level 2 common services or restore the current "
                    "Vault root token before continuing."
                )
                return False

        print("Checking KV engine...")
        secrets_list = self.run_silent(
            f"kubectl exec {pod_name} -n {namespace} -- "
            f"env VAULT_TOKEN={shlex.quote(root_token)} vault secrets list -format=json"
        )

        kv_exists = False
        if secrets_list:
            try:
                mounts = json.loads(secrets_list)
                kv_exists = "secret/" in mounts
            except Exception:
                pass

        if not kv_exists:
            print("Enabling KV v2 engine...")
            enable_kv = self.run_silent(
                f"kubectl exec {pod_name} -n {namespace} -- "
                f"env VAULT_TOKEN={shlex.quote(root_token)} vault secrets enable -path=secret kv-v2"
            )
            if enable_kv:
                print("KV v2 engine enabled")
            else:
                print("Warning: KV v2 engine not enabled, continuing")
        else:
            print("KV v2 engine already enabled")

        final_status, final_status_error = self._read_vault_status(pod_name, namespace)
        if not final_status:
            print(f"Error: Could not get final Vault status: {final_status_error}")
            return False

        try:
            initialized = final_status.get("initialized", False)
            sealed = final_status.get("sealed", True)
            print("\nVault final status:")
            print(f"  Initialized: {initialized}")
            print(f"  Sealed: {sealed}\n")
            return initialized and not sealed
        except Exception as e:
            print(f"Error parsing final Vault status: {e}")
            return False

    def ensure_vault_unsealed(self, timeout=30, poll_interval=2):
        print("Checking Vault state...")
        pod = self.get_pod_by_name(self.config.NS_COMMON, "vault")

        if not pod:
            print("Vault pod not found")
            return False

        data, status_error = self._read_vault_status(pod, self.config.NS_COMMON)
        if not data:
            ensure_vault_keys_file = getattr(self.config, "ensure_vault_keys_file", None)
            vault_keys_path = ensure_vault_keys_file() if callable(ensure_vault_keys_file) else self.config.vault_keys_path()
            if not os.path.exists(vault_keys_path):
                print(f"Could not get Vault status: {status_error}")
                return False
            print(f"Vault status temporarily unavailable ({status_error}); trying existing unseal key")
            data = {"initialized": True, "sealed": True}

        if not data.get("initialized"):
            print("Vault not initialized")
            return False

        if data.get("sealed"):
            print("Vault sealed. Running unseal...")
            ensure_vault_keys_file = getattr(self.config, "ensure_vault_keys_file", None)
            vault_keys_path = ensure_vault_keys_file() if callable(ensure_vault_keys_file) else self.config.vault_keys_path()
            with open(vault_keys_path) as f:
                keys = json.load(f)
            unseal_key = keys["unseal_keys_hex"][0]
            unseal_result = self.run(
                f"kubectl exec {pod} -n {self.config.NS_COMMON} -- vault operator unseal {unseal_key}",
                check=False,
            )
            if unseal_result is None:
                print("Vault unseal command failed")
                return False
        else:
            print("Vault already unsealed")

        deadline = time.time() + max(int(timeout), 1)
        while time.time() <= deadline:
            final_data, _ = self._read_vault_status(pod, self.config.NS_COMMON)
            if final_data and final_data.get("initialized") and not final_data.get("sealed"):
                print("Vault ready and unsealed")
                return True
            time.sleep(max(poll_interval, 1))

        print("Vault did not become ready and unsealed in time")
        return False

    def sync_vault_token_to_deployer_config(self):
        print("\nSynchronizing Vault token with deployer config...")
        return self.reconcile_vault_state_for_local_runtime()

    @staticmethod
    def _read_vault_token_from_deployer_config(config_path):
        try:
            with open(config_path, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if line.startswith("VT_TOKEN="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            return None
        return None

    def _vault_keys_artifact_path(self):
        ensure_vault_keys_file = getattr(self.config, "ensure_vault_keys_file", None)
        return ensure_vault_keys_file() if callable(ensure_vault_keys_file) else self.config.vault_keys_path()

    @staticmethod
    def _read_vault_keys_artifact(vault_json_path):
        if not vault_json_path or not os.path.exists(vault_json_path):
            return None, "missing"
        try:
            with open(vault_json_path, encoding="utf-8") as handle:
                return json.load(handle), None
        except json.JSONDecodeError:
            return None, "corrupted"
        except OSError as exc:
            return None, str(exc)

    def _write_vault_token_to_deployer_config(self, config_path, token):
        if not token:
            return False
        try:
            self._write_key_value_updates(config_path, {"VT_TOKEN": token}, ("VT_TOKEN",))
        except OSError as exc:
            print(f"Error writing {config_path}: {exc}")
            return False
        return True

    def _write_vault_keys_artifact_transactionally(self, vault_json_path, vault_data, pod_name, namespace):
        if not vault_json_path or not vault_data:
            return False

        token = vault_data.get("root_token")
        if not token:
            return False

        with tempfile.TemporaryDirectory(prefix="pionera-vault-artifact-") as temp_dir:
            backup_path = None
            if os.path.exists(vault_json_path):
                backup_path = os.path.join(temp_dir, "init-keys-vault.backup.json")
                shutil.copy2(vault_json_path, backup_path)

            temp_path = os.path.join(temp_dir, "init-keys-vault.json")
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(vault_data, handle, indent=2)
                handle.write("\n")

            os.makedirs(os.path.dirname(vault_json_path), exist_ok=True)
            os.replace(temp_path, vault_json_path)

            if self._vault_root_token_valid(pod_name, namespace, token):
                return True

            if backup_path and os.path.exists(backup_path):
                os.replace(backup_path, vault_json_path)
            elif os.path.exists(vault_json_path):
                os.remove(vault_json_path)
            return False

    def reconcile_vault_state_for_local_runtime(self, pod_name=None, namespace=None, quiet=False):
        """Keep the shared local Vault token artifact and deployer.config aligned.

        Vault does not expose the root token after initialization. This method
        only reconciles already available local sources that validate against
        the running Vault, and never logs token values.
        """
        namespace = namespace or self.config.NS_COMMON
        vault_json_path = self._vault_keys_artifact_path()
        config_path = self._vault_token_deployer_config_path()

        if not quiet:
            print("Reconciling shared Vault token state...")

        pod_name = pod_name or self.get_pod_by_name(namespace, "vault")
        if not pod_name:
            if not quiet:
                print(f"Vault pod not found in namespace {namespace}")
            return False

        vault_data, vault_error = self._read_vault_keys_artifact(vault_json_path)
        artifact_token = (vault_data or {}).get("root_token")
        config_token = self._read_vault_token_from_deployer_config(config_path)

        if artifact_token and self._vault_root_token_valid(pod_name, namespace, artifact_token):
            if not self._write_vault_token_to_deployer_config(config_path, artifact_token):
                return False
            if not quiet:
                print("Vault token synchronized from shared artifact")
            return True

        if config_token and self._vault_root_token_valid(pod_name, namespace, config_token):
            if vault_data and vault_data.get("unseal_keys_hex"):
                repaired_data = dict(vault_data)
                repaired_data["root_token"] = config_token
                if not self._write_vault_keys_artifact_transactionally(
                    vault_json_path,
                    repaired_data,
                    pod_name,
                    namespace,
                ):
                    if not quiet:
                        print("Could not repair shared Vault keys artifact transactionally")
                    return False
                if not quiet:
                    print("Shared Vault keys artifact repaired from valid deployer.config token")
            elif not quiet:
                print(
                    "Valid Vault token found in deployer.config, but the shared keys artifact "
                    f"is {vault_error or 'missing unseal keys'} and cannot be fully rebuilt automatically"
                )

            if not self._write_vault_token_to_deployer_config(config_path, config_token):
                return False
            if not quiet:
                print("Vault token synchronized from deployer.config")
            return True

        if not quiet:
            print(
                "No valid local Vault token candidate was found. The running Vault and local "
                "artifacts are out of sync."
            )
        return False

    def _vault_token_deployer_config_path(self):
        infrastructure_config_path = getattr(self.config, "infrastructure_deployer_config_path", None)
        if callable(infrastructure_config_path):
            candidate = infrastructure_config_path()
            if os.path.exists(candidate):
                return candidate
        return self.config.deployer_config_path()

    def show_correspondence_table(self, values, config):
        rows = []

        def status(expected, current):
            return "OK" if expected == current else "DIFF"

        def add_row_value(logical_var, values_path, expected_value, current_value):
            rows.append([
                logical_var,
                values_path,
                expected_value,
                current_value,
                status(expected_value, current_value)
            ])

        def add_row(logical_var, values_path, config_var, current_value):
            add_row_value(logical_var, values_path, config.get(config_var), current_value)

        add_row("PG_PASSWORD", "postgresql.auth.postgresPassword", "PG_PASSWORD", values["postgresql"]["auth"]["postgresPassword"])
        add_row("PG_PASSWORD", "keycloak.externalDatabase.password", "PG_PASSWORD", values["keycloak"]["externalDatabase"]["password"])
        add_row("KC_USER", "keycloak.auth.adminUser", "KC_USER", values["keycloak"]["auth"]["adminUser"])
        add_row("KC_PASSWORD", "keycloak.auth.adminPassword", "KC_PASSWORD", values["keycloak"]["auth"]["adminPassword"])
        expected_proxy = self._expected_keycloak_proxy(values)
        if expected_proxy:
            add_row_value(
                "KEYCLOAK_HTTP_PROXY",
                "keycloak.proxy",
                expected_proxy,
                values.get("keycloak", {}).get("proxy", ""),
            )
            for ingress_key in ("ingress", "adminIngress"):
                add_row_value(
                    "KEYCLOAK_HTTP_COOKIE_FLAGS",
                    f"keycloak.{ingress_key}.annotations.{self.KEYCLOAK_HTTP_COOKIE_ANNOTATION}",
                    self.KEYCLOAK_HTTP_COOKIE_SNIPPET,
                    (
                        values.get("keycloak", {})
                        .get(ingress_key, {})
                        .get("annotations", {})
                        .get(self.KEYCLOAK_HTTP_COOKIE_ANNOTATION, "")
                    ),
                )
        minio_user, minio_password = self._minio_admin_credentials(config)
        minio_values = values.get("minio", {})
        add_row_value("MINIO_USER", "minio.rootUser", minio_user, minio_values.get("rootUser"))
        add_row_value("MINIO_PASSWORD", "minio.rootPassword", minio_password, minio_values.get("rootPassword"))
        domain_base = config.get("DOMAIN_BASE")
        if domain_base:
            common_hostnames = canonical_common_service_hostnames(domain_base)
            add_row_value(
                "DOMAIN_BASE",
                "keycloak.ingress.hostname",
                common_hostnames["keycloak_hostname"],
                values["keycloak"]["ingress"]["hostname"],
            )
            add_row_value(
                "DOMAIN_BASE",
                "keycloak.adminIngress.hostname",
                common_hostnames["keycloak_admin_hostname"],
                values["keycloak"]["adminIngress"]["hostname"],
            )
            add_row_value(
                "DOMAIN_BASE",
                "minio.ingress.hosts",
                common_hostnames["minio_hostname"],
                values.get("minio", {}).get("ingress", {}).get("hosts", [""])[0]
                if values.get("minio", {}).get("ingress", {}).get("hosts")
                else "",
            )
            add_row_value(
                "DOMAIN_BASE",
                "minio.consoleIngress.hosts",
                common_hostnames["minio_console_hostname"],
                values.get("minio", {}).get("consoleIngress", {}).get("hosts", [""])[0]
                if values.get("minio", {}).get("consoleIngress", {}).get("hosts")
                else "",
            )


        for item in values["keycloak"]["keycloakConfigCli"]["extraEnv"]:
            if item["name"] == "KEYCLOAK_USER":
                add_row("KC_USER", "keycloakConfigCli.KEYCLOAK_USER", "KC_USER", item["value"])
            if item["name"] == "KEYCLOAK_PASSWORD":
                add_row("KC_PASSWORD", "keycloakConfigCli.KEYCLOAK_PASSWORD", "KC_PASSWORD", item["value"])

        print("\nConfiguration synchronization: deployer.config -> common/values.yaml\n")
        print(tabulate(rows, headers=["DEPLOYER.CONFIG", "COMMON/VALUES.YAML", "EXPECTED", "FOUND", "STATUS"], tablefmt="grid"))
        print()
        return any(row[4] == "DIFF" for row in rows)

    def apply_sync(self, values, config):
        pg_password = config.get("PG_PASSWORD")
        kc_user = config.get("KC_USER")
        kc_password = config.get("KC_PASSWORD")
        minio_user, minio_password = self._minio_admin_credentials(config)

        values["postgresql"]["auth"]["postgresPassword"] = pg_password
        values["postgresql"]["auth"]["password"] = pg_password
        values["keycloak"]["externalDatabase"]["password"] = pg_password
        values["keycloak"]["auth"]["adminUser"] = kc_user
        values["keycloak"]["auth"]["adminPassword"] = kc_password
        self._apply_keycloak_proxy_policy(values)
        values.setdefault("minio", {})
        if minio_user:
            values["minio"]["rootUser"] = minio_user
        if minio_password:
            values["minio"]["rootPassword"] = minio_password

        domain_base = config.get("DOMAIN_BASE")
        if domain_base:
            common_hostnames = canonical_common_service_hostnames(domain_base)
            values["keycloak"]["ingress"]["hostname"] = common_hostnames["keycloak_hostname"]
            values["keycloak"]["adminIngress"]["hostname"] = common_hostnames["keycloak_admin_hostname"]
            
            master_json_str = values["keycloak"]["keycloakConfigCli"]["configuration"]["master.json"]
            try:
                import json
                master_json_data = json.loads(master_json_str)
                if "attributes" not in master_json_data:
                    master_json_data["attributes"] = {}
                master_json_data["attributes"]["frontendUrl"] = (
                    f"http://{common_hostnames['keycloak_admin_hostname']}"
                )
                values["keycloak"]["keycloakConfigCli"]["configuration"]["master.json"] = json.dumps(master_json_data, indent=2)
            except Exception as e:
                print(f"Warning: Could not update frontendUrl in master.json: {e}")

            if "minio" in values and "ingress" in values["minio"]:
                values["minio"]["ingress"]["hosts"] = [common_hostnames["minio_hostname"]]
            if "minio" in values and "consoleIngress" in values["minio"]:
                values["minio"]["consoleIngress"]["hosts"] = [common_hostnames["minio_console_hostname"]]

            # Also update TLS hosts if they exist
            if "extraTls" in values["keycloak"]["ingress"]:
                for tls in values["keycloak"]["ingress"]["extraTls"]:
                    tls["hosts"] = [common_hostnames["keycloak_hostname"]]
            if "extraTls" in values["keycloak"]["adminIngress"]:
                for tls in values["keycloak"]["adminIngress"]["extraTls"]:
                    tls["hosts"] = [common_hostnames["keycloak_admin_hostname"]]


        for item in values["keycloak"]["keycloakConfigCli"]["extraEnv"]:
            if item["name"] == "KEYCLOAK_USER":
                item["value"] = kc_user
            if item["name"] == "KEYCLOAK_PASSWORD":
                item["value"] = kc_password

        return values

    def sync_common_values(self):
        ensure_values_file = getattr(self.config, "ensure_common_values_file", None)
        values_path = ensure_values_file() if callable(ensure_values_file) else self.config.values_path()
        config_path = self.config.deployer_config_path()
        ds_name = self._dataspace_name()

        if not os.path.exists(values_path):
            print("File not found: common/values.yaml")
            return

        config = self.config_adapter.load_deployer_config()
        if not config:
            print("File not found: deployer.config")
            return
        with open(values_path) as f:
            values = yaml_ruamel.load(f)

        has_diffs = self.show_correspondence_table(values, config)

        if has_diffs:
            if self._auto_mode():
                choice = "Y"
                print("[AUTO_MODE] Automatically applying detected changes")
            else:
                choice = input("Apply detected changes? (Y/N): ").strip().upper()

            if choice == "Y":
                values = self.apply_sync(values, config)
                master_json = values["keycloak"]["keycloakConfigCli"]["configuration"]["master.json"]
                values["keycloak"]["keycloakConfigCli"]["configuration"]["master.json"] = LiteralScalarString(master_json)
                with open(values_path, "w") as f:
                    yaml_ruamel.dump(values, f)
                print("Configuration synchronized\n")
            else:
                print("No changes applied\n")
                return
        else:
            print("No differences found\n")

        hosts = self.config_adapter.generate_hosts(ds_name)
        print("Hosts entries to add to your system:\n")
        for host in hosts:
            print(host)
        print()

    def _secret_value(self, namespace, secret_name, key):
        value = self.run_silent(
            f"kubectl get secret {secret_name} -n {namespace} "
            f"-o jsonpath='{{.data.{key}}}'"
        )
        if not value:
            return None

        decoded = self.run_silent(f"printf '%s' '{value}' | base64 -d")
        return decoded if decoded is not None else None

    def _common_credentials_deployer_config_path(self):
        infrastructure_config_path = getattr(self.config, "infrastructure_deployer_config_path", None)
        if callable(infrastructure_config_path):
            return infrastructure_config_path()
        return self.config.deployer_config_path()

    @staticmethod
    def _read_key_value_file(path):
        values = {}
        if not path or not os.path.isfile(path):
            return values
        try:
            with open(path, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
        except OSError:
            return values
        return values

    @staticmethod
    def _write_key_value_updates(path, updates, preferred_order):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = []
        seen = set()
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.rstrip("\n")
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key, _value = stripped.split("=", 1)
                        key = key.strip()
                        if key in updates:
                            lines.append(f"{key}={updates[key]}\n")
                            seen.add(key)
                            continue
                    lines.append(raw_line if raw_line.endswith("\n") else f"{raw_line}\n")

        ordered_keys = [key for key in preferred_order if key in updates and key not in seen]
        ordered_keys.extend(sorted(key for key in updates if key not in seen and key not in ordered_keys))
        for key in ordered_keys:
            lines.append(f"{key}={updates[key]}\n")

        with open(path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)

    def sync_common_credentials_from_kubernetes(self):
        """Recover local common-service credentials from the running cluster.

        Level 3 must talk to the already deployed common services. If local
        deployer.config was copied from examples or another checkout, the
        Kubernetes secrets are the effective source of truth until Level 2 is
        recreated.
        """
        config_path = self._common_credentials_deployer_config_path()
        current = self._read_key_value_file(config_path)

        recovered = {
            "PG_PASSWORD": self._secret_value(
                self.config.NS_COMMON,
                "common-srvs-postgresql",
                "postgres-password",
            ),
            "KC_USER": self._secret_value(
                self.config.NS_COMMON,
                "common-srvs-keycloak",
                "admin-user",
            ),
            "KC_PASSWORD": self._secret_value(
                self.config.NS_COMMON,
                "common-srvs-keycloak",
                "admin-password",
            ),
            "MINIO_USER": self._secret_value(
                self.config.NS_COMMON,
                "common-srvs-minio",
                "rootUser",
            ),
            "MINIO_PASSWORD": self._secret_value(
                self.config.NS_COMMON,
                "common-srvs-minio",
                "rootPassword",
            ),
        }
        recovered["MINIO_ADMIN_USER"] = recovered["MINIO_USER"]
        recovered["MINIO_ADMIN_PASS"] = recovered["MINIO_PASSWORD"]

        updates = {}
        for key, value in recovered.items():
            if value in (None, ""):
                continue
            if current.get(key) != value:
                updates[key] = value

        domain_base = str(current.get("DOMAIN_BASE") or "").strip()
        if domain_base:
            expected_access = canonical_common_service_config_values(domain_base)
            for key, value in expected_access.items():
                if current.get(key) != value:
                    updates[key] = value

        if not updates:
            return False

        try:
            self._write_key_value_updates(config_path, updates, self.COMMON_CREDENTIAL_KEYS)
        except OSError as exc:
            print(f"Warning: could not synchronize local common credentials: {exc}")
            return False

        print(
            "Synchronized local common service credentials from Kubernetes secrets: "
            + ", ".join(sorted(updates))
        )
        return True

    def _common_services_release_status(self):
        release_name = self.config.helm_release_common()
        namespace = self.config.NS_COMMON
        result = self.run_silent(
            f"helm status {shlex.quote(str(release_name))} -n {shlex.quote(str(namespace))} -o json"
        )
        if result:
            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                payload = None
            if payload:
                info = payload.get("info", {}) or {}
                status = info.get("status") or payload.get("status")
                if status:
                    return str(status).strip().lower()

        result = self.run_silent(
            f"helm status {shlex.quote(str(release_name))} -n {shlex.quote(str(namespace))}"
        )
        if not result:
            return None

        for line in result.splitlines():
            if line.strip().upper().startswith("STATUS:"):
                return line.split(":", 1)[1].strip().lower() or "unknown"
        return "unknown"

    def common_services_release_status(self):
        return self._common_services_release_status()

    def _common_services_release_exists(self):
        return self._common_services_release_status() is not None

    def _common_services_has_only_ignored_hook_issues(self):
        namespace = str(getattr(self.config, "NS_COMMON", "") or "").strip()
        if not namespace:
            return False

        result = self.run_silent(f"kubectl get pods -n {shlex.quote(namespace)} --no-headers")
        if not result:
            return False

        observed_relevant_pod = False
        observed_ignored_hook = False

        for line in result.splitlines():
            columns = line.split()
            if len(columns) < 3:
                continue

            name = columns[0]
            ready = columns[1] if len(columns) > 1 else ""
            status = columns[2]

            if self._is_ignored_transient_hook_pod(namespace, name):
                observed_ignored_hook = True
                continue

            if status in ["CrashLoopBackOff", "Error", "ImagePullBackOff"]:
                return False

            if status == "Completed":
                continue

            observed_relevant_pod = True

            if status != "Running":
                return False

            if "/" in ready:
                ready_current, ready_total = ready.split("/", 1)
                if ready_current != ready_total:
                    return False
            elif not ready:
                return False

        return observed_relevant_pod and observed_ignored_hook

    def _common_services_release_recoverable_after_helm_failure(self):
        status = self._common_services_release_status()
        if status is None:
            return False

        if status != "failed":
            return False

        print(
            "Helm reported a common services failure. Checking whether only ignored hook "
            "pods remain outside the ready set..."
        )

        if not self._common_services_has_only_ignored_hook_issues():
            return False

        print(
            "Helm reported a failed common services release, but only ignored hook pods "
            "remain outside the ready set. Continuing with framework-level checks."
        )
        return True

    def _common_services_has_terminal_runtime_errors(self):
        namespace = str(getattr(self.config, "NS_COMMON", "") or "").strip()
        if not namespace:
            return False

        result = self.run_silent(f"kubectl get pods -n {shlex.quote(namespace)} --no-headers")
        if not result:
            return False

        terminal_statuses = {
            "CrashLoopBackOff",
            "Error",
            "ImagePullBackOff",
            "ErrImagePull",
            "CreateContainerConfigError",
            "CreateContainerError",
            "RunContainerError",
        }

        for line in result.splitlines():
            columns = line.split()
            if len(columns) < 3:
                continue

            name = columns[0]
            status = columns[2]

            if self._is_ignored_transient_hook_pod(namespace, name):
                continue

            if status in terminal_statuses:
                return True

        return False

    def _repair_failed_common_services_helm_release(self, values_path, common_dir):
        status = self._common_services_release_status()
        if status != "failed":
            return True

        if self._common_services_release_recoverable_after_helm_failure():
            print(
                "Skipping Helm release repair because runtime services are healthy and "
                "only ignored hook pods remain outside the ready set."
            )
            return True

        print(
            "\nCommon services are running, but Helm still marks release "
            f"'{self.config.helm_release_common()}' as failed."
        )
        print("Re-running Helm after runtime readiness to reconcile release status...")

        repair_timeout = max(int(getattr(self.config, "TIMEOUT_POD_WAIT", 120)), 180)
        repaired = self.deploy_helm_release(
            self.config.helm_release_common(),
            self.config.NS_COMMON,
            values_path,
            cwd=common_dir,
            wait=False,
            timeout_seconds=repair_timeout,
        )
        if not repaired:
            print("Helm release status repair failed")
            return False

        status = self._common_services_release_status()
        if status != "deployed":
            print(f"Helm release status is still {status or 'unknown'} after repair")
            return False

        print("Helm release status recovered to deployed")
        return True

    def _begin_temporary_vault_keys_backup_for_repair(self):
        self.finalize_local_common_services_reset(success=True)
        vault_json_path = self._vault_keys_artifact_path()
        if not vault_json_path or not os.path.exists(vault_json_path):
            return None

        temp_dir = tempfile.TemporaryDirectory(prefix="pionera-vault-repair-")
        backup_path = os.path.join(temp_dir.name, "init-keys-vault.json")
        shutil.move(vault_json_path, backup_path)
        self._vault_repair_temp_backup = {
            "temp_dir": temp_dir,
            "backup_path": backup_path,
            "original_path": vault_json_path,
        }
        print("Temporarily moved stale Vault keys artifact for repair")
        return backup_path

    def finalize_local_common_services_reset(self, success=True):
        backup = getattr(self, "_vault_repair_temp_backup", None)
        if not backup:
            return

        temp_dir = backup.get("temp_dir")
        backup_path = backup.get("backup_path")
        original_path = backup.get("original_path")
        try:
            if not success and backup_path and original_path and os.path.exists(backup_path) and not os.path.exists(original_path):
                os.makedirs(os.path.dirname(original_path), exist_ok=True)
                shutil.move(backup_path, original_path)
                print("Restored previous Vault keys artifact after failed repair")
        finally:
            if temp_dir:
                temp_dir.cleanup()
            self._vault_repair_temp_backup = None

    def finalize_common_services_level4_repair(self, success=True):
        self.finalize_local_common_services_reset(success=success)

    def _wait_for_namespace_absent(self, namespace, timeout=120, poll_interval=3):
        deadline = time.time() + max(int(timeout), 1)
        namespace_arg = shlex.quote(str(namespace))
        while time.time() <= deadline:
            result = self.run_silent(f"kubectl get namespace {namespace_arg} --no-headers")
            if not result:
                return True
            time.sleep(max(int(poll_interval), 1))
        print(f"Namespace '{namespace}' did not disappear in time")
        return False

    def reset_local_shared_common_services(self, reason=None):
        print("\nResetting local shared common services...")
        if reason:
            print(f"Reset reason: {reason}")
        print("This removes the local common-srvs namespace and regenerates Vault credentials on the next Level 2 run.")

        self.stop_port_forward_service(self.config.NS_COMMON, "postgresql", quiet=True)
        self.stop_port_forward_service(self.config.NS_COMMON, "vault", quiet=True)
        self.stop_port_forward_service(self.config.NS_COMMON, "minio", quiet=True)
        self._begin_temporary_vault_keys_backup_for_repair()

        release_arg = shlex.quote(str(self.config.helm_release_common()))
        namespace_arg = shlex.quote(str(self.config.NS_COMMON))
        self.run(f"helm uninstall {release_arg} -n {namespace_arg}", check=False)
        self.run(f"kubectl delete namespace {namespace_arg} --ignore-not-found=true", check=False)

        if not self._wait_for_namespace_absent(self.config.NS_COMMON):
            self.finalize_local_common_services_reset(success=False)
            return False

        print("Local shared common services reset completed")
        return True

    def reset_common_services_for_level4_repair(self, reason=None):
        return self.reset_local_shared_common_services(reason=reason)

    def _common_services_config_drift(self):
        if not self._common_services_release_exists():
            return []

        config = self.config_adapter.load_deployer_config()
        expected_pg_password = config.get("PG_PASSWORD")
        expected_kc_password = config.get("KC_PASSWORD")
        expected_minio_user, expected_minio_password = self._minio_admin_credentials(config)

        drift = []

        actual_pg_password = self._secret_value(
            self.config.NS_COMMON, "common-srvs-postgresql", "postgres-password"
        )
        if actual_pg_password and expected_pg_password and actual_pg_password != expected_pg_password:
            drift.append("PostgreSQL secret does not match PG_PASSWORD from deployer.config")

        actual_kc_password = self._secret_value(
            self.config.NS_COMMON, "common-srvs-keycloak", "admin-password"
        )
        if actual_kc_password and expected_kc_password and actual_kc_password != expected_kc_password:
            drift.append("Keycloak secret does not match KC_PASSWORD from deployer.config")

        actual_minio_user = self._secret_value(
            self.config.NS_COMMON, "common-srvs-minio", "rootUser"
        )
        if actual_minio_user and expected_minio_user and actual_minio_user != expected_minio_user:
            drift.append("MinIO secret does not match MINIO_USER from deployer.config")

        actual_minio_password = self._secret_value(
            self.config.NS_COMMON, "common-srvs-minio", "rootPassword"
        )
        if actual_minio_password and expected_minio_password and actual_minio_password != expected_minio_password:
            drift.append("MinIO secret does not match MINIO_PASSWORD from deployer.config")

        return drift

    def reconcile_common_services_source_of_truth(self):
        drift = self._common_services_config_drift()
        if not drift:
            return

        print("\nDetected configuration drift in deployed common services:")
        for item in drift:
            print(f"- {item}")

        print("\nRecreating common services so deployer.config becomes the effective source of truth...")
        self.stop_port_forward_service(self.config.NS_COMMON, "postgresql", quiet=True)
        self.stop_port_forward_service(self.config.NS_COMMON, "vault", quiet=True)
        self.stop_port_forward_service(self.config.NS_COMMON, "minio", quiet=True)

        self.run(
            f"helm uninstall {self.config.helm_release_common()} -n {self.config.NS_COMMON}",
            check=False,
        )
        self.run(
            f"kubectl delete pvc --all -n {self.config.NS_COMMON}",
            check=False,
        )
        self.run(
            f"kubectl delete secret common-srvs-postgresql common-srvs-keycloak common-srvs-minio -n {self.config.NS_COMMON}",
            check=False,
        )
        time.sleep(5)

    def ensure_local_infra_access(self):
        print("\nVerifying local access to PostgreSQL, Vault and MinIO...")
        full_timeout = max(int(getattr(self.config, "TIMEOUT_PORT", 30)), 1)
        probe_timeout = max(min(3, full_timeout), 1)

        if not self._ensure_local_postgres_access(full_timeout, probe_timeout):
            return False

        vault_ok, _ = self._ensure_local_service_access(
            "Vault",
            self.config.NS_COMMON,
            "vault",
            self.config.PORT_VAULT,
            8200,
            probe_timeout=probe_timeout,
            wait_timeout=full_timeout,
        )
        if not vault_ok:
            return False

        minio_ok, _ = self._ensure_local_service_access(
            "MinIO",
            self.config.NS_COMMON,
            "minio",
            getattr(self.config, "PORT_MINIO", 9000),
            9000,
            probe_timeout=probe_timeout,
            wait_timeout=full_timeout,
        )
        if not minio_ok:
            return False

        print("Local infrastructure OK\n")
        return True

    def wait_for_registration_service_schema(self, timeout=None, poll_interval=3, quiet=False):
        timeout = timeout or self.config.TIMEOUT_POD_WAIT
        if not quiet:
            print("\nWaiting for registration-service schema to be ready...")
        start = time.time()
        next_progress = start + max(float(poll_interval) * 5, 15)
        pg_host, pg_user, pg_password = self.config_adapter.get_pg_credentials()
        pg_port = self._configured_pg_port()
        registration_db = self.config.registration_db_name()
        sql = "SELECT to_regclass('public.edc_participant');"

        while time.time() - start <= timeout:
            result = self.run_silent(
                f"PGPASSWORD={shlex.quote(str(pg_password))} psql -h {shlex.quote(str(pg_host))} "
                f"-p {shlex.quote(str(pg_port))} -U {shlex.quote(str(pg_user))} "
                f"-d {registration_db} -t -A -c \"{sql}\""
            )

            if result and result.strip() == "edc_participant":
                if not quiet:
                    print("registration-service schema ready: public.edc_participant exists")
                return True

            if not quiet and time.time() >= next_progress:
                elapsed = int(time.time() - start)
                print(f"registration-service schema not ready yet ({elapsed}s elapsed)...")
                next_progress = time.time() + max(float(poll_interval) * 5, 15)

            time.sleep(poll_interval)

        if not quiet:
            print("Timeout waiting for registration-service schema readiness")
            self.run(
                f"PGPASSWORD={shlex.quote(str(pg_password))} psql -h {shlex.quote(str(pg_host))} "
                f"-p {shlex.quote(str(pg_port))} -U {shlex.quote(str(pg_user))} "
                f"-d {registration_db} -c \"\\dt public.*\"",
                check=False,
                silent=True,
            )
        return False

    def wait_for_registration_service_liquibase(self, timeout=None, poll_interval=3):
        timeout = timeout or self.config.TIMEOUT_POD_WAIT
        local_port = self.config.PORT_REGISTRATION_SERVICE
        namespace = self._registration_service_namespace()
        created_port_forward = False
        last_issue = None
        next_progress = None

        try:
            local_timeout = max(int(getattr(self.config, "TIMEOUT_PORT", 30)), 1)
            actuator_ok, created_port_forward = self._ensure_local_service_access(
                "registration-service actuator",
                namespace,
                "registration-service",
                local_port,
                8080,
                quiet=True,
                probe_timeout=min(2, local_timeout),
                wait_timeout=local_timeout,
            )
            if not actuator_ok:
                self._last_registration_service_liquibase_issue = (
                    "temporary port-forward to registration-service actuator could not be established"
                )
                return False

            endpoint = f"http://127.0.0.1:{local_port}/api/actuator/liquibase"
            start = time.time()
            next_progress = start + max(float(poll_interval) * 5, 15)
            print("\nWaiting for registration-service Liquibase actuator...")

            while time.time() - start <= timeout:
                try:
                    response = requests.get(endpoint, timeout=5)
                    if response.status_code == 200:
                        payload = response.json()
                        if "liquibaseBeans" in payload:
                            self._last_registration_service_liquibase_issue = None
                            return True
                        last_issue = "liquibaseBeans not present in actuator response"
                    else:
                        last_issue = f"registration-service actuator returned HTTP {response.status_code}"
                except Exception:
                    last_issue = "registration-service actuator did not respond in time"

                if time.time() >= next_progress:
                    elapsed = int(time.time() - start)
                    detail = f" Last issue: {last_issue}" if last_issue else ""
                    print(f"registration-service Liquibase actuator not ready yet ({elapsed}s elapsed).{detail}")
                    next_progress = time.time() + max(float(poll_interval) * 5, 15)

                time.sleep(poll_interval)

            self._last_registration_service_liquibase_issue = last_issue or "registration-service actuator did not confirm Liquibase readiness"
            return False
        finally:
            if created_port_forward:
                self.stop_port_forward_service(namespace, "registration-service", quiet=True)

    def wait_for_kubernetes_ready(self, timeout=180):
        print("\nWaiting for Kubernetes cluster to become ready...\n")
        start = time.time()

        while True:
            nodes = self.run_silent("kubectl get nodes")
            if nodes and " Ready " in nodes:
                print("Kubernetes node is Ready\n")
                return True

            if time.time() - start > timeout:
                print("Timeout waiting for Kubernetes node readiness")
                return False

            time.sleep(3)
    def _pod_snapshot(self, namespace):
        result = self.run_silent(f"kubectl get pods -n {namespace} --no-headers")
        if not result:
            return []

        snapshot = []
        for line in result.splitlines():
            columns = line.split()
            if len(columns) < 4:
                continue
            snapshot.append({
                "name": columns[0],
                "ready": columns[1],
                "status": columns[2],
                "restarts": columns[3],
            })
        return snapshot

    def wait_for_namespace_stability(self, namespace, duration=15, poll_interval=3, timeout=None):
        """Observe namespace health during a stability window."""
        print(f"\nObserving namespace '{namespace}' stability for {duration}s...")
        last_issue = None
        stable_since = None
        timeout = max(timeout or getattr(self.config, "TIMEOUT_NAMESPACE", 90), duration * 3)
        deadline = time.time() + timeout

        while time.time() < deadline:
            snapshot = self._pod_snapshot(namespace)
            if not snapshot:
                last_issue = f"no pods found in namespace '{namespace}'"
                stable_since = None
                time.sleep(poll_interval)
                continue

            unhealthy = []
            relevant_pods = []
            for pod in snapshot:
                # Ignore known transient hook jobs so the stability window
                # tracks the long-lived service pods instead.
                if self._is_ignored_transient_hook_pod(namespace, pod["name"]):
                    continue

                relevant_pods.append(pod)

            if not relevant_pods:
                last_issue = f"no relevant pods found in namespace '{namespace}'"
                stable_since = None
                time.sleep(poll_interval)
                continue

            for pod in relevant_pods:
                if pod["status"] not in ("Running", "Completed"):
                    unhealthy.append(f"{pod['name']} ({pod['status']})")
                    continue

                if pod["status"] == "Running" and "/" in pod["ready"]:
                    ready_current, ready_total = pod["ready"].split("/", 1)
                    if ready_current != ready_total:
                        unhealthy.append(f"{pod['name']} readiness {pod['ready']}")

            if unhealthy:
                last_issue = ", ".join(unhealthy)
                stable_since = None
                time.sleep(poll_interval)
                continue

            if stable_since is None:
                stable_since = time.time()
                last_issue = None

            if time.time() - stable_since >= duration:
                print(f"Namespace '{namespace}' is stable\n")
                return True

            time.sleep(poll_interval)

        if last_issue:
            print(f"Namespace '{namespace}' failed stability window: {last_issue}")
            self.run(f"kubectl get pods -n {namespace}", check=False)
            return False

        print(f"Namespace '{namespace}' did not achieve a continuous {duration}s stability window in time")
        self.run(f"kubectl get pods -n {namespace}", check=False)
        return False

    def verify_cluster_ready_for_level2(self, cluster_runtime=None):
        """Ensure Level 1 leaves a cluster stable enough for Level 2."""
        ingress_ready_timeout = max(int(getattr(self.config, "TIMEOUT_POD_WAIT", 120)), 300)
        ingress_stability_timeout = max(int(getattr(self.config, "TIMEOUT_NAMESPACE", 90)), 180)
        runtime = dict(cluster_runtime or self._cluster_runtime_config())
        cluster_type = str(runtime.get("cluster_type") or "minikube").strip().lower()

        if cluster_type == "k3s":
            service_name = str(runtime.get("k3s_service_name") or "k3s").strip() or "k3s"
            if self.run_silent(f"systemctl is-active {shlex.quote(service_name)}") != "active":
                return False, f"{service_name} service is not active"
        else:
            status = self.run_silent("minikube status --output=json")
            if not status:
                return False, "minikube status unavailable"

            try:
                status_data = json.loads(status)
            except json.JSONDecodeError:
                return False, "minikube status output is not valid JSON"

            for key in ("Host", "Kubelet", "APIServer"):
                value = str(status_data.get(key, "")).lower()
                if value != "running":
                    return False, f"{key} is '{status_data.get(key)}'"

        nodes = self.run_silent("kubectl get nodes --no-headers")
        if not nodes or " Ready " not in f" {nodes} ":
            return False, "kubectl does not report a Ready node"

        if not self.wait_for_pods("ingress-nginx", timeout=ingress_ready_timeout):
            return False, "ingress-nginx pods did not become ready"

        if not self.wait_for_namespace_stability(
            "ingress-nginx",
            duration=10,
            poll_interval=3,
            timeout=ingress_stability_timeout,
        ):
            return False, "ingress-nginx namespace did not remain stable"

        return True, None

    def verify_common_services_ready_for_level3(self):
        """Ensure Level 2 leaves common services stable enough for Level 3."""
        common_ready_timeout = max(self._common_services_startup_timeout(), 300)
        common_stability_timeout = max(int(getattr(self.config, "TIMEOUT_NAMESPACE", 90)), 180)
        release_status = self._common_services_release_status()
        if release_status is None:
            return False, "common services Helm release not found"
        if release_status and release_status != "deployed":
            if (
                release_status == "failed"
                and self._common_services_release_recoverable_after_helm_failure()
            ):
                print(
                    "Common services Helm release is failed, but the remaining issue is "
                    "limited to ignored hook pods. Continuing with readiness checks."
                )
            else:
                return False, f"common services Helm release is {release_status}"

        if not self.wait_for_level2_service_pods(
            self.config.NS_COMMON,
            timeout=common_ready_timeout,
            require_vault_ready=True,
        ):
            return False, "common services pods did not become ready"

        if not self.wait_for_namespace_stability(
            self.config.NS_COMMON,
            duration=12,
            poll_interval=3,
            timeout=common_stability_timeout,
        ):
            return False, "common services namespace did not remain stable"

        if not self.ensure_vault_unsealed():
            return False, "Vault is not initialized/unsealed"

        return True, None

    def verify_dataspace_ready_for_level4(self):
        """Ensure Level 3 leaves dataspace services stable enough for Level 4."""
        self._last_registration_service_liquibase_issue = None
        dataspace_name_getter = getattr(self.config, "dataspace_name", None)
        dataspace_name = (
            dataspace_name_getter()
            if callable(dataspace_name_getter)
            else getattr(self.config, "DS_NAME", self.config.namespace_demo())
        )
        if not self.wait_for_dataspace_level3_pods(
            self._registration_service_namespace(),
            dataspace_name=dataspace_name,
        ):
            return False, "Level 3 dataspace pods did not become ready"

        quick_schema_timeout = 15
        final_schema_timeout = 105

        if self.wait_for_registration_service_schema(
            timeout=quick_schema_timeout,
            poll_interval=3,
            quiet=True,
        ):
            print("registration-service schema ready")
            return True, None

        print("registration-service schema not ready yet. Checking Liquibase actuator...")
        self.wait_for_registration_service_liquibase(timeout=60, poll_interval=3)

        if not self.wait_for_registration_service_schema(timeout=final_schema_timeout, poll_interval=3):
            if self._last_registration_service_liquibase_issue:
                print(
                    "Registration-service Liquibase check was inconclusive: "
                    f"{self._last_registration_service_liquibase_issue}"
                )
            return False, "registration-service schema was not ready"

        return True, None

    def verify_minikube_runtime_capacity(self, runtime):
        """Fail early when the requested local profile cannot be backed by Docker."""
        requested_memory = parse_memory_quantity_mb((runtime or {}).get("memory"))
        docker_memory = parse_memory_quantity_mb(
            self.run_silent("docker info --format '{{.MemTotal}}'")
        )
        resource_profile = str((runtime or {}).get("local_resource_profile") or "").strip().lower()

        if resource_profile == "coexistence" and (
            requested_memory is None or requested_memory < LOCAL_COEXISTENCE_MEMORY_MB
        ):
            self._fail(
                "Local coexistence profile requires more Minikube memory",
                root_cause=(
                    f"Set MINIKUBE_MEMORY={LOCAL_COEXISTENCE_MEMORY_MB} in "
                    "deployers/infrastructure/topologies/local.config and rerun Level 1"
                ),
            )

        if docker_memory and requested_memory and requested_memory > docker_memory:
            self._fail(
                "Docker Desktop does not expose enough memory for the requested Minikube profile",
                root_cause=(
                    f"requested={requested_memory} MiB, docker={docker_memory} MiB. "
                    "Increase Docker Desktop resources or lower MINIKUBE_MEMORY before rerunning Level 1"
                ),
            )

        if resource_profile == "coexistence" and docker_memory and docker_memory < LOCAL_COEXISTENCE_MEMORY_MB:
            self._fail(
                "Docker Desktop memory is too low for clean local EDC/INESData coexistence",
                root_cause=(
                    f"coexistence requires at least {LOCAL_COEXISTENCE_MEMORY_MB} MiB, "
                    f"docker exposes {docker_memory} MiB"
                ),
            )

        if resource_profile == "coexistence":
            print(
                "Local coexistence resource profile enabled "
                f"({requested_memory or 'unknown'} MiB requested for Minikube)."
            )
        elif docker_memory and docker_memory < LOCAL_COEXISTENCE_MEMORY_MB:
            print(
                "Local Docker capacity supports the single-adapter profile. "
                f"Docker exposes {docker_memory} MiB; clean EDC/INESData coexistence requires "
                f"{LOCAL_COEXISTENCE_MEMORY_MB} MiB. The framework will block installing a second "
                "local adapter until resources are increased or the cluster is recreated for the other adapter."
            )
        return True

    def setup_cluster(self):
        self.announce_level(1, "CLUSTER SETUP")
        self.ensure_unix_environment()
        cluster_runtime = self._cluster_runtime_config()
        if cluster_runtime["cluster_type"] == "k3s":
            self._setup_cluster_k3s(cluster_runtime)
            self.run("kubectl get pods -n ingress-nginx", check=False)
            cluster_ready, root_cause = self.verify_cluster_ready_for_level2(cluster_runtime=cluster_runtime)
            if not cluster_ready:
                self._fail("Level 1 did not leave the cluster ready for Level 2", root_cause=root_cause)
            self.complete_level(1)
            return

        if not self.ensure_wsl_docker_config():
            self._fail("Could not adjust WSL Docker configuration safely")
        runtime = self._minikube_runtime_config()
        profile = shlex.quote(runtime["profile"])
        driver = shlex.quote(runtime["driver"])

        print("Checking Minikube installation...")
        if self.run("which minikube", capture=True) is None:
            print("Installing Minikube...")
            self.run("curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64")
            self.run("sudo install minikube-linux-amd64 /usr/local/bin/minikube")
            self.run("rm -f minikube-linux-amd64")

        self.run("minikube version")

        print("\nChecking Helm installation...")
        if self.run("which helm", capture=True) is None:
            self.run("sudo snap install helm --classic", check=False)
        self.run("helm version")

        print("\nChecking Docker...")
        if self.run("docker info", capture=True, check=False) is None:
            self._fail("Docker is not running. Start Docker and retry")

        print("Docker is running")
        self.verify_minikube_runtime_capacity(runtime)
        print("\nDeleting existing Minikube cluster (clean state)...\n")
        self.run(f"minikube delete -p {profile}", check=False)

        print("\nStarting fresh Minikube cluster...\n")
        self.run(
            f"minikube start -p {profile} --driver={driver} "
            f"--cpus={runtime['cpus']} --memory={runtime['memory']}"
        )

        if not self.wait_for_kubernetes_ready():
            self._fail("Cluster failed to initialize", root_cause="Kubernetes node did not become Ready")

        print("\nEnabling ingress addon...\n")
        if self.run_silent(f"minikube -p {profile} addons enable ingress") is None:
            print(
                "Warning: minikube reported a transient ingress addon enable failure; "
                "verifying ingress controller readiness directly."
            )
        self._patch_ingress_nginx_configmap()
        self.run("kubectl get pods -n ingress-nginx", check=False)
        cluster_ready, root_cause = self.verify_cluster_ready_for_level2()
        if not cluster_ready:
            self._fail("Level 1 did not leave the cluster ready for Level 2", root_cause=root_cause)
        self.complete_level(1)

    def _setup_cluster_k3s(self, runtime):
        kubeconfig = runtime["k3s_kubeconfig"]
        kubeconfig_q = shlex.quote(kubeconfig)
        service_name = runtime.get("k3s_service_name") or "k3s"
        service_name_q = shlex.quote(service_name)
        install_exec = runtime.get("k3s_install_exec") or "--disable=traefik"
        ingress_controller = runtime.get("k3s_ingress_controller") or "ingress-nginx"
        ingress_service_type = runtime.get("k3s_ingress_service_type") or "NodePort"
        repair_policy = str(runtime.get("k3s_repair_on_level1") or "prompt").strip().lower()
        kubeconfig_mode = runtime.get("k3s_write_kubeconfig_mode") or "0644"

        print("Cluster runtime: k3s")
        print("Checking k3s installation...")
        k3s_binary = self.run("which k3s", capture=True, check=False)
        service_ready = self.run(f"systemctl status {service_name_q} --no-pager", capture=True, check=False) is not None
        kubeconfig_ready = self.run(f"test -f {kubeconfig_q}", capture=True, check=False) is not None
        sudo_ready = self.run("sudo -n true", capture=True, check=False) is not None
        interactive_sudo_allowed = False

        if k3s_binary is None or not service_ready or not kubeconfig_ready:
            details = []
            if k3s_binary is None:
                details.append("k3s binary is missing")
            if not service_ready:
                details.append("k3s systemd service is missing or inactive")
            if not kubeconfig_ready:
                details.append(f"k3s kubeconfig is missing at {kubeconfig}")
            if not sudo_ready:
                print("k3s installation is incomplete:")
                for detail in details:
                    print(f"  - {detail}")
                if repair_policy in {"1", "true", "yes", "on", "always"}:
                    interactive_sudo_allowed = True
                elif repair_policy in {"0", "false", "no", "off", "never"}:
                    interactive_sudo_allowed = False
                else:
                    interactive_sudo_allowed = self._confirm_interactive(
                        "Install or repair k3s now using sudo?",
                        default=False,
                    )
                if not interactive_sudo_allowed:
                    self._fail(
                        "k3s is not fully installed and sudo is not available non-interactively",
                        root_cause=(
                            "; ".join(details)
                            + ". Install k3s manually, run Level 1 from the interactive menu and approve "
                            "the k3s repair prompt, or enable passwordless sudo for Level 1, then retry."
                        ),
                    )
            print(f"Installing or repairing k3s with install args: {install_exec}")
            install_exec_args = " ".join(shlex.quote(part) for part in shlex.split(install_exec))
            install_command = (
                f"curl -sfL https://get.k3s.io | sudo -n sh -s - {install_exec_args}"
                if sudo_ready
                else f"curl -sfL https://get.k3s.io | sudo sh -s - {install_exec_args}"
            )
            self.run(install_command)
        else:
            print("k3s already installed")

        self._disable_k3s_agent_for_single_node_server(
            service_name=service_name,
            sudo_ready=sudo_ready,
            interactive_sudo_allowed=interactive_sudo_allowed,
        )

        if sudo_ready:
            self.run(f"sudo -n systemctl start {service_name_q}", check=False)
        elif interactive_sudo_allowed:
            self.run(f"sudo systemctl start {service_name_q}", check=False)

        service_active = self.run(f"systemctl is-active {service_name_q}", capture=True, check=False)
        if service_active is None:
            self._fail(
                "k3s service is not active after installation or repair",
                root_cause=(
                    f"Run 'systemctl status {service_name}' and 'journalctl -xeu {service_name}' to inspect "
                    f"the failed service, then start it with 'sudo systemctl start {service_name}' and retry Level 1."
                ),
            )

        if kubeconfig:
            os.environ["KUBECONFIG"] = kubeconfig
            if self.run(f"test -r {kubeconfig_q}", capture=True, check=False) is None and sudo_ready:
                self.run(f"sudo -n chmod {shlex.quote(kubeconfig_mode)} {kubeconfig_q}", check=False)
            elif self.run(f"test -r {kubeconfig_q}", capture=True, check=False) is None and interactive_sudo_allowed:
                self.run(f"sudo chmod {shlex.quote(kubeconfig_mode)} {kubeconfig_q}", check=False)
            if self.run(f"test -r {kubeconfig_q}", capture=True, check=False) is None:
                self._fail(
                    "k3s kubeconfig is not readable",
                    root_cause=(
                        f"{kubeconfig} is not readable by the current user. Set K3S_WRITE_KUBECONFIG_MODE=0644 "
                        "or run the Level 1 repair with sudo so the framework can adjust the kubeconfig mode."
                    ),
                )
            current_context = self.run("kubectl config current-context", capture=True, check=False)
            if str(current_context or "").strip().lower() == "minikube":
                self._fail(
                    "k3s Level 1 is using the Minikube kubeconfig",
                    root_cause=(
                        f"K3S_KUBECONFIG points to {kubeconfig}, whose current context is minikube. "
                        "Set K3S_KUBECONFIG=/etc/rancher/k3s/k3s.yaml or another kubeconfig that targets k3s."
                    ),
                )

        print("\nChecking Helm installation...")
        if self.run("which helm", capture=True, check=False) is None:
            self.run("sudo snap install helm --classic", check=False)
        self.run("helm version")

        if not self.wait_for_kubernetes_ready():
            self._fail("k3s cluster failed to initialize", root_cause="Kubernetes node did not become Ready")

        print(f"\nInstalling {ingress_controller} for k3s...\n")
        self.run("helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx", check=False)
        self.run("helm repo update")
        if self.run_silent("helm status ingress-nginx -n ingress-nginx") is None:
            existing_controller = self.run_silent(
                "kubectl get deployment ingress-nginx-controller -n ingress-nginx -o name"
            )
            if existing_controller:
                print(
                    "ingress-nginx resources already exist outside Helm; "
                    "reusing them and reconciling service/configmap settings."
                )
            elif self.run(
                "helm install ingress-nginx ingress-nginx/ingress-nginx "
                "-n ingress-nginx --create-namespace "
                f"--set controller.service.type={shlex.quote(ingress_service_type)} "
                "--set controller.watchIngressWithoutClass=true "
                "--set controller.allowSnippetAnnotations=true "
                "--set controller.config.allow-snippet-annotations=true "
                "--set controller.config.annotations-risk-level=Critical "
                "--wait --timeout 180s"
            ) is None:
                self._fail("Failed to install ingress-nginx for k3s")
        else:
            print(f"{ingress_controller} already installed")

        self._patch_k3s_ingress_nginx_service(ingress_service_type)
        self._patch_ingress_nginx_configmap()

    def _disable_k3s_agent_for_single_node_server(
        self,
        *,
        service_name="k3s",
        sudo_ready=False,
        interactive_sudo_allowed=False,
    ):
        if str(service_name or "").strip() != "k3s":
            return
        if self.run("systemctl list-unit-files k3s-agent.service --no-pager", capture=True, check=False) is None:
            return

        print("Disabling residual k3s-agent service for vm-single server runtime...")
        if sudo_ready:
            self.run("sudo -n systemctl stop k3s-agent", check=False)
            self.run("sudo -n systemctl disable k3s-agent", check=False)
        elif interactive_sudo_allowed:
            self.run("sudo systemctl stop k3s-agent", check=False)
            self.run("sudo systemctl disable k3s-agent", check=False)
        elif self.run("systemctl is-active k3s-agent", capture=True, check=False) is not None:
            self._fail(
                "k3s-agent is active while vm-single expects k3s server",
                root_cause=(
                    "Run 'sudo systemctl stop k3s-agent && sudo systemctl disable k3s-agent', "
                    "then retry Level 1."
                ),
            )

    def _patch_k3s_ingress_nginx_service(self, service_type="NodePort"):
        print(f"Ensuring k3s ingress-nginx-controller uses {service_type}...")
        patch_json = json.dumps({"spec": {"type": service_type}})
        self.run(
            "kubectl patch svc ingress-nginx-controller "
            f"-n ingress-nginx --type merge -p {shlex.quote(patch_json)}",
            check=False,
        )

    def _patch_ingress_nginx_configmap(self):
        print("Allowing ingress-nginx snippet annotations for DEV HTTP flows...")
        patch_json = json.dumps(
            {
                "data": {
                    "allow-snippet-annotations": "true",
                    "annotations-risk-level": "Critical",
                }
            }
        )
        self.run(
            "kubectl patch configmap ingress-nginx-controller "
            f"-n ingress-nginx --type merge -p {shlex.quote(patch_json)}",
            check=False,
        )

    def _deploy_infrastructure_runtime(self, *, skip_hosts=False, host_sync_message=None):
        self.announce_level(2, "DEPLOY COMMON SERVICES")

        if not self.ensure_wsl_docker_config():
            self._fail("Could not adjust WSL Docker configuration safely")

        repo_dir = self.config.repo_dir()
        common_dir = self.config.common_dir()
        values_path = self.config.values_path()

        if not os.path.isdir(repo_dir):
            self._fail(
                "Missing INESData deployer artifacts",
                root_cause=(
                    f"Expected {repo_dir}. The framework no longer clones "
                    "the legacy deployment repository automatically; deployers/inesdata must be part "
                    "of this repository checkout."
                ),
            )

        print("Shared common-services deployer artifacts found")

        self.config_adapter.copy_local_deployer_config()

        print("\nSynchronizing configuration...\n")
        self.sync_common_values()
        self.reconcile_common_services_source_of_truth()

        if skip_hosts:
            print(f"\n{host_sync_message or 'Skipping hosts synchronization for this topology.'}")
        else:
            print("\nConfiguring hosts...")
            hosts_entries = self.config_adapter.generate_hosts(self._dataspace_name())
            self.manage_hosts_entries(hosts_entries)

        self.add_helm_repos()

        print("\nBuilding Helm dependencies...")
        self.run("helm dependency build", cwd=common_dir)

        print("\nDeploying common services...")
        common_release_exists = self._common_services_release_exists()
        common_services_startup_timeout = self._common_services_startup_timeout()
        common_services_deployed = self.deploy_helm_release(
            self.config.helm_release_common(),
            self.config.NS_COMMON,
            values_path,
            cwd=common_dir,
            wait=False,
            timeout_seconds=None if common_release_exists else common_services_startup_timeout,
        )
        if not common_services_deployed and not self._common_services_release_recoverable_after_helm_failure():
            release_status = self._common_services_release_status()
            if release_status and not self._common_services_has_terminal_runtime_errors():
                print(
                    "Helm reported a common services failure before the cold-start runtime "
                    f"finished converging (release status: {release_status}). Waiting for "
                    "framework-level readiness checks before aborting..."
                )
            else:
                self._fail("Error deploying common services")

        # Keycloak can take noticeably longer than PostgreSQL/MinIO on fresh
        # installs, so give the pre-Vault readiness check the same minimum
        # budget we already use for the final Level 2 verification.
        pre_vault_timeout = common_services_startup_timeout
        if not self.wait_for_level2_service_pods(self.config.NS_COMMON, timeout=pre_vault_timeout):
            self._fail(
                "Services did not reach the pre-Vault-ready state",
                root_cause="Keycloak, MinIO and PostgreSQL must be 1/1 Running, and Vault must exist in Running state before setup",
            )

        if not self.wait_for_vault_pod(self.config.NS_COMMON):
            self._fail("Vault pod not detected")

        if not self.setup_vault(self.config.NS_COMMON):
            self._fail("Error configuring Vault")

        if not self.reconcile_vault_state_for_local_runtime():
            print("Warning: Could not synchronize Vault token")

        if not self._repair_failed_common_services_helm_release(values_path, common_dir):
            self._fail(
                "Level 2 could not recover common services Helm release",
                root_cause="Helm release remained failed after runtime services became ready",
            )

        common_ready, root_cause = self.verify_common_services_ready_for_level3()
        if not common_ready:
            self._fail("Level 2 did not leave common services ready for Level 3", root_cause=root_cause)

        self.complete_level(2)

    def deploy_infrastructure(self):
        self._deploy_infrastructure_runtime()

    def describe(self) -> str:
        return "INESDataInfrastructureAdapter contains infrastructure logic for INESData."

