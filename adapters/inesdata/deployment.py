import os
import shlex

from adapters.shared import deployment as shared_deployment_module
from adapters.shared.deployment import SharedDataspaceDeploymentAdapter
from deployers.shared.lib.topology import LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY, normalize_topology

from .config import INESDataConfigAdapter, InesdataConfig

requests = shared_deployment_module.requests
ensure_python_requirements = shared_deployment_module.ensure_python_requirements


class INESDataDeploymentAdapter(SharedDataspaceDeploymentAdapter):
    """Contains deployment logic for the INESData dataspace runtime."""

    LEVEL3_LOCAL_IMAGE_TOPOLOGIES = {LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY}

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
