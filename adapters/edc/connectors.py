"""Connector lifecycle helpers for the generic EDC adapter."""

import base64
import json
import os
import re
import shutil
import shlex
import sys
import time
from urllib.parse import urlparse

import requests
import yaml

from deployers.shared.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    build_topology_profile,
)
from deployers.shared.lib.components import (
    configured_component_host,
    configured_component_public_url,
    normalize_component_key,
    resolve_component_release_name,
)
from deployers.shared.lib.vm_distributed_public_access import resolve_vm_distributed_public_urls
from adapters.inesdata.connectors import INESDataConnectorsAdapter
from runtime_dependencies import ensure_python_requirements

from .config import EDCConfigAdapter, EdcConfig


class EDCConnectorsAdapter(INESDataConnectorsAdapter):
    """EDC connector adapter that keeps the existing framework contract stable."""

    MANAGED_LABEL_KEY = "validation-environment-adapter"
    DASHBOARD_PROXY_PREFIX = "/edc-dashboard-api"
    LEVEL4_LOCAL_IMAGE_TOPOLOGIES = {LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY}
    # Backward-compatible fallback. Normal deployments resolve this from the
    # active dataspace and topology configuration.
    DEFAULT_ONTOLOGY_HUB_URL = "http://ontology-hub-demo.dev.ds.dataspaceunit.upm"

    def __init__(self, run, run_silent, auto_mode_getter, infrastructure_adapter, config_adapter=None, config_cls=None, topology="local"):
        self.topology = topology or EdcConfig.DEFAULT_TOPOLOGY
        self._last_runtime_prerequisite_error = None
        self._last_runtime_prerequisite_code = None
        super().__init__(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            infrastructure_adapter=infrastructure_adapter,
            config_adapter=config_adapter or EDCConfigAdapter(config_cls or EdcConfig, topology=self.topology),
            config_cls=config_cls or EdcConfig,
        )

    def _fail_runtime_prerequisite(self, message, code=None):
        self._last_runtime_prerequisite_error = message
        self._last_runtime_prerequisite_code = code
        print(message)
        return None, None

    def build_connector_url(self, connector_name):
        public_base_url = self._connector_public_base_url(connector_name)
        if public_base_url:
            return f"{public_base_url.rstrip('/')}/management/v3"

        ds_domain = self.config_adapter.ds_domain_base()
        if not ds_domain:
            raise ValueError("DS_DOMAIN_BASE not defined in deployer.config")
        return f"http://{connector_name}.{ds_domain}/management/v3"

    def build_protocol_address(self, connector_name, path="/protocol"):
        base_url = self._connector_base_url(connector_name)
        if not base_url:
            raise ValueError("DS_DOMAIN_BASE not defined in deployer.config")
        normalized_path = f"/{str(path or '/protocol').lstrip('/')}"
        return f"{base_url.rstrip('/')}{normalized_path}"

    def wait_for_connector_ready(self, connector_name, timeout=300):
        return self.wait_for_management_api_ready(connector_name, timeout=timeout)

    def wait_for_management_api_ready(self, connector_name, timeout=180, poll_interval=3):
        print(f"Waiting for EDC management API to be ready: {connector_name}")
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
            },
            "offset": 0,
            "limit": 1,
        }
        local_url, local_fallback = self._start_connector_management_api_fallback(connector_name)
        if local_url:
            url = local_url
            print(f"Using temporary local EDC management API port-forward for {connector_name}.")
        else:
            url = f"{self.connector_base_url(connector_name).rstrip('/')}/management/v3/assets/request"

        start = time.time()
        last_issue = None
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
                        print(f"EDC management API ready: {connector_name}")
                        return True
                    if response.status_code == 401:
                        last_issue = "HTTP 401"
                        self.invalidate_management_api_token(connector_name)
                        time.sleep(poll_interval)
                        continue
                    last_issue = f"HTTP {response.status_code}"
                except requests.RequestException as exc:
                    last_issue = str(exc)

                time.sleep(poll_interval)
        finally:
            self._close_temporary_port_forward(local_fallback)

        if last_issue:
            print(f"EDC management API not ready for {connector_name}: {last_issue}")
        else:
            print(f"EDC management API not ready for {connector_name}")
        return False

    def wait_for_all_connectors(self, connectors):
        print("\nWaiting for all EDC connectors to expose their management API...\n")
        for connector in connectors:
            if not self.wait_for_management_api_ready(connector):
                print(f"Connector management API not ready: {connector}")
                return False
        return True

    def _managed_label_value(self):
        return getattr(self.config, "EDC_MANAGED_LABEL", "edc")

    def _resource_metadata(self, resource_type, resource_name, namespace):
        output = self.run_silent(
            f"kubectl get {resource_type} {resource_name} -n {namespace} -o json"
        )
        if not output:
            return None
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return None
        return payload.get("metadata", {}) or {}

    def _resource_conflicts_with_edc(self, resource_type, resource_name, namespace):
        metadata = self._resource_metadata(resource_type, resource_name, namespace)
        if metadata is None:
            return False
        labels = metadata.get("labels", {}) or {}
        return labels.get(self.MANAGED_LABEL_KEY) != self._managed_label_value()

    def _conflicting_runtime_resources(self, connector_name, namespace):
        resource_names = (
            ("deployment", connector_name),
            ("service", connector_name),
            ("configmap", f"{connector_name}-config"),
            ("ingress", f"{connector_name}-ingress"),
        )
        conflicts = []
        for resource_type, resource_name in resource_names:
            if self._resource_conflicts_with_edc(resource_type, resource_name, namespace):
                conflicts.append(f"{resource_type}/{resource_name}")
        return conflicts

    def _values_file_path(self, connector_name, ds_name=None):
        return self.config_adapter.edc_connector_values_file(connector_name, ds_name=ds_name)

    def _edc_connector_dir(self):
        return self.config_adapter.edc_connector_dir()

    def _edc_connector_source_dir(self):
        resolver = getattr(self.config_adapter, "edc_connector_source_dir", None)
        if callable(resolver):
            return resolver()
        return os.path.join(
            self._framework_root_dir(),
            "adapters",
            "edc",
            "sources",
            "connector",
        )

    def _edc_runtime_dir(self, ds_name=None):
        return self.config_adapter.edc_dataspace_runtime_dir(ds_name=ds_name)

    def _framework_root_dir(self):
        resolver = getattr(self.config, "script_dir", None)
        if callable(resolver):
            return resolver()
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def _level4_edc_local_images_mode(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        raw_value = (
            os.environ.get("PIONERA_EDC_LOCAL_IMAGES_MODE")
            or os.environ.get("EDC_LOCAL_IMAGES_MODE")
            or deployer_config.get("EDC_LOCAL_IMAGES_MODE")
            or deployer_config.get("LEVEL4_EDC_LOCAL_IMAGES_MODE")
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
        print(f"Unknown EDC local images mode '{raw_value}'. Falling back to auto.")
        return "auto"

    def _edc_local_minikube_profile(self):
        env_profile = os.getenv("PIONERA_MINIKUBE_PROFILE") or os.getenv("MINIKUBE_PROFILE")
        if env_profile:
            return env_profile.strip() or "minikube"
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        return str(deployer_config.get("MINIKUBE_PROFILE") or "minikube").strip() or "minikube"

    def _edc_connector_image_override_configured(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        image_name = str(
            os.environ.get("PIONERA_EDC_CONNECTOR_IMAGE_NAME")
            or deployer_config.get("EDC_CONNECTOR_IMAGE_NAME")
            or ""
        ).strip()
        image_tag = str(
            os.environ.get("PIONERA_EDC_CONNECTOR_IMAGE_TAG")
            or deployer_config.get("EDC_CONNECTOR_IMAGE_TAG")
            or ""
        ).strip()
        return bool(image_name and image_tag)

    def _edc_connector_image_override_matches_local_defaults(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        image_name = str(
            os.environ.get("PIONERA_EDC_CONNECTOR_IMAGE_NAME")
            or deployer_config.get("EDC_CONNECTOR_IMAGE_NAME")
            or ""
        ).strip()
        image_tag = str(
            os.environ.get("PIONERA_EDC_CONNECTOR_IMAGE_TAG")
            or deployer_config.get("EDC_CONNECTOR_IMAGE_TAG")
            or ""
        ).strip()
        defaults = self._edc_local_connector_image_defaults()
        return image_name == defaults["name"] and image_tag == defaults["tag"]

    def _edc_local_connector_image_defaults(self):
        return {
            "name": str(
                os.environ.get("PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_NAME")
                or "validation-environment/edc-connector"
            ).strip(),
            "tag": str(
                os.environ.get("PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_TAG")
                or "local"
            ).strip(),
        }

    def _edc_dashboard_image_values(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        return {
            "dashboard_name": str(
                os.environ.get("PIONERA_EDC_DASHBOARD_IMAGE_NAME")
                or deployer_config.get("EDC_DASHBOARD_IMAGE_NAME")
                or self.config_adapter.edc_dashboard_image_name()
                or "validation-environment/edc-dashboard"
            ).strip(),
            "dashboard_tag": str(
                os.environ.get("PIONERA_EDC_DASHBOARD_IMAGE_TAG")
                or deployer_config.get("EDC_DASHBOARD_IMAGE_TAG")
                or self.config_adapter.edc_dashboard_image_tag()
                or "latest"
            ).strip(),
            "proxy_name": str(
                os.environ.get("PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME")
                or deployer_config.get("EDC_DASHBOARD_PROXY_IMAGE_NAME")
                or self.config_adapter.edc_dashboard_proxy_image_name()
                or "validation-environment/edc-dashboard-proxy"
            ).strip(),
            "proxy_tag": str(
                os.environ.get("PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG")
                or deployer_config.get("EDC_DASHBOARD_PROXY_IMAGE_TAG")
                or self.config_adapter.edc_dashboard_proxy_image_tag()
                or "latest"
            ).strip(),
        }

    def _run_level4_edc_image_script(self, script_path, args=None, env_prefix=""):
        root_dir = self._framework_root_dir()
        command = " ".join(
            shlex.quote(part)
            for part in [
                "bash",
                script_path,
                "--apply",
                *(args or []),
            ]
        )
        env_prefix = str(env_prefix or "").strip()
        if env_prefix:
            command = f"{env_prefix} {command}"
        return self.run(command, cwd=root_dir, check=False) is not None

    def _edc_image_prepared_targets(self, attribute_name):
        prepared = getattr(self, attribute_name, None)
        if not isinstance(prepared, set):
            prepared = set()
            setattr(self, attribute_name, prepared)
        return prepared

    @staticmethod
    def _edc_image_target_key(env_prefix):
        return str(env_prefix or "").strip() or "local"

    def _edc_remote_image_env_prefix_for_namespace(self, namespace, dataspace=None):
        resolver = getattr(self, "_remote_image_import_env_prefix_for_namespace", None)
        if not callable(resolver):
            return ""
        return str(resolver(namespace, dataspace=dataspace) or "").strip()

    def _edc_level4_image_env_prefixes(self):
        topology = self._normalized_topology()
        if topology == VM_SINGLE_TOPOLOGY:
            prefix = self._edc_remote_image_env_prefix_for_namespace("common")
            return [prefix] if prefix else [""]
        if topology != "vm-distributed":
            return [""]

        prefixes = []
        missing_namespaces = []
        try:
            dataspaces = self.load_dataspace_connectors() or []
        except Exception:
            dataspaces = []

        for dataspace in dataspaces:
            for namespace in self._dataspace_connector_target_namespaces(
                dataspace,
                dataspaces=dataspaces,
            ):
                prefix = self._edc_remote_image_env_prefix_for_namespace(
                    namespace,
                    dataspace=dataspace,
                )
                if not prefix:
                    missing_namespaces.append(namespace)
                    continue
                if prefix not in prefixes:
                    prefixes.append(prefix)

        if missing_namespaces:
            raise RuntimeError(
                "EDC Level 4 cannot prepare local images for vm-distributed because "
                "remote k3s image import is not configured for namespaces: "
                + ", ".join(sorted(set(missing_namespaces)))
            )
        return prefixes or [""]

    def _export_ontology_validator_patch_env_for_edc_build(self):
        try:
            context = self._ontology_validator_patch_context()
        except Exception as exc:
            print(f"Ontology validator URL patch env skipped: {exc}")
            return

        config = dict(getattr(context, "config", {}) or {})
        dataspace_name = str(getattr(context, "dataspace_name", "") or "").strip()
        if not dataspace_name:
            print("Ontology validator URL patch env skipped: dataspace name is not configured.")
            return

        namespace_roles = getattr(context, "namespace_roles", None)
        components_namespace = str(
            getattr(namespace_roles, "components_namespace", "")
            or config.get("COMPONENTS_NAMESPACE")
            or "components"
        ).strip() or "components"

        os.environ["PIONERA_ONTOLOGY_PATCH_DATASPACE"] = dataspace_name
        os.environ["PIONERA_ONTOLOGY_PATCH_DS_DOMAIN_BASE"] = str(config.get("DS_DOMAIN_BASE") or "")
        os.environ["PIONERA_ONTOLOGY_PATCH_COMPONENTS_NAMESPACE"] = components_namespace

        ontology_url = self._resolve_ontology_hub_url(config)
        if ontology_url:
            os.environ["PIONERA_ONTOLOGY_PATCH_ONTOLOGY_HUB_URL"] = ontology_url

    def _maybe_prepare_level4_local_edc_connector_image(self, mode, env_prefix=""):
        target_key = self._edc_image_target_key(env_prefix)
        prepared_targets = self._edc_image_prepared_targets("_edc_connector_image_prepared_targets")
        if target_key in prepared_targets:
            print("Level 4 local EDC connector image already prepared for this target.")
            return True
        if (
            not env_prefix
            and self._is_truthy(os.environ.get("PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_PREPARED"))
        ):
            print("Level 4 local EDC connector image already prepared for this execution.")
            return True

        skip_build = self._is_truthy(os.environ.get("PIONERA_SKIP_EDC_LOCAL_CONNECTOR_IMAGE_BUILD"))
        if skip_build and mode != "required":
            if self._edc_connector_image_override_configured():
                print("Skipping Level 4 local EDC connector image preparation; disabled by environment.")
                return True
            print(
                "EDC Level 4 local connector image preparation is disabled, "
                "but no explicit EDC connector image override is configured."
            )
            return False

        if self._edc_connector_image_override_configured() and mode != "required":
            if not env_prefix or not self._edc_connector_image_override_matches_local_defaults():
                print("Skipping Level 4 local EDC connector image preparation; explicit image override is configured.")
                return True

        image = self._edc_local_connector_image_defaults()
        if not image["name"] or not image["tag"]:
            print("EDC local connector image name/tag are not configured.")
            return False

        root_dir = self._framework_root_dir()
        script_path = os.path.join(root_dir, "adapters", "edc", "scripts", "build_image.sh")
        if not os.path.isfile(script_path):
            detail = os.path.relpath(script_path, root_dir)
            print(f"Required EDC connector local image script is missing: {detail}")
            return False

        minikube_profile = self._edc_local_minikube_profile()
        cluster_type = str(self._cluster_runtime().get("cluster_type") or "minikube").strip().lower() or "minikube"
        print("\nPreparing local EDC connector image for Level 4...")
        print(f"Cluster runtime: {cluster_type}")
        print(f"This builds and loads {image['name']}:{image['tag']} before Helm deploy.")
        repo_url_getter = getattr(self.config_adapter, "edc_reference_repo_url", None)
        repo_subdir_getter = getattr(self.config_adapter, "edc_reference_repo_subdir", None)
        repo_url = repo_url_getter() if callable(repo_url_getter) else "https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"
        repo_subdir = repo_subdir_getter() if callable(repo_subdir_getter) else "asset-filter-template"
        self._export_ontology_validator_patch_env_for_edc_build()
        if not self._run_level4_edc_image_script(
            script_path,
            args=[
                "--source-dir",
                self._edc_connector_source_dir(),
                "--sync-git-url",
                repo_url,
                "--sync-subdir",
                repo_subdir,
                "--image",
                image["name"],
                "--tag",
                image["tag"],
                "--minikube-profile",
                minikube_profile,
                "--cluster-runtime",
                cluster_type,
            ],
            env_prefix=env_prefix,
        ):
            print("Error preparing local EDC connector image for Level 4.")
            return False

        os.environ["PIONERA_EDC_CONNECTOR_IMAGE_NAME"] = image["name"]
        os.environ["PIONERA_EDC_CONNECTOR_IMAGE_TAG"] = image["tag"]
        os.environ.setdefault("PIONERA_EDC_CONNECTOR_IMAGE_PULL_POLICY", "IfNotPresent")
        prepared_targets.add(target_key)
        if not env_prefix:
            os.environ["PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_PREPARED"] = "true"
        return True

    def _maybe_prepare_level4_local_edc_dashboard_images(self, mode, env_prefix=""):
        if not self.config_adapter.edc_dashboard_enabled():
            return True
        target_key = self._edc_image_target_key(env_prefix)
        prepared_targets = self._edc_image_prepared_targets("_edc_dashboard_images_prepared_targets")
        if target_key in prepared_targets:
            print("Level 4 local EDC dashboard images already prepared for this target.")
            return True
        if (
            not env_prefix
            and self._is_truthy(os.environ.get("PIONERA_EDC_LOCAL_DASHBOARD_IMAGES_PREPARED"))
        ):
            print("Level 4 local EDC dashboard images already prepared for this execution.")
            return True

        if self._is_truthy(os.environ.get("PIONERA_SKIP_EDC_LOCAL_DASHBOARD_IMAGE_BUILD")) and mode != "required":
            print("Skipping Level 4 local EDC dashboard image preparation; disabled by environment.")
            return True

        images = self._edc_dashboard_image_values()
        missing = [key for key, value in images.items() if not value]
        if missing:
            print("EDC dashboard local image values are incomplete: " + ", ".join(sorted(missing)))
            return False

        root_dir = self._framework_root_dir()
        scripts = [
            os.path.join(root_dir, "adapters", "edc", "scripts", "build_dashboard_image.sh"),
            os.path.join(root_dir, "adapters", "edc", "scripts", "build_dashboard_proxy_image.sh"),
        ]
        for script_path in scripts:
            if not os.path.isfile(script_path):
                detail = os.path.relpath(script_path, root_dir)
                print(f"Required EDC dashboard local image script is missing: {detail}")
                return False

        minikube_profile = self._edc_local_minikube_profile()
        cluster_type = str(self._cluster_runtime().get("cluster_type") or "minikube").strip().lower() or "minikube"
        os.environ["PIONERA_EDC_DASHBOARD_IMAGE_NAME"] = images["dashboard_name"]
        os.environ["PIONERA_EDC_DASHBOARD_IMAGE_TAG"] = images["dashboard_tag"]
        os.environ["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME"] = images["proxy_name"]
        os.environ["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG"] = images["proxy_tag"]

        print("\nPreparing local EDC dashboard images for Level 4...")
        print(f"Cluster runtime: {cluster_type}")
        print(
            "This builds and loads "
            f"{images['dashboard_name']}:{images['dashboard_tag']} and "
            f"{images['proxy_name']}:{images['proxy_tag']} before Helm deploy."
        )
        for script_path in scripts:
            if not self._run_level4_edc_image_script(
                script_path,
                args=[
                    "--minikube-profile",
                    minikube_profile,
                    "--cluster-runtime",
                    cluster_type,
                ],
                env_prefix=env_prefix,
            ):
                print("Error preparing local EDC dashboard images for Level 4.")
                return False

        os.environ.setdefault("PIONERA_EDC_DASHBOARD_IMAGE_PULL_POLICY", "IfNotPresent")
        os.environ.setdefault("PIONERA_EDC_DASHBOARD_PROXY_IMAGE_PULL_POLICY", "IfNotPresent")
        prepared_targets.add(target_key)
        if not env_prefix:
            os.environ["PIONERA_EDC_LOCAL_DASHBOARD_IMAGES_PREPARED"] = "true"
        return True

    def _maybe_prepare_level4_local_edc_images(self):
        mode = self._level4_edc_local_images_mode()
        normalized_mode = str(mode or "auto").strip().lower() or "auto"
        topology = self._normalized_topology()
        connector_mode = mode
        if topology in self.LEVEL4_LOCAL_IMAGE_TOPOLOGIES:
            policy = {
                "topology": topology,
                "mode": normalized_mode,
                "prepare_local_images": True,
                "allow_local_image_overrides": True,
                "message": "",
                "error": "",
            }
            if normalized_mode != "disabled":
                connector_mode = "required"
        else:
            policy = self._resolve_level4_local_image_policy(
                mode=mode,
                label="EDC",
            )
        if policy["error"]:
            print(policy["error"])
            return False
        if not policy["prepare_local_images"]:
            if policy["message"]:
                print(policy["message"])
            return True
        if mode == "disabled":
            if not self._edc_connector_image_override_configured():
                print(
                    "Level 4 local EDC images are disabled, but no explicit EDC connector "
                    "image override is configured."
                )
                return False
            print("Level 4 local EDC images disabled by configuration.")
            return True
        ensure_docker_config = getattr(getattr(self, "infrastructure", None), "ensure_wsl_docker_config", None)
        if callable(ensure_docker_config) and not ensure_docker_config():
            print("Could not adjust WSL Docker configuration before preparing local EDC images.")
            return False
        try:
            env_prefixes = self._edc_level4_image_env_prefixes()
        except RuntimeError as exc:
            print(str(exc))
            return False
        for env_prefix in env_prefixes:
            if env_prefix:
                print("Preparing EDC local images through remote k3s image import.")
            if not self._maybe_prepare_level4_local_edc_connector_image(connector_mode, env_prefix=env_prefix):
                return False
            if not self._maybe_prepare_level4_local_edc_dashboard_images(mode, env_prefix=env_prefix):
                return False
        return True

    def _should_sync_vault_token_to_deployer_config(self):
        # EDC composes shared credentials at runtime; only mutate a local config
        # file when the user intentionally created either the shared
        # infrastructure config or the EDC-specific overlay.
        for resolver_name in ("infrastructure_deployer_config_path", "deployer_config_path"):
            resolver = getattr(self.config, resolver_name, None)
            if callable(resolver) and os.path.exists(resolver()):
                return True
        return False

    @staticmethod
    def _edc_vault_management_token_paths():
        return [
            "sys/policies/acl/edc-preflight",
            "auth/token/create",
        ]

    @staticmethod
    def _edc_vault_network_failure_message(stage, exc):
        if stage == "capabilities":
            return f"Vault token capabilities check failed: Vault is not reachable ({exc})"
        return f"Vault token validation failed: Vault is not reachable ({exc})"

    def _verify_edc_vault_management_token_over_http(self, vault_url, vault_token):
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
                "for the running Vault."
            )
            return False, None

        paths = self._edc_vault_management_token_paths()
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
                f"HTTP {response.status_code}. EDC connector bootstrap requires policy "
                "and token creation permissions."
            )
            return False, None

        try:
            capabilities_payload = response.json()
        except ValueError:
            return True, None

        for path in paths:
            capabilities = capabilities_payload.get(path)
            if capabilities is None:
                capabilities = capabilities_payload.get("capabilities")
            if capabilities is not None and not self._vault_capabilities_allow_management(capabilities):
                print(
                    "Vault token capabilities check failed: token does not have management "
                    f"permissions for '{path}'. Recreate Level 2 common services or restore "
                    "the current Vault root token before deploying EDC connectors."
                )
                return False, None

        return True, None

    def _verify_edc_vault_management_token_via_port_forward(self, vault_url, vault_token):
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
            validated, network_failure = self._verify_edc_vault_management_token_over_http(
                local_url,
                vault_token,
            )
            if network_failure:
                print(
                    self._edc_vault_network_failure_message(
                        network_failure["stage"],
                        network_failure["exception"],
                    )
                )
            return validated
        finally:
            self._close_temporary_port_forward(port_forward)

    def _verify_vault_management_token(self):
        config_loader = getattr(self.config_adapter, "load_deployer_config", None)
        if not callable(config_loader):
            return True

        deployer_config = config_loader() or {}
        vault_url = str(
            deployer_config.get("VT_URL") or deployer_config.get("VAULT_URL") or ""
        ).strip().rstrip("/")
        vault_token = str(deployer_config.get("VT_TOKEN") or "").strip()
        if not vault_url or not vault_token:
            print("Vault token validation failed: VT_URL/VT_TOKEN are not defined in deployer.config")
            return False

        validated, network_failure = self._verify_edc_vault_management_token_over_http(
            vault_url,
            vault_token,
        )
        if validated:
            return True

        if network_failure:
            if (
                self._should_attempt_local_fallback(network_failure["exception"])
                and self._vault_cluster_service_reference(vault_url)
                and self._verify_edc_vault_management_token_via_port_forward(vault_url, vault_token)
            ):
                return True
            print(
                self._edc_vault_network_failure_message(
                    network_failure["stage"],
                    network_failure["exception"],
                )
            )
            return False

        return False

    def _vault_management_runtime(self):
        config_loader = getattr(self.config_adapter, "load_deployer_config", None)
        if not callable(config_loader):
            return None, None
        deployer_config = config_loader() or {}
        vault_url = str(
            deployer_config.get("VT_URL") or deployer_config.get("VAULT_URL") or ""
        ).strip().rstrip("/")
        vault_token = str(deployer_config.get("VT_TOKEN") or "").strip()
        return vault_url, vault_token

    def _connector_credentials_file_path(self, connector_name, ds_name=None, for_write=False):
        resolver = getattr(self.config_adapter, "edc_connector_credentials_path", None)
        if callable(resolver):
            try:
                return resolver(connector_name, ds_name=ds_name, for_write=for_write)
            except TypeError as exc:
                if "for_write" not in str(exc):
                    raise
                return resolver(connector_name, ds_name=ds_name)
        return self.config.connector_credentials_path(connector_name)

    def _connector_certificates_dir_from_credentials(self, credentials, ds_name):
        certificates = (credentials or {}).get("certificates") or {}
        certs_path = str(certificates.get("path") or "").strip()
        if certs_path:
            if os.path.isabs(certs_path):
                return certs_path
            return os.path.join(self.config.script_dir(), certs_path)
        resolver = getattr(self.config_adapter, "edc_connector_certs_dir", None)
        if callable(resolver):
            return resolver(ds_name=ds_name)
        return self.config.connector_certificates_dir()

    def _connector_vault_secret_payload(self, connector_name, ds_name, credentials):
        minio = (credentials or {}).get("minio") or {}
        access_key = str(minio.get("access_key") or "").strip()
        secret_key = str(minio.get("secret_key") or "").strip()
        if not access_key or not secret_key:
            print(f"Cannot reconcile Vault S3 secrets for {connector_name}: MinIO credentials are missing.")
            return None

        secrets = {
            f"{ds_name}/{connector_name}/aws-access-key": access_key,
            f"{ds_name}/{connector_name}/aws-secret-key": secret_key,
        }
        certs_dir = self._connector_certificates_dir_from_credentials(credentials, ds_name)
        cert_files = {
            f"{ds_name}/{connector_name}/public-key": os.path.join(
                certs_dir,
                f"{connector_name}-public.crt",
            ),
            f"{ds_name}/{connector_name}/private-key": os.path.join(
                certs_dir,
                f"{connector_name}-private.key",
            ),
        }
        for secret_path, file_path in cert_files.items():
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as handle:
                    secrets[secret_path] = handle.read()
        return secrets

    @staticmethod
    def _vault_headers(token):
        return {"X-Vault-Token": token}

    def _vault_secret_exists(self, vault_url, vault_token, secret_path):
        try:
            response = requests.get(
                f"{vault_url}/v1/secret/data/{secret_path}",
                headers=self._vault_headers(vault_token),
                timeout=5,
                verify=False,
            )
        except requests.RequestException:
            return False
        return response.status_code == 200

    def _vault_token_is_valid(self, vault_url, vault_token):
        if not vault_token:
            return False
        try:
            response = requests.get(
                f"{vault_url}/v1/auth/token/lookup-self",
                headers=self._vault_headers(vault_token),
                timeout=5,
                verify=False,
            )
        except requests.RequestException:
            return False
        return response.status_code == 200

    def _write_connector_credentials_file(self, credentials_path, credentials):
        os.makedirs(os.path.dirname(credentials_path), exist_ok=True)
        with open(credentials_path, "w", encoding="utf-8") as handle:
            json.dump(credentials, handle, indent=2)

    def _reconcile_connector_vault_secrets(self, connector_name, ds_name, credentials=None, vault_url=None):
        credentials_path = self._connector_credentials_file_path(connector_name, ds_name, for_write=True)
        credentials = credentials or self.load_connector_credentials(connector_name)
        if not credentials:
            print(f"Cannot reconcile Vault secrets for {connector_name}: credentials file is missing.")
            return False

        configured_vault_url, management_token = self._vault_management_runtime()
        vault_url = str(vault_url or configured_vault_url or "").strip().rstrip("/")
        if not vault_url or not management_token:
            print("Cannot reconcile EDC Vault secrets: VT_URL/VT_TOKEN are not defined in deployer.config")
            return False

        vault_bootstrap_access = None
        if vault_url == configured_vault_url and self._vault_cluster_service_reference(vault_url):
            vault_bootstrap_access = self._start_vault_bootstrap_access()
            if vault_bootstrap_access is None:
                return False
            vault_url = vault_bootstrap_access.get("vault_url") or vault_url

        try:
            required_secret_paths = (
                f"{ds_name}/{connector_name}/aws-access-key",
                f"{ds_name}/{connector_name}/aws-secret-key",
            )
            current_connector_token = str((credentials.get("vault") or {}).get("token") or "").strip()
            needs_reconcile = not self._vault_token_is_valid(vault_url, current_connector_token)
            if not needs_reconcile:
                needs_reconcile = not all(
                    self._vault_secret_exists(vault_url, management_token, secret_path)
                    for secret_path in required_secret_paths
                )
            if not needs_reconcile:
                return True

            secrets_payload = self._connector_vault_secret_payload(connector_name, ds_name, credentials)
            if not secrets_payload:
                return False

            print(f"Reconciling Vault secrets for EDC connector {connector_name}...")
            headers = self._vault_headers(management_token)
            policy_name = f"{connector_name}-secrets-policy"
            policy = f"""
path "secret/data/{ds_name}/{connector_name}/*" {{
    capabilities = ["create", "read", "update", "list", "delete"]
}}
"""
            try:
                response = requests.put(
                    f"{vault_url}/v1/sys/policies/acl/{policy_name}",
                    headers=headers,
                    json={"policy": policy},
                    timeout=30,
                    verify=False,
                )
                response.raise_for_status()
                response = requests.post(
                    f"{vault_url}/v1/auth/token/create",
                    headers=headers,
                    json={"period": "768h", "policies": [policy_name], "renewable": True},
                    timeout=30,
                    verify=False,
                )
                response.raise_for_status()
                connector_token = response.json()["auth"]["client_token"]
                for secret_path, content in secrets_payload.items():
                    response = requests.post(
                        f"{vault_url}/v1/secret/data/{secret_path}",
                        headers=headers,
                        json={"data": {"content": content}},
                        timeout=30,
                        verify=False,
                    )
                    response.raise_for_status()
            except (KeyError, requests.RequestException) as exc:
                print(f"Could not reconcile Vault secrets for {connector_name}: {exc}")
                return False

            credentials.setdefault("vault", {})
            credentials["vault"].update(
                {
                    "token": connector_token,
                    "path": f"secret/data/{ds_name}/{connector_name}/",
                }
            )
            self._write_connector_credentials_file(credentials_path, credentials)
            return True
        finally:
            self._stop_vault_bootstrap_access(vault_bootstrap_access)

    def _edc_dataspace_transfer_policy_name(self, connector_name, ds_name):
        return f"policy-{ds_name}-{connector_name}-dataspace-transfer"

    def _edc_dataspace_transfer_policy_payload(self, ds_name):
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["s3:*"],
                    "Resource": [
                        f"arn:aws:s3:::{ds_name}-*",
                        f"arn:aws:s3:::{ds_name}-*/*",
                    ],
                }
            ],
        }

    def ensure_minio_dataspace_transfer_policy_attached(self, connector_name, ds_name=None):
        ds_name = ds_name or self._dataspace_name()
        namespace = self.config.NS_COMMON
        policy_name = self._edc_dataspace_transfer_policy_name(connector_name, ds_name)

        deployer_config = self.config_adapter.load_deployer_config() or {}
        minio_endpoint = deployer_config.get("MINIO_ENDPOINT") or "http://127.0.0.1:9000"
        minio_admin_user, minio_admin_pass = self._minio_admin_credentials(deployer_config)

        minio_pod = self.infrastructure.get_pod_by_name(namespace, self.config.service_minio())
        if not minio_pod:
            print(f"  MinIO pod not found — skipping EDC dataspace transfer policy for {connector_name}")
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

        policy_path_pod = f"/tmp/{policy_name}.json"
        policy_b64 = base64.b64encode(
            json.dumps(self._edc_dataspace_transfer_policy_payload(ds_name)).encode("utf-8")
        ).decode("ascii")
        write_policy_result = self.run(
            f"{mc} sh -c \"echo '{policy_b64}' | base64 -d > {policy_path_pod}\"",
            check=False,
            silent=True,
        )
        if write_policy_result is None:
            print(f"  Warning: could not write EDC dataspace transfer policy inside pod for {connector_name}")
            return False

        self.run(
            f"{mc} mc admin policy create minio {shlex.quote(policy_name)} {shlex.quote(policy_path_pod)}",
            capture=True,
            check=False,
            silent=True,
        )
        self.run(
            f"{mc} mc admin policy attach minio {shlex.quote(policy_name)} "
            f"--user {shlex.quote(connector_name)}",
            capture=True,
            check=False,
            silent=True,
        )

        user_info = self.run_silent(f"{mc} mc admin user info minio {shlex.quote(connector_name)}")
        if user_info and policy_name in user_info:
            print(f"  MinIO policy '{policy_name}' attached to '{connector_name}'")
            return True

        print(f"  Warning: EDC dataspace transfer policy attach could not be verified for '{connector_name}'")
        return False

    def ensure_minio_policy_attached(self, connector_name, ds_name=None):
        base_policy_ok = super().ensure_minio_policy_attached(connector_name, ds_name=ds_name)
        transfer_policy_ok = self.ensure_minio_dataspace_transfer_policy_attached(
            connector_name,
            ds_name=ds_name,
        )
        return bool(base_policy_ok and transfer_policy_ok)

    def _ensure_edc_runtime_dir(self, ds_name=None):
        runtime_dir = self._edc_runtime_dir(ds_name=ds_name)
        os.makedirs(runtime_dir, exist_ok=True)
        return runtime_dir

    def _remove_edc_values_file(self, connector_name, ds_name=None):
        values_path = self._values_file_path(connector_name, ds_name=ds_name)
        if os.path.exists(values_path):
            try:
                os.remove(values_path)
                print(f"Removed stale EDC connector values file: {values_path}")
            except OSError as exc:
                print(f"Warning: could not remove stale EDC values file {values_path}: {exc}")
        return values_path

    def _bootstrap_source_dir(self, repo_dir, ds_name):
        return os.path.join(
            repo_dir,
            "deployments",
            self.config_adapter.deployment_environment_name(),
            ds_name,
        )

    def _copy_if_exists(self, source_path, target_path, *, overwrite=True):
        if not os.path.exists(source_path):
            return None
        if os.path.abspath(source_path) == os.path.abspath(target_path):
            return target_path
        if os.path.exists(target_path) and not overwrite:
            return target_path
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(source_path, target_path)
        return target_path

    def _copy_tree_if_exists(self, source_dir, target_dir, *, overwrite=True):
        if not os.path.isdir(source_dir):
            return None
        if os.path.abspath(source_dir) == os.path.abspath(target_dir):
            return target_dir
        if os.path.isdir(target_dir) and os.listdir(target_dir) and not overwrite:
            return target_dir
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
        return target_dir

    def _runtime_relative_path(self, absolute_path):
        if not absolute_path:
            return None
        script_dir = self.config.script_dir()
        try:
            relative_path = os.path.relpath(absolute_path, script_dir)
        except ValueError:
            return absolute_path
        if relative_path.startswith(".."):
            return absolute_path
        return relative_path

    def _rewrite_staged_connector_credentials(self, credentials_path, certs_dir=None):
        if not credentials_path or not os.path.exists(credentials_path):
            return None
        with open(credentials_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        certificates = payload.get("certificates")
        if certs_dir and isinstance(certificates, dict):
            certificates["path"] = self._runtime_relative_path(certs_dir)

        with open(credentials_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4)
        return credentials_path

    def _stage_bootstrap_artifacts(self, connector_name, ds_name, repo_dir):
        source_dir = self._bootstrap_source_dir(repo_dir, ds_name)
        runtime_dir = self._ensure_edc_runtime_dir(ds_name=ds_name)
        staged = {}

        credentials_name = f"credentials-connector-{connector_name}.json"
        staged_credentials = self._copy_if_exists(
            os.path.join(source_dir, credentials_name),
            self._connector_credentials_file_path(connector_name, ds_name=ds_name, for_write=True),
            overwrite=False,
        )
        if staged_credentials:
            staged["credentials"] = staged_credentials

        dataspace_credentials_name = f"credentials-dataspace-{ds_name}.json"
        staged_dataspace_credentials = self._copy_if_exists(
            os.path.join(source_dir, dataspace_credentials_name),
            os.path.join(runtime_dir, dataspace_credentials_name),
            overwrite=False,
        )
        if staged_dataspace_credentials:
            staged["dataspace_credentials"] = staged_dataspace_credentials

        policy_name = f"policy-{ds_name}-{connector_name}.json"
        staged_policy = self._copy_if_exists(
            os.path.join(source_dir, policy_name),
            self._connector_minio_policy_path(connector_name, ds_name=ds_name, for_write=True),
            overwrite=False,
        )
        if staged_policy:
            staged["policy"] = staged_policy

        source_certs_dir = os.path.join(source_dir, "certs")
        runtime_certs_dir = self.config_adapter.edc_connector_certs_dir(ds_name=ds_name)
        staged_certs_dir = self._copy_tree_if_exists(
            source_certs_dir,
            runtime_certs_dir,
            overwrite=False,
        )
        if staged_certs_dir:
            staged["certs"] = staged_certs_dir

        if staged_credentials:
            self._rewrite_staged_connector_credentials(
                staged_credentials,
                certs_dir=staged_certs_dir or runtime_certs_dir,
            )

        return staged

    def _stage_legacy_bootstrap_artifacts_if_needed(self, connector_name, ds_name=None):
        ds_name = ds_name or self._dataspace_name()
        credentials_path = self._connector_credentials_file_path(
            connector_name,
            ds_name=ds_name,
            for_write=False,
        )
        if credentials_path and os.path.exists(credentials_path):
            return credentials_path

        repo_dir_getter = getattr(self.config_adapter, "edc_deployment_dir", None)
        if callable(repo_dir_getter):
            repo_dir = repo_dir_getter()
        else:
            repo_dir_getter = getattr(self.config, "repo_dir", None)
            repo_dir = repo_dir_getter() if callable(repo_dir_getter) else ""
        if not repo_dir:
            return None

        legacy_source = os.path.join(
            self._bootstrap_source_dir(repo_dir, ds_name),
            f"credentials-connector-{connector_name}.json",
        )
        if not os.path.exists(legacy_source):
            return None

        staged = self._stage_bootstrap_artifacts(connector_name, ds_name, repo_dir)
        staged_credentials = staged.get("credentials") if isinstance(staged, dict) else None
        if staged_credentials:
            print(
                "Migrated EDC connector runtime artifacts to the topology-scoped layout: "
                f"{connector_name}"
            )
        return staged_credentials

    def load_connector_credentials(self, connector_name):
        creds_file = self._connector_credentials_file_path(connector_name, for_write=False)
        if not os.path.exists(creds_file):
            staged_credentials = self._stage_legacy_bootstrap_artifacts_if_needed(connector_name)
            if staged_credentials:
                creds_file = staged_credentials
            else:
                return None

        try:
            with open(creds_file, encoding="utf-8") as handle:
                credentials = json.load(handle)
        except (json.JSONDecodeError, IOError):
            return None
        return self._with_connector_public_access_urls(connector_name, credentials)

    def _with_connector_public_access_urls(self, connector_name, credentials):
        if not isinstance(credentials, dict):
            return credentials

        topology = self._normalized_topology()
        if topology not in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
            return credentials

        public_urls = credentials.get("public_access_urls")
        if not isinstance(public_urls, dict):
            public_urls = {}
        else:
            public_urls = dict(public_urls)

        public_base_url = self._edc_connector_public_base_url_without_credentials(
            connector_name,
            credentials=credentials,
        )
        if public_base_url:
            dashboard_base_href = self.config_adapter.edc_dashboard_base_href()
            inferred_urls = {
                "connector_ingress": public_base_url,
                "connector_management_api": f"{public_base_url}/management",
                "connector_management_api_v3": f"{public_base_url}/management/v3",
                "connector_protocol_api": f"{public_base_url}/protocol",
                "connector_default_api": f"{public_base_url}/api",
                "connector_control_api": f"{public_base_url}/control",
                "edc_dashboard_login": f"{public_base_url}{dashboard_base_href}",
            }
            if self.config_adapter.edc_dashboard_proxy_auth_mode() == "oidc-bff":
                inferred_urls["edc_dashboard_oidc_login"] = (
                    f"{public_base_url}{self.DASHBOARD_PROXY_PREFIX}/auth/login"
                )
            for key, value in inferred_urls.items():
                public_urls.setdefault(key, value)

        dataspace = self._dataspace_name()
        keycloak_base = self._keycloak_base_url()
        if keycloak_base and dataspace:
            public_urls.setdefault("keycloak_realm", f"{keycloak_base}/realms/{dataspace}")
            public_urls.setdefault("keycloak_account", f"{keycloak_base}/realms/{dataspace}/account")
            public_urls.setdefault(
                "keycloak_admin_console",
                f"{keycloak_base}/admin/{dataspace}/console/",
            )

        common_base_url = self._vm_public_common_base_url()
        if common_base_url:
            public_urls.setdefault("minio_api", common_base_url)
            public_urls.setdefault("minio_console", f"{common_base_url}/s3-console/")

        if public_urls:
            credentials = dict(credentials)
            credentials["public_access_urls"] = public_urls
        return credentials

    def _edc_connector_public_base_url_without_credentials(self, connector_name, credentials=None, dataspace=None):
        deployer_config = self.config_adapter.load_deployer_config() or {}
        topology = self._normalized_topology()
        ds_name = str(dataspace or self._dataspace_name() or "").strip()
        if topology == VM_SINGLE_TOPOLOGY:
            return self._normalize_public_url(
                self._vm_single_connector_public_base_url_from_config(
                    connector_name,
                    deployer_config,
                    dataspace=ds_name,
                )
            )

        if topology == VM_DISTRIBUTED_TOPOLOGY:
            public_urls = (credentials or {}).get("public_access_urls") or {}
            if isinstance(public_urls, dict) and public_urls.get("connector_ingress"):
                return self._normalize_public_url(public_urls["connector_ingress"])
            layout = self._connector_layout_metadata(connector_name)
            role = (
                layout.get("namespace_role")
                or layout.get("validation_role")
                or layout.get("role")
                or self._connector_kubeconfig_role(connector_name)
            )
            return self._normalize_public_url(
                self._connector_public_url_for_role(role, deployer_config)
            )

        return ""

    def _vm_public_common_base_url(self):
        deployer_config = self.config_adapter.load_deployer_config() or {}
        topology = self._normalized_topology()
        public_urls = {}
        if topology in {VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}:
            public_urls = resolve_vm_distributed_public_urls(
                {
                    **dict(deployer_config or {}),
                    "TOPOLOGY": topology,
                }
            )
        return self._normalize_public_url(
            deployer_config.get("VM_SINGLE_PUBLIC_URL")
            or deployer_config.get("VM_SINGLE_HTTP_URL")
            or public_urls.get("VM_COMMON_PUBLIC_URL")
            or deployer_config.get("VM_COMMON_PUBLIC_URL")
            or deployer_config.get("VM_COMMON_HTTP_URL")
            or ""
        )

    def _vm_single_connector_public_path_ingress_manifests(self, values, namespace):
        if self._normalized_topology() != VM_SINGLE_TOPOLOGY:
            return []

        connector = (values or {}).get("connector") or {}
        connector_name = str(connector.get("name") or "").strip()
        ds_name = str(connector.get("dataspace") or self._dataspace_name()).strip() or self._dataspace_name()
        if not connector_name:
            return []

        namespace = str(namespace or self._connector_runtime_namespace(connector_name) or "").strip()
        if not namespace:
            return []

        ingress = connector.get("ingress") or {}
        public_url = (
            str(ingress.get("publicHostname") or "").strip()
            or self._edc_connector_public_base_url_without_credentials(connector_name)
        )
        host, path_prefix = self._public_hostname_and_path(public_url)
        if not host or not path_prefix:
            return []

        escaped_prefix = re.escape(path_prefix)
        proxy_body_size = str(ingress.get("proxyBodySize") or "800m")
        common_annotations = {
            "nginx.ingress.kubernetes.io/proxy-body-size": proxy_body_size,
            "nginx.org/client-max-body-size": proxy_body_size,
            "nginx.ingress.kubernetes.io/use-regex": "true",
        }

        def backend(service_name, port):
            return {
                "service": {
                    "name": service_name,
                    "port": {"number": port},
                }
            }

        route_specs = [
            ("api", connector_name, 19191),
            ("control", connector_name, 19192),
            ("management", connector_name, 19193),
            ("protocol", connector_name, 19194),
            ("version", connector_name, 19195),
            ("shared", connector_name, 19196),
            ("public", connector_name, 19291),
        ]
        dashboard = (values or {}).get("dashboard") or {}
        if dashboard.get("enabled"):
            dashboard_proxy = dashboard.get("proxy") or {}
            if dashboard_proxy.get("enabled"):
                route_specs.append(
                    (
                        "edc-dashboard-api",
                        f"{connector_name}-dashboard-proxy",
                        int(dashboard_proxy.get("port") or 8080),
                    )
                )
            route_specs.append(("edc-dashboard", f"{connector_name}-dashboard", 80))

        routed_ingress = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": f"{connector_name}-public-path-ingress",
                "namespace": namespace,
                "annotations": {
                    **common_annotations,
                    "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
                },
            },
            "spec": {
                "rules": [
                    {
                        "host": host,
                        "http": {
                            "paths": [
                                {
                                    "pathType": "ImplementationSpecific",
                                    "path": f"{escaped_prefix}(/|$)({segment}.*)",
                                    "backend": backend(service_name, port),
                                }
                                for segment, service_name, port in route_specs
                            ]
                        },
                    }
                ]
            },
        }

        manifests = [routed_ingress]
        if dashboard.get("enabled"):
            manifests.append(
                {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "Ingress",
                    "metadata": {
                        "name": f"{connector_name}-public-root-ingress",
                        "namespace": namespace,
                        "annotations": {
                            **common_annotations,
                            "nginx.ingress.kubernetes.io/rewrite-target": "/edc-dashboard/",
                        },
                    },
                    "spec": {
                        "rules": [
                            {
                                "host": host,
                                "http": {
                                    "paths": [
                                        {
                                            "pathType": "ImplementationSpecific",
                                            "path": f"{escaped_prefix}/?$",
                                            "backend": backend(f"{connector_name}-dashboard", 80),
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            )
        return manifests

    def _edc_runtime_present(self, connector_name, namespace):
        metadata = self._resource_metadata("deployment", connector_name, namespace)
        if metadata is None:
            return False
        labels = metadata.get("labels", {}) or {}
        return labels.get(self.MANAGED_LABEL_KEY) == self._managed_label_value()

    def _connector_base_url(self, connector_name):
        ds_domain = self.config_adapter.ds_domain_base()
        if not ds_domain:
            return None
        deployer_config = self.config_adapter.load_deployer_config()
        environment = str(deployer_config.get("ENVIRONMENT", "DEV")).strip().upper()
        scheme = "https" if environment == "PRO" else "http"
        return f"{scheme}://{connector_name}.{ds_domain}"

    def _common_services_namespace(self, deployer_config=None):
        if deployer_config is None:
            try:
                deployer_config = self.config_adapter.load_deployer_config() or {}
            except Exception:
                deployer_config = {}
        return str(
            (deployer_config or {}).get("COMMON_SERVICES_NAMESPACE")
            or getattr(self.config, "NS_COMMON", "common-srvs")
            or "common-srvs"
        ).strip() or "common-srvs"

    def _common_service_hostname(self, deployer_config, service_name, default_port=None):
        common_namespace = self._common_services_namespace(deployer_config)
        hostname = f"common-srvs-{service_name}.{common_namespace}.svc"
        if default_port is not None:
            return f"{hostname}:{int(default_port)}"
        return hostname

    @staticmethod
    def _is_loopback_hostname(hostname):
        normalized = str(hostname or "").strip().lower()
        return normalized in {"localhost", "127.0.0.1", "::1"} or normalized.startswith("127.")

    @staticmethod
    def _service_url_parts(raw_value, default_protocol="http"):
        value = str(raw_value or "").strip()
        if not value:
            return "", "", ""
        parsed = urlparse(value if "://" in value else f"{default_protocol}://{value}")
        hostname = str(parsed.netloc or parsed.path or "").strip().rstrip("/")
        if not hostname:
            return "", "", ""
        protocol = str(parsed.scheme or default_protocol or "http").strip().rstrip(":/") or "http"
        path = str(parsed.path or "").strip().rstrip("/")
        url = f"{protocol}://{hostname}{path}"
        return hostname, protocol, url.rstrip("/")

    def _configured_service_endpoint(
        self,
        deployer_config,
        *,
        url_keys,
        hostname_keys,
        default_service_name,
        default_port,
        default_protocol="http",
    ):
        for key in url_keys:
            hostname, protocol, url = self._service_url_parts(
                (deployer_config or {}).get(key),
                default_protocol=default_protocol,
            )
            if hostname and not self._is_loopback_hostname(urlparse(url).hostname):
                return {"hostname": hostname, "protocol": protocol, "url": url}

        for key in hostname_keys:
            hostname, protocol, url = self._service_url_parts(
                (deployer_config or {}).get(key),
                default_protocol=default_protocol,
            )
            if hostname and not self._is_loopback_hostname(urlparse(url).hostname):
                return {"hostname": hostname, "protocol": protocol, "url": url}

        hostname = self._common_service_hostname(
            deployer_config,
            default_service_name,
            default_port=default_port,
        )
        return {
            "hostname": hostname,
            "protocol": "http",
            "url": f"http://{hostname}",
        }

    def _connector_runtime_common_service_endpoints(self, deployer_config, environment):
        default_protocol = "https" if str(environment or "").strip().lower() == "pro" else "http"
        return {
            "database_hostname": str(
                (deployer_config or {}).get("DATABASE_HOSTNAME")
                or self._common_service_hostname(deployer_config, "postgresql")
            ).strip(),
            "keycloak": self._configured_service_endpoint(
                deployer_config,
                url_keys=(
                    "EDC_KEYCLOAK_BASE_URL",
                    "KEYCLOAK_INTERNAL_URL",
                    "KC_INTERNAL_URL",
                ),
                hostname_keys=(
                    "EDC_KEYCLOAK_HOSTNAME",
                    "KEYCLOAK_HOSTNAME",
                ),
                default_service_name="keycloak",
                default_port=80,
                default_protocol=default_protocol,
            ),
            "minio": self._configured_service_endpoint(
                deployer_config,
                url_keys=(
                    "EDC_MINIO_ENDPOINT",
                    "MINIO_INTERNAL_URL",
                    "MINIO_ENDPOINT",
                ),
                hostname_keys=(
                    "EDC_MINIO_HOSTNAME",
                    "MINIO_HOSTNAME",
                ),
                default_service_name="minio",
                default_port=9000,
                default_protocol=default_protocol,
            ),
        }

    def _protocol_url(self, connector_name):
        base_url = self._connector_base_url(connector_name)
        if not base_url:
            return None
        return f"{base_url}/protocol"

    def _host_alias_target_address(self):
        topology = self._normalized_topology()
        if topology == LOCAL_TOPOLOGY:
            return self.run_silent("minikube ip") or self.config.MINIKUBE_IP
        if topology != VM_SINGLE_TOPOLOGY:
            return ""

        config_loader = getattr(self.config_adapter, "load_deployer_config", None)
        deployer_config = dict(config_loader() or {}) if callable(config_loader) else {}
        try:
            profile = build_topology_profile(topology, deployer_config)
        except Exception:
            return ""
        return str(
            getattr(profile, "ingress_external_ip", "")
            or getattr(profile, "default_address", "")
            or ""
        ).strip()

    def _host_aliases(self, connector_hostnames, ds_name=None, ds_namespace=None, connector_name=None):
        target_ip = self._host_alias_target_address()
        if not target_ip:
            return []

        hostnames = self._host_alias_domains_for_dataspace(
            ds_name=ds_name,
            ds_namespace=ds_namespace,
            connector_name=connector_name,
        )
        ds_domain = self.config_adapter.ds_domain_base()
        if ds_domain:
            for connector in connector_hostnames or []:
                hostname = f"{connector}.{ds_domain}"
                if hostname not in hostnames:
                    hostnames.append(hostname)
        return [{"ip": target_ip, "hostnames": hostnames}]

    def _ensure_dashboard_runtime_dir(self, connector_name, ds_name=None):
        runtime_dir = self.config_adapter.edc_dashboard_runtime_dir(connector_name, ds_name=ds_name)
        os.makedirs(runtime_dir, exist_ok=True)
        return runtime_dir

    def _keycloak_base_url(self, override_url=None):
        if override_url:
            keycloak_url = str(override_url).strip()
            if keycloak_url and not keycloak_url.startswith("http"):
                keycloak_url = f"http://{keycloak_url}"
            return keycloak_url.rstrip("/")

        deployer_config = self.config_adapter.load_deployer_config()
        topology = self._normalized_topology()
        public_urls = {}
        if topology in {VM_SINGLE_TOPOLOGY, "vm-distributed"}:
            public_urls = resolve_vm_distributed_public_urls(
                {
                    **dict(deployer_config or {}),
                    "TOPOLOGY": topology,
                }
            )
        keycloak_url = (
            deployer_config.get("KC_MANAGEMENT_URL")
            or deployer_config.get("KEYCLOAK_FRONTEND_URL")
            or deployer_config.get("KEYCLOAK_PUBLIC_URL")
            or public_urls.get("KEYCLOAK_FRONTEND_URL")
            or public_urls.get("KEYCLOAK_PUBLIC_URL")
            or deployer_config.get("KC_INTERNAL_URL")
            or deployer_config.get("KC_URL")
            or deployer_config.get("KEYCLOAK_HOSTNAME")
        )
        if not keycloak_url:
            return None
        if not keycloak_url.startswith("http"):
            keycloak_url = f"http://{keycloak_url}"
        return keycloak_url.rstrip("/")

    def _keycloak_realm_status(self, ds_name, keycloak_url=None):
        keycloak_url = self._keycloak_base_url(keycloak_url)
        if not keycloak_url:
            return "unknown", "KC_INTERNAL_URL/KC_URL is not configured"

        try:
            response = requests.get(
                f"{keycloak_url}/realms/{ds_name}",
                timeout=5,
                verify=False,
            )
        except requests.RequestException as exc:
            return "unknown", str(exc)

        if response.status_code in {200, 302}:
            return "ready", ""
        if response.status_code == 404:
            return "missing", "Keycloak returned HTTP 404 for the dataspace realm"
        return "unknown", f"Keycloak returned HTTP {response.status_code}: {response.text}"

    def _ensure_keycloak_realm_available(self, ds_name, keycloak_url=None):
        status, detail = self._keycloak_realm_status(ds_name, keycloak_url=keycloak_url)
        if status == "ready":
            return True

        if status == "missing":
            message = (
                f"EDC Level 4 cannot continue because Keycloak realm '{ds_name}' does not exist. "
                "Run Level 3 for the EDC adapter to create the dataspace realm, "
                "registration-service state and shared dataspace credentials before deploying connectors."
            )
            self._last_runtime_prerequisite_error = message
            self._last_runtime_prerequisite_code = "keycloak_realm_missing"
            print(message)
            return False

        message = (
            f"EDC Level 4 cannot verify Keycloak realm '{ds_name}' before connector bootstrap. "
            f"Detail: {detail}"
        )
        self._last_runtime_prerequisite_error = message
        self._last_runtime_prerequisite_code = "keycloak_realm_unverified"
        print(message)
        return False

    def _keycloak_token_url_for_dataspace(self, ds_name):
        keycloak_url = self._keycloak_base_url()
        if not keycloak_url:
            return None
        return f"{keycloak_url}/realms/{ds_name}/protocol/openid-connect/token"

    def _keycloak_authorization_url_for_dataspace(self, ds_name):
        keycloak_url = self._keycloak_base_url()
        if not keycloak_url:
            return None
        return f"{keycloak_url}/realms/{ds_name}/protocol/openid-connect/auth"

    def _keycloak_logout_url_for_dataspace(self, ds_name):
        keycloak_url = self._keycloak_base_url()
        if not keycloak_url:
            return None
        return f"{keycloak_url}/realms/{ds_name}/protocol/openid-connect/logout"

    @staticmethod
    def _join_public_paths(prefix, path):
        normalized_prefix = str(prefix or "").strip().rstrip("/")
        normalized_path = str(path or "").strip()
        if not normalized_path:
            normalized_path = "/"
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        return f"{normalized_prefix}{normalized_path}" if normalized_prefix else normalized_path

    def _dashboard_public_path_prefix(self, connector_name, ds_name=None):
        public_base_url = self._edc_connector_public_base_url_without_credentials(
            connector_name,
            dataspace=ds_name,
        )
        if not public_base_url:
            return ""
        parsed = urlparse(public_base_url)
        return str(parsed.path or "").rstrip("/")

    def _dashboard_public_base_href(self, connector_name, ds_name=None):
        public_base_href = self._join_public_paths(
            self._dashboard_public_path_prefix(connector_name, ds_name=ds_name),
            self.config_adapter.edc_dashboard_base_href(),
        )
        return f"{public_base_href.rstrip('/')}/"

    def _dashboard_browser_proxy_connector_path(self, dashboard_connector_name, target_connector_name, service_name, ds_name=None):
        return self._join_public_paths(
            self._dashboard_public_path_prefix(dashboard_connector_name, ds_name=ds_name),
            self._dashboard_proxy_connector_path(target_connector_name, service_name),
        )

    def _dashboard_browser_component_proxy_path(self, dashboard_connector_name, component_name, ds_name=None):
        return self._join_public_paths(
            self._dashboard_public_path_prefix(dashboard_connector_name, ds_name=ds_name),
            self._dashboard_component_proxy_path(component_name),
        )

    def _dashboard_proxy_connector_path(self, connector_name, service_name):
        return f"{self.DASHBOARD_PROXY_PREFIX}/connectors/{connector_name}/{service_name}"

    @staticmethod
    def _dashboard_service_target(connector_name, service_name, connector_namespace=None):
        port_map = {
            "management": 19193,
            "api": 19191,
            "control": 19192,
            "protocol": 19194,
        }
        path_map = {
            "management": "/management",
            "api": "/api",
            "control": "/control",
            "protocol": "/protocol",
        }
        port = port_map[service_name]
        path = path_map[service_name]
        namespace = str(connector_namespace or "").strip()
        host = f"{connector_name}.{namespace}.svc.cluster.local" if namespace else connector_name
        return f"http://{host}:{port}{path}"

    def _dashboard_connector_namespace_map(self, ds_name, connector_hostnames):
        try:
            dataspaces = self.load_dataspace_connectors() or []
        except Exception:
            return {}

        current = None
        for dataspace in dataspaces:
            if str(dataspace.get("name") or "").strip() == str(ds_name or "").strip():
                current = dataspace
                break
            connectors = set(dataspace.get("connectors") or [])
            if any(connector in connectors for connector in connector_hostnames or []):
                current = dataspace
                break

        if not current:
            return {}

        result = {}
        for connector_name in connector_hostnames or []:
            namespace = str(
                self._connector_target_namespace(
                    connector_name,
                    dataspace=current,
                    dataspaces=dataspaces,
                )
                or ""
            ).strip()
            if namespace:
                result[connector_name] = namespace
        return result

    @staticmethod
    def _dashboard_menu_items():
        return [
            {
                "text": "Home",
                "materialSymbol": "home_app_logo",
                "routerPath": "home",
                "divider": True,
            },
            {
                "text": "ML Assets",
                "materialSymbol": "deployed_code_update",
                "routerPath": "ml-assets",
            },
            {
                "text": "Model Execution",
                "materialSymbol": "smart_toy",
                "routerPath": "model-execution",
            },
            {
                "text": "Model Benchmarking",
                "materialSymbol": "query_stats",
                "routerPath": "model-benchmarking",
            },
            {
                "text": "Model Observer",
                "materialSymbol": "fact_check",
                "routerPath": "model-observer",
            },
            {
                "text": "Catalog",
                "materialSymbol": "book_ribbon",
                "routerPath": "catalog",
            },
            {
                "text": "Assets",
                "materialSymbol": "deployed_code_update",
                "routerPath": "assets",
            },
            {
                "text": "Policy Definitions",
                "materialSymbol": "policy",
                "routerPath": "policies",
            },
            {
                "text": "Contract Definitions",
                "materialSymbol": "contract_edit",
                "routerPath": "contract-definitions",
                "divider": True,
            },
            {
                "text": "Ontologies",
                "materialSymbol": "account_tree",
                "routerPath": "ontologies",
                "viewDescription": (
                    "Browse ontologies registered in Ontology Hub and open the hub to create or edit vocabularies."
                ),
            },
            {
                "text": "Contracts",
                "materialSymbol": "handshake",
                "routerPath": "contracts",
            },
            {
                "text": "Transfer History",
                "materialSymbol": "schedule_send",
                "routerPath": "transfer-history",
            },
        ]

    def _dashboard_app_config_payload(self, connector_name, ds_name=None):
        return {
            "appTitle": f"EDC Dashboard - {connector_name}",
            "healthCheckIntervalSeconds": 30,
            "enableUserConfig": False,
            "menuItems": self._dashboard_menu_items(),
            "runtime": self._dashboard_runtime_config_block(
                connector_name=connector_name,
                ds_name=ds_name,
            ),
        }

    def _dashboard_runtime_config_block(self, connector_name=None, ds_name=None):
        config = self.config_adapter.load_deployer_config()
        dataspace_name = ""
        getter = getattr(self.config_adapter, "primary_dataspace_name", None)
        if callable(getter):
            dataspace_name = str(getter() or "").strip()
        if ds_name:
            dataspace_name = str(ds_name or "").strip()
        if not dataspace_name:
            dataspace_name = str(config.get("DS_1_NAME") or getattr(self.config, "DS_NAME", "") or "").strip()

        ontology_public_url = self._resolve_ontology_hub_url(config, dataspace_name=dataspace_name)
        ontology_url = (
            self._dashboard_browser_component_proxy_path(
                connector_name,
                "ontology-hub",
                ds_name=dataspace_name,
            )
            if connector_name and self._dashboard_component_proxy_enabled(config)
            else self._dashboard_component_proxy_path("ontology-hub")
            if self._dashboard_component_proxy_enabled(config)
            else ontology_public_url
        )
        model_observer_url = ""
        if connector_name:
            model_observer_url = (
                f"{self._dashboard_browser_proxy_connector_path(connector_name, connector_name, 'api', ds_name=dataspace_name)}/check"
            )
        return {
            "ontologyUrl": ontology_url,
            "ontologyPublicUrl": ontology_public_url,
            "ontologyAdminUser": str(config.get("ONTOLOGY_HUB_ADMIN_EMAIL") or "").strip(),
            "ontologyAdminPassword": str(config.get("ONTOLOGY_HUB_ADMIN_PASSWORD") or "").strip(),
            "modelObserverUrl": model_observer_url,
            "transferProcessBasePath": "transferprocesses",
        }

    @classmethod
    def _dashboard_component_proxy_path(cls, component_name):
        normalized = str(component_name or "").strip().strip("/")
        return f"{cls.DASHBOARD_PROXY_PREFIX}/components/{normalized}"

    def _dashboard_component_proxy_enabled(self, config):
        raw_value = str(config.get("EDC_DASHBOARD_COMPONENT_PROXY_ENABLED", "true") or "true").strip().lower()
        return raw_value not in {"0", "false", "no", "off"}

    def _dashboard_component_proxy_config_entries(self, config, ds_name):
        if not self._dashboard_component_proxy_enabled(config):
            return []
        ontology_target = self._resolve_ontology_hub_internal_url(config, ds_name)
        entries = []
        if ontology_target:
            entries.append({"name": "ontology-hub", "target": ontology_target})
        return entries

    @staticmethod
    def _component_base_dataspace_name(ds_name):
        resolved = str(ds_name or "").strip()
        for suffix in ("-edc", "_edc"):
            if resolved.lower().endswith(suffix):
                return resolved[: -len(suffix)] or resolved
        return resolved

    def _component_uses_shared_release_scope(self, component_name, config):
        normalized = normalize_component_key(component_name)
        if not normalized:
            return False

        raw_value = str(
            (config or {}).get("COMPONENTS_SHARED_RELEASE_COMPONENTS")
            or "ontology-hub,ai-model-hub,semantic-virtualization"
        ).strip()
        lowered = raw_value.lower()
        if lowered in {"*", "all"}:
            return True
        if lowered in {"", "none", "false", "no", "0"}:
            return False

        configured = {
            normalize_component_key(token)
            for token in raw_value.split(",")
            if str(token or "").strip()
        }
        return normalized in configured

    def _component_release_dataspace_name(self, component_name, config, ds_name=""):
        resolved_ds_name = str(ds_name or (config or {}).get("DS_1_NAME") or "").strip()
        explicit = str(
            (config or {}).get("COMPONENTS_RELEASE_DATASPACE_NAME")
            or (config or {}).get("COMPONENTS_HELM_RELEASE_DATASPACE_NAME")
            or ""
        ).strip()
        if explicit:
            return explicit

        scope = str((config or {}).get("COMPONENTS_RELEASE_SCOPE") or "auto").strip().lower()
        if scope in {"dataspace", "adapter", "per-adapter", "adapter-dataspace"}:
            return resolved_ds_name
        if scope in {"shared", "base", "common", "common-dataspace"}:
            return self._component_base_dataspace_name(resolved_ds_name)
        if self._component_uses_shared_release_scope(component_name, config):
            return self._component_base_dataspace_name(resolved_ds_name)
        return resolved_ds_name

    def _component_internal_service_url(self, component_name, config, ds_name, default_port):
        normalized = normalize_component_key(component_name)
        if not normalized:
            return ""

        namespace = str((config or {}).get("COMPONENTS_NAMESPACE") or "components").strip() or "components"
        component_ds_name = self._component_release_dataspace_name(
            normalized,
            config,
            ds_name=ds_name,
        )
        release_name = resolve_component_release_name(
            normalized,
            dataspace_name=component_ds_name,
        )
        if not release_name:
            return ""
        return f"http://{release_name}.{namespace}:{int(default_port)}"

    def _component_internal_clusterlocal_url(self, component_name, config, ds_name, default_port):
        service_url = self._component_internal_service_url(
            component_name,
            config,
            ds_name,
            default_port,
        )
        if not service_url:
            return ""
        parsed = urlparse(service_url)
        host = str(parsed.netloc or "").split(":", 1)[0]
        if not host or ".svc." in host:
            return service_url
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme or 'http'}://{host}.svc.cluster.local{port}"

    def _resolve_ontology_hub_internal_url(self, config, ds_name):
        explicit = str(
            config.get("ONTOLOGY_HUB_INTERNAL_URL")
            or config.get("ONTOLOGY_HUB_INTERNAL_BASE_URL")
            or ""
        ).strip()
        if explicit:
            return explicit.rstrip("/")

        return self._component_internal_service_url(
            "ontology-hub",
            config,
            str(ds_name or config.get("DS_1_NAME") or "").strip(),
            3333,
        )

    def _resolve_ontology_hub_internal_clusterlocal_url(self, config, ds_name):
        explicit = str(
            config.get("ONTOLOGY_HUB_INTERNAL_CLUSTERLOCAL_URL")
            or config.get("ONTOLOGY_HUB_INTERNAL_CLUSTERLOCAL_BASE_URL")
            or ""
        ).strip()
        if explicit:
            return explicit.rstrip("/")

        return self._component_internal_clusterlocal_url(
            "ontology-hub",
            config,
            str(ds_name or config.get("DS_1_NAME") or "").strip(),
            3333,
        )

    def _resolve_ontology_hub_url(self, config, dataspace_name=""):
        explicit = str(
            config.get("ONTOLOGY_HUB_PUBLIC_URL")
            or config.get("ONTOLOGY_HUB_PUBLIC_BASE_URL")
            or config.get("ONTOLOGY_HUB_URL")
            or config.get("ONTOLOGY_HUB_BASE_URL")
            or ""
        ).strip()
        if explicit:
            return explicit.rstrip("/")

        raw_host = str(
            config.get("ONTOLOGY_HUB_HOST")
            or config.get("ONTOLOGY_HUB_HOSTNAME")
            or ""
        ).strip()
        if raw_host.startswith("http://") or raw_host.startswith("https://"):
            return raw_host.rstrip("/")
        if raw_host:
            return f"http://{raw_host}".rstrip("/")

        if not dataspace_name:
            dataspace_name = str(config.get("DS_1_NAME") or getattr(self.config, "DS_NAME", "") or "").strip()
        component_dataspace_name = self._component_release_dataspace_name(
            "ontology-hub",
            config,
            ds_name=dataspace_name,
        )

        configured_url = configured_component_public_url(
            "ontology-hub",
            config,
            dataspace_name=component_dataspace_name,
        )
        if configured_url:
            return configured_url.rstrip("/")

        configured_host = configured_component_host(
            "ontology-hub",
            config,
            dataspace_name=component_dataspace_name,
        )
        if configured_host:
            return f"http://{configured_host}".rstrip("/")

        return EDCConnectorsAdapter.DEFAULT_ONTOLOGY_HUB_URL

    def _dashboard_connector_config_payload(self, connector_name, connector_hostnames, ds_name=None):
        ordered_connectors = [connector_name] + [
            hostname for hostname in (connector_hostnames or []) if hostname != connector_name
        ]
        connector_entries = []
        for hostname in ordered_connectors:
            connector_entries.append(
                {
                    "connectorName": hostname,
                    "managementUrl": self._dashboard_browser_proxy_connector_path(
                        connector_name,
                        hostname,
                        "management",
                        ds_name=ds_name,
                    ),
                    "defaultUrl": self._dashboard_browser_proxy_connector_path(
                        connector_name,
                        hostname,
                        "api",
                        ds_name=ds_name,
                    ),
                    "protocolUrl": self._dashboard_browser_proxy_connector_path(
                        connector_name,
                        hostname,
                        "protocol",
                        ds_name=ds_name,
                    ),
                    "controlUrl": self._dashboard_browser_proxy_connector_path(
                        connector_name,
                        hostname,
                        "control",
                        ds_name=ds_name,
                    ),
                    "federatedCatalogEnabled": False,
                }
            )
        return connector_entries

    def _dashboard_proxy_config_payload(self, ds_name, connector_hostnames, connector_name=None):
        config = self.config_adapter.load_deployer_config()
        auth_mode = self.config_adapter.edc_dashboard_proxy_auth_mode()
        connector_namespaces = self._dashboard_connector_namespace_map(ds_name, connector_hostnames)
        external_base_url = self._edc_connector_public_base_url_without_credentials(
            connector_name or (connector_hostnames or [""])[0],
            dataspace=ds_name,
        )
        connector_entries = []
        for connector_name in connector_hostnames or []:
            credentials = self.load_connector_credentials(connector_name)
            connector_user = credentials.get("connector_user", {}) if credentials else {}
            connector_namespace = connector_namespaces.get(connector_name)
            connector_entries.append(
                {
                    "connectorName": connector_name,
                    "managementTarget": self._dashboard_service_target(
                        connector_name,
                        "management",
                        connector_namespace=connector_namespace,
                    ),
                    "defaultTarget": self._dashboard_service_target(
                        connector_name,
                        "api",
                        connector_namespace=connector_namespace,
                    ),
                    "controlTarget": self._dashboard_service_target(
                        connector_name,
                        "control",
                        connector_namespace=connector_namespace,
                    ),
                    "protocolTarget": self._dashboard_service_target(
                        connector_name,
                        "protocol",
                        connector_namespace=connector_namespace,
                    ),
                    "username": connector_user.get("user", ""),
                }
            )
        return {
            "authMode": auth_mode,
            "clientId": self.config_adapter.edc_dashboard_proxy_client_id(),
            "scope": self.config_adapter.edc_dashboard_proxy_scope(),
            "tokenUrl": self._keycloak_token_url_for_dataspace(ds_name),
            "authorizationUrl": self._keycloak_authorization_url_for_dataspace(ds_name),
            "logoutUrl": self._keycloak_logout_url_for_dataspace(ds_name),
            "externalBaseUrl": external_base_url,
            "callbackPath": f"{self.DASHBOARD_PROXY_PREFIX}/auth/callback",
            "loginPath": f"{self.DASHBOARD_PROXY_PREFIX}/auth/login",
            "logoutPath": f"{self.DASHBOARD_PROXY_PREFIX}/auth/logout",
            "postLoginRedirectPath": self.config_adapter.edc_dashboard_base_href(),
            "postLogoutRedirectPath": self.config_adapter.edc_dashboard_base_href(),
            "cookieName": self.config_adapter.edc_dashboard_proxy_cookie_name(),
            "cookieSecure": (external_base_url or self._connector_base_url(connector_hostnames[0])).startswith("https://")
            if connector_hostnames
            else False,
            "connectors": connector_entries,
            "components": self._dashboard_component_proxy_config_entries(config=config, ds_name=ds_name),
        }

    def _dashboard_proxy_auth_payload(self, connector_hostnames):
        if self.config_adapter.edc_dashboard_proxy_auth_mode() != "service-account":
            return {"connectors": []}
        connector_entries = []
        for connector_name in connector_hostnames or []:
            credentials = self.load_connector_credentials(connector_name)
            connector_user = credentials.get("connector_user", {}) if credentials else {}
            connector_entries.append(
                {
                    "connectorName": connector_name,
                    "password": connector_user.get("passwd", ""),
                }
            )
        return {"connectors": connector_entries}

    def _dashboard_runtime_payload(self, connector_name, connector_hostnames, ds_name=None):
        return {
            "appConfig": self._dashboard_app_config_payload(connector_name, ds_name=ds_name),
            "connectorConfig": self._dashboard_connector_config_payload(
                connector_name,
                connector_hostnames,
                ds_name=ds_name,
            ),
            "baseHref": self._dashboard_public_base_href(connector_name, ds_name=ds_name),
        }

    @staticmethod
    def _write_json_file(target_path, payload):
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    @staticmethod
    def _write_text_file(target_path, content):
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def _validate_dashboard_runtime_payload(self, connector_name, runtime_payload):
        if not self.config_adapter.edc_dashboard_enabled():
            return True

        app_config = runtime_payload.get("appConfig") or {}
        runtime = app_config.get("runtime") or {}
        menu_items = app_config.get("menuItems") or []
        menu_paths = {
            str(item.get("routerPath") or "").strip()
            for item in menu_items
            if isinstance(item, dict)
        }

        issues = []
        if "model-observer" not in menu_paths:
            issues.append("menuItems must include routerPath 'model-observer'")
        if "ontologies" not in menu_paths:
            issues.append("menuItems must include routerPath 'ontologies'")

        try:
            config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            config = {}
        if self._dashboard_component_proxy_enabled(config):
            ontology_url = str(runtime.get("ontologyUrl") or "").strip()
            expected_suffix = self._dashboard_component_proxy_path("ontology-hub")
            if not ontology_url.endswith(expected_suffix):
                issues.append(
                    "runtime.ontologyUrl must use the dashboard component proxy "
                    f"'{expected_suffix}'"
                )

        if connector_name:
            observer_url = str(runtime.get("modelObserverUrl") or "").strip()
            expected_prefix = self._dashboard_proxy_connector_path(connector_name, "api")
            if expected_prefix not in observer_url:
                issues.append(
                    "runtime.modelObserverUrl must point to the selected connector proxy "
                    f"'{expected_prefix}'"
                )

        if issues:
            raise RuntimeError(
                "Generated EDC dashboard runtime is incomplete for "
                f"{connector_name}: " + "; ".join(issues)
            )
        return True

    def _write_dashboard_runtime_config(self, connector_name, ds_name, runtime_payload):
        self._validate_dashboard_runtime_payload(connector_name, runtime_payload)
        self._ensure_dashboard_runtime_dir(connector_name, ds_name=ds_name)
        app_config_path = self.config_adapter.edc_dashboard_app_config_file(
            connector_name,
            ds_name=ds_name,
        )
        connector_config_path = self.config_adapter.edc_dashboard_connector_config_file(
            connector_name,
            ds_name=ds_name,
        )
        base_href_path = self.config_adapter.edc_dashboard_base_href_file(
            connector_name,
            ds_name=ds_name,
        )
        self._write_json_file(app_config_path, runtime_payload["appConfig"])
        self._write_json_file(connector_config_path, runtime_payload["connectorConfig"])
        self._write_text_file(base_href_path, runtime_payload["baseHref"])
        return {
            "directory": self.config_adapter.edc_dashboard_runtime_dir(
                connector_name,
                ds_name=ds_name,
            ),
            "appConfigFile": app_config_path,
            "connectorConfigFile": connector_config_path,
            "baseHrefFile": base_href_path,
        }

    def _connector_values_payload(self, connector_name, ds_name, connector_hostnames, connector_namespace=None):
        deployer_config = self.config_adapter.load_deployer_config()
        credentials = self.load_connector_credentials(connector_name)
        if not credentials:
            raise RuntimeError(f"Connector credentials not found for {connector_name}")

        environment = (
            "pro"
            if str(deployer_config.get("ENVIRONMENT", "DEV")).strip().upper() == "PRO"
            else "dev"
        )
        ds_domain = self.config_adapter.ds_domain_base()
        if not ds_domain:
            raise RuntimeError("DS_DOMAIN_BASE not defined in deployer.config")

        common_service_endpoints = self._connector_runtime_common_service_endpoints(
            deployer_config,
            environment,
        )
        keycloak_endpoint = common_service_endpoints["keycloak"]
        minio_endpoint = common_service_endpoints["minio"]
        database_hostname = common_service_endpoints["database_hostname"]
        ontology_hub_external_url = self._resolve_ontology_hub_url(
            deployer_config,
            dataspace_name=ds_name,
        )
        ontology_hub_internal_url = self._resolve_ontology_hub_internal_url(
            deployer_config,
            ds_name,
        )
        ontology_hub_clusterlocal_url = self._resolve_ontology_hub_internal_clusterlocal_url(
            deployer_config,
            ds_name,
        )

        dashboard_runtime = self._dashboard_runtime_payload(
            connector_name,
            connector_hostnames,
            ds_name=ds_name,
        )
        dashboard_proxy_config = self._dashboard_proxy_config_payload(
            ds_name,
            connector_hostnames,
            connector_name=connector_name,
        )
        dashboard_proxy_auth = self._dashboard_proxy_auth_payload(connector_hostnames)
        if environment == "pro":
            registration_service_hostname = f"registration-service-{ds_name}.ds.dataspaceunit-project.eu"
        else:
            hostname_getter = getattr(self.config_adapter, "registration_service_internal_hostname", None)
            if callable(hostname_getter):
                registration_service_hostname = hostname_getter(
                    ds_name=ds_name,
                    connector_namespace=connector_namespace,
                )
            else:
                registration_service_hostname = f"{ds_name}-registration-service:8080"

        return {
            "connector": {
                "name": connector_name,
                "dataspace": ds_name,
                "environment": environment,
                "layout": self._connector_layout_metadata(
                    connector_name,
                    ds_name=ds_name,
                    ds_namespace=connector_namespace,
                ),
                "image": {
                    "name": self.config_adapter.edc_connector_image_name(),
                    "tag": self.config_adapter.edc_connector_image_tag(),
                    "pullPolicy": self.config_adapter.edc_connector_image_pull_policy(),
                },
                "replicas": 1,
                "jvmArgs": (
                    "-Djavax.net.ssl.trustStore=/opt/connector/tls-cacerts/cacerts.jks "
                    "-Djavax.net.ssl.trustStorePassword=dataspaceunit"
                    if environment == "pro"
                    else ""
                ),
                "configuration": {
                    "configFilePath": "/opt/connector/config/connector-configuration.properties",
                },
                "sql": {
                    "schemaAutocreate": self.config_adapter.edc_sql_schema_autocreate(),
                },
                "ingress": {
                    "hostname": f"{connector_name}.{ds_domain}",
                    "protocol": "https" if environment == "pro" else "http",
                },
                "minio": {
                    "accesskey": f"{ds_name}/{connector_name}/aws-access-key",
                    "secretkey": f"{ds_name}/{connector_name}/aws-secret-key",
                },
                "oauth2": {
                    "allowedRole1": "connector-admin",
                    "allowedRole2": "connector-management",
                    "allowedRole3": "connector-user",
                    "client": connector_name,
                    "privatekey": f"{ds_name}/{connector_name}/private-key",
                    "publickey": f"{ds_name}/{connector_name}/public-key",
                },
                "transfer": {
                    "privatekey": f"{ds_name}/{connector_name}/private-key",
                    "publickey": f"{ds_name}/{connector_name}/public-key",
                },
                "keys": {
                    "createSecret": False,
                    "existingSecret": "",
                },
                "ontologyHub": {
                    "externalBase": ontology_hub_external_url,
                    "internalBase": ontology_hub_internal_url,
                    "internalFallback": "http://ontology-hub:3333",
                    "internalClusterLocalFallback": ontology_hub_clusterlocal_url,
                },
            },
            "dashboard": {
                "enabled": self.config_adapter.edc_dashboard_enabled(),
                "replicas": 1,
                "baseHref": dashboard_runtime["baseHref"],
                "image": {
                    "name": self.config_adapter.edc_dashboard_image_name(),
                    "tag": self.config_adapter.edc_dashboard_image_tag(),
                    "pullPolicy": self.config_adapter.edc_dashboard_image_pull_policy(),
                },
                "proxy": {
                    "enabled": self.config_adapter.edc_dashboard_enabled(),
                    "port": 8080,
                    "image": {
                        "name": self.config_adapter.edc_dashboard_proxy_image_name(),
                        "tag": self.config_adapter.edc_dashboard_proxy_image_tag(),
                        "pullPolicy": self.config_adapter.edc_dashboard_proxy_image_pull_policy(),
                    },
                    "config": dashboard_proxy_config,
                    "auth": dashboard_proxy_auth,
                },
                "runtime": dashboard_runtime,
            },
            "services": {
                "db": {
                    "hostname": database_hostname,
                    "name": credentials["database"]["name"],
                    "user": credentials["database"]["user"],
                    "password": credentials["database"]["passwd"],
                },
                "keycloak": {
                    "hostname": keycloak_endpoint["hostname"],
                    "external": keycloak_endpoint["hostname"],
                    "protocol": keycloak_endpoint["protocol"],
                    "url": keycloak_endpoint["url"],
                },
                "minio": {
                    "hostname": minio_endpoint["hostname"],
                    "bucket": f"{ds_name}-{connector_name}",
                    "protocol": minio_endpoint["protocol"],
                    "url": minio_endpoint["url"],
                },
                "registrationService": {
                    "hostname": registration_service_hostname,
                    "protocol": "https" if environment == "pro" else "http",
                },
                "vault": {
                    "url": deployer_config.get("VAULT_URL") or deployer_config.get("VT_URL"),
                    "token": credentials.get("vault", {}).get("token", ""),
                    "path": f"{ds_name}/{connector_name}/",
                },
            },
            "hostAliases": self._host_aliases(
                connector_hostnames,
                ds_name=ds_name,
                connector_name=connector_name,
            ),
        }

    def _render_values_file(self, connector_name, ds_name, connector_hostnames, connector_namespace=None):
        values_path = self._values_file_path(connector_name, ds_name=ds_name)
        os.makedirs(os.path.dirname(values_path), exist_ok=True)
        payload = self._connector_values_payload(
            connector_name,
            ds_name,
            connector_hostnames,
            connector_namespace=connector_namespace,
        )
        dashboard_runtime = payload.get("dashboard", {}).get("runtime")
        if dashboard_runtime:
            self._write_dashboard_runtime_config(
                connector_name,
                ds_name,
                dashboard_runtime,
            )
        with open(values_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False)
        return values_path

    def _redacted_values_preview(self, payload):
        connector = payload.get("connector", {}) or {}
        services = payload.get("services", {}) or {}
        image = connector.get("image", {}) or {}
        ingress = connector.get("ingress", {}) or {}
        db = services.get("db", {}) or {}
        registration_service = services.get("registrationService", {}) or {}
        minio = services.get("minio", {}) or {}
        host_aliases = payload.get("hostAliases", []) or []
        first_alias = host_aliases[0] if host_aliases else {}
        dashboard = payload.get("dashboard", {}) or {}

        protocol = ingress.get("protocol", "http")
        hostname = ingress.get("hostname")
        dsp_url = f"{protocol}://{hostname}/protocol" if hostname else None
        dashboard_url = (
            f"{protocol}://{hostname}{dashboard.get('baseHref', '/edc-dashboard/')}"
            if hostname and dashboard.get("enabled")
            else None
        )
        registration_protocol = registration_service.get("protocol", "http")
        registration_host = registration_service.get("hostname")
        registration_url = (
            f"{registration_protocol}://{registration_host}/api"
            if registration_host
            else None
        )

        return {
            "image": f"{image.get('name', '')}:{image.get('tag', '')}",
            "ingress_hostname": hostname,
            "management_api_url": self.build_connector_url(connector.get("name")),
            "dsp_url": dsp_url,
            "dashboard_url": dashboard_url,
            "database_name": db.get("name"),
            "minio_bucket": minio.get("bucket"),
            "registration_service_url": registration_url,
            "host_aliases": list(first_alias.get("hostnames", []) or []),
        }

    def preview_deploy_connectors(self):
        preview = {
            "status": "ready",
            "chart_dir": self._edc_connector_dir(),
            "dataspaces": [],
            "blocking_reasons": [],
        }

        try:
            dataspaces = self.load_dataspace_connectors()
        except Exception as exc:
            return {
                "status": "blocked",
                "chart_dir": self._edc_connector_dir(),
                "dataspaces": [],
                "blocking_reasons": [str(exc)],
            }

        if not dataspaces:
            preview["status"] = "empty"
            preview["blocking_reasons"].append("No dataspaces defined in deployer.config")
            return preview

        any_blocked = False
        any_bootstrap_required = False

        for dataspace in dataspaces:
            ds_name = dataspace["name"]
            namespace = dataspace["namespace"]
            connectors = dataspace["connectors"]
            target_namespaces = self._dataspace_connector_target_namespaces(dataspace, dataspaces=dataspaces)
            connector_details = {
                entry.get("name"): entry
                for entry in (dataspace.get("connector_details") or [])
                if entry.get("name")
            }
            dataspace_preview = {
                "name": ds_name,
                "namespace": namespace,
                "namespace_profile": dataspace.get("namespace_profile", "compact"),
                "namespace_roles": dict(dataspace.get("namespace_roles") or {}),
                "planned_namespace_roles": dict(dataspace.get("planned_namespace_roles") or {}),
                "connector_roles": dict(dataspace.get("connector_roles") or {}),
                "connectors": [],
            }

            for connector in connectors:
                connector_layout = connector_details.get(connector, {})
                target_namespace = self._connector_target_namespace(
                    connector,
                    dataspace=dataspace,
                    dataspaces=dataspaces,
                )
                connector_preview = {
                    "name": connector,
                    "role": connector_layout.get("role"),
                    "release_name": f"{connector}-{ds_name}",
                    "namespace": namespace,
                    "target_namespace": target_namespace,
                    "active_namespace": connector_layout.get("active_namespace", namespace),
                    "planned_namespace": connector_layout.get("planned_namespace", namespace),
                    "registration_service_namespace": connector_layout.get(
                        "registration_service_namespace",
                        dataspace_preview["namespace_roles"].get("registration_service_namespace"),
                    ),
                    "planned_registration_service_namespace": connector_layout.get(
                        "planned_registration_service_namespace",
                        dataspace_preview["planned_namespace_roles"].get("registration_service_namespace"),
                    ),
                    "values_file": self._values_file_path(connector, ds_name=ds_name),
                    "management_api_url": self.build_connector_url(connector),
                    "dsp_url": self._protocol_url(connector),
                    "credentials_present": False,
                    "bootstrap_required": False,
                    "conflicts": [],
                    "render_summary": None,
                    "issues": [],
                    "status": "ready",
                }

                conflicts = self._conflicting_runtime_resources(
                    connector,
                    connector_preview["target_namespace"],
                )
                if conflicts:
                    connector_preview["status"] = "blocked"
                    connector_preview["conflicts"] = conflicts
                    connector_preview["issues"].append(
                        "Existing runtime resources are not managed by the EDC adapter."
                    )
                    preview["blocking_reasons"].append(
                        f"{connector} in namespace {connector_preview['target_namespace']}: {', '.join(conflicts)}"
                    )
                    any_blocked = True

                credentials = self.load_connector_credentials(connector)
                connector_preview["credentials_present"] = bool(credentials)
                if not credentials:
                    connector_preview["bootstrap_required"] = True
                    connector_preview["issues"].append(
                        "Missing connector credentials. Bootstrap is required before the final values file can be rendered."
                    )
                    if connector_preview["status"] != "blocked":
                        connector_preview["status"] = "bootstrap-required"
                    any_bootstrap_required = True
                elif connector_preview["status"] != "blocked":
                    payload = self._connector_values_payload(
                        connector,
                        ds_name,
                        connectors,
                        connector_namespace=target_namespace,
                    )
                    connector_preview["render_summary"] = self._redacted_values_preview(payload)

                dataspace_preview["connectors"].append(connector_preview)

            preview["dataspaces"].append(dataspace_preview)

        if any_blocked:
            preview["status"] = "blocked"
        elif any_bootstrap_required:
            preview["status"] = "bootstrap-required"

        return preview

    def _prepare_runtime_prerequisites(self):
        self._last_runtime_prerequisite_error = None
        self._last_runtime_prerequisite_code = None
        repo_dir = self.config.repo_dir()
        native_bootstrap = bool(getattr(self.config, "EDC_NATIVE_BOOTSTRAP", False))
        python_exec = self.config.python_exec() if hasattr(self.config, "python_exec") else sys.executable
        if not os.path.exists(repo_dir):
            return self._fail_runtime_prerequisite(f"EDC deployment directory not found: {repo_dir}")
        bootstrap_script = self.config_adapter.edc_bootstrap_script()
        if not os.path.exists(bootstrap_script):
            return self._fail_runtime_prerequisite(f"EDC bootstrap deployer not found: {bootstrap_script}")
        if not native_bootstrap:
            if not os.path.exists(self.config.venv_path()):
                return self._fail_runtime_prerequisite("Python environment not found. Run Level 3 first")
            ensure_python_requirements(
                python_exec,
                self.config.repo_requirements_path(),
                label="EDC runtime",
                quiet=True,
            )
        if not os.path.isdir(self._edc_connector_dir()):
            return self._fail_runtime_prerequisite(
                f"EDC connector chart directory not found: {self._edc_connector_dir()}"
            )
        if not self._ensure_local_runtime_access_if_required():
            return self._fail_runtime_prerequisite(
                "EDC Level 4 cannot continue because local access to PostgreSQL, Vault or MinIO is not ready."
            )
        if not self.infrastructure.ensure_vault_unsealed():
            return self._fail_runtime_prerequisite(
                "EDC Level 4 cannot continue because Vault is not ready and unsealed."
            )
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
                return self._fail_runtime_prerequisite(
                    "EDC Level 4 cannot continue because the local Vault token does not match "
                    "the running common services. Restore the topology-scoped Vault keys artifact "
                    "from the environment that created common-srvs, or recreate Level 2 common services "
                    "and then rerun Level 3 and Level 4.",
                    code="vault_token_mismatch",
                )
        if not self._verify_vault_management_token():
            return self._fail_runtime_prerequisite(
                "EDC Level 4 cannot continue because deployer.config does not contain a valid "
                "Vault management token for the running common services.",
                code="vault_token_invalid",
            )
        return repo_dir, python_exec

    def _prepare_connector_prerequisites(self, connector_name, ds_name, namespace, repo_dir, python_exec):
        bootstrap_access = self._start_level4_connector_bootstrap_access()
        if bootstrap_access is None:
            return False
        vault_url = bootstrap_access.get("vault_url")
        keycloak_url = bootstrap_access.get("keycloak_url")
        pg_host = bootstrap_access.get("pg_host")
        pg_port = bootstrap_access.get("pg_port")

        try:
            self._stage_bootstrap_artifacts(connector_name, ds_name, repo_dir)
            credentials = self.load_connector_credentials(connector_name)
            runtime_present = self._edc_runtime_present(connector_name, namespace)

            if not credentials:
                credentials = self.load_connector_credentials(connector_name)

            if credentials and runtime_present:
                database_credentials_valid = True
                database_validator = getattr(self, "_connector_database_credentials_query_valid", None)
                if callable(database_validator):
                    database_credentials_valid = bool(
                        database_validator(
                            connector_name,
                            pg_host=pg_host,
                            pg_port=pg_port,
                        )
                    )
                if not database_credentials_valid:
                    print(
                        "EDC connector database credentials are stale or invalid; "
                        f"recreating connector state: {connector_name}"
                    )
                else:
                    reconcile_kwargs = {"credentials": credentials}
                    if vault_url:
                        reconcile_kwargs["vault_url"] = vault_url
                    if not self._reconcile_connector_vault_secrets(
                        connector_name,
                        ds_name,
                        **reconcile_kwargs,
                    ):
                        return False
                    self.ensure_minio_policy_attached(connector_name, ds_name=ds_name)
                    return True

            if getattr(self, "infrastructure", None) is not None:
                if not self._ensure_registration_service_schema_ready_for_level4(
                    ds_name,
                    pg_host=pg_host,
                    pg_port=pg_port,
                ):
                    return False

            if keycloak_url:
                keycloak_ready = self.wait_for_keycloak_admin_ready(keycloak_url=keycloak_url)
            else:
                keycloak_ready = self.wait_for_keycloak_admin_ready()
            if not keycloak_ready:
                print("Keycloak admin API not ready for connector provisioning")
                return False
            if not self._ensure_keycloak_realm_available(ds_name, keycloak_url=keycloak_url):
                return False

            self._remove_edc_values_file(connector_name, ds_name=ds_name)
            cleanup_kwargs = {"namespace": namespace}
            if vault_url:
                cleanup_kwargs["vault_url"] = vault_url
            if keycloak_url:
                cleanup_kwargs["keycloak_url"] = keycloak_url
            if pg_host:
                cleanup_kwargs["pg_host"] = pg_host
            if pg_port:
                cleanup_kwargs["pg_port"] = pg_port
            self._cleanup_connector_state(
                connector_name,
                repo_dir,
                ds_name,
                python_exec,
                **cleanup_kwargs,
            )

            print(f"Bootstrapping connector prerequisites for {connector_name}...")
            create_cmd = self._bootstrap_connector_create_command(
                python_exec,
                connector_name,
                ds_name,
                vault_url=vault_url,
                keycloak_url=keycloak_url,
                pg_host=pg_host,
                pg_port=pg_port,
            )
            create_result = None
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                create_result = self.run(create_cmd, cwd=repo_dir, check=False)
                if create_result is not None:
                    break
                if attempt < max_attempts:
                    print(
                        f"Connector bootstrap failed on attempt {attempt}. "
                        "Cleaning partial state and retrying..."
                    )
                    self._remove_edc_values_file(connector_name, ds_name=ds_name)
                    self._cleanup_connector_state(
                        connector_name,
                        repo_dir,
                        ds_name,
                        python_exec,
                        **cleanup_kwargs,
                    )
                    if keycloak_url:
                        keycloak_ready = self.wait_for_keycloak_admin_ready(keycloak_url=keycloak_url)
                    else:
                        keycloak_ready = self.wait_for_keycloak_admin_ready()
                    if not keycloak_ready:
                        print("Keycloak admin API not ready for connector provisioning retry")
                        return False

            if create_result is None:
                print(f"Failed to bootstrap connector prerequisites for {connector_name}")
                return False

            self._stage_bootstrap_artifacts(connector_name, ds_name, repo_dir)
            self.invalidate_management_api_token(connector_name)
            credentials_path = self._connector_credentials_file_path(connector_name, ds_name)
            if os.path.exists(credentials_path):
                self.setup_minio_bucket(self.config.NS_COMMON, ds_name, connector_name, credentials_path)
            reconcile_kwargs = {}
            if vault_url:
                reconcile_kwargs["vault_url"] = vault_url
            if not self._reconcile_connector_vault_secrets(connector_name, ds_name, **reconcile_kwargs):
                return False
            self.ensure_minio_policy_attached(connector_name, ds_name=ds_name)
            return True
        finally:
            self._stop_level4_connector_bootstrap_access(bootstrap_access)

    def _discover_existing_connectors(self, ds_name, namespace, include_runtime_artifacts=True):
        existing = set()
        if include_runtime_artifacts:
            creds_dir = self._edc_runtime_dir(ds_name=ds_name)
            if os.path.isdir(creds_dir):
                for entry in os.listdir(creds_dir):
                    if not (entry.startswith("credentials-connector-") and entry.endswith(".json")):
                        continue
                    connector = entry[len("credentials-connector-"):-len(".json")]
                    if connector and self._connector_belongs_to_dataspace(connector, ds_name):
                        existing.add(connector)

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

    def _wait_for_edc_deployment_rollout(self, deployment_name, namespace, timeout=300, label=None):
        rollout_waiter = getattr(self.infrastructure, "wait_for_deployment_rollout", None)
        timeout = max(int(timeout or 300), 1)
        rollout_label = label or f"EDC connector runtime '{deployment_name}'"
        if callable(rollout_waiter):
            return bool(
                rollout_waiter(
                    namespace,
                    deployment_name,
                    timeout_seconds=timeout,
                    label=rollout_label,
                )
            )
        wait_for_namespace_pods = getattr(self.infrastructure, "wait_for_namespace_pods", None)
        if callable(wait_for_namespace_pods):
            return bool(wait_for_namespace_pods(namespace, timeout=timeout))
        return False

    def _edc_local_image_prepared(self, attribute_name, env_name):
        prepared_targets = getattr(self, attribute_name, None)
        if isinstance(prepared_targets, set) and prepared_targets:
            return True
        return self._is_truthy(os.environ.get(env_name))

    def _edc_local_deployment_restart_targets(self, connector_name):
        if self._normalized_topology() not in self.LEVEL4_LOCAL_IMAGE_TOPOLOGIES:
            return []
        restart_targets = []
        if self._edc_local_image_prepared(
            "_edc_connector_image_prepared_targets",
            "PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_PREPARED",
        ):
            restart_targets.append(("connector runtime", connector_name))

        if (
            self._edc_local_image_prepared(
                "_edc_dashboard_images_prepared_targets",
                "PIONERA_EDC_LOCAL_DASHBOARD_IMAGES_PREPARED",
            )
            and self.config_adapter.edc_dashboard_enabled()
        ):
            restart_targets.extend(
                [
                    ("dashboard", f"{connector_name}-dashboard"),
                    ("dashboard proxy", f"{connector_name}-dashboard-proxy"),
                ]
            )
        return restart_targets

    def _restart_local_edc_deployments_if_needed(
        self,
        connector_name,
        namespace,
        rollout_timeout=300,
        restart_targets=None,
    ):
        restart_targets = (
            list(restart_targets)
            if restart_targets is not None
            else self._edc_local_deployment_restart_targets(connector_name)
        )

        for target_label, deployment_name in restart_targets:
            print(
                f"Restarting EDC {target_label} deployment to apply local image updates: "
                f"{deployment_name}"
            )
            if self.run(f"kubectl rollout restart deployment/{deployment_name} -n {namespace}") is None:
                print(f"Error restarting EDC {target_label} deployment: {deployment_name}")
                return False
            if not self._wait_for_edc_deployment_rollout(
                deployment_name,
                namespace,
                timeout=rollout_timeout,
                label=f"EDC {target_label} '{deployment_name}'",
            ):
                print(
                    f"Timeout waiting for EDC {target_label} deployment rollout after restart: "
                    f"{deployment_name}"
                )
                return False
        return True

    def deploy_connectors(self):
        print("\n========================================")
        print("DEPLOY GENERIC EDC CONNECTORS FROM CONFIG")
        print("========================================\n")

        repo_dir, python_exec = self._prepare_runtime_prerequisites()
        if not repo_dir or not python_exec:
            raise RuntimeError(
                self._last_runtime_prerequisite_error
                or "EDC Level 4 prerequisites are not ready."
            )

        dataspaces = self.load_dataspace_connectors()
        if not dataspaces:
            print("No dataspaces defined in deployer.config")
            return []

        all_connectors = []
        for dataspace in dataspaces:
            ds_name = dataspace["name"]
            namespace = dataspace["namespace"]
            connectors = dataspace["connectors"]
            target_namespaces = self._dataspace_connector_target_namespaces(dataspace, dataspaces=dataspaces)

            print(f"\nDataspace: {ds_name}")
            print(f"Namespace: {namespace}")
            if self._role_aligned_level4_namespaces_active(dataspace, dataspaces=dataspaces):
                print(f"Target connector namespaces: {target_namespaces}")
            print(f"Connectors defined: {connectors}\n")

            if not self._ensure_keycloak_realm_available(ds_name):
                raise RuntimeError(
                    self._last_runtime_prerequisite_error
                    or "EDC Level 4 dataspace prerequisites are not ready."
                )

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
                print(f"Found stale connectors for dataspace '{ds_name}': {stale}")
                for stale_connector in stale:
                    stale_namespace = existing_namespaces.get(stale_connector) or namespace
                    self._cleanup_connector_state(
                        stale_connector,
                        repo_dir,
                        ds_name,
                        python_exec,
                        namespace=stale_namespace,
                    )

            for connector in connectors:
                target_namespace = self._connector_target_namespace(
                    connector,
                    dataspace=dataspace,
                    dataspaces=dataspaces,
                )
                conflicts = self._conflicting_runtime_resources(connector, target_namespace)
                if conflicts:
                    raise RuntimeError(
                        "Refusing to deploy generic EDC connector because it would replace "
                        f"existing non-EDC resources for {connector} in namespace {target_namespace}: "
                        f"{', '.join(conflicts)}. Use an isolated dataspace configuration or "
                        "remove the conflicting runtime first."
                    )

            if not self._maybe_prepare_level4_local_edc_images():
                return []

            for connector in connectors:
                target_namespace = self._connector_target_namespace(
                    connector,
                    dataspace=dataspace,
                    dataspaces=dataspaces,
                )
                if not self._prepare_connector_prerequisites(
                    connector,
                    ds_name,
                    target_namespace,
                    repo_dir,
                    python_exec,
                ):
                    if self._last_runtime_prerequisite_code in {
                        "keycloak_realm_missing",
                        "keycloak_realm_unverified",
                    }:
                        raise RuntimeError(
                            self._last_runtime_prerequisite_error
                            or "EDC Level 4 dataspace prerequisites are not ready."
                        )
                    return []

            for connector in connectors:
                target_namespace = self._connector_target_namespace(
                    connector,
                    dataspace=dataspace,
                    dataspaces=dataspaces,
                )
                values_file = self._render_values_file(
                    connector,
                    ds_name,
                    connectors,
                    connector_namespace=target_namespace,
                )
                release_name = f"{connector}-{ds_name}"
                print(f"Deploying generic EDC connector: {connector}")
                if not self.infrastructure.deploy_helm_release(
                    release_name,
                    target_namespace,
                    values_file,
                    cwd=self._edc_connector_dir(),
                ):
                    print(f"Error deploying generic EDC connector: {connector}")
                    return []

                rollout_timeout = max(int(getattr(self.config, "TIMEOUT_POD_WAIT", 120)), 180)
                restart_targets = self._edc_local_deployment_restart_targets(connector)
                if restart_targets:
                    if not self._restart_local_edc_deployments_if_needed(
                        connector,
                        target_namespace,
                        rollout_timeout=rollout_timeout,
                        restart_targets=restart_targets,
                    ):
                        return []
                else:
                    if not self._wait_for_edc_deployment_rollout(
                        connector,
                        target_namespace,
                        timeout=rollout_timeout,
                    ):
                        print(f"Timeout waiting for EDC connector deployment rollout: {connector}")
                        return []

                if not self._sync_vm_single_connector_public_path_ingresses(values_file, target_namespace):
                    return []

                all_connectors.append(connector)

        deduplicated = sorted(set(all_connectors))
        print("\nAll generic EDC connectors deployed or updated\n")
        if self._is_local_topology():
            print("Configuring connector hosts...")
            connector_hosts = self.config_adapter.generate_connector_hosts(deduplicated)
            self.infrastructure.manage_hosts_entries(connector_hosts)
        else:
            print(f"Skipping connector hosts synchronization for topology '{self.config_adapter.topology}'.")
        if not self.wait_for_all_connectors(deduplicated):
            return []
        return deduplicated

    def describe(self) -> str:
        return "EDCConnectorsAdapter provides the generic EDC connector contract for the framework."
