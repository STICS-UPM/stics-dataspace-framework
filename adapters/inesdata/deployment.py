import os
import shlex

from adapters.shared import deployment as shared_deployment_module
from adapters.shared.deployment import SharedDataspaceDeploymentAdapter
from deployers.shared.lib.remote_k3s_images import remote_k3s_image_import_target
from deployers.shared.lib.topology import (
    LOCAL_TOPOLOGY,
    VM_DISTRIBUTED_TOPOLOGY,
    VM_SINGLE_TOPOLOGY,
    normalize_topology,
)

from .config import INESDataConfigAdapter, InesdataConfig

requests = shared_deployment_module.requests
ensure_python_requirements = shared_deployment_module.ensure_python_requirements


class INESDataDeploymentAdapter(SharedDataspaceDeploymentAdapter):
    """Contains deployment logic for the INESData dataspace runtime."""

    LEVEL3_LOCAL_IMAGE_TOPOLOGIES = {LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}

    def __init__(self, run, run_silent, auto_mode_getter, infrastructure_adapter, config_adapter=None, config_cls=None):
        resolved_config = config_cls or InesdataConfig
        super().__init__(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            infrastructure_adapter=infrastructure_adapter,
            config_adapter=config_adapter or INESDataConfigAdapter(resolved_config),
            config_cls=resolved_config,
        )
        self._level3_local_images_ready = False

    @staticmethod
    def _sync_shared_bindings():
        shared_deployment_module.requests = requests
        shared_deployment_module.ensure_python_requirements = ensure_python_requirements

    def _normalized_topology(self):
        return normalize_topology(
            getattr(self.config_adapter, "topology", None)
            or getattr(self, "topology", None)
            or LOCAL_TOPOLOGY
        )

    def _framework_root_dir(self):
        resolver = getattr(self.config, "script_dir", None)
        if callable(resolver):
            return resolver()
        repo_resolver = getattr(self.config, "repo_dir", None)
        if callable(repo_resolver):
            return os.path.abspath(os.path.join(repo_resolver(), "..", ".."))
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def _local_minikube_profile(self):
        env_profile = os.getenv("PIONERA_MINIKUBE_PROFILE") or os.getenv("MINIKUBE_PROFILE")
        if env_profile:
            return env_profile.strip() or "minikube"
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        return str(deployer_config.get("MINIKUBE_PROFILE") or "minikube").strip() or "minikube"

    @staticmethod
    def _config_value(config, *keys):
        values = dict(config or {})
        for key in keys:
            value = str(values.get(key) or "").strip()
            if value:
                return value
        return ""

    def _vm_single_remote_image_import_target(self, deployer_config):
        config = dict(deployer_config or {})
        raw_enabled = str(config.get("VM_SINGLE_REMOTE_IMAGE_IMPORT") or "auto").strip().lower()
        if raw_enabled in {"0", "false", "no", "n", "off", "disabled", "disable", "never", "none"}:
            return None

        host = self._config_value(config, "VM_SINGLE_SSH_HOST", "VM_EXTERNAL_IP", "VM_SINGLE_IP")
        if not host:
            return None

        remote_config = dict(config)
        remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT"] = "true"
        remote_config["VM_COMMON_SSH_HOST"] = host
        remote_config["VM_COMMON_IP"] = self._config_value(config, "VM_EXTERNAL_IP", "VM_SINGLE_IP") or host
        remote_config["VM_COMMON_SSH_PORT"] = self._config_value(config, "VM_SINGLE_SSH_PORT") or "22"
        remote_config["VM_COMMON_SSH_USER"] = self._config_value(
            config,
            "VM_SINGLE_SSH_USER",
            "VM_SSH_USER",
            "SSH_BASTION_USER",
        )
        remote_config["VM_COMMON_SSH_IDENTITY_FILE"] = self._config_value(
            config,
            "VM_SINGLE_SSH_IDENTITY_FILE",
            "SSH_IDENTITY_FILE",
            "SSH_BASTION_IDENTITY_FILE",
        )
        if self._config_value(config, "VM_SINGLE_SSH_ACCESS_MODE"):
            remote_config["SSH_ACCESS_MODE"] = self._config_value(config, "VM_SINGLE_SSH_ACCESS_MODE")
        remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND"] = self._config_value(
            config,
            "VM_SINGLE_REMOTE_IMAGE_IMPORT_COMMAND",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND",
            "K3S_IMAGE_IMPORT_COMMAND",
        )
        remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR"] = (
            self._config_value(config, "VM_SINGLE_REMOTE_IMAGE_IMPORT_DIR", "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR")
            or "/tmp"
        )
        remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE"] = (
            self._config_value(
                config,
                "VM_SINGLE_REMOTE_IMAGE_IMPORT_INTERACTIVE",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE",
            )
            or "auto"
        )
        remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY"] = self._config_value(
            config,
            "VM_SINGLE_REMOTE_IMAGE_IMPORT_TTY",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY",
        )
        remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE"] = self._config_value(
            config,
            "VM_SINGLE_REMOTE_IMAGE_PRUNE",
            "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE",
        )
        remote_config["VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP"] = (
            self._config_value(
                config,
                "VM_SINGLE_REMOTE_IMAGE_PRUNE_KEEP",
                "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP",
            )
            or "2"
        )

        return remote_k3s_image_import_target(remote_config, role="common")

    @staticmethod
    def _explicit_bool(value):
        raw_value = str(value or "").strip().lower()
        if not raw_value:
            return None
        if raw_value in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
            return True
        if raw_value in {"0", "false", "no", "n", "off", "disabled", "disable", "never", "none"}:
            return False
        return None

    def _should_prepull_level3_images(self, topology):
        normalized_topology = normalize_topology(topology)
        if normalized_topology != VM_SINGLE_TOPOLOGY:
            return super()._should_prepull_level3_images(topology)

        env_value = str(os.environ.get("PIONERA_K3S_LEVEL3_IMAGE_PREPULL") or "").strip()
        if env_value:
            return super()._should_prepull_level3_images(topology)

        deployer_config = self._deployer_config()
        for key in ("VM_SINGLE_K3S_LEVEL3_IMAGE_PREPULL", "K3S_LEVEL3_IMAGE_PREPULL"):
            configured = self._explicit_bool(deployer_config.get(key))
            if configured is not None:
                if not configured:
                    return False
                return super()._should_prepull_level3_images(topology)

        return False

    def _level3_local_images_mode(self):
        try:
            deployer_config = self.config_adapter.load_deployer_config() or {}
        except Exception:
            deployer_config = {}
        raw_value = (
            os.environ.get("PIONERA_INESDATA_LEVEL3_LOCAL_IMAGES_MODE")
            or os.environ.get("INESDATA_LEVEL3_LOCAL_IMAGES_MODE")
            or os.environ.get("PIONERA_INESDATA_DATASPACE_LOCAL_IMAGES_MODE")
            or os.environ.get("INESDATA_DATASPACE_LOCAL_IMAGES_MODE")
            or deployer_config.get("PIONERA_INESDATA_LEVEL3_LOCAL_IMAGES_MODE")
            or deployer_config.get("INESDATA_LEVEL3_LOCAL_IMAGES_MODE")
            or deployer_config.get("PIONERA_INESDATA_DATASPACE_LOCAL_IMAGES_MODE")
            or deployer_config.get("INESDATA_DATASPACE_LOCAL_IMAGES_MODE")
            or deployer_config.get("LEVEL3_INESDATA_LOCAL_IMAGES_MODE")
            or deployer_config.get("LEVEL3_LOCAL_IMAGES_MODE")
            or "auto"
        )
        mode = str(raw_value or "auto").strip().lower()
        if mode in {"0", "false", "no", "off", "disabled", "disable"}:
            return "disabled"
        if mode in {"1", "true", "yes", "on", "auto", ""}:
            return "auto"
        if mode in {"required", "require", "strict"}:
            return "required"
        print(f"Unknown INESData Level 3 local images mode '{raw_value}'. Falling back to auto.")
        return "auto"

    def _resolve_level3_local_image_policy(self, *, mode):
        normalized_mode = str(mode or "auto").strip().lower() or "auto"
        topology = self._normalized_topology()
        if topology in self.LEVEL3_LOCAL_IMAGE_TOPOLOGIES:
            return {
                "topology": topology,
                "mode": normalized_mode,
                "prepare_local_images": True,
                "message": "",
                "error": "",
            }

        if normalized_mode == "required":
            supported = ", ".join(sorted(self.LEVEL3_LOCAL_IMAGE_TOPOLOGIES))
            return {
                "topology": topology,
                "mode": normalized_mode,
                "prepare_local_images": False,
                "message": "",
                "error": (
                    "INESData Level 3 local dataspace image preparation mode 'required' "
                    f"is only supported in topologies {supported}. Configure pullable "
                    f"image references before running Level 3 on topology '{topology}'."
                ),
            }

        return {
            "topology": topology,
            "mode": normalized_mode,
            "prepare_local_images": False,
            "message": (
                f"Skipping INESData Level 3 local dataspace image preparation for topology '{topology}'. "
                "Using chart-configured image references."
            ),
            "error": "",
        }

    def _level3_local_override_path(self, filename):
        return os.path.join(
            self._framework_root_dir(),
            "adapters",
            "inesdata",
            "build",
            "local-overrides",
            filename,
        )

    @staticmethod
    def _existing_override(path):
        if path and os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
        return None

    def _prepare_level3_local_dataspace_images(self, *, topology, namespace, dataspace):
        self._level3_local_images_ready = False
        mode = self._level3_local_images_mode()
        policy = self._resolve_level3_local_image_policy(mode=mode)
        if policy["error"]:
            print(policy["error"])
            return False
        if not policy["prepare_local_images"]:
            if policy["message"]:
                print(policy["message"])
            return True
        if mode == "disabled":
            print("Level 3 local INESData dataspace images disabled by configuration.")
            return True

        root_dir = self._framework_root_dir()
        adapter_dir = os.path.join(root_dir, "adapters", "inesdata")
        script_path = os.path.join(adapter_dir, "scripts", "local_build_load_deploy.sh")
        source_dirs = [
            os.path.join(adapter_dir, "sources", "inesdata-registration-service"),
            os.path.join(adapter_dir, "sources", "inesdata-public-portal-backend"),
            os.path.join(adapter_dir, "sources", "inesdata-public-portal-frontend"),
        ]
        missing_sources = [path for path in source_dirs if not os.path.isdir(path)]

        if missing_sources:
            detail = ", ".join(os.path.relpath(path, root_dir) for path in missing_sources)
            if mode == "required":
                print(f"Required INESData Level 3 local dataspace sources are missing: {detail}")
                return False
            print(f"Skipping Level 3 local dataspace image preparation; missing sources: {detail}")
            return True

        if not os.path.isfile(script_path):
            detail = os.path.relpath(script_path, root_dir)
            if mode == "required":
                print(f"Required INESData local image workflow script is missing: {detail}")
                return False
            print(f"Skipping Level 3 local dataspace image preparation; missing script: {detail}")
            return True

        cluster_runtime = self._cluster_runtime(normalize_topology(topology))
        cluster_type = str(cluster_runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
        env_prefix = ""
        if normalize_topology(topology) == VM_DISTRIBUTED_TOPOLOGY and cluster_type == "k3s":
            try:
                deployer_config = self.config_adapter.load_deployer_config() or {}
            except Exception:
                deployer_config = {}
            remote_target = remote_k3s_image_import_target(deployer_config, role="common")
            if not remote_target or not remote_target.is_configured():
                detail = (
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT=true and VM_COMMON_SSH_HOST "
                    "are required to load Level 3 local images into the common-services VM."
                )
                if mode == "required":
                    print(detail)
                    return False
                print(f"Skipping Level 3 local dataspace image preparation for vm-distributed. {detail}")
                return True
            env_prefix = f"{remote_target.render_shell_env_prefix()} "
        elif normalize_topology(topology) == VM_SINGLE_TOPOLOGY and cluster_type == "k3s":
            try:
                deployer_config = self.config_adapter.load_deployer_config() or {}
            except Exception:
                deployer_config = {}
            remote_target = self._vm_single_remote_image_import_target(deployer_config)
            if remote_target and remote_target.is_configured():
                env_prefix = f"{remote_target.render_shell_env_prefix()} "
        command = " ".join(
            shlex.quote(part)
            for part in [
                "bash",
                script_path,
                "--apply",
                "--platform-dir",
                self.config.repo_dir(),
                "--namespace",
                namespace,
                "--dataspace",
                dataspace,
                "--minikube-profile",
                self._local_minikube_profile(),
                "--cluster-runtime",
                cluster_type,
                "--deploy-target",
                "dataspace",
                "--skip-deploy",
            ]
        )
        if env_prefix:
            command = f"{env_prefix}{command}"

        print("\nPreparing local INESData dataspace images for Level 3...")
        print(f"Cluster runtime: {cluster_type}")
        print("This builds and loads registration-service, public-portal-backend and public-portal-frontend before Helm deploy.")
        result = self.run(command, check=False)
        if result is None:
            print("Error preparing local INESData dataspace images for Level 3.")
            return False
        self._level3_local_images_ready = True
        return True

    def _level3_local_dataspace_images_prepared(self):
        return self._level3_local_images_ready

    def _level3_registration_values_files(self, values_file):
        override = self._existing_override(
            self._level3_local_override_path("registration-local-overrides.yaml")
        )
        return [values_file, override] if self._level3_local_images_ready and override else values_file

    def _level3_public_portal_values_files(self, values_file):
        override = self._existing_override(
            self._level3_local_override_path("public-portal-local-overrides.yaml")
        )
        return [values_file, override] if self._level3_local_images_ready and override else values_file

    def wait_for_keycloak_admin_ready(self, kc_url, kc_user, kc_password, timeout=120, poll_interval=3):
        self._sync_shared_bindings()
        return super().wait_for_keycloak_admin_ready(
            kc_url,
            kc_user,
            kc_password,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def deploy_dataspace(self):
        self._sync_shared_bindings()
        return super().deploy_dataspace()

    def deploy_dataspace_for_topology(self, topology="local"):
        self._sync_shared_bindings()
        return super().deploy_dataspace_for_topology(topology=topology)

    def describe(self) -> str:
        return "INESDataDeploymentAdapter contains deployment logic for INESData."
