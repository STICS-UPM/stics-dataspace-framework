import json
import os
import shutil
import shlex
import socket
import tempfile
import time
import ipaddress
from contextlib import contextmanager

import yaml

from deployers.shared.lib.components import (
    resolve_component_release_name,
    component_values_file_candidates,
    configured_component_host,
    configured_component_public_path,
    configured_component_public_url,
    infer_component_hostname,
    strip_url_scheme,
)
from deployers.shared.lib.cluster_runtime import build_cluster_runtime
from deployers.shared.lib.remote_k3s_images import remote_k3s_image_import_target, shell_join
from deployers.shared.lib.topology import VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY, normalize_topology
from deployers.infrastructure.lib.paths import shared_artifact_roots
from .config import INESDataConfigAdapter, InesdataConfig


class INESDataComponentsAdapter:
    """Deploy optional platform components via Helm charts (Level 5).

    This adapter is intentionally isolated from Level 3/4 logic so introducing
    components does not change the stability of Levels 1-4.
    """

    _LEVEL6_EXCLUDED_KEYS = {
        # Components that are part of the base dataspace lifecycle.
        "registration-service",
        "public-portal",
    }
    _ONTOLOGY_HUB_REPO_URL = "https://github.com/ProyectoPIONERA/Ontology-Hub.git"
    _ONTOLOGY_HUB_REPO_DIRNAME = "Ontology-Hub"
    _AI_MODEL_HUB_REPO_URL = "https://github.com/ProyectoPIONERA/AIModelHub.git"
    _AI_MODEL_HUB_REPO_DIRNAME = "AIModelHub"
    _MORPH_KGV_REPO_URL = "https://github.com/ProyectoPIONERA/morph-kgv.git"
    _MORPH_KGV_REPO_DIRNAME = "morph-kgv"
    _MAPPING_EDITOR_REPO_URL = "https://github.com/ProyectoPIONERA/mapping-editor.git"
    _MAPPING_EDITOR_REPO_DIRNAME = "mapping-editor"
    _AUTOMAP_REPO_URL = "https://github.com/ProyectoPIONERA/automap.git"
    _AUTOMAP_REPO_DIRNAME = "automap"

    def __init__(
        self,
        run,
        run_silent,
        auto_mode_getter,
        infrastructure_adapter,
        config_adapter=None,
        config_cls=None,
    ):
        self.run = run
        self.run_silent = run_silent
        self.auto_mode_getter = auto_mode_getter
        self.infrastructure = infrastructure_adapter
        self.config = config_cls or InesdataConfig
        self.config_adapter = config_adapter or INESDataConfigAdapter(self.config)
        self._attempted_platform_repo_refresh = False

    def _auto_mode(self) -> bool:
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

    @staticmethod
    def _normalize_component_key(component: str) -> str:
        return (component or "").strip().lower().replace("_", "-")

    @staticmethod
    def _to_http_url(host_or_url: str) -> str:
        value = (host_or_url or "").strip()
        if not value:
            return ""
        if value.startswith("http://"):
            return value
        if value.startswith("https://"):
            return "http://" + value[len("https://"):]
        return f"http://{value}"

    @staticmethod
    def _to_public_url(host_or_url: str) -> str:
        value = (host_or_url or "").strip()
        if not value:
            return ""
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return f"http://{value}"

    def _ontology_hub_self_host_url(self, public_url: str, deployer_config: dict) -> str:
        explicit = (
            deployer_config.get("ONTOLOGY_HUB_SELF_HOST_URL")
            or deployer_config.get("ONTOLOGY_HUB_INTERNAL_SELF_HOST_URL")
        )
        if explicit:
            return str(explicit).strip().rstrip("/")
        if self._is_vm_single_topology():
            return self._ontology_hub_internal_service_url(deployer_config).rstrip("/")
        if self._is_vm_distributed_topology():
            return self._to_http_url(public_url).rstrip("/")
        return (public_url or "").strip().rstrip("/")

    def _ontology_hub_internal_service_url(self, deployer_config: dict) -> str:
        config = dict(deployer_config or {})
        service_name = str(
            config.get("ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME")
            or config.get("ONTOLOGY_HUB_SERVICE_NAME")
            or f"{self._dataspace_name()}-ontology-hub"
        ).strip()
        namespace = str(
            config.get("ONTOLOGY_HUB_SELF_HOST_NAMESPACE")
            or config.get("ONTOLOGY_HUB_SERVICE_NAMESPACE")
            or config.get("COMPONENTS_NAMESPACE")
            or "components"
        ).strip()
        port = str(
            config.get("ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT")
            or config.get("ONTOLOGY_HUB_SELF_HOST_PORT")
            or config.get("ONTOLOGY_HUB_SERVICE_PORT")
            or "3333"
        ).strip()
        if not service_name:
            service_name = f"{self._dataspace_name()}-ontology-hub"
        if not namespace:
            namespace = "components"
        if not port:
            port = "3333"
        return f"http://{service_name}.{namespace}:{port}"

    def _component_chart_roots(self):
        return shared_artifact_roots("components")

    def _refresh_platform_repo_once(self):
        if self._attempted_platform_repo_refresh:
            return
        self._attempted_platform_repo_refresh = True

        repo_dir = self.config.repo_dir()
        git_dir = os.path.join(repo_dir, ".git")
        if not os.path.isdir(git_dir):
            return

        repo_q = shlex.quote(repo_dir)
        print("Refreshing INESData deployer artifacts repository (git pull) to discover component charts...")
        self.run(f"git -C {repo_q} fetch --all --prune", check=False)
        self.run(f"git -C {repo_q} pull --ff-only", check=False)

    def _discover_component_charts(self) -> dict:
        """Discover deployable Helm charts.

        Convention:
        - Each component chart is a directory containing a Chart.yaml.
        - Root: <repo_dir>/components/*
        """
        charts = {}
        for root in self._component_chart_roots():
            if not os.path.isdir(root):
                continue
            for entry in os.listdir(root):
                chart_dir = os.path.join(root, entry)
                if not os.path.isdir(chart_dir):
                    continue
                if os.path.isfile(os.path.join(chart_dir, "Chart.yaml")):
                    charts[self._normalize_component_key(entry)] = chart_dir
        if charts:
            return charts

        # If the repo exists but charts are missing, attempt a single refresh.
        self._refresh_platform_repo_once()

        charts = {}
        for root in self._component_chart_roots():
            if not os.path.isdir(root):
                continue
            for entry in os.listdir(root):
                chart_dir = os.path.join(root, entry)
                if not os.path.isdir(chart_dir):
                    continue
                if os.path.isfile(os.path.join(chart_dir, "Chart.yaml")):
                    charts[self._normalize_component_key(entry)] = chart_dir
        return charts

    def list_deployable_components(self):
        return sorted(self._discover_component_charts().keys())

    def _resolve_component_chart_dir(self, component_key: str) -> str:
        normalized = self._normalize_component_key(component_key)
        charts = self._discover_component_charts()
        chart_dir = charts.get(normalized)
        if chart_dir:
            return chart_dir

        if not charts:
            self._fail(
                "No deployable component charts discovered in deployer artifacts",
                root_cause=(
                    "Expected Helm charts under deployers/shared/components or deployers/inesdata/components. "
                    "Verify that the deployer artifacts are present in this repository checkout."
                ),
            )

        available = ", ".join(sorted(charts)) or "(none)"
        self._fail(
            f"Unknown component '{component_key}'. "
            f"Deployable components discovered in deployer artifacts: {available}"
        )

    def _resolve_component_values_file(self, chart_dir: str, ds_name: str, namespace: str) -> str:
        candidates = component_values_file_candidates(chart_dir, ds_name, namespace)
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

        self._fail(
            "No values file found for component chart. "
            f"Tried: {', '.join(os.path.basename(p) for p in candidates)} in {chart_dir}"
        )

    def _resolve_component_release_name(self, normalized_component: str) -> str:
        return resolve_component_release_name(
            normalized_component,
            dataspace_name=self._dataspace_name(),
            registration_service_release_name=self.config.helm_release_rs(),
        )

    def _resolve_dataspace_index(self, *, ds_name=None, ds_namespace=None, deployer_config=None) -> int:
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        resolved_name = str(ds_name or "").strip()
        resolved_namespace = str(ds_namespace or "").strip()

        dataspace_index_getter = getattr(self.config_adapter, "dataspace_index", None)
        if callable(dataspace_index_getter):
            try:
                resolved_index = int(
                    dataspace_index_getter(
                        ds_name=resolved_name or None,
                        ds_namespace=resolved_namespace or None,
                    )
                )
            except TypeError:
                try:
                    resolved_index = int(dataspace_index_getter(resolved_name or None, resolved_namespace or None))
                except Exception:
                    resolved_index = 1
            except Exception:
                resolved_index = 1
            return resolved_index if resolved_index >= 1 else 1

        index = 1
        while True:
            configured_name = str(resolved_config.get(f"DS_{index}_NAME") or "").strip()
            configured_namespace = str(
                resolved_config.get(f"DS_{index}_NAMESPACE") or configured_name
            ).strip()
            if not configured_name:
                break
            if resolved_name and configured_name == resolved_name:
                return index
            if resolved_namespace and configured_namespace == resolved_namespace:
                return index
            index += 1
        return 1

    def _resolve_legacy_components_namespace(self, *, ds_name=None, deployer_config=None) -> str:
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        resolved_name = str(ds_name or self._dataspace_name() or "").strip() or self._dataspace_name()
        resolved_index = self._resolve_dataspace_index(
            ds_name=resolved_name,
            deployer_config=resolved_config,
        )

        configured_namespace = str(
            resolved_config.get(f"DS_{resolved_index}_NAMESPACE")
            or resolved_config.get(f"DS_{resolved_index}_NAME")
            or ""
        ).strip()
        if configured_namespace:
            return configured_namespace

        primary_namespace_getter = getattr(self.config_adapter, "primary_dataspace_namespace", None)
        if callable(primary_namespace_getter):
            try:
                resolved_primary_namespace = str(primary_namespace_getter() or "").strip()
            except Exception:
                resolved_primary_namespace = ""
            if resolved_primary_namespace:
                return resolved_primary_namespace

        legacy_namespace_getter = getattr(self.config, "namespace_demo", None)
        if callable(legacy_namespace_getter):
            try:
                resolved_legacy_namespace = str(legacy_namespace_getter() or "").strip()
            except Exception:
                resolved_legacy_namespace = ""
            if resolved_legacy_namespace:
                return resolved_legacy_namespace

        return resolved_name

    @staticmethod
    def _extract_components_namespace(namespace_plan) -> str:
        if isinstance(namespace_plan, dict):
            namespace_roles = namespace_plan.get("namespace_roles") or namespace_plan.get("planned_namespace_roles") or {}
        else:
            namespace_roles = namespace_plan

        if isinstance(namespace_roles, dict):
            resolved_namespace = namespace_roles.get("components_namespace")
        else:
            resolved_namespace = getattr(namespace_roles, "components_namespace", None)

        return str(resolved_namespace or "").strip()

    def _resolve_components_namespace(self, *, ds_name=None, namespace=None, deployer_config=None) -> str:
        explicit_namespace = str(namespace or "").strip()
        if explicit_namespace:
            return explicit_namespace

        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        resolved_name = str(ds_name or self._dataspace_name() or "").strip() or self._dataspace_name()
        resolved_legacy_namespace = self._resolve_legacy_components_namespace(
            ds_name=resolved_name,
            deployer_config=resolved_config,
        )
        resolved_index = self._resolve_dataspace_index(
            ds_name=resolved_name,
            ds_namespace=resolved_legacy_namespace,
            deployer_config=resolved_config,
        )

        namespace_plan_getter = getattr(self.config_adapter, "namespace_plan_for_dataspace", None)
        if callable(namespace_plan_getter):
            try:
                namespace_plan = namespace_plan_getter(
                    ds_name=resolved_name,
                    ds_namespace=resolved_legacy_namespace,
                    ds_index=resolved_index,
                )
            except TypeError:
                try:
                    namespace_plan = namespace_plan_getter(
                        ds_name=resolved_name,
                        ds_namespace=resolved_legacy_namespace,
                    )
                except Exception:
                    namespace_plan = None
            except Exception:
                namespace_plan = None
            resolved_components_namespace = self._extract_components_namespace(namespace_plan)
            if resolved_components_namespace:
                return resolved_components_namespace

        configured_namespace = str(resolved_config.get("COMPONENTS_NAMESPACE") or "").strip()
        if configured_namespace:
            return configured_namespace
        return "components"

    @staticmethod
    def _parse_bool(value, default=False) -> bool:
        if value is None:
            return default
        raw = str(value).strip().lower()
        if raw == "":
            return default
        if raw in ("1", "true", "yes", "y", "on"):
            return True
        if raw in ("0", "false", "no", "n", "off"):
            return False
        return default

    @staticmethod
    def _parse_positive_int(value) -> int | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _strip_url_scheme(host_or_url: str) -> str:
        return strip_url_scheme(host_or_url)

    def _cleanup_components(self, components, namespace: str):
        namespace = (namespace or "").strip()
        if not namespace:
            return

        ns_q = shlex.quote(namespace)
        print("\nCleaning previous component deployments (Level 5)...")

        for component in components:
            normalized = self._normalize_component_key(component)
            if normalized in self._LEVEL6_EXCLUDED_KEYS:
                continue

            release_name = self._resolve_component_release_name(normalized)
            rel_q = shlex.quote(release_name)

            status = self.run_silent(f"helm status {rel_q} -n {ns_q}")
            if status is None:
                continue

            print(f"- Removing {normalized} (release {release_name})")

            pvc_pvs = []
            pv_list = self.run_silent(
                f"kubectl get pvc -n {ns_q} -l app.kubernetes.io/instance={rel_q} "
                f"-o jsonpath='{{range .items[*]}}{{.spec.volumeName}}{{\"\\n\"}}{{end}}'"
            )
            if pv_list:
                pvc_pvs = [line.strip() for line in pv_list.splitlines() if line.strip()]

            self.run(f"helm uninstall {rel_q} -n {ns_q}", check=False)
            self.run(
                f"kubectl delete pvc -n {ns_q} -l app.kubernetes.io/instance={rel_q} --ignore-not-found",
                check=False,
            )
            self.run(
                f"kubectl wait --for=delete pod -n {ns_q} -l app.kubernetes.io/instance={rel_q} --timeout=5m",
                check=False,
            )

            for pv_name in pvc_pvs:
                pv_q = shlex.quote(pv_name)
                reclaim = self.run_silent(
                    f"kubectl get pv {pv_q} -o jsonpath='{{.spec.persistentVolumeReclaimPolicy}}'"
                )
                if reclaim and reclaim.strip().upper() == "RETAIN":
                    self.run(f"kubectl delete pv {pv_q}", check=False)

    def _cleanup_legacy_component_releases(
        self,
        components,
        *,
        active_namespace,
        ds_name=None,
        deployer_config=None,
    ):
        resolved_active_namespace = str(active_namespace or "").strip()
        if not resolved_active_namespace:
            return None

        legacy_namespace = self._resolve_legacy_components_namespace(
            ds_name=ds_name,
            deployer_config=deployer_config,
        )
        if not legacy_namespace or legacy_namespace == resolved_active_namespace:
            return None

        legacy_ns_q = shlex.quote(legacy_namespace)
        for component in list(components or []):
            normalized = self._normalize_component_key(component)
            if normalized in self._LEVEL6_EXCLUDED_KEYS:
                continue
            release_name = self._resolve_component_release_name(normalized)
            rel_q = shlex.quote(release_name)
            status = self.run_silent(f"helm status {rel_q} -n {legacy_ns_q}")
            if status is None:
                continue
            print(
                "\nDetected legacy component release outside components namespace; "
                f"cleaning {release_name} from {legacy_namespace} before deploying to {resolved_active_namespace}"
            )
            self._cleanup_components(components, legacy_namespace)
            return legacy_namespace
        return None

    def _component_public_path_for_ingress(self, normalized_component: str, deployer_config: dict) -> str:
        public_path = configured_component_public_path(normalized_component, deployer_config)
        if not public_path:
            return ""
        if self._component_public_path_rewrite_enabled(normalized_component, deployer_config, public_path):
            return f"{public_path}(/|$)(.*)"
        return public_path

    @staticmethod
    def _ingress_first_host_and_path(ingress: dict) -> tuple[str, str]:
        try:
            rule = (ingress.get("spec", {}).get("rules") or [])[0]
            path = (rule.get("http", {}).get("paths") or [])[0]
            return str(rule.get("host") or "").strip(), str(path.get("path") or "").strip()
        except Exception:
            return "", ""

    def _is_framework_vm_distributed_public_path_ingress(
        self,
        ingress: dict,
        *,
        component: str,
        deployer_config: dict,
    ) -> bool:
        metadata = ingress.get("metadata") or {}
        labels = metadata.get("labels") or {}
        if labels.get("app.kubernetes.io/managed-by") != "validation-environment":
            return False
        if labels.get("app.kubernetes.io/part-of") != "vm-distributed":
            return False
        if labels.get("app.kubernetes.io/component") != component:
            return False

        expected_host = configured_component_host(
            component,
            deployer_config,
            dataspace_name=self._dataspace_name(),
        )
        expected_path = self._component_public_path_for_ingress(component, deployer_config)
        actual_host, actual_path = self._ingress_first_host_and_path(ingress)
        if expected_host and actual_host and actual_host != expected_host:
            return False
        if expected_path and actual_path and actual_path != expected_path:
            return False
        return True

    def _delete_framework_public_path_ingress_if_present(
        self,
        *,
        name: str,
        namespace: str,
        component: str,
        deployer_config: dict,
    ) -> bool:
        name = str(name or "").strip()
        namespace = str(namespace or "").strip()
        if not name or not namespace:
            return False

        name_q = shlex.quote(name)
        ns_q = shlex.quote(namespace)
        raw = self.run_silent(f"kubectl get ingress {name_q} -n {ns_q} -o json")
        if not raw:
            return False
        try:
            ingress = json.loads(raw)
        except Exception:
            return False

        if not self._is_framework_vm_distributed_public_path_ingress(
            ingress,
            component=component,
            deployer_config=deployer_config,
        ):
            return False

        print(f"- Removing legacy vm-distributed public path ingress {name}")
        self.run(f"kubectl delete ingress {name_q} -n {ns_q} --ignore-not-found", check=False)
        return True

    def _cleanup_vm_distributed_legacy_public_path_ingresses(
        self,
        deployment_items,
        *,
        namespace: str,
        deployer_config: dict,
    ) -> list[str]:
        if not self._is_vm_distributed_topology():
            return []

        namespace = str(namespace or "").strip()
        if not namespace:
            return []

        resolved_config = dict(deployer_config or {})
        removed = []
        for item in list(deployment_items or []):
            normalized = self._normalize_component_key(item.get("normalized") or item.get("component"))
            if not normalized or normalized in self._LEVEL6_EXCLUDED_KEYS:
                continue
            release_name = str(item.get("release_name") or "").strip()
            if not release_name:
                continue

            candidates = [(normalized, f"{release_name}-public-path")]
            if normalized == "semantic-virtualization" and self._semantic_virtualization_mapping_editor_enabled(
                resolved_config
            ):
                candidates.append(("semantic-virtualization-editor", f"{release_name}-editor-public-path"))

            for route_component, ingress_name in candidates:
                if self._delete_framework_public_path_ingress_if_present(
                    name=ingress_name,
                    namespace=namespace,
                    component=route_component,
                    deployer_config=resolved_config,
                ):
                    removed.append(ingress_name)
        return removed

    @staticmethod
    def _safe_load_yaml_file(path: str) -> dict:
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            raise RuntimeError(f"Could not load YAML file: {path}. {exc}")

    @staticmethod
    def _extract_primary_image_ref(values: dict):
        image = (values or {}).get("image") or {}
        repository = (image.get("repository") or "").strip()
        tag_raw = image.get("tag")
        tag = str(tag_raw).strip() if tag_raw is not None else ""
        if not repository or not tag:
            return None
        return f"{repository}:{tag}"

    @staticmethod
    def _extract_mapping_editor_image_ref(values: dict):
        mapping_editor = (values or {}).get("mappingEditor") or {}
        image = mapping_editor.get("image") or {}
        repository = (image.get("repository") or "").strip()
        tag_raw = image.get("tag")
        tag = str(tag_raw).strip() if tag_raw is not None else ""
        if not repository or not tag:
            return None
        return f"{repository}:{tag}"

    def _component_image_config_prefixes(self, normalized_component: str):
        normalized = self._normalize_component_key(normalized_component)
        if normalized == "ontology-hub":
            return ("ONTOLOGY_HUB",)
        if normalized == "ai-model-hub":
            return ("AI_MODEL_HUB",)
        if normalized == "semantic-virtualization":
            return ("SEMANTIC_VIRTUALIZATION",)
        if normalized == "semantic-virtualization-editor":
            return (
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR",
                "SEMANTIC_VIRTUALIZATION_EDITOR",
                "MAPPING_EDITOR",
            )
        return (normalized.upper().replace("-", "_"),)

    @staticmethod
    def _split_image_ref(image_ref: str):
        resolved = str(image_ref or "").strip()
        if not resolved:
            return None
        slash_index = resolved.rfind("/")
        colon_index = resolved.rfind(":")
        if colon_index <= slash_index:
            return None
        repository = resolved[:colon_index].strip()
        tag = resolved[colon_index + 1 :].strip()
        if not repository or not tag:
            return None
        return {"repository": repository, "tag": tag}

    def _configured_component_image_override(self, normalized_component: str, deployer_config: dict):
        config = dict(deployer_config or {})
        prefixes = self._component_image_config_prefixes(normalized_component)

        image_ref = ""
        for prefix in prefixes:
            image_ref = str(
                config.get(f"{prefix}_IMAGE_REF")
                or config.get(f"{prefix}_PREBUILT_IMAGE_REF")
                or config.get(f"{prefix}_PREBUILT_IMAGE")
                or ""
            ).strip()
            if image_ref:
                break

        image = None
        if image_ref:
            image = self._split_image_ref(image_ref)
            if not image:
                self._fail(
                    "Invalid prebuilt component image reference",
                    root_cause=(
                        f"{normalized_component}: {image_ref}. "
                        "Use a full image reference with an explicit tag, for example "
                        "registry.example.org/project/component:1.0.0."
                    ),
                )
        else:
            repository = ""
            tag = ""
            for prefix in prefixes:
                repository = str(
                    config.get(f"{prefix}_IMAGE_REPOSITORY")
                    or config.get(f"{prefix}_PREBUILT_IMAGE_REPOSITORY")
                    or ""
                ).strip()
                tag = str(
                    config.get(f"{prefix}_IMAGE_TAG")
                    or config.get(f"{prefix}_PREBUILT_IMAGE_TAG")
                    or ""
                ).strip()
                if repository or tag:
                    break
            if repository or tag:
                if not repository or not tag:
                    self._fail(
                        "Incomplete prebuilt component image configuration",
                        root_cause=(
                            f"{normalized_component}: set both IMAGE_REPOSITORY and IMAGE_TAG, "
                            "or use IMAGE_REF."
                        ),
                    )
                image = {"repository": repository, "tag": tag}

        if not image:
            return {}

        pull_policy = ""
        for prefix in prefixes:
            pull_policy = str(
                config.get(f"{prefix}_IMAGE_PULL_POLICY")
                or config.get(f"{prefix}_PREBUILT_IMAGE_PULL_POLICY")
                or ""
            ).strip()
            if pull_policy:
                break
        if not pull_policy:
            pull_policy = str(config.get("COMPONENTS_IMAGE_PULL_POLICY") or "").strip()
        if pull_policy:
            if pull_policy not in {"Always", "IfNotPresent", "Never"}:
                self._fail(
                    "Invalid component image pull policy",
                    root_cause=f"{normalized_component}: {pull_policy}. Use Always, IfNotPresent or Never.",
                )
            image["pullPolicy"] = pull_policy
        return image

    def _minikube_is_available(self, profile: str) -> bool:
        profile_q = shlex.quote(profile)
        return self.run_silent(f"minikube -p {profile_q} status") is not None

    def _minikube_has_image(self, profile: str, image_ref: str) -> bool:
        profile_q = shlex.quote(profile)
        output = self.run_silent(f"minikube -p {profile_q} image ls")
        if not output:
            return False

        suffix = image_ref.strip()
        for line in output.splitlines():
            candidate = (line or "").strip()
            if candidate.endswith(suffix):
                return True
        return False

    def _cluster_runtime(self, deployer_config: dict | None = None) -> dict:
        runtime_getter = getattr(self.config_adapter, "cluster_runtime", None)
        if callable(runtime_getter):
            try:
                return dict(runtime_getter() or {})
            except Exception:
                pass
        config = dict(deployer_config or {})
        if not config:
            try:
                config = dict(self.config_adapter.load_deployer_config() or {})
            except Exception:
                config = {}
        topology = str(getattr(self.config_adapter, "topology", "local") or "local").strip().lower() or "local"
        return build_cluster_runtime(config, topology=topology)

    def _component_kubeconfig(self, deployer_config: dict | None = None) -> str:
        runtime = self._cluster_runtime(deployer_config)
        if str(runtime.get("cluster_type") or "").strip().lower() != "k3s":
            return ""

        if self._is_vm_distributed_topology():
            kubeconfig = str(
                runtime.get("k3s_kubeconfig_components")
                or runtime.get("k3s_kubeconfig_common")
                or runtime.get("k3s_kubeconfig")
                or ""
            ).strip()
        elif self._is_vm_single_topology():
            config = dict(deployer_config or {})
            kubeconfig = str(
                config.get("VM_SINGLE_LOCAL_KUBECONFIG")
                or runtime.get("k3s_kubeconfig")
                or runtime.get("k3s_kubeconfig_common")
                or config.get("K3S_KUBECONFIG")
                or ""
            ).strip()
        else:
            kubeconfig = ""

        return os.path.abspath(os.path.expanduser(kubeconfig)) if kubeconfig else ""

    @contextmanager
    def _temporary_component_kubeconfig(self, deployer_config: dict | None = None):
        kubeconfig = self._component_kubeconfig(deployer_config)
        if not kubeconfig:
            yield
            return

        previous_kubeconfig = os.environ.get("KUBECONFIG")
        previous_role = os.environ.get("PIONERA_KUBECONFIG_ROLE")
        os.environ["KUBECONFIG"] = kubeconfig
        os.environ["PIONERA_KUBECONFIG_ROLE"] = "components"
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

    def _resolve_ontology_hub_source_dir(self, deployer_config: dict) -> str:
        sources_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")
        ontology_hub_dir = os.path.join(sources_dir, self._ONTOLOGY_HUB_REPO_DIRNAME)
        dockerfile_path = os.path.join(ontology_hub_dir, "Dockerfile")
        if os.path.isfile(dockerfile_path):
            return ontology_hub_dir

        should_clone = not os.path.isdir(ontology_hub_dir)
        if not should_clone:
            try:
                remaining_entries = os.listdir(ontology_hub_dir)
            except OSError:
                remaining_entries = []
            should_clone = len(remaining_entries) == 0

        if should_clone:
            os.makedirs(sources_dir, exist_ok=True)
            if os.path.isdir(ontology_hub_dir):
                try:
                    os.rmdir(ontology_hub_dir)
                except OSError:
                    pass
            print(f"Cloning Ontology-Hub into {ontology_hub_dir} ...")
            import subprocess
            try:
                subprocess.run(["git", "clone", self._ONTOLOGY_HUB_REPO_URL, ontology_hub_dir], check=True)
            except Exception as exc:
                self._fail(
                    "Could not clone Ontology-Hub repository",
                    root_cause=str(exc),
                )

        if os.path.isfile(dockerfile_path):
            return ontology_hub_dir

        self._fail(
            "Ontology-Hub source directory is not usable",
            root_cause=(
                f"Expected Dockerfile at: {dockerfile_path}. "
                "Level 5 expects the canonical checkout at "
                "adapters/inesdata/sources/Ontology-Hub."
            ),
        )

    def _resolve_ai_model_hub_source_dir(self, deployer_config: dict) -> str:
        sources_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")
        ai_model_hub_dir = os.path.join(sources_dir, self._AI_MODEL_HUB_REPO_DIRNAME)
        dashboard_dir = os.path.join(ai_model_hub_dir, "DataDashboard")
        dockerfile_path = os.path.join(dashboard_dir, "Dockerfile")
        if os.path.isfile(dockerfile_path):
            return dashboard_dir

        should_clone = not os.path.isdir(ai_model_hub_dir)
        if not should_clone:
            try:
                remaining_entries = os.listdir(ai_model_hub_dir)
            except OSError:
                remaining_entries = []
            should_clone = len(remaining_entries) == 0

        if should_clone:
            os.makedirs(sources_dir, exist_ok=True)
            if os.path.isdir(ai_model_hub_dir):
                try:
                    os.rmdir(ai_model_hub_dir)
                except OSError:
                    pass
            print(f"Cloning AI Model Hub into {ai_model_hub_dir} ...")
            import subprocess
            try:
                subprocess.run(["git", "clone", self._AI_MODEL_HUB_REPO_URL, ai_model_hub_dir], check=True)
            except Exception as exc:
                self._fail(
                    "Could not clone AI Model Hub repository",
                    root_cause=str(exc),
                )

        if os.path.isfile(dockerfile_path):
            return dashboard_dir

        self._fail(
            "AI Model Hub source directory is not usable",
            root_cause=(
                f"Expected Dockerfile at: {dockerfile_path}. "
                "Level 5 expects the canonical checkout at "
                "adapters/inesdata/sources/AIModelHub."
            ),
        )

    def _resolve_morph_kgv_source_dir(self, deployer_config: dict) -> str:
        sources_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")
        morph_kgv_dir = os.path.join(sources_dir, self._MORPH_KGV_REPO_DIRNAME)
        pyproject_path = os.path.join(morph_kgv_dir, "pyproject.toml")
        package_path = os.path.join(morph_kgv_dir, "src", "morph_kgc", "__init__.py")
        virt_store_path = os.path.join(morph_kgv_dir, "src", "morph_kgc", "sparql", "virt_store.py")
        if os.path.isfile(pyproject_path) and os.path.isfile(package_path) and os.path.isfile(virt_store_path):
            return morph_kgv_dir

        should_clone = not os.path.isdir(morph_kgv_dir)
        if not should_clone:
            try:
                remaining_entries = os.listdir(morph_kgv_dir)
            except OSError:
                remaining_entries = []
            should_clone = len(remaining_entries) == 0

        if should_clone:
            os.makedirs(sources_dir, exist_ok=True)
            if os.path.isdir(morph_kgv_dir):
                try:
                    os.rmdir(morph_kgv_dir)
                except OSError:
                    pass
            print(f"Cloning morph-kgv into {morph_kgv_dir} ...")
            import subprocess
            try:
                subprocess.run(["git", "clone", self._MORPH_KGV_REPO_URL, morph_kgv_dir], check=True)
            except Exception as exc:
                self._fail(
                    "Could not clone morph-kgv repository",
                    root_cause=str(exc),
                )

        if os.path.isfile(pyproject_path) and os.path.isfile(package_path) and os.path.isfile(virt_store_path):
            return morph_kgv_dir

        self._fail(
            "morph-kgv source directory is not usable",
            root_cause=(
                f"Expected pyproject.toml at: {pyproject_path}, package at: {package_path} "
                f"and SPARQL store at: {virt_store_path}. "
                "Level 5 expects the canonical checkout at "
                "adapters/inesdata/sources/morph-kgv."
            ),
        )

    def _resolve_mapping_editor_source_dir(self, deployer_config: dict) -> str:
        sources_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")
        mapping_editor_dir = os.path.join(sources_dir, self._MAPPING_EDITOR_REPO_DIRNAME)
        app_path = os.path.join(mapping_editor_dir, "Mapping_Editor.py")
        requirements_path = os.path.join(mapping_editor_dir, "requirements.txt")
        if os.path.isfile(app_path) and os.path.isfile(requirements_path):
            return mapping_editor_dir

        should_clone = not os.path.isdir(mapping_editor_dir)
        if not should_clone:
            try:
                remaining_entries = os.listdir(mapping_editor_dir)
            except OSError:
                remaining_entries = []
            should_clone = len(remaining_entries) == 0

        if should_clone:
            os.makedirs(sources_dir, exist_ok=True)
            if os.path.isdir(mapping_editor_dir):
                try:
                    os.rmdir(mapping_editor_dir)
                except OSError:
                    pass
            print(f"Cloning mapping-editor into {mapping_editor_dir} ...")
            import subprocess
            try:
                subprocess.run(["git", "clone", self._MAPPING_EDITOR_REPO_URL, mapping_editor_dir], check=True)
            except Exception as exc:
                self._fail(
                    "Could not clone mapping-editor repository",
                    root_cause=str(exc),
                )

        if os.path.isfile(app_path) and os.path.isfile(requirements_path):
            return mapping_editor_dir

        self._fail(
            "mapping-editor source directory is not usable",
            root_cause=(
                f"Expected Mapping_Editor.py at: {app_path} and requirements.txt at: {requirements_path}. "
                "Level 5 expects the canonical checkout at "
                "adapters/inesdata/sources/mapping-editor."
            ),
        )

    def _resolve_automap_source_dir(self, deployer_config: dict) -> str:
        sources_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")
        automap_dir = os.path.join(sources_dir, self._AUTOMAP_REPO_DIRNAME)
        required_paths = [
            os.path.join(automap_dir, "README.md"),
            os.path.join(automap_dir, "pyproject.toml"),
            os.path.join(automap_dir, "main.py"),
            os.path.join(automap_dir, "langgraph.json"),
            os.path.join(automap_dir, "agents", "schema_agent.py"),
            os.path.join(automap_dir, "graph", "workflow.py"),
            os.path.join(automap_dir, "tools", "rml_tools.py"),
            os.path.join(automap_dir, "evaluation", "metrics.py"),
        ]
        if all(os.path.isfile(path) for path in required_paths):
            return automap_dir

        should_clone = not os.path.isdir(automap_dir)
        if not should_clone:
            try:
                remaining_entries = os.listdir(automap_dir)
            except OSError:
                remaining_entries = []
            should_clone = len(remaining_entries) == 0

        if should_clone:
            os.makedirs(sources_dir, exist_ok=True)
            if os.path.isdir(automap_dir):
                try:
                    os.rmdir(automap_dir)
                except OSError:
                    pass
            print(f"Cloning automap into {automap_dir} ...")
            import subprocess
            try:
                subprocess.run(["git", "clone", self._AUTOMAP_REPO_URL, automap_dir], check=True)
            except Exception as exc:
                self._fail(
                    "Could not clone automap repository",
                    root_cause=str(exc),
                )

        if all(os.path.isfile(path) for path in required_paths):
            return automap_dir

        self._fail(
            "automap source directory is not usable",
            root_cause=(
                "Expected README.md, pyproject.toml, main.py, langgraph.json and core "
                "agents/graph/tools/evaluation modules under "
                "adapters/inesdata/sources/automap."
            ),
        )

    def _semantic_virtualization_api_dockerfile(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "containers",
            "semantic-virtualization-api",
            "Dockerfile",
        )

    def _semantic_virtualization_api_server_file(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "containers",
            "semantic-virtualization-api",
            "morph_kgv_http_server.py",
        )

    def _mapping_editor_dockerfile(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "containers",
            "mapping-editor",
            "Dockerfile",
        )

    def _ontology_hub_build_args(self, ontology_hub_dir: str) -> dict:
        compose_path = os.path.join(ontology_hub_dir, "docker-compose.yml")
        if os.path.isfile(compose_path):
            compose = self._safe_load_yaml_file(compose_path)
            lov_server = ((compose.get("services") or {}).get("lov_server") or {})
            build = lov_server.get("build") or {}
            args = build.get("args") or {}
            if isinstance(args, dict) and args:
                return {str(k): str(v) for k, v in args.items() if v is not None}

        return {
            "REPO_URL": "https://github.com/ProyectoPIONERA/Ontology-Hub-Scripts.git",
            "BRANCH_NAME": "dev",
            "REPO_NAME": "Ontology-Hub-Scripts",
            "REPO_PATRONES": "https://github.com/oeg-upm/GrOwEr.git",
        }

    def _host_has_image(self, image_ref: str) -> bool:
        image_q = shlex.quote(image_ref)
        docker_q = shlex.quote(self._docker_cmd())
        return self.run_silent(f"{docker_q} image inspect {image_q}") is not None

    @staticmethod
    def _docker_cmd() -> str:
        configured = os.environ.get("PIONERA_DOCKER_CMD") or os.environ.get("DOCKER_CMD")
        if configured:
            return configured.strip() or "docker"
        resolved = shutil.which("docker")
        if resolved:
            return resolved
        docker_desktop = "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
        if os.path.exists(docker_desktop):
            return docker_desktop
        return "docker"

    @staticmethod
    def _k3s_cri_image_ref_alias(image_ref: str) -> str:
        normalized = str(image_ref or "").strip()
        if not normalized:
            return ""
        has_path = "/" in normalized
        first_segment = normalized.split("/", 1)[0]
        if has_path and ("." in first_segment or ":" in first_segment or first_segment == "localhost"):
            return normalized
        if has_path:
            return f"docker.io/{normalized}"
        return f"docker.io/library/{normalized}"

    @staticmethod
    def _dedupe_image_refs(image_refs) -> list[str]:
        deduped = []
        seen = set()
        for raw_ref in list(image_refs or []):
            image_ref = str(raw_ref or "").strip()
            if not image_ref or image_ref in seen:
                continue
            seen.add(image_ref)
            deduped.append(image_ref)
        return deduped

    def _k3s_image_save_refs(self, image_ref: str) -> list[str]:
        image_ref = str(image_ref or "").strip()
        if not image_ref:
            return []
        save_refs = [image_ref]
        cri_alias = self._k3s_cri_image_ref_alias(image_ref)
        if cri_alias and cri_alias != image_ref:
            save_refs.append(cri_alias)
        return save_refs

    def _normalized_topology(self) -> str:
        return normalize_topology(getattr(self.config_adapter, "topology", None) or "local")

    def _is_vm_distributed_topology(self) -> bool:
        return self._normalized_topology() == VM_DISTRIBUTED_TOPOLOGY

    def _is_vm_single_topology(self) -> bool:
        return self._normalized_topology() == VM_SINGLE_TOPOLOGY

    @staticmethod
    def _config_value(config: dict | None, *keys: str) -> str:
        values = dict(config or {})
        for key in keys:
            value = str(values.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _local_k3s_command_available() -> bool:
        if shutil.which("k3s"):
            return True
        return any(os.path.exists(path) for path in ("/usr/local/bin/k3s", "/usr/bin/k3s"))

    @staticmethod
    def _resolve_host_addresses(host: str) -> set[str]:
        value = str(host or "").strip()
        if not value:
            return set()
        try:
            return {str(ipaddress.ip_address(value))}
        except ValueError:
            pass
        try:
            return {
                str(item[4][0])
                for item in socket.getaddrinfo(value, None)
                if item and item[4] and item[4][0]
            }
        except OSError:
            return set()

    def _local_host_addresses(self) -> set[str]:
        addresses = {"127.0.0.1", "::1"}
        for candidate in {socket.gethostname(), socket.getfqdn()}:
            addresses.update(self._resolve_host_addresses(candidate))
        try:
            hostname_ips = self.run_silent("hostname -I")
        except Exception:
            hostname_ips = ""
        for raw_value in str(hostname_ips or "").split():
            addresses.update(self._resolve_host_addresses(raw_value))
        return {address for address in addresses if address}

    def _vm_single_running_on_target(self, deployer_config: dict | None = None) -> bool:
        if os.environ.get("PIONERA_VM_SINGLE_REMOTE_LEVEL_ACTIVE") == "true":
            return True
        config = dict(deployer_config or {})
        local_names = {
            "localhost",
            socket.gethostname().strip().lower(),
            socket.getfqdn().strip().lower(),
        }
        target_values = {
            self._config_value(config, "VM_SINGLE_SSH_HOST"),
            self._config_value(config, "VM_EXTERNAL_IP"),
            self._config_value(config, "VM_SINGLE_IP"),
            self._config_value(config, "VM_SINGLE_ADDRESS"),
        }
        for value in target_values:
            normalized = str(value or "").strip().lower()
            if normalized and normalized in local_names:
                return True
        target_addresses = set()
        for value in target_values:
            target_addresses.update(self._resolve_host_addresses(value))
        return bool(target_addresses.intersection(self._local_host_addresses()))

    def _vm_single_should_use_local_k3s_import(self, deployer_config: dict | None = None) -> bool:
        if not self._local_k3s_command_available():
            return False
        config = dict(deployer_config or {})
        mode = str(config.get("VM_SINGLE_LEVEL_EXECUTION_MODE") or "").strip().lower()
        if mode in {"local", "direct"}:
            return True
        if self._vm_single_running_on_target(config):
            return True
        return self._vm_single_remote_image_import_target(config) is None

    def _resolved_cluster_type(self, deployer_config: dict | None = None) -> str:
        config = dict(deployer_config or {})
        runtime = self._cluster_runtime(config)
        return (
            str(config.get("CLUSTER_TYPE") or runtime.get("cluster_type") or "minikube").strip().lower()
            or "minikube"
        )

    def _assume_level5_local_images_available(self, deployer_config: dict | None = None) -> bool:
        config = dict(deployer_config or {})
        flag = config.get("LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE")
        if flag is None:
            flag = config.get("LEVEL6_ASSUME_LOCAL_IMAGES_AVAILABLE")
        if flag is None:
            flag = os.environ.get("LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE")
        if flag is None:
            flag = os.environ.get("LEVEL6_ASSUME_LOCAL_IMAGES_AVAILABLE")
        return self._parse_bool(flag, default=False)

    def _vm_single_remote_image_import_target(self, deployer_config: dict | None = None):
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

    def _remote_k3s_image_import_target(self, deployer_config: dict | None = None):
        config = dict(deployer_config or {})
        if not config:
            try:
                config = dict(self.config_adapter.load_deployer_config() or {})
            except Exception:
                config = {}
        if self._is_vm_distributed_topology():
            return remote_k3s_image_import_target(config, role="components")
        if self._is_vm_single_topology() and self._resolved_cluster_type(config) == "k3s":
            if self._vm_single_should_use_local_k3s_import(config):
                return None
            return self._vm_single_remote_image_import_target(config)
        return None

    @staticmethod
    def _remote_import_command_uses_noninteractive_sudo(import_command: str) -> bool:
        try:
            parts = shlex.split(str(import_command or "").strip())
        except ValueError:
            parts = str(import_command or "").strip().split()
        if not parts or parts[0] != "sudo":
            return False
        for part in parts[1:]:
            if part == "-n":
                return True
            if not part.startswith("-"):
                return False
        return False

    def _ensure_remote_k3s_image_import_prerequisites(self, remote_target, image_ref: str):
        if not remote_target:
            return
        if remote_target.allows_interactive_fallback():
            return
        if not self._remote_import_command_uses_noninteractive_sudo(remote_target.import_command):
            return

        probe_command = shell_join(remote_target.ssh_sudo_probe_args())
        if self.run(probe_command, check=False) is not None:
            return

        self._fail(
            "Remote k3s image import requires non-interactive sudo for k3s",
            root_cause=(
                f"Image '{image_ref}' must be imported on '{remote_target.host}', but the configured "
                f"command uses '{remote_target.import_command}' and a non-interactive k3s sudo probe "
                "failed over SSH. Configure a registry image, run Level 5 from the k3s host, or ask the "
                "administrator to allow the deployment user to run k3s image import commands without an "
                "interactive password."
            ),
        )

    def _ensure_k3s_local_image_import_supported(self, image_ref: str, deployer_config: dict | None = None):
        topology = self._normalized_topology()
        if topology not in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}:
            return
        if topology == VM_SINGLE_TOPOLOGY and self._vm_single_should_use_local_k3s_import(deployer_config):
            return
        remote_target = self._remote_k3s_image_import_target(deployer_config)
        if remote_target:
            self._ensure_remote_k3s_image_import_prerequisites(remote_target, image_ref)
            return
        if topology == VM_SINGLE_TOPOLOGY:
            self._fail(
                "Remote k3s image import is not configured for vm-single Level 5",
                root_cause=(
                    f"Image '{image_ref}' must be available in the vm-single k3s runtime. "
                    "Run Level 5 from the vm-single VM, publish the component image to a registry "
                    "reachable by the cluster, or configure VM_SINGLE_REMOTE_IMAGE_IMPORT with "
                    "VM_SINGLE_SSH_HOST so the framework can import it remotely. "
                    "A local 'sudo k3s ctr images import' would target the operator host, not the "
                    "vm-single cluster."
                ),
            )
        self._fail(
            "Remote k3s image import is not configured for vm-distributed Level 5",
            root_cause=(
                f"Image '{image_ref}' must be available in the remote k3s runtime. "
                "Publish the component image to a registry reachable by the cluster, "
                "or set VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT=true with VM_COMPONENTS_SSH_HOST "
                "(or VM_COMMON_SSH_HOST) so the framework can import it on the components VM. "
                "A local 'sudo k3s ctr images import' would target the WSL host, not the remote cluster."
            ),
        )

    def _load_image_into_minikube(self, profile: str, image_ref: str):
        profile_q = shlex.quote(profile)
        image_q = shlex.quote(image_ref)
        print(f"\nLoading image into minikube: {image_ref}")
        if self.run(f"minikube -p {profile_q} image load {image_q}", check=False) is None:
            self._fail("Failed to load image into minikube", root_cause=image_ref)

    def _load_image_into_k3s(self, image_ref: str, deployer_config: dict | None = None):
        self._load_images_into_k3s([image_ref], deployer_config)

    def _load_images_into_k3s(self, image_refs, deployer_config: dict | None = None):
        image_refs = self._dedupe_image_refs(image_refs)
        if not image_refs:
            return

        docker_q = shlex.quote(self._docker_cmd())
        save_refs = []
        for image_ref in image_refs:
            image_q = shlex.quote(image_ref)
            cri_alias = self._k3s_cri_image_ref_alias(image_ref)
            if not cri_alias or cri_alias == image_ref:
                save_refs.append(image_ref)
                continue
            cri_alias_q = shlex.quote(cri_alias)
            if self.run(f"{docker_q} tag {image_q} {cri_alias_q}", check=False) is None:
                self._fail("Failed to tag local image with k3s CRI alias", root_cause=f"{image_ref} -> {cri_alias}")
            save_refs.extend(self._k3s_image_save_refs(image_ref))

        save_refs = self._dedupe_image_refs(save_refs)
        save_refs_q = " ".join(shlex.quote(ref) for ref in save_refs)
        fd, archive_path = tempfile.mkstemp(prefix="pionera-component-images-", suffix=".tar")
        os.close(fd)
        archive_q = shlex.quote(archive_path)
        refs_label = ", ".join(image_refs)
        try:
            remote_target = self._remote_k3s_image_import_target(deployer_config)
            if remote_target:
                print(f"\nLoading image(s) into remote k3s containerd ({remote_target.host}): {refs_label}")
            else:
                print(f"\nLoading image(s) into k3s containerd: {refs_label}")
            if self.run(f"{docker_q} save {save_refs_q} -o {archive_q}", check=False) is None:
                self._fail("Failed to export local image(s) for k3s", root_cause=refs_label)
            if remote_target:
                remote_archive_path = remote_target.remote_archive_path(archive_path)
                scp_command = shell_join(remote_target.scp_upload_args(archive_path, remote_archive_path))
                if self.run(scp_command, check=False) is None:
                    self._fail("Failed to copy image archive to remote k3s node", root_cause=remote_target.host)
                interactive_import = False
                if remote_target.allows_interactive_fallback():
                    probe_command = shell_join(remote_target.ssh_sudo_probe_args())
                    if self.run(probe_command, check=False) is None:
                        print(
                            "Remote k3s image import needs sudo password; "
                            "retrying with an interactive prompt."
                        )
                        interactive_import = True
                ssh_command = shell_join(
                    remote_target.ssh_import_args(remote_archive_path, interactive=interactive_import)
                )
                if self.run(ssh_command, check=False) is None:
                    self._fail("Failed to import image(s) into remote k3s containerd", root_cause=refs_label)
                return
            if self.run(f"sudo k3s ctr -n k8s.io images import {archive_q}", check=False) is None:
                self._fail("Failed to import image(s) into k3s containerd", root_cause=refs_label)
        finally:
            try:
                os.unlink(archive_path)
            except OSError:
                pass

    def _load_image_into_cluster_runtime(
        self,
        cluster_runtime: str,
        profile: str,
        image_ref: str,
        deployer_config: dict | None = None,
    ):
        if cluster_runtime == "k3s":
            self._ensure_k3s_local_image_import_supported(image_ref, deployer_config)
            self._load_image_into_k3s(image_ref, deployer_config)
            return
        self._load_image_into_minikube(profile, image_ref)

    def _load_images_into_cluster_runtime(
        self,
        cluster_runtime: str,
        profile: str,
        image_refs,
        deployer_config: dict | None = None,
    ):
        image_refs = self._dedupe_image_refs(image_refs)
        if not image_refs:
            return
        if cluster_runtime == "k3s":
            for image_ref in image_refs:
                self._ensure_k3s_local_image_import_supported(image_ref, deployer_config)
            self._load_images_into_k3s(image_refs, deployer_config)
            return
        for image_ref in image_refs:
            self._load_image_into_minikube(profile, image_ref)

    def _build_ontology_hub_image_on_host(self, image_ref: str, deployer_config: dict):
        ontology_hub_dir = self._resolve_ontology_hub_source_dir(deployer_config)
        dockerfile_path = os.path.join(ontology_hub_dir, "Dockerfile")
        if not os.path.isfile(dockerfile_path):
            self._fail(
                "Ontology-Hub source directory not found",
                root_cause=(
                    f"Expected Dockerfile at: {dockerfile_path}. "
                    "The canonical checkout in adapters/inesdata/sources/Ontology-Hub is missing or incomplete."
                ),
            )

        build_args = self._ontology_hub_build_args(ontology_hub_dir)
        required = ("REPO_URL", "BRANCH_NAME", "REPO_NAME", "REPO_PATRONES")
        missing = [k for k in required if not (build_args.get(k) or "").strip()]
        if missing:
            self._fail(
                "Ontology-Hub build args are missing",
                root_cause=f"Missing keys: {', '.join(missing)} (see {os.path.join(ontology_hub_dir, 'docker-compose.yml')})",
            )

        image_q = shlex.quote(image_ref)
        docker_q = shlex.quote(self._docker_cmd())
        arg_flags = " ".join(
            f"--build-arg {shlex.quote(f'{k}={v}')}"
            for k, v in build_args.items()
            if (v is not None and str(v).strip() != "")
        )

        print(f"\nBuilding local image on host: {image_ref}")
        cmd = f"{docker_q} build -t {image_q}"
        if arg_flags:
            cmd += f" {arg_flags}"
        cmd += " -f Dockerfile ."
        if self.run(cmd, check=False, cwd=ontology_hub_dir) is None:
            self._fail("Failed to build ontology-hub image on host", root_cause=image_ref)

    def _build_ai_model_hub_image_on_host(self, image_ref: str, deployer_config: dict):
        dashboard_dir = self._resolve_ai_model_hub_source_dir(deployer_config)
        dockerfile_path = os.path.join(dashboard_dir, "Dockerfile")
        if not os.path.isfile(dockerfile_path):
            self._fail(
                "AI Model Hub source directory not found",
                root_cause=(
                    f"Expected Dockerfile at: {dockerfile_path}. "
                    "The canonical checkout in adapters/inesdata/sources/AIModelHub is missing or incomplete."
                ),
            )

        image_q = shlex.quote(image_ref)
        docker_q = shlex.quote(self._docker_cmd())
        print(f"\nBuilding local image on host: {image_ref}")
        cmd = f"{docker_q} build -t {image_q} ."
        if self.run(cmd, check=False, cwd=dashboard_dir) is None:
            self._fail("Failed to build AI Model Hub image on host", root_cause=image_ref)

    def _prepare_semantic_virtualization_api_build_context(self, morph_kgv_dir: str) -> str:
        build_context = tempfile.mkdtemp(prefix="pionera-morph-kgv-build-")
        source_target = os.path.join(build_context, "morph-kgv")
        shutil.copytree(
            morph_kgv_dir,
            source_target,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv"),
        )
        shutil.copy2(
            self._semantic_virtualization_api_server_file(),
            os.path.join(build_context, "morph_kgv_http_server.py"),
        )
        return build_context

    def _build_semantic_virtualization_image_on_host(self, image_ref: str, deployer_config: dict):
        morph_kgv_dir = self._resolve_morph_kgv_source_dir(deployer_config)
        # Keep the UI/editor source available as part of the component bundle,
        # while the A5.2 API image is built from morph-kgv.
        self._resolve_mapping_editor_source_dir(deployer_config)
        # Automap is included as mapping-generation tooling for the virtualizer
        # scope, but it is not part of the runtime API image.
        self._resolve_automap_source_dir(deployer_config)
        dockerfile_path = self._semantic_virtualization_api_dockerfile()
        server_file = self._semantic_virtualization_api_server_file()
        if not os.path.isfile(dockerfile_path):
            self._fail(
                "Semantic Virtualization API Dockerfile not found",
                root_cause=(
                    f"Expected Dockerfile at: {dockerfile_path}. "
                    "The framework wraps morph-kgv as a local SPARQL API for A5.2 validation."
                ),
            )
        if not os.path.isfile(server_file):
            self._fail(
                "Semantic Virtualization API server wrapper not found",
                root_cause=(
                    f"Expected wrapper at: {server_file}. "
                    "Level 5 needs it to expose morph-kgv through HTTP for Level 6."
                ),
            )

        image_q = shlex.quote(image_ref)
        dockerfile_q = shlex.quote(dockerfile_path)
        docker_q = shlex.quote(self._docker_cmd())
        build_context = self._prepare_semantic_virtualization_api_build_context(morph_kgv_dir)
        try:
            print(f"\nBuilding local image on host: {image_ref}")
            cmd = f"{docker_q} build -t {image_q} -f {dockerfile_q} ."
            if self.run(cmd, check=False, cwd=build_context) is None:
                self._fail("Failed to build Semantic Virtualization image on host", root_cause=image_ref)
        finally:
            shutil.rmtree(build_context, ignore_errors=True)

    def _build_mapping_editor_image_on_host(self, image_ref: str, deployer_config: dict):
        mapping_editor_dir = self._resolve_mapping_editor_source_dir(deployer_config)
        dockerfile_path = self._mapping_editor_dockerfile()
        if not os.path.isfile(dockerfile_path):
            self._fail(
                "mapping-editor Dockerfile not found",
                root_cause=(
                    f"Expected Dockerfile at: {dockerfile_path}. "
                    "The framework deploys mapping-editor as an opt-in Streamlit UI for A5.2 validation."
                ),
            )

        image_q = shlex.quote(image_ref)
        dockerfile_q = shlex.quote(dockerfile_path)
        docker_q = shlex.quote(self._docker_cmd())
        print(f"\nBuilding local image on host: {image_ref}")
        cmd = f"{docker_q} build -t {image_q} -f {dockerfile_q} ."
        if self.run(cmd, check=False, cwd=mapping_editor_dir) is None:
            self._fail("Failed to build mapping-editor image on host", root_cause=image_ref)

    def _effective_component_values(self, normalized_component: str, values_file: str, deployer_config: dict) -> dict:
        values = dict(self._safe_load_yaml_file(values_file) or {})
        overrides = self._component_values_override_payload(normalized_component, deployer_config)

        image_overrides = overrides.get("image") or {}
        if image_overrides:
            image_values = dict(values.get("image") or {})
            image_values.update(image_overrides)
            values["image"] = image_values

        mapping_editor_overrides = (overrides.get("mappingEditor") or {}).get("image") or {}
        if mapping_editor_overrides:
            mapping_editor_values = dict(values.get("mappingEditor") or {})
            mapping_editor_image_values = dict(mapping_editor_values.get("image") or {})
            mapping_editor_image_values.update(mapping_editor_overrides)
            mapping_editor_values["image"] = mapping_editor_image_values
            values["mappingEditor"] = mapping_editor_values

        return values

    def _maybe_prepare_level6_local_image(self, normalized_component: str, values_file: str, deployer_config: dict) -> bool:
        """Ensure local images referenced by a Level 5 component exist in the active cluster runtime.

        Returns True when the active cluster runtime image cache was updated.
        """
        values = self._effective_component_values(normalized_component, values_file, deployer_config)
        image_ref = self._extract_primary_image_ref(values)
        runtime = self._cluster_runtime(deployer_config)
        cluster_type = str(runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
        configured_image_override = self._configured_component_image_override(
            normalized_component,
            deployer_config,
        )

        profile = (
            deployer_config.get("MINIKUBE_PROFILE")
            or getattr(self.config, "MINIKUBE_PROFILE", "minikube")
            or "minikube"
        ).strip() or "minikube"
        auto_build_flag = deployer_config.get("LEVEL5_AUTO_BUILD_LOCAL_IMAGES")
        if auto_build_flag is None:
            auto_build_flag = deployer_config.get("LEVEL6_AUTO_BUILD_LOCAL_IMAGES")
        if auto_build_flag is None:
            auto_build_flag = os.environ.get("LEVEL5_AUTO_BUILD_LOCAL_IMAGES")
        if auto_build_flag is None:
            auto_build_flag = os.environ.get("LEVEL6_AUTO_BUILD_LOCAL_IMAGES")
        auto_build_enabled = self._parse_bool(auto_build_flag, default=True)

        if normalized_component == "ontology-hub":
            if not image_ref:
                self._fail(
                    "Ontology-Hub chart image is not declared",
                    root_cause=f"Values file: {values_file}",
                )
            if not image_ref.lower().endswith(":local"):
                if configured_image_override:
                    print(
                        "Ontology-Hub is configured with a prebuilt image. "
                        f"Skipping local image build: {image_ref}"
                    )
                    return False
                self._fail(
                    "Ontology-Hub must use a local image in Level 5/6 unless a prebuilt image is configured",
                    root_cause=f"Configured image: {image_ref}",
                )
            if not auto_build_enabled:
                if (
                    cluster_type == "k3s"
                    and self._normalized_topology() in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}
                    and not self._assume_level5_local_images_available(deployer_config)
                ):
                    self._fail(
                        f"Local image auto-build disabled for '{normalized_component}'",
                        root_cause=(
                            f"Image '{image_ref}' uses the local tag and must already exist in the k3s runtime. "
                            "Enable LEVEL5_AUTO_BUILD_LOCAL_IMAGES, configure a registry image, or set "
                            "LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE=true only when the image has already been "
                            "imported into the target k3s cluster."
                        ),
                    )
                print(
                    f"Local image auto-build disabled for '{normalized_component}'. "
                    f"Using existing cluster image '{image_ref}'."
                )
                return False
            if cluster_type == "minikube" and not self._minikube_is_available(profile):
                self._fail(
                    "Minikube profile is not available for Ontology-Hub local image deployment",
                    root_cause=profile,
                )
            if cluster_type == "k3s":
                self._ensure_k3s_local_image_import_supported(image_ref, deployer_config)
            self._build_ontology_hub_image_on_host(image_ref, deployer_config)
            self._load_image_into_cluster_runtime(cluster_type, profile, image_ref, deployer_config)
            return True

        if not auto_build_enabled:
            if (
                image_ref
                and image_ref.lower().endswith(":local")
                and cluster_type == "k3s"
                and self._normalized_topology() in {VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY}
                and not self._assume_level5_local_images_available(deployer_config)
            ):
                self._fail(
                    f"Local image auto-build disabled for '{normalized_component}'",
                    root_cause=(
                        f"Image '{image_ref}' uses the local tag and must already exist in the k3s runtime. "
                        "Enable LEVEL5_AUTO_BUILD_LOCAL_IMAGES, configure a registry image, or set "
                        "LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE=true only when the image has already been "
                        "imported into the target k3s cluster."
                    ),
                )
            return False

        if not image_ref:
            return False

        if not image_ref.lower().endswith(":local"):
            return False

        if cluster_type == "minikube" and not self._minikube_is_available(profile):
            print(
                f"Local image '{image_ref}' referenced, but minikube profile '{profile}' is not available. "
                "Skipping auto-build."
            )
            return False

        if cluster_type == "k3s":
            self._ensure_k3s_local_image_import_supported(image_ref, deployer_config)

        if normalized_component == "ai-model-hub":
            self._build_ai_model_hub_image_on_host(image_ref, deployer_config)
            self._load_image_into_cluster_runtime(cluster_type, profile, image_ref, deployer_config)
            return True

        if normalized_component == "semantic-virtualization":
            image_refs_to_load = [image_ref]
            self._build_semantic_virtualization_image_on_host(image_ref, deployer_config)
            if self._semantic_virtualization_mapping_editor_enabled(deployer_config):
                editor_image_ref = self._extract_mapping_editor_image_ref(values)
                if not editor_image_ref:
                    self._fail(
                        "mapping-editor chart image is not declared",
                        root_cause=f"Values file: {values_file}",
                    )
                if editor_image_ref.lower().endswith(":local"):
                    if cluster_type == "k3s":
                        self._ensure_k3s_local_image_import_supported(editor_image_ref, deployer_config)
                    self._build_mapping_editor_image_on_host(editor_image_ref, deployer_config)
                    image_refs_to_load.append(editor_image_ref)
            self._load_images_into_cluster_runtime(
                cluster_type,
                profile,
                image_refs_to_load,
                deployer_config,
            )
            return True

        if cluster_type == "minikube" and self._minikube_has_image(profile, image_ref):
            return False

        print(
            f"Local image '{image_ref}' is missing in {cluster_type}, "
            f"but no auto-build recipe exists for '{normalized_component}'."
        )
        return False

    def _infer_component_hostname(self, normalized_component: str, values_file: str, deployer_config: dict):
        """Infer component hostname (ingress host) from Helm values."""
        try:
            values = self._safe_load_yaml_file(values_file)
        except Exception:
            return None

        return infer_component_hostname(
            normalized_component,
            values,
            deployer_config,
            dataspace_name=(getattr(self.config, "DS_NAME", "") or "").strip(),
        )

    def _configured_component_host(self, normalized_component: str, deployer_config: dict) -> str:
        return configured_component_host(
            normalized_component,
            deployer_config,
            dataspace_name=(getattr(self.config, "DS_NAME", "") or "").strip(),
        )

    def _configured_component_public_path(self, normalized_component: str, deployer_config: dict) -> str:
        return configured_component_public_path(normalized_component, deployer_config)

    def _configured_component_public_url(self, normalized_component: str, deployer_config: dict) -> str:
        return configured_component_public_url(
            normalized_component,
            deployer_config,
            dataspace_name=(getattr(self.config, "DS_NAME", "") or "").strip(),
        )

    def _component_public_path_rewrite_enabled(
        self,
        normalized_component: str,
        deployer_config: dict,
        public_path: str,
    ) -> bool:
        if not public_path:
            return False
        env_key = self._normalize_component_key(normalized_component).upper().replace("-", "_")
        value = deployer_config.get(f"{env_key}_PUBLIC_PATH_REWRITE")
        if value is None:
            value = deployer_config.get("COMPONENTS_PUBLIC_PATH_REWRITE")
        return self._parse_bool(value, default=True)

    def _component_ingress_override(
        self,
        normalized_component: str,
        host: str,
        deployer_config: dict,
    ) -> dict:
        ingress = {
            "enabled": True,
            "host": host,
        }
        public_path = self._configured_component_public_path(normalized_component, deployer_config)
        if not public_path:
            return ingress

        if self._component_public_path_rewrite_enabled(normalized_component, deployer_config, public_path):
            ingress["path"] = f"{public_path}(/|$)(.*)"
            ingress["pathType"] = "ImplementationSpecific"
            ingress["annotations"] = {
                "nginx.ingress.kubernetes.io/use-regex": "true",
                "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
            }
        else:
            ingress["path"] = public_path
            ingress["pathType"] = "Prefix"
        return ingress

    def _resolve_dataspace_connector_ids(self, *, ds_name=None, deployer_config=None):
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        resolved_name = str(ds_name or self._dataspace_name() or "").strip() or self._dataspace_name()
        resolved_index = self._resolve_dataspace_index(
            ds_name=resolved_name,
            deployer_config=resolved_config,
        )

        raw = str(resolved_config.get(f"DS_{resolved_index}_CONNECTORS") or "").strip()
        connector_ids = []
        for token in raw.split(","):
            normalized = str(token or "").strip()
            if not normalized:
                continue
            if normalized.startswith("conn-"):
                connector_ids.append(normalized)
            else:
                connector_ids.append(f"conn-{normalized}-{resolved_name}")
        return connector_ids

    def _connector_public_base_url(self, connector_id: str, deployer_config: dict) -> str:
        resolved_connector_id = str(connector_id or "").strip()
        if not resolved_connector_id:
            return ""

        resolved_domain = str((deployer_config or {}).get("DS_DOMAIN_BASE") or "").strip()
        if not resolved_domain:
            return ""
        return self._to_http_url(f"{resolved_connector_id}.{resolved_domain}")

    @staticmethod
    def _connector_short_name(connector_id: str, dataspace: str) -> str:
        short_name = str(connector_id or "").strip()
        if short_name.startswith("conn-"):
            short_name = short_name[len("conn-"):]
        suffix = f"-{dataspace}"
        if dataspace and short_name.endswith(suffix):
            short_name = short_name[: -len(suffix)]
        return short_name

    @staticmethod
    def _vm_single_connector_public_path_prefix(deployer_config: dict) -> str:
        prefix = str((deployer_config or {}).get("VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX") or "/c").strip()
        if not prefix:
            prefix = "/c"
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        return prefix.rstrip("/")

    def _vm_single_connector_public_base_url(self, connector_id: str, deployer_config: dict) -> str:
        config = dict(deployer_config or {})
        topology = normalize_topology(
            config.get("TOPOLOGY")
            or config.get("PIONERA_TOPOLOGY")
            or config.get("INESDATA_TOPOLOGY")
            or self._normalized_topology()
        )
        if topology != VM_SINGLE_TOPOLOGY:
            return ""

        common_base = str(
            config.get("VM_SINGLE_PUBLIC_URL")
            or config.get("VM_SINGLE_HTTP_URL")
            or config.get("VM_COMMON_PUBLIC_URL")
            or config.get("VM_COMMON_HTTP_URL")
            or ""
        ).strip().rstrip("/")
        if not common_base:
            return ""

        short_name = self._connector_short_name(connector_id, self._dataspace_name())
        if not short_name:
            return ""
        return f"{common_base}{self._vm_single_connector_public_path_prefix(config)}/{short_name}"

    def _connector_external_base_url(self, connector_id: str, deployer_config: dict, *, role: str = "") -> str:
        config = dict(deployer_config or {})
        normalized_role = str(role or "").strip().lower()
        role_key = {
            "provider": "VM_PROVIDER_PUBLIC_URL",
            "consumer": "VM_CONSUMER_PUBLIC_URL",
        }.get(normalized_role)
        if role_key:
            explicit = str(config.get(role_key) or "").strip()
            if explicit:
                return explicit.rstrip("/")

        vm_single_base = self._vm_single_connector_public_base_url(connector_id, config)
        if vm_single_base:
            return vm_single_base.rstrip("/")

        return self._connector_public_base_url(connector_id, config)

    def _connector_protocol_base_url(self, connector_id: str, deployer_config: dict, *, role: str = "") -> str:
        config = dict(deployer_config or {})
        mode = str(
            config.get("PIONERA_CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or config.get("CONNECTOR_PROTOCOL_ADDRESS_MODE")
            or "public"
        ).strip().lower()
        if mode in {"internal", "private"}:
            return self._connector_public_base_url(connector_id, config)
        return self._connector_external_base_url(connector_id, config, role=role)

    def _ai_model_hub_connector_config(self, *, ds_name=None, deployer_config=None) -> list[dict]:
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        connector_ids = self._resolve_dataspace_connector_ids(
            ds_name=ds_name,
            deployer_config=resolved_config,
        )
        if not connector_ids:
            return []

        provider_id = connector_ids[0] if connector_ids else ""
        consumer_id = connector_ids[1] if len(connector_ids) > 1 else ""
        entries = []

        if consumer_id:
            consumer_base = self._connector_external_base_url(consumer_id, resolved_config, role="consumer")
            consumer_protocol_base = self._connector_protocol_base_url(
                consumer_id,
                resolved_config,
                role="consumer",
            )
            if consumer_base:
                entries.append(
                    {
                        "connectorName": "Consumer",
                        "managementUrl": f"{consumer_base}/management",
                        "defaultUrl": f"{consumer_base}/api",
                        "protocolUrl": f"{(consumer_protocol_base or consumer_base)}/protocol",
                        "federatedCatalogEnabled": False,
                    }
                )

        if provider_id:
            provider_base = self._connector_external_base_url(provider_id, resolved_config, role="provider")
            provider_protocol_base = self._connector_protocol_base_url(
                provider_id,
                resolved_config,
                role="provider",
            )
            if provider_base:
                entries.append(
                    {
                        "connectorName": "Provider",
                        "managementUrl": f"{provider_base}/management",
                        "defaultUrl": f"{provider_base}/api",
                        "protocolUrl": f"{(provider_protocol_base or provider_base)}/protocol",
                        "federatedCatalogEnabled": False,
                    }
                )

        return entries

    def _component_values_override_payload(self, normalized_component: str, deployer_config: dict) -> dict:
        normalized = self._normalize_component_key(normalized_component)
        overrides = {}

        image_override = self._configured_component_image_override(normalized, deployer_config)
        if image_override:
            overrides["image"] = image_override

        if normalized == "ontology-hub":
            host = self._configured_component_host(normalized, deployer_config)
            if host:
                public_base_url = self._to_public_url(
                    self._configured_component_public_url(normalized, deployer_config) or host
                ).rstrip("/")
                self_host_url = self._ontology_hub_self_host_url(public_base_url, deployer_config)
                overrides["ingress"] = self._component_ingress_override(normalized, host, deployer_config)
                overrides["env"] = {
                    "SELF_HOST_URL": self_host_url,
                    "BASE_URL": public_base_url,
                }
                host_alias_ip = self._resolve_ontology_hub_self_host_alias_ip(deployer_config)
                if host_alias_ip:
                    overrides["hostAliases"] = [
                        {
                            "ip": host_alias_ip,
                            "hostnames": [host],
                        }
                    ]

            if "ONTOLOGY_HUB_SAMPLE_DATA_ENABLED" in deployer_config:
                overrides.setdefault("sampleData", {})["enabled"] = self._parse_bool(
                    deployer_config.get("ONTOLOGY_HUB_SAMPLE_DATA_ENABLED"),
                    default=True,
                )
            persistence_enabled = deployer_config.get("ONTOLOGY_HUB_VERSIONS_PERSISTENCE_ENABLED")
            if persistence_enabled is None:
                persistence_enabled = deployer_config.get("COMPONENTS_VERSIONS_PERSISTENCE_ENABLED")
            if persistence_enabled is None and (self._is_vm_single_topology() or self._is_vm_distributed_topology()):
                persistence_enabled = True
            if persistence_enabled is not None:
                versions = overrides.setdefault("versions", {})
                persistence = versions.setdefault("persistence", {})
                persistence["enabled"] = self._parse_bool(persistence_enabled, default=True)
                persistence_size = str(
                    deployer_config.get("ONTOLOGY_HUB_VERSIONS_PERSISTENCE_SIZE")
                    or deployer_config.get("COMPONENTS_VERSIONS_PERSISTENCE_SIZE")
                    or ""
                ).strip()
                if persistence_size:
                    persistence["size"] = persistence_size

            disk_threshold_enabled = deployer_config.get("ONTOLOGY_HUB_ELASTICSEARCH_DISK_THRESHOLD_ENABLED")
            if disk_threshold_enabled is None:
                disk_threshold_enabled = deployer_config.get("COMPONENTS_ELASTICSEARCH_DISK_THRESHOLD_ENABLED")
            if disk_threshold_enabled is None and self._is_vm_single_topology():
                runtime = self._cluster_runtime(deployer_config)
                cluster_type = str(runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
                if cluster_type == "k3s":
                    disk_threshold_enabled = False
            if disk_threshold_enabled is not None:
                disk_threshold = overrides.setdefault("elasticsearch", {}).setdefault("diskThreshold", {})
                disk_threshold["enabled"] = self._parse_bool(disk_threshold_enabled, default=True)
                watermark_keys = {
                    "low": (
                        "ONTOLOGY_HUB_ELASTICSEARCH_DISK_WATERMARK_LOW",
                        "COMPONENTS_ELASTICSEARCH_DISK_WATERMARK_LOW",
                    ),
                    "high": (
                        "ONTOLOGY_HUB_ELASTICSEARCH_DISK_WATERMARK_HIGH",
                        "COMPONENTS_ELASTICSEARCH_DISK_WATERMARK_HIGH",
                    ),
                    "floodStage": (
                        "ONTOLOGY_HUB_ELASTICSEARCH_DISK_WATERMARK_FLOOD_STAGE",
                        "COMPONENTS_ELASTICSEARCH_DISK_WATERMARK_FLOOD_STAGE",
                    ),
                }
                for target_key, source_keys in watermark_keys.items():
                    value = ""
                    for source_key in source_keys:
                        value = str(deployer_config.get(source_key) or "").strip()
                        if value:
                            break
                    if value:
                        disk_threshold[target_key] = value

        if normalized == "ai-model-hub":
            host = self._configured_component_host(normalized, deployer_config)
            if host:
                overrides["ingress"] = self._component_ingress_override(normalized, host, deployer_config)

            connector_config = self._ai_model_hub_connector_config(
                ds_name=self._dataspace_name(),
                deployer_config=deployer_config,
            )
            if connector_config:
                overrides.setdefault("config", {})["edcConnectorConfig"] = connector_config

        if normalized == "semantic-virtualization":
            host = self._configured_component_host(normalized, deployer_config)
            if host:
                public_url = self._configured_component_public_url(normalized, deployer_config) or host
                overrides["ingress"] = self._component_ingress_override(normalized, host, deployer_config)
                overrides.setdefault("env", {})["SEMANTIC_VIRTUALIZATION_PUBLIC_URL"] = self._to_public_url(public_url)

            if self._semantic_virtualization_mapping_editor_enabled(deployer_config):
                editor_host = self._semantic_virtualization_mapping_editor_host(deployer_config)
                mapping_editor = {"enabled": True}
                editor_image_override = self._configured_component_image_override(
                    "semantic-virtualization-editor",
                    deployer_config,
                )
                if editor_image_override:
                    mapping_editor["image"] = editor_image_override
                service_type = self._semantic_virtualization_mapping_editor_service_type(deployer_config)
                service_node_port = self._semantic_virtualization_mapping_editor_service_node_port(deployer_config)
                if service_type or service_node_port:
                    mapping_editor["service"] = {}
                    if service_type:
                        mapping_editor["service"]["type"] = service_type
                    if service_node_port:
                        mapping_editor["service"]["nodePort"] = service_node_port

                host_port = self._semantic_virtualization_mapping_editor_host_port(deployer_config)
                if host_port:
                    mapping_editor["hostPort"] = {
                        "enabled": True,
                        "port": host_port,
                    }

                if editor_host and self._semantic_virtualization_mapping_editor_uses_ingress(deployer_config):
                    mapping_editor["ingress"] = self._component_ingress_override(
                        "semantic-virtualization-editor",
                        editor_host,
                        deployer_config,
                    )
                overrides["mappingEditor"] = mapping_editor

        return overrides

    def _semantic_virtualization_mapping_editor_enabled(self, deployer_config: dict) -> bool:
        config = dict(deployer_config or {})
        enabled = config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED")
        if enabled is None:
            enabled = config.get("MAPPING_EDITOR_ENABLED")
        return self._parse_bool(enabled, default=False)

    def _semantic_virtualization_mapping_editor_host(self, deployer_config: dict) -> str:
        config = dict(deployer_config or {})
        public_url = self._configured_component_public_url("semantic-virtualization-editor", config)
        if public_url:
            return strip_url_scheme(public_url).split("/", 1)[0]

        explicit = (
            config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST")
            or config.get("MAPPING_EDITOR_HOST")
            or config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL")
        )
        explicit_host = self._strip_url_scheme(explicit or "")
        if explicit_host:
            return explicit_host

        ds_domain = str(config.get("DS_DOMAIN_BASE") or "").strip()
        ds_name = self._dataspace_name()
        if ds_domain and ds_name:
            return f"semantic-virtualization-editor-{ds_name}.{ds_domain}"
        return ""

    def _semantic_virtualization_mapping_editor_host_port(self, deployer_config: dict) -> int | None:
        config = dict(deployer_config or {})
        return self._parse_positive_int(
            config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT")
            or config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_PORT")
            or config.get("MAPPING_EDITOR_HOST_PORT")
            or config.get("MAPPING_EDITOR_PUBLIC_PORT")
        )

    def _semantic_virtualization_mapping_editor_service_node_port(self, deployer_config: dict) -> int | None:
        config = dict(deployer_config or {})
        return self._parse_positive_int(
            config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NODE_PORT")
            or config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NODEPORT")
            or config.get("MAPPING_EDITOR_NODE_PORT")
            or config.get("MAPPING_EDITOR_NODEPORT")
        )

    def _semantic_virtualization_mapping_editor_service_type(self, deployer_config: dict) -> str:
        config = dict(deployer_config or {})
        service_type = str(
            config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_TYPE")
            or config.get("MAPPING_EDITOR_SERVICE_TYPE")
            or ""
        ).strip()
        if service_type:
            return service_type
        if self._semantic_virtualization_mapping_editor_service_node_port(config):
            return "NodePort"
        return ""

    def _semantic_virtualization_mapping_editor_exposure_mode(self, deployer_config: dict) -> str:
        config = dict(deployer_config or {})
        mode = str(
            config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE")
            or config.get("MAPPING_EDITOR_EXPOSURE_MODE")
            or ""
        ).strip().lower()
        if mode:
            return mode.replace("_", "-")
        if self._semantic_virtualization_mapping_editor_host_port(config):
            return "host-port"
        return "ingress"

    def _semantic_virtualization_mapping_editor_direct_public_url(self, deployer_config: dict) -> str:
        config = dict(deployer_config or {})
        host_port = self._semantic_virtualization_mapping_editor_host_port(config)
        if not host_port:
            return ""
        host = str(
            config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_HOST")
            or config.get("MAPPING_EDITOR_PUBLIC_HOST")
            or config.get("VM_COMPONENTS_IP")
            or config.get("VM_SINGLE_IP")
            or config.get("VM_EXTERNAL_IP")
            or config.get("INGRESS_EXTERNAL_IP")
            or ""
        ).strip()
        if not host:
            return ""
        return f"http://{host}:{host_port}"

    def _semantic_virtualization_mapping_editor_public_url(self, deployer_config: dict) -> str:
        config = dict(deployer_config or {})
        direct_url = self._semantic_virtualization_mapping_editor_direct_public_url(config)
        configured_url = self._configured_component_public_url("semantic-virtualization-editor", config)
        explicit_url = str(
            config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL")
            or config.get("SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL")
            or config.get("MAPPING_EDITOR_PUBLIC_URL")
            or config.get("MAPPING_EDITOR_URL")
            or ""
        ).strip()
        return (explicit_url or direct_url or configured_url).rstrip("/")

    def _semantic_virtualization_mapping_editor_uses_ingress(self, deployer_config: dict) -> bool:
        return self._semantic_virtualization_mapping_editor_exposure_mode(deployer_config) not in {
            "direct",
            "host-port",
            "hostport",
            "vm-port",
        }

    def _additional_component_public_hosts(self, normalized_component: str, deployer_config: dict) -> list[str]:
        normalized = self._normalize_component_key(normalized_component)
        if normalized == "semantic-virtualization" and self._semantic_virtualization_mapping_editor_enabled(
            deployer_config
        ):
            editor_host = self._semantic_virtualization_mapping_editor_host(deployer_config)
            return [editor_host] if editor_host else []
        return []

    def _add_additional_component_url_hosts(
        self,
        inferred_hosts: dict,
        components,
        deployer_config: dict,
    ) -> dict:
        resolved_hosts = dict(inferred_hosts or {})
        for component in components or []:
            normalized = self._normalize_component_key(component)
            if normalized == "semantic-virtualization" and self._semantic_virtualization_mapping_editor_enabled(
                deployer_config
            ):
                editor_host = self._semantic_virtualization_mapping_editor_host(deployer_config)
                if editor_host:
                    resolved_hosts["semantic-virtualization-editor"] = (
                        self._semantic_virtualization_mapping_editor_public_url(deployer_config)
                        or editor_host
                    )
        return resolved_hosts

    def _resolve_ontology_hub_self_host_alias_ip(self, deployer_config: dict) -> str:
        explicit_ip = (deployer_config.get("ONTOLOGY_HUB_SELF_HOST_ALIAS_IP") or "").strip()
        if explicit_ip:
            return explicit_ip if self._is_ip_address(explicit_ip) else ""

        namespace = (
            deployer_config.get("ONTOLOGY_HUB_SELF_HOST_ALIAS_SERVICE_NAMESPACE")
            or "ingress-nginx"
        ).strip()
        service_name = (
            deployer_config.get("ONTOLOGY_HUB_SELF_HOST_ALIAS_SERVICE_NAME")
            or "ingress-nginx-controller"
        ).strip()
        if not namespace or not service_name:
            return ""

        svc_q = shlex.quote(service_name)
        ns_q = shlex.quote(namespace)
        ip = (
            self.run_silent(
                f"kubectl get svc {svc_q} -n {ns_q} -o jsonpath='{{.spec.clusterIP}}'"
            )
            or ""
        ).strip()
        return ip if self._is_ip_address(ip) else ""

    @staticmethod
    def _is_ip_address(value: str) -> bool:
        try:
            ipaddress.ip_address((value or "").strip())
            return True
        except ValueError:
            return False

    def _write_component_values_override_file(self, chart_dir: str, normalized_component: str, deployer_config: dict):
        override_planner = getattr(self, "plan_component_override_values", None)
        if callable(override_planner):
            override_plan = override_planner(
                normalized_component,
                chart_dir=chart_dir,
                deployer_config=deployer_config,
            )
            payload = dict(override_plan.get("payload") or {})
        else:
            payload = self._component_values_override_payload(normalized_component, deployer_config)
        if not payload:
            return None

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f"{self._normalize_component_key(normalized_component)}-override-",
            suffix=".yaml",
            dir=chart_dir,
            delete=False,
        )
        try:
            yaml.safe_dump(payload, handle, sort_keys=False)
        finally:
            handle.close()
        return handle.name

    def _wait_for_pods_ready_by_selector(self, namespace: str, selector: str, timeout_seconds: int, label: str = "component") -> bool:
        namespace = (namespace or "").strip()
        selector = (selector or "").strip()
        if not namespace or not selector:
            return False

        ns_q = shlex.quote(namespace)
        sel_q = shlex.quote(selector)
        print(f"Waiting for {label} pods to be Running and Ready...")

        start = time.time()
        error_markers = (
            "ImagePullBackOff",
            "ErrImagePull",
            "CrashLoopBackOff",
            "CreateContainerConfigError",
            "RunContainerError",
        )

        while True:
            result = self.run_silent(f"kubectl get pods -n {ns_q} -l {sel_q} --no-headers")

            if result:
                all_ready = True
                for line in result.splitlines():
                    columns = line.split()
                    if len(columns) < 3:
                        continue

                    pod_name = columns[0]
                    ready = columns[1] if len(columns) > 1 else ""
                    status = columns[2]

                    if any(marker in status for marker in error_markers) or "BackOff" in status:
                        print(f"\nPod in error state: {pod_name} ({status})")
                        self.run(f"kubectl get pods -n {ns_q} -l {sel_q}", check=False)
                        self.run(f"kubectl describe pod -n {ns_q} {shlex.quote(pod_name)}", check=False)
                        return False

                    if status == "Completed":
                        continue

                    if status != "Running":
                        all_ready = False
                        break

                    if "/" in ready:
                        ready_current, ready_total = ready.split("/", 1)
                        if ready_current != ready_total:
                            all_ready = False
                            break
                    else:
                        all_ready = False
                        break

                if all_ready:
                    print(f"\n{label} pods are Running and Ready\n")
                    self.run(f"kubectl get pods -n {ns_q} -l {sel_q}", check=False)
                    return True

            if time.time() - start > timeout_seconds:
                print(f"\nTimeout waiting for {label} pods to be ready\n")
                self.run(f"kubectl get pods -n {ns_q} -l {sel_q}", check=False)
                return False

            time.sleep(2)

    def _wait_for_component_rollout(self, namespace: str, deployment_name: str, timeout_seconds: int, label: str) -> bool:
        rollout_waiter = getattr(self.infrastructure, "wait_for_deployment_rollout", None)
        if callable(rollout_waiter):
            return bool(
                rollout_waiter(
                    namespace,
                    deployment_name,
                    timeout_seconds=timeout_seconds,
                    label=label,
                )
            )

        selector = f"app.kubernetes.io/instance={deployment_name}"
        return self._wait_for_pods_ready_by_selector(
            namespace,
            selector,
            timeout_seconds=timeout_seconds,
            label=label,
        )

    def deploy_components(self, components, *, ds_name=None, namespace=None, deployer_config=None):
        return self.COMPONENTS(
            components,
            ds_name=ds_name,
            namespace=namespace,
            deployer_config=deployer_config,
        )

    def infer_component_urls(self, components, *, ds_name=None, namespace=None, deployer_config=None):
        if not components:
            return {}

        ds_name = str(ds_name or self._dataspace_name() or "").strip()
        deployer_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        namespace = self._resolve_components_namespace(
            ds_name=ds_name,
            namespace=namespace,
            deployer_config=deployer_config,
        )
        runtime_batch_resolver = getattr(self, "prepare_component_runtime_metadata", None)
        runtime_resolver = getattr(self, "resolve_component_runtime_metadata", None)

        inferred_hosts = {}
        inferred_urls = {}
        if callable(runtime_batch_resolver):
            prepared_metadata = runtime_batch_resolver(
                components,
                ds_name=ds_name,
                namespace=namespace,
                deployer_config=deployer_config,
            )
            for metadata in prepared_metadata:
                if metadata.get("excluded") or metadata.get("error"):
                    continue
                normalized = metadata.get("normalized_component")
                host = metadata.get("host")
                public_url = metadata.get("public_url") or (
                    self._configured_component_public_url(normalized, deployer_config) if normalized else ""
                )
                if normalized and public_url:
                    inferred_urls[normalized] = public_url
                elif normalized and host:
                    inferred_hosts[normalized] = host
        else:
            for component in components:
                normalized = self._normalize_component_key(component)
                if normalized in self._LEVEL6_EXCLUDED_KEYS:
                    continue
                try:
                    if callable(runtime_resolver):
                        runtime_metadata = runtime_resolver(
                            normalized,
                            ds_name=ds_name,
                            namespace=namespace,
                            deployer_config=deployer_config,
                        )
                        host = runtime_metadata.get("host")
                    else:
                        chart_dir = self._resolve_component_chart_dir(normalized)
                        values_file = self._resolve_component_values_file(chart_dir, ds_name=ds_name, namespace=namespace)
                        host = self._infer_component_hostname(normalized, values_file, deployer_config)
                except Exception:
                    host = None

                public_url = self._configured_component_public_url(normalized, deployer_config)
                if public_url:
                    inferred_urls[normalized] = public_url
                elif host:
                    inferred_hosts[normalized] = host

        inferred_hosts = self._add_additional_component_url_hosts(
            inferred_hosts,
            components,
            deployer_config,
        )
        urls = {k: self._to_public_url(v) for k, v in inferred_hosts.items() if v}
        urls.update({k: self._to_public_url(v) for k, v in inferred_urls.items() if v})
        return urls

    def COMPONENTS(self, components, *, ds_name=None, namespace=None, deployer_config=None):
        if not components:
            print("No components selected for deployment")
            return {"deployed": [], "urls": {}}

        topology = str(getattr(self.config_adapter, "topology", "local") or "local").strip().lower() or "local"
        requires_local_runtime_access = topology == "local"
        repo_dir = self.config.repo_dir()
        if not os.path.exists(repo_dir):
            self._fail("Repository not found. Run Level 2 first")

        if requires_local_runtime_access:
            if not self.infrastructure.ensure_local_infra_access():
                self._fail("Local access to PostgreSQL/Vault is not available")
        else:
            print(
                f"Skipping local PostgreSQL/Vault/MinIO port-forward checks for topology '{topology}'."
            )

        deployer_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        with self._temporary_component_kubeconfig(deployer_config):
            if not self.infrastructure.ensure_vault_unsealed():
                self._fail("Vault is not initialized or unsealed")

            reconcile_vault_state = getattr(self.infrastructure, "reconcile_vault_state_for_local_runtime", None)
            if callable(reconcile_vault_state) and not reconcile_vault_state():
                if topology == "local":
                    self._fail("Vault token could not be synchronized with the shared local runtime")
                print(
                    "Warning: Vault token synchronization with the shared local runtime failed. "
                    f"Continuing Level 5 for topology '{topology}' because component chart reconciliation "
                    "does not require the local Vault token."
                )

        ds_name = str(ds_name or self._dataspace_name() or "").strip()
        namespace = self._resolve_components_namespace(
            ds_name=ds_name,
            namespace=namespace,
            deployer_config=deployer_config,
        )
        runtime_batch_resolver = getattr(self, "prepare_component_runtime_metadata", None)
        runtime_resolver = getattr(self, "resolve_component_runtime_metadata", None)
        deployment_plan_builder = getattr(self, "prepare_component_deployment_plan", None)
        component_release_deployer = getattr(self, "deploy_component_release", None)
        runtime_execution_preparer = getattr(self, "prepare_component_runtime_execution", None)
        runtime_finalizer = getattr(self, "finalize_component_runtime", None)
        publication_verifier = getattr(self, "verify_component_publication", None)
        shared_runtime_deployer = getattr(self, "deploy_shared_component_runtime", None)

        prepared_metadata = None
        metadata_by_component = {}
        inferred_hosts = {}
        inferred_urls = {}
        if callable(runtime_batch_resolver):
            prepared_metadata = runtime_batch_resolver(
                components,
                ds_name=ds_name,
                namespace=namespace,
                deployer_config=deployer_config,
            )
            for metadata in prepared_metadata:
                normalized = metadata.get("normalized_component")
                if normalized:
                    metadata_by_component[normalized] = metadata
                if metadata.get("excluded") or metadata.get("error"):
                    continue
                host = metadata.get("host")
                public_url = metadata.get("public_url") or (
                    self._configured_component_public_url(normalized, deployer_config) if normalized else ""
                )
                if normalized and public_url:
                    inferred_urls[normalized] = public_url
                elif normalized and host:
                    inferred_hosts[normalized] = host
        else:
            for component in components:
                normalized = self._normalize_component_key(component)
                if normalized in self._LEVEL6_EXCLUDED_KEYS:
                    continue

                try:
                    if callable(runtime_resolver):
                        runtime_metadata = runtime_resolver(
                            normalized,
                            ds_name=ds_name,
                            namespace=namespace,
                            deployer_config=deployer_config,
                        )
                        host = runtime_metadata.get("host")
                    else:
                        chart_dir = self._resolve_component_chart_dir(normalized)
                        values_file = self._resolve_component_values_file(chart_dir, ds_name=ds_name, namespace=namespace)
                        host = self._infer_component_hostname(normalized, values_file, deployer_config)
                except Exception:
                    host = None

                public_url = self._configured_component_public_url(normalized, deployer_config)
                if public_url:
                    inferred_urls[normalized] = public_url
                elif host:
                    inferred_hosts[normalized] = host

        hostnames_to_sync = set(inferred_hosts.values())
        for component in components:
            normalized = self._normalize_component_key(component)
            hostnames_to_sync.update(self._additional_component_public_hosts(normalized, deployer_config))

        if hostnames_to_sync:
            print("\nComponent hostnames inferred from values:")
            for host in sorted(hostnames_to_sync):
                print(f"- {host}")

            if requires_local_runtime_access:
                desired_entries = [f"127.0.0.1 {h}" for h in sorted(hostnames_to_sync)]
                self.infrastructure.manage_hosts_entries(
                    desired_entries,
                    header_comment="# Components",
                    auto_confirm=True,
                )
            else:
                print(f"Skipping component hosts synchronization for topology '{topology}'.")

        deployment_items = []
        for component in components:
            normalized = self._normalize_component_key(component)

            if normalized in self._LEVEL6_EXCLUDED_KEYS:
                self._fail(
                    f"'{normalized}' is part of the base dataspace and must not be deployed via Level 5. "
                    "Deploy it via Level 3 (dataspace) and remove it from COMPONENTS."
                )

            if normalized in metadata_by_component and not metadata_by_component[normalized].get("error"):
                runtime_metadata = metadata_by_component[normalized]
            elif callable(runtime_resolver):
                runtime_metadata = runtime_resolver(
                    normalized,
                    ds_name=ds_name,
                    namespace=namespace,
                    deployer_config=deployer_config,
                )
            else:
                runtime_metadata = None

            if callable(deployment_plan_builder):
                deployment_plan = deployment_plan_builder(
                    normalized,
                    ds_name=ds_name,
                    namespace=namespace,
                    deployer_config=deployer_config,
                    runtime_metadata=runtime_metadata,
                )
                chart_dir = deployment_plan["chart_dir"]
                values_file = deployment_plan["values_file"]
                release_name = deployment_plan["release_name"]
                override_plan = dict(deployment_plan.get("override_plan") or {})
            else:
                if runtime_metadata:
                    chart_dir = runtime_metadata["chart_dir"]
                    values_file = runtime_metadata["values_file"]
                    release_name = runtime_metadata["release_name"]
                else:
                    chart_dir = self._resolve_component_chart_dir(normalized)
                    values_file = self._resolve_component_values_file(chart_dir, ds_name=ds_name, namespace=namespace)
                    release_name = self._resolve_component_release_name(normalized)
                override_planner = getattr(self, "plan_component_override_values", None)
                if callable(override_planner):
                    override_plan = dict(
                        override_planner(
                            normalized,
                            chart_dir=chart_dir,
                            deployer_config=deployer_config,
                        )
                        or {}
                    )
                else:
                    legacy_payload = self._component_values_override_payload(normalized, deployer_config)
                    override_plan = {
                        "normalized_component": normalized,
                        "chart_dir": chart_dir,
                        "payload": legacy_payload,
                        "has_override": bool(legacy_payload),
                        "filename_prefix": f"{normalized}-override-" if legacy_payload else None,
                    }
            current_deployment_plan = {
                "component": component,
                "normalized_component": normalized,
                "chart_dir": chart_dir,
                "values_file": values_file,
                "host": runtime_metadata.get("host") if runtime_metadata else None,
                "release_name": release_name,
                "override_plan": override_plan,
            }
            current_public_url = (
                runtime_metadata.get("public_url")
                if runtime_metadata
                else self._configured_component_public_url(normalized, deployer_config)
            )
            if current_public_url:
                current_deployment_plan["public_url"] = current_public_url

            deployment_items.append(
                {
                    "component": component,
                    "normalized": normalized,
                    "chart_dir": chart_dir,
                    "values_file": values_file,
                    "release_name": release_name,
                    "override_plan": override_plan,
                    "deployment_plan": current_deployment_plan,
                }
            )

        deployed = []
        with self._temporary_component_kubeconfig(deployer_config):
            prepared_executions = {}
            for item in deployment_items:
                normalized = item["normalized"]
                release_name = item["release_name"]
                values_file = item["values_file"]
                current_deployment_plan = item["deployment_plan"]
                if callable(runtime_execution_preparer):
                    execution = runtime_execution_preparer(
                        normalized,
                        deployment_plan=current_deployment_plan,
                        namespace=namespace,
                        deployer_config=deployer_config,
                    )
                else:
                    built_local_image = False
                    try:
                        built_local_image = self._maybe_prepare_level6_local_image(
                            normalized,
                            values_file,
                            deployer_config,
                        )
                    except Exception as exc:
                        self._fail(
                            f"Error preparing local images for component '{normalized}'",
                            root_cause=str(exc),
                        )
                    execution = {
                        "component": normalized,
                        "release_name": release_name,
                        "namespace": namespace,
                        "deployer_config": deployer_config,
                        "built_local_image": built_local_image,
                    }
                prepared_executions[normalized] = execution

            self._cleanup_legacy_component_releases(
                components,
                active_namespace=namespace,
                ds_name=ds_name,
                deployer_config=deployer_config,
            )
            self._cleanup_components(components, namespace)
            self._cleanup_vm_distributed_legacy_public_path_ingresses(
                deployment_items,
                namespace=namespace,
                deployer_config=deployer_config,
            )

            for item in deployment_items:
                component = item["component"]
                normalized = item["normalized"]
                chart_dir = item["chart_dir"]
                values_file = item["values_file"]
                release_name = item["release_name"]
                override_plan = item["override_plan"]
                current_deployment_plan = item["deployment_plan"]
                execution = prepared_executions.get(normalized) or {}
                built_local_image = bool(execution.get("built_local_image"))

                if callable(shared_runtime_deployer):
                    shared_runtime_result = shared_runtime_deployer(
                        normalized,
                        deployment_plan=current_deployment_plan,
                        namespace=namespace,
                        deployer_config=deployer_config,
                        prepared_execution=execution,
                    )
                    if shared_runtime_result is not None:
                        deployed.append(normalized)
                        continue

                if callable(component_release_deployer):
                    component_release_deployer(
                        normalized,
                        deployment_plan=current_deployment_plan,
                        namespace=namespace,
                        deployer_config=deployer_config,
                    )
                else:
                    override_values_file = None
                    print(f"\nDeploying component: {normalized}")
                    print(f"  Chart: {chart_dir}")
                    print(f"  Values: {os.path.basename(values_file)}")
                    print(f"  Release: {release_name}")
                    print(f"  Namespace: {namespace}")
                    try:
                        if override_plan.get("has_override"):
                            override_values_file = self._write_component_values_override_file(
                                chart_dir,
                                normalized,
                                deployer_config,
                            )
                        else:
                            override_values_file = None
                        values_files = [os.path.basename(values_file)]
                        if override_values_file:
                            values_files.append(override_values_file)
                            print(f"  Override values: {os.path.basename(override_values_file)}")

                        if not self.infrastructure.deploy_helm_release(
                            release_name,
                            namespace,
                            values_files,
                            cwd=chart_dir,
                        ):
                            self._fail(f"Error deploying component '{normalized}'")
                    finally:
                        if override_values_file and os.path.exists(override_values_file):
                            os.unlink(override_values_file)

                if callable(runtime_finalizer):
                    runtime_finalizer(
                        normalized,
                        release_name=release_name,
                        namespace=namespace,
                        built_local_image=built_local_image,
                        deployer_config=deployer_config,
                    )
                else:
                    restart_reason = ""
                    if built_local_image:
                        restart_reason = "local image"
                    elif override_plan.get("has_override"):
                        restart_reason = "configuration overrides"

                    if restart_reason:
                        print(f"Restarting deployment/{release_name} to pick up {restart_reason}...\n")
                        self.run(
                            f"kubectl rollout restart deployment/{release_name} -n {namespace}",
                            check=False,
                        )

                        timeout_seconds = 1800 if normalized == "ontology-hub" else 300
                        if not self._wait_for_component_rollout(
                            namespace,
                            release_name,
                            timeout_seconds=timeout_seconds,
                            label=normalized,
                        ):
                            self._fail(f"Timeout waiting for component '{normalized}' deployment rollout")

                if callable(publication_verifier):
                    publication_verifier(
                        normalized,
                        deployment_plan=current_deployment_plan,
                        namespace=namespace,
                    )

                deployed.append(normalized)

        inferred_hosts = self._add_additional_component_url_hosts(
            inferred_hosts,
            components,
            deployer_config,
        )
        urls = {k: self._to_public_url(v) for k, v in inferred_hosts.items() if v}
        urls.update({k: self._to_public_url(v) for k, v in inferred_urls.items() if v})
        return {"deployed": deployed, "urls": urls}

    def describe(self) -> str:
        return "INESDataComponentsAdapter deploys optional components via Helm charts."
