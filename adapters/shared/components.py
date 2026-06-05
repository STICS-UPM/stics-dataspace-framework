"""Shared Level 5 component facade reused by multiple adapters."""

from contextlib import contextmanager
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import requests

from adapters.inesdata.components import INESDataComponentsAdapter
from deployers.shared.lib.components import (
    configured_component_public_path,
    configured_component_public_url,
    infer_component_hostname,
    resolve_component_release_name,
    summarize_components_for_adapter,
)


class SharedComponentsAdapter(INESDataComponentsAdapter):
    """Neutral facade for Level 5 component workflows.

    For now this preserves the existing stable INESData implementation while
    exposing a shared entry point that can be reused by other adapters.
    """

    def __init__(self, *args, active_adapter="inesdata", **kwargs):
        super().__init__(*args, **kwargs)
        self.active_adapter = str(active_adapter or "inesdata").strip().lower() or "inesdata"

    def configured_components_summary(self):
        config = self.config_adapter.load_deployer_config() or {}
        return summarize_components_for_adapter(config, self.active_adapter)

    def resolve_component_runtime_metadata(
        self,
        component,
        *,
        ds_name=None,
        namespace=None,
        deployer_config=None,
    ):
        normalized = self._normalize_component_key(component)
        resolved_ds_name = str(ds_name or self._dataspace_name() or "").strip()
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        resolved_namespace = self._resolve_components_namespace(
            ds_name=resolved_ds_name,
            namespace=namespace,
            deployer_config=resolved_config,
        )

        chart_dir = self._resolve_component_chart_dir(normalized)
        values_file = self._resolve_component_values_file(
            chart_dir,
            ds_name=resolved_ds_name,
            namespace=resolved_namespace,
        )
        public_url = configured_component_public_url(
            normalized,
            resolved_config,
            dataspace_name=resolved_ds_name,
        )
        metadata_payload = {
            "component": component,
            "normalized_component": normalized,
            "dataspace_name": resolved_ds_name,
            "namespace": resolved_namespace,
            "chart_dir": chart_dir,
            "values_file": values_file,
            "host": self._infer_component_hostname_for_dataspace(
                normalized,
                values_file,
                resolved_config,
                dataspace_name=resolved_ds_name,
            ),
            "release_name": resolve_component_release_name(
                normalized,
                dataspace_name=resolved_ds_name,
            ),
        }
        if public_url:
            metadata_payload["public_url"] = public_url
        return metadata_payload

    def _infer_component_hostname_for_dataspace(
        self,
        normalized_component,
        values_file,
        deployer_config,
        *,
        dataspace_name,
    ):
        try:
            values = self._safe_load_yaml_file(values_file)
        except Exception:
            legacy_infer = getattr(self, "_infer_component_hostname", None)
            if callable(legacy_infer):
                return legacy_infer(normalized_component, values_file, deployer_config)
            return None

        return infer_component_hostname(
            normalized_component,
            values,
            deployer_config,
            dataspace_name=dataspace_name,
        )

    def prepare_component_runtime_metadata(
        self,
        components,
        *,
        ds_name=None,
        namespace=None,
        deployer_config=None,
    ):
        prepared = []
        for component in list(components or []):
            normalized = self._normalize_component_key(component)
            entry = {
                "component": component,
                "normalized_component": normalized,
                "excluded": normalized in getattr(self, "_LEVEL6_EXCLUDED_KEYS", set()),
            }
            if entry["excluded"]:
                prepared.append(entry)
                continue
            try:
                entry.update(
                    self.resolve_component_runtime_metadata(
                        normalized,
                        ds_name=ds_name,
                        namespace=namespace,
                        deployer_config=deployer_config,
                    )
                )
                entry["error"] = None
            except Exception as exc:  # pragma: no cover - defensive integration path
                entry["error"] = str(exc)
            prepared.append(entry)
        return prepared

    def plan_component_override_values(
        self,
        component,
        *,
        chart_dir=None,
        deployer_config=None,
    ):
        normalized = self._normalize_component_key(component)
        resolved_chart_dir = str(chart_dir or "").strip()
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        payload = self._component_values_override_payload(normalized, resolved_config)
        if not payload:
            return {
                "normalized_component": normalized,
                "chart_dir": resolved_chart_dir,
                "payload": {},
                "has_override": False,
                "filename_prefix": None,
            }
        return {
            "normalized_component": normalized,
            "chart_dir": resolved_chart_dir,
            "payload": payload,
            "has_override": True,
            "filename_prefix": f"{normalized}-override-",
        }

    def prepare_component_deployment_plan(
        self,
        component,
        *,
        ds_name=None,
        namespace=None,
        deployer_config=None,
        runtime_metadata=None,
    ):
        normalized = self._normalize_component_key(component)
        metadata = dict(runtime_metadata or {})
        if not metadata:
            metadata = self.resolve_component_runtime_metadata(
                normalized,
                ds_name=ds_name,
                namespace=namespace,
                deployer_config=deployer_config,
            )

        override_plan = self.plan_component_override_values(
            normalized,
            chart_dir=metadata.get("chart_dir"),
            deployer_config=deployer_config,
        )
        plan = {
            "component": component,
            "normalized_component": normalized,
            "chart_dir": metadata["chart_dir"],
            "values_file": metadata["values_file"],
            "host": metadata.get("host"),
            "release_name": metadata["release_name"],
            "override_plan": override_plan,
        }
        if metadata.get("public_url"):
            plan["public_url"] = metadata.get("public_url")
        return plan

    def deploy_component_release(
        self,
        component,
        *,
        deployment_plan,
        namespace,
        deployer_config=None,
    ):
        normalized = self._normalize_component_key(component)
        plan = dict(deployment_plan or {})
        chart_dir = plan["chart_dir"]
        values_file = plan["values_file"]
        release_name = plan["release_name"]
        override_plan = dict(plan.get("override_plan") or {})
        resolved_namespace = str(namespace or "").strip()
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})

        print(f"\nDeploying component: {normalized}")
        print(f"  Chart: {chart_dir}")
        print(f"  Values: {os.path.basename(values_file)}")
        print(f"  Release: {release_name}")
        print(f"  Namespace: {resolved_namespace}")

        override_values_file = None
        try:
            if override_plan.get("has_override"):
                override_values_file = self._write_component_values_override_file(
                    chart_dir,
                    normalized,
                    resolved_config,
                )
            values_files = [os.path.basename(values_file)]
            if override_values_file:
                values_files.append(override_values_file)
                print(f"  Override values: {os.path.basename(override_values_file)}")

            if not self.infrastructure.deploy_helm_release(
                release_name,
                resolved_namespace,
                values_files,
                cwd=chart_dir,
            ):
                self._fail(f"Error deploying component '{normalized}'")
        finally:
            if override_values_file and os.path.exists(override_values_file):
                os.unlink(override_values_file)

        return {
            "component": normalized,
            "release_name": release_name,
            "namespace": resolved_namespace,
            "values_files": values_files,
        }

    def prepare_component_runtime_execution(
        self,
        component,
        *,
        deployment_plan,
        namespace,
        deployer_config=None,
    ):
        normalized = self._normalize_component_key(component)
        plan = dict(deployment_plan or {})
        resolved_release_name = str(plan.get("release_name") or "").strip()
        resolved_namespace = str(namespace or "").strip()
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        values_file = plan["values_file"]

        built_local_image = False
        try:
            built_local_image = self._maybe_prepare_level6_local_image(
                normalized,
                values_file,
                resolved_config,
            )
        except Exception as exc:
            self._fail(
                f"Error preparing local images for component '{normalized}'",
                root_cause=str(exc),
            )

        return {
            "component": normalized,
            "release_name": resolved_release_name,
            "namespace": resolved_namespace,
            "deployer_config": resolved_config,
            "built_local_image": built_local_image,
        }

    def finalize_component_runtime(
        self,
        component,
        *,
        release_name,
        namespace,
        built_local_image=False,
        deployer_config=None,
    ):
        normalized = self._normalize_component_key(component)
        resolved_release_name = str(release_name or "").strip()
        resolved_namespace = str(namespace or "").strip()
        resolved_config = dict(deployer_config or {})
        rollout_targets = self._component_runtime_rollout_targets(
            normalized,
            resolved_release_name,
            resolved_config,
        )

        if normalized == "ai-model-hub" and not built_local_image:
            built_local_image = self._ensure_vm_single_ai_model_hub_image_before_rollout(
                resolved_release_name,
                resolved_namespace,
                resolved_config,
            )

        if normalized in {"ontology-hub", "ai-model-hub", "semantic-virtualization"}:
            rendered_images_imported = self._ensure_vm_single_local_images_before_rollout(
                rollout_targets,
                resolved_namespace,
                resolved_config,
            )
            built_local_image = bool(built_local_image or rendered_images_imported)

        if built_local_image:
            for deployment_name, _label in rollout_targets:
                print(f"Restarting deployment/{deployment_name} to pick up local image...\n")
                self.run(
                    f"kubectl rollout restart deployment/{deployment_name} -n {resolved_namespace}",
                    check=False,
                )

        waited_for_rollout = False
        if normalized in {"ontology-hub", "ai-model-hub", "semantic-virtualization"}:
            if not self._wait_for_component_rollout(
                resolved_namespace,
                rollout_targets[0][0],
                timeout_seconds=self._component_runtime_rollout_timeout_seconds(normalized),
                label=rollout_targets[0][1],
            ):
                self._fail(f"Timeout waiting for component '{rollout_targets[0][1]}' deployment rollout")
            waited_for_rollout = True
            for deployment_name, label in rollout_targets[1:]:
                if not self._wait_for_component_rollout(
                    resolved_namespace,
                    deployment_name,
                    timeout_seconds=self._component_runtime_rollout_timeout_seconds(label),
                    label=label,
                ):
                    self._fail(f"Timeout waiting for component '{label}' deployment rollout")

        model_server = None
        if normalized == "ai-model-hub":
            if deployer_config is not None:
                resolved_config = dict(deployer_config or {})
            else:
                try:
                    resolved_config = dict(self.config_adapter.load_deployer_config() or {})
                except Exception:
                    resolved_config = {}
            if resolved_config or deployer_config is not None:
                model_server = self._ensure_ai_model_hub_model_server(
                    resolved_namespace,
                    resolved_config,
                )

        result = {
            "component": normalized,
            "release_name": resolved_release_name,
            "namespace": resolved_namespace,
            "built_local_image": bool(built_local_image),
            "waited_for_rollout": waited_for_rollout,
        }
        public_root_aliases = []
        if normalized == "ontology-hub":
            if deployer_config is not None:
                resolved_config = dict(deployer_config or {})
            else:
                try:
                    resolved_config = dict(self.config_adapter.load_deployer_config() or {})
                except Exception:
                    resolved_config = {}
            public_root_aliases = self._sync_ontology_hub_public_root_alias_ingress(
                resolved_release_name,
                resolved_namespace,
                resolved_config,
            )
        if public_root_aliases:
            result["public_root_aliases"] = public_root_aliases
        if model_server:
            result["model_server"] = model_server
        return result

    def _ensure_vm_single_local_images_before_rollout(self, rollout_targets, namespace, deployer_config):
        if not self._is_vm_single_topology():
            return False

        resolved_config = dict(deployer_config or {})
        runtime = self._cluster_runtime(resolved_config)
        cluster_type = str(runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
        if cluster_type != "k3s":
            return False

        resolved_namespace = str(namespace or "").strip()
        if not resolved_namespace:
            return False

        images_to_import = []
        image_labels = {}
        for deployment_name, label in list(rollout_targets or []):
            deployment = str(deployment_name or "").strip()
            if not deployment:
                continue
            deployment_q = shlex.quote(deployment)
            namespace_q = shlex.quote(resolved_namespace)
            raw_images = self.run_silent(
                f"kubectl get deployment {deployment_q} -n {namespace_q} "
                "-o jsonpath='{range .spec.template.spec.containers[*]}{.image}{\"\\n\"}{end}'"
            )
            for raw_image in str(raw_images or "").splitlines():
                image_ref = raw_image.strip().strip("'").strip('"')
                if not image_ref or not image_ref.lower().endswith(":local"):
                    continue
                if image_ref not in images_to_import:
                    images_to_import.append(image_ref)
                    image_labels[image_ref] = str(label or "").strip()

        if not images_to_import:
            return False

        print(
            "Ensuring vm-single local component image(s) are available in k3s before rollout: "
            f"{', '.join(images_to_import)}"
        )
        for image_ref in images_to_import:
            self._ensure_k3s_local_image_import_supported(image_ref, resolved_config)
            if not self._host_has_image(image_ref):
                self._build_component_local_image_for_rollout(
                    image_labels.get(image_ref, ""),
                    image_ref,
                    resolved_config,
                )

        profile = (
            resolved_config.get("MINIKUBE_PROFILE")
            or getattr(self.config, "MINIKUBE_PROFILE", "minikube")
            or "minikube"
        ).strip() or "minikube"
        self._load_images_into_cluster_runtime(
            "k3s",
            profile,
            images_to_import,
            resolved_config,
        )
        return True

    def _build_component_local_image_for_rollout(self, component_label, image_ref, deployer_config):
        label = self._normalize_component_key(component_label)
        if label == "ontology-hub":
            self._build_ontology_hub_image_on_host(image_ref, deployer_config)
            return
        if label == "ai-model-hub":
            self._build_ai_model_hub_image_on_host(image_ref, deployer_config)
            return
        if label == "semantic-virtualization":
            self._build_semantic_virtualization_image_on_host(image_ref, deployer_config)
            return
        if label == "semantic-virtualization-editor":
            self._build_mapping_editor_image_on_host(image_ref, deployer_config)
            return

        self._fail(
            "No local image build recipe is available for component rollout",
            root_cause=f"{component_label}: {image_ref}",
        )

    def _ensure_vm_single_ai_model_hub_image_before_rollout(self, release_name, namespace, deployer_config):
        if not self._is_vm_single_topology():
            return False

        resolved_config = dict(deployer_config or {})
        runtime = self._cluster_runtime(resolved_config)
        cluster_type = str(runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
        if cluster_type != "k3s":
            return False

        release_q = shlex.quote(str(release_name or "").strip())
        namespace_q = shlex.quote(str(namespace or "").strip())
        image_ref = self.run_silent(
            f"kubectl get deployment {release_q} -n {namespace_q} "
            "-o jsonpath='{.spec.template.spec.containers[0].image}'"
        )
        image_ref = str(image_ref or "").strip().strip("'").strip('"')
        if not image_ref or not image_ref.lower().endswith(":local"):
            return False

        print(
            "Ensuring vm-single AI Model Hub local image is available in k3s before rollout: "
            f"{image_ref}"
        )
        profile = (
            resolved_config.get("MINIKUBE_PROFILE")
            or getattr(self.config, "MINIKUBE_PROFILE", "minikube")
            or "minikube"
        ).strip() or "minikube"
        self._ensure_k3s_local_image_import_supported(image_ref, resolved_config)
        self._build_ai_model_hub_image_on_host(image_ref, resolved_config)
        self._load_image_into_cluster_runtime(cluster_type, profile, image_ref, resolved_config)
        return True

    def _component_runtime_rollout_targets(self, normalized_component, release_name, deployer_config=None):
        normalized = self._normalize_component_key(normalized_component)
        resolved_release_name = str(release_name or "").strip()
        targets = [(resolved_release_name, normalized)]

        if normalized == "semantic-virtualization" and self._semantic_virtualization_mapping_editor_enabled(
            dict(deployer_config or {})
        ):
            targets.append((f"{resolved_release_name}-editor", "semantic-virtualization-editor"))

        return targets

    @staticmethod
    def _component_runtime_rollout_timeout_seconds(normalized_component):
        normalized = str(normalized_component or "").strip()
        if normalized == "ontology-hub":
            return 1800
        if normalized == "ai-model-hub":
            return 900
        if normalized in {"semantic-virtualization", "semantic-virtualization-editor"}:
            return 900
        return 300

    def _vm_distributed_role_kubeconfig(self, role, deployer_config=None):
        runtime = self._cluster_runtime(deployer_config)
        if str(runtime.get("cluster_type") or "").strip().lower() != "k3s":
            return ""
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
    def _temporary_component_kubeconfig(self, deployer_config=None):
        with super()._temporary_component_kubeconfig(deployer_config):
            yield

    def _ai_model_hub_model_server_enabled(self, deployer_config):
        config = dict(deployer_config or {})
        flag = config.get("AI_MODEL_HUB_MODEL_SERVER_ENABLED")
        if flag is None:
            flag = config.get("LEVEL5_AI_MODEL_HUB_MODEL_SERVER_ENABLED")
        return self._parse_bool(flag, default=True)

    @staticmethod
    def _normalize_ai_model_hub_model_server_mode(mode):
        normalized = str(mode or "").strip().lower().replace("_", "-")
        aliases = {
            "": "mock",
            "fixture": "mock",
            "deterministic": "mock",
            "real": "use-cases",
            "usecases": "use-cases",
            "use-cases": "use-cases",
            "combined-real": "combined",
            "real-combined": "combined",
            "remote": "external",
        }
        return aliases.get(normalized, normalized)

    def _ai_model_hub_model_server_mode(self, deployer_config):
        config = dict(deployer_config or {})
        raw_mode = (
            config.get("AI_MODEL_HUB_MODEL_SERVER_MODE")
            or config.get("LEVEL5_AI_MODEL_HUB_MODEL_SERVER_MODE")
            or config.get("MODEL_SERVER_MODE")
            or "mock"
        )
        mode = self._normalize_ai_model_hub_model_server_mode(raw_mode)
        allowed_modes = {"mock", "use-cases", "combined", "external"}
        if mode not in allowed_modes:
            self._fail(
                "Invalid AI Model Hub model-server mode",
                root_cause=(
                    f"Unsupported mode '{raw_mode}'. "
                    "Allowed values are: mock, use-cases, combined, external."
                ),
            )
        return mode

    def _project_root_dir(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return project_root

    def _resolve_project_path(self, value):
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        expanded = os.path.expanduser(raw_value)
        if os.path.isabs(expanded):
            return expanded
        return os.path.abspath(os.path.join(self._project_root_dir(), expanded))

    def _ai_model_hub_model_server_source_dir(self, deployer_config=None):
        config = dict(deployer_config or {})
        explicit = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR")
            or config.get("MODEL_SERVER_SOURCE_DIR")
            or ""
        ).strip()
        if explicit:
            source_dir = self._resolve_project_path(explicit)
            repository_url = self._ai_model_hub_model_server_source_repository(config)
            if repository_url:
                return self._ensure_ai_model_hub_model_server_source_checkout(
                    source_dir,
                    repository_url,
                    config,
                )
            return source_dir

        mode = self._ai_model_hub_model_server_mode(config)
        if mode in {"use-cases", "combined"}:
            real_source = str(
                config.get("AI_MODEL_HUB_REAL_MODEL_SERVER_SOURCE_DIR")
                or config.get("AI_MODEL_HUB_USE_CASE_MODEL_SERVER_SOURCE_DIR")
                or config.get("MODEL_SERVER_REAL_SOURCE_DIR")
                or ""
            ).strip()
            if real_source:
                source_dir = self._resolve_project_path(real_source)
                repository_url = self._ai_model_hub_model_server_source_repository(config)
                if repository_url:
                    return self._ensure_ai_model_hub_model_server_source_checkout(
                        source_dir,
                        repository_url,
                        config,
                    )
                return source_dir
            repository_url = self._ai_model_hub_model_server_source_repository(config)
            if repository_url:
                source_dir = os.path.join(
                    self._project_root_dir(),
                    "adapters",
                    "inesdata",
                    "sources",
                    "AIModelHub-Use-Cases",
                )
                return self._ensure_ai_model_hub_model_server_source_checkout(
                    source_dir,
                    repository_url,
                    config,
                )
            self._fail(
                "AI Model Hub real model-server source is not configured",
                root_cause=(
                    "Set AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR or "
                    "AI_MODEL_HUB_REAL_MODEL_SERVER_SOURCE_DIR for use-cases/combined mode. "
                    "Alternatively set AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY."
                ),
            )

        return os.path.join(self._project_root_dir(), "adapters", "inesdata", "sources", "model-server")

    @staticmethod
    def _ai_model_hub_model_server_source_repository(deployer_config):
        return str(
            (deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY")
            or (deployer_config or {}).get("AI_MODEL_HUB_USE_CASE_MODEL_SERVER_REPOSITORY")
            or (deployer_config or {}).get("AI_MODEL_HUB_REAL_MODEL_SERVER_REPOSITORY")
            or (deployer_config or {}).get("MODEL_SERVER_SOURCE_REPOSITORY")
            or ""
        ).strip()

    @staticmethod
    def _ai_model_hub_model_server_source_ref(deployer_config):
        return str(
            (deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF")
            or (deployer_config or {}).get("MODEL_SERVER_SOURCE_REF")
            or ""
        ).strip()

    def _ensure_ai_model_hub_model_server_source_checkout(self, source_dir, repository_url, deployer_config):
        resolved_source_dir = os.path.abspath(os.path.expanduser(str(source_dir or "").strip()))
        resolved_repository_url = str(repository_url or "").strip()
        if not resolved_source_dir or not resolved_repository_url:
            return resolved_source_dir

        should_clone = not os.path.isdir(resolved_source_dir)
        if not should_clone:
            try:
                entries = [entry for entry in os.listdir(resolved_source_dir) if entry not in {".gitkeep"}]
            except OSError:
                entries = []
            should_clone = len(entries) == 0

        if should_clone:
            os.makedirs(os.path.dirname(resolved_source_dir), exist_ok=True)
            print(
                "Cloning AI Model Hub model-server source repository into "
                f"{resolved_source_dir}"
            )
            try:
                subprocess.run(
                    ["git", "clone", resolved_repository_url, resolved_source_dir],
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                self._fail(
                    "Could not clone AI Model Hub model-server source repository",
                    root_cause=f"{resolved_repository_url}: {exc}",
                )

        source_ref = self._ai_model_hub_model_server_source_ref(deployer_config)
        if source_ref:
            try:
                subprocess.run(
                    ["git", "-C", resolved_source_dir, "checkout", source_ref],
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                self._fail(
                    "Could not checkout AI Model Hub model-server source ref",
                    root_cause=f"{source_ref}: {exc}",
                )

        return resolved_source_dir

    def _ai_model_hub_model_server_image_ref(self, deployer_config):
        return str((deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_IMAGE") or "model-server:latest").strip()

    def _ai_model_hub_model_server_manifest_path(self, source_dir, deployer_config):
        config = dict(deployer_config or {})
        explicit = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH")
            or config.get("MODEL_SERVER_MANIFEST_PATH")
            or ""
        ).strip()
        if explicit:
            return self._resolve_project_path(explicit)
        return os.path.join(source_dir, "k8s-model-server.yaml")

    def _ai_model_hub_model_server_explicit_manifest_path(self, deployer_config):
        config = dict(deployer_config or {})
        explicit = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH")
            or config.get("MODEL_SERVER_MANIFEST_PATH")
            or ""
        ).strip()
        return self._resolve_project_path(explicit) if explicit else ""

    def _ai_model_hub_model_server_readiness_path(self, deployer_config):
        config = dict(deployer_config or {})
        explicit = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH")
            or config.get("MODEL_SERVER_READINESS_PATH")
            or ""
        ).strip()
        if explicit:
            return explicit if explicit.startswith("/") else f"/{explicit}"
        mode = self._ai_model_hub_model_server_mode(config)
        if mode in {"use-cases", "combined"}:
            return "/models"
        return "/api/v1/health"

    def _ai_model_hub_model_server_service_url(self, namespace):
        resolved_namespace = str(namespace or "").strip() or "components"
        return f"http://model-server.{resolved_namespace}.svc.cluster.local:8080"

    @staticmethod
    def _ai_model_hub_model_server_container_port(deployer_config):
        raw_value = str(
            (deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT")
            or (deployer_config or {}).get("MODEL_SERVER_CONTAINER_PORT")
            or "8080"
        ).strip()
        try:
            port = int(raw_value)
        except ValueError:
            port = 8080
        return port if 1 <= port <= 65535 else 8080

    @staticmethod
    def _ai_model_hub_model_server_docker_base_image(deployer_config):
        return str(
            (deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE")
            or (deployer_config or {}).get("MODEL_SERVER_DOCKER_BASE_IMAGE")
            or "python:3.10-slim"
        ).strip()

    @staticmethod
    def _ai_model_hub_model_server_uvicorn_app(deployer_config, mode):
        explicit = str(
            (deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP")
            or (deployer_config or {}).get("MODEL_SERVER_UVICORN_APP")
            or ""
        ).strip()
        if explicit:
            return explicit
        return "combined_model_server.server:app" if mode == "combined" else "src.server:app"

    @staticmethod
    def _ai_model_hub_model_server_image_pull_policy(image_ref, deployer_config):
        explicit = str(
            (deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY")
            or (deployer_config or {}).get("MODEL_SERVER_IMAGE_PULL_POLICY")
            or ""
        ).strip()
        if explicit in {"Always", "IfNotPresent", "Never"}:
            return explicit
        normalized_image = str(image_ref or "").strip().lower()
        if normalized_image.endswith(":local") or normalized_image.endswith(":latest") or normalized_image.startswith("local/"):
            return "Never"
        return "IfNotPresent"

    @staticmethod
    def _ai_model_hub_model_server_copy_excludes(deployer_config):
        raw_value = str(
            (deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES")
            or (deployer_config or {}).get("MODEL_SERVER_COPY_EXCLUDES")
            or ""
        ).strip()
        excludes = [
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".venv",
            "venv",
            "node_modules",
        ]
        for token in raw_value.replace(";", ",").split(","):
            value = token.strip()
            if value and value not in excludes:
                excludes.append(value)
        return excludes

    def _validate_ai_model_hub_use_case_source(self, source_dir):
        required_paths = [
            os.path.join(source_dir, "requirements.txt"),
            os.path.join(source_dir, "src", "server.py"),
        ]
        missing = [path for path in required_paths if not os.path.isfile(path)]
        if missing:
            self._fail(
                "AI Model Hub use-case model-server source is not usable",
                root_cause=(
                    "Missing required file(s): "
                    + ", ".join(missing)
                    + ". The source directory must contain the real FastAPI server repository."
                ),
            )

    @staticmethod
    def _ai_model_hub_combined_model_server_source():
        return '''"""Combined use-case and deterministic mock model server."""

from __future__ import annotations

import hashlib
import importlib
import os
import sys
from typing import Any, Dict, Iterable, List

from fastapi import Request


DEFAULT_MOCK_HTTP_COUNT = 10
MAX_MOCK_HTTP_COUNT = 15

MOCK_MODELS: List[Dict[str, str]] = [
    {"slug": "chest-xray", "endpoint": "/api/v1/vision/chest-xray", "group": "vision"},
    {"slug": "pneumonia", "endpoint": "/api/v1/vision/pneumonia", "group": "vision"},
    {"slug": "covid19", "endpoint": "/api/v1/vision/covid19", "group": "vision"},
    {"slug": "lung-nodule", "endpoint": "/api/v1/vision/lung-nodule", "group": "vision"},
    {"slug": "tuberculosis", "endpoint": "/api/v1/vision/tuberculosis", "group": "vision"},
    {"slug": "ecommerce-sentiment", "endpoint": "/api/v1/nlp/ecommerce-sentiment", "group": "nlp"},
    {"slug": "twitter-sentiment", "endpoint": "/api/v1/nlp/twitter-sentiment", "group": "nlp"},
    {"slug": "product-review", "endpoint": "/api/v1/nlp/product-review", "group": "nlp"},
    {"slug": "customer-feedback", "endpoint": "/api/v1/nlp/customer-feedback", "group": "nlp"},
    {"slug": "social-media-sentiment", "endpoint": "/api/v1/nlp/social-media", "group": "nlp"},
    {"slug": "bmi", "endpoint": "/api/v1/health/bmi", "group": "health"},
    {"slug": "body-fat", "endpoint": "/api/v1/health/body-fat", "group": "health"},
    {"slug": "bmr", "endpoint": "/api/v1/health/bmr", "group": "health"},
    {"slug": "ideal-weight", "endpoint": "/api/v1/health/ideal-weight", "group": "health"},
    {"slug": "health-risk", "endpoint": "/api/v1/health/risk-assessment", "group": "health"},
]


def _use_case_server_dir() -> str:
    configured_dir = os.environ.get("USE_CASE_SERVER_DIR") or os.environ.get("USE_CASE_MODEL_SERVER_DIR")
    return os.path.abspath(os.path.expanduser(configured_dir or "/app/use_cases"))


def _mock_http_count() -> int:
    raw_value = os.environ.get("COMBINED_MOCK_HTTP_COUNT", str(DEFAULT_MOCK_HTTP_COUNT))
    try:
        count = int(raw_value)
    except ValueError:
        count = DEFAULT_MOCK_HTTP_COUNT
    return max(1, min(count, MAX_MOCK_HTTP_COUNT))


def _load_use_case_app():
    server_dir = _use_case_server_dir()
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    try:
        module = importlib.import_module("src.server")
    except Exception as exc:
        raise RuntimeError(
            "Unable to import AIModelHub-Use-Cases src.server. "
            f"Check USE_CASE_SERVER_DIR={server_dir} and the prepared model artifacts."
        ) from exc
    return module.app


app = _load_use_case_app()


def _records_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item if isinstance(item, dict) else {"value": item} for item in payload]
    if isinstance(payload, dict):
        return [payload]
    return [{"value": payload}]


def _score(slug: str, record: Dict[str, Any]) -> float:
    digest = hashlib.sha256(f"{slug}:{record}".encode("utf-8")).hexdigest()
    return round(0.70 + (int(digest[:4], 16) % 2500) / 10000, 4)


def _numeric(record: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(record.get(key, default))
    except (TypeError, ValueError):
        return default


def _vision_prediction(slug: str, record: Dict[str, Any]) -> Dict[str, Any]:
    labels = {
        "chest-xray": "no_acute_finding",
        "pneumonia": "pneumonia_not_detected",
        "covid19": "covid19_not_detected",
        "lung-nodule": "low_nodule_risk",
        "tuberculosis": "tuberculosis_not_detected",
    }
    return {
        "label": labels.get(slug, "normal"),
        "confidence": _score(slug, record),
        "explanation": "deterministic mock image classification",
    }


def _nlp_prediction(slug: str, record: Dict[str, Any]) -> Dict[str, Any]:
    text = str(record.get("text", record.get("message", ""))).lower()
    positive_terms = ("good", "great", "excellent", "useful", "bueno", "excelente", "positivo")
    negative_terms = ("bad", "poor", "terrible", "malo", "negativo", "problema")
    if any(term in text for term in positive_terms):
        label = "positive"
    elif any(term in text for term in negative_terms):
        label = "negative"
    else:
        label = "neutral"
    return {
        "label": label,
        "confidence": _score(slug, record),
        "explanation": "deterministic mock text classification",
    }


def _health_prediction(slug: str, record: Dict[str, Any]) -> Dict[str, Any]:
    weight = _numeric(record, "weight_kg", 70.0)
    height = max(_numeric(record, "height_m", 1.75), 0.5)
    age = _numeric(record, "age", 40.0)
    bmi = round(weight / (height * height), 2)
    outputs = {
        "bmi": {"value": bmi, "unit": "kg/m2", "category": "normal" if bmi < 25 else "elevated"},
        "body-fat": {"value": round(1.2 * bmi + 0.23 * age - 16.2, 2), "unit": "percent"},
        "bmr": {"value": round(10 * weight + 625 * height - 5 * age + 5, 2), "unit": "kcal/day"},
        "ideal-weight": {"value": round(22 * height * height, 2), "unit": "kg"},
        "health-risk": {"value": "low" if bmi < 25 else "moderate", "score": min(round(bmi / 40, 3), 1.0)},
    }
    return {
        "label": slug,
        "confidence": _score(slug, record),
        "output": outputs.get(slug, outputs["health-risk"]),
    }


def _predict(model: Dict[str, str], record: Dict[str, Any]) -> Dict[str, Any]:
    group = model["group"]
    slug = model["slug"]
    if group == "vision":
        result = _vision_prediction(slug, record)
    elif group == "nlp":
        result = _nlp_prediction(slug, record)
    else:
        result = _health_prediction(slug, record)
    return {"input": record, "result": result}


def _register_mock_endpoint(model: Dict[str, str]) -> None:
    async def endpoint(request: Request) -> Dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        records = _records_from_payload(payload)
        return {
            "model": model["slug"],
            "serverMode": "combined",
            "predictions": [_predict(model, record) for record in records],
        }

    route_name = f"combined_{model['slug'].replace('-', '_')}"
    endpoint.__name__ = route_name
    app.add_api_route(model["endpoint"], endpoint, methods=["POST"], name=route_name)


def _active_mock_models() -> Iterable[Dict[str, str]]:
    return MOCK_MODELS[:_mock_http_count()]


for _model in _active_mock_models():
    _register_mock_endpoint(_model)


@app.get("/combined-models")
def combined_models() -> Dict[str, Any]:
    return {
        "mode": "combined",
        "useCaseServerDir": _use_case_server_dir(),
        "mockHttp": [
            {"slug": model["slug"], "endpoint": model["endpoint"], "group": model["group"]}
            for model in _active_mock_models()
        ],
    }
'''

    def _prepare_ai_model_hub_model_server_build_context(self, source_dir, mode, deployer_config):
        dockerfile_path = os.path.join(source_dir, "Dockerfile")
        if os.path.isfile(dockerfile_path):
            return source_dir, False

        if mode not in {"use-cases", "combined"}:
            self._fail(
                "AI Model Hub model-server Dockerfile not found",
                root_cause=(
                    f"Expected Dockerfile at: {dockerfile_path}. "
                    "Set AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR when using a custom model server source."
                ),
            )

        self._validate_ai_model_hub_use_case_source(source_dir)
        build_context = tempfile.mkdtemp(prefix="pionera-ai-model-hub-model-server-")
        target_dir = os.path.join(build_context, "use_cases")
        shutil.copytree(
            source_dir,
            target_dir,
            ignore=shutil.ignore_patterns(*self._ai_model_hub_model_server_copy_excludes(deployer_config)),
        )

        if mode == "combined":
            wrapper_dir = os.path.join(build_context, "combined_model_server")
            os.makedirs(wrapper_dir, exist_ok=True)
            with open(os.path.join(wrapper_dir, "__init__.py"), "w", encoding="utf-8") as handle:
                handle.write("")
            with open(os.path.join(wrapper_dir, "server.py"), "w", encoding="utf-8") as handle:
                handle.write(self._ai_model_hub_combined_model_server_source())

        container_port = self._ai_model_hub_model_server_container_port(deployer_config)
        uvicorn_app = self._ai_model_hub_model_server_uvicorn_app(deployer_config, mode)
        dockerfile_lines = [
            f"FROM {self._ai_model_hub_model_server_docker_base_image(deployer_config)}",
            "ENV PYTHONUNBUFFERED=1",
            "ENV PIP_NO_CACHE_DIR=1",
            "WORKDIR /app",
            "COPY use_cases/requirements.txt /tmp/use-case-requirements.txt",
            "RUN python -m pip install --upgrade pip && python -m pip install -r /tmp/use-case-requirements.txt",
            "COPY use_cases /app/use_cases",
            "ENV PYTHONPATH=/app/use_cases:/app",
            "ENV USE_CASE_SERVER_DIR=/app/use_cases",
        ]
        if mode == "combined":
            dockerfile_lines.append("COPY combined_model_server /app/combined_model_server")
        dockerfile_lines.extend(
            [
                f"EXPOSE {container_port}",
                f'CMD ["python", "-m", "uvicorn", "{uvicorn_app}", "--host", "0.0.0.0", "--port", "{container_port}"]',
                "",
            ]
        )
        with open(os.path.join(build_context, "Dockerfile"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(dockerfile_lines))

        return build_context, True

    def _generated_ai_model_hub_model_server_manifest(self, namespace, image_ref, mode, deployer_config):
        container_port = self._ai_model_hub_model_server_container_port(deployer_config)
        readiness_path = self._ai_model_hub_model_server_readiness_path(deployer_config)
        image_pull_policy = self._ai_model_hub_model_server_image_pull_policy(image_ref, deployer_config)
        return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: model-server
  namespace: {namespace}
  labels:
    app.kubernetes.io/name: model-server
    app.kubernetes.io/component: ai-model-hub-model-server
    app.kubernetes.io/managed-by: validation-environment
    app.kubernetes.io/mode: {mode}
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: model-server
  template:
    metadata:
      labels:
        app.kubernetes.io/name: model-server
        app.kubernetes.io/component: ai-model-hub-model-server
        app.kubernetes.io/mode: {mode}
    spec:
      containers:
        - name: model-server
          image: {image_ref}
          imagePullPolicy: {image_pull_policy}
          ports:
            - name: http
              containerPort: {container_port}
          readinessProbe:
            httpGet:
              path: {readiness_path}
              port: http
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 24
          livenessProbe:
            httpGet:
              path: {readiness_path}
              port: http
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 3
            failureThreshold: 8
---
apiVersion: v1
kind: Service
metadata:
  name: model-server
  namespace: {namespace}
  labels:
    app.kubernetes.io/name: model-server
    app.kubernetes.io/component: ai-model-hub-model-server
    app.kubernetes.io/managed-by: validation-environment
spec:
  selector:
    app.kubernetes.io/name: model-server
  ports:
    - name: http
      port: 8080
      targetPort: http
"""

    def _render_ai_model_hub_model_server_manifest(self, source_dir, namespace, image_ref, mode, deployer_config):
        manifest_path = self._ai_model_hub_model_server_manifest_path(source_dir, deployer_config)
        explicit_manifest = self._ai_model_hub_model_server_explicit_manifest_path(deployer_config)
        if os.path.isfile(manifest_path):
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = handle.read()
        elif explicit_manifest:
            self._fail(
                "AI Model Hub model-server Kubernetes manifest not found",
                root_cause=f"Expected configured manifest at: {explicit_manifest}",
            )
        elif mode in {"use-cases", "combined"}:
            manifest = self._generated_ai_model_hub_model_server_manifest(
                namespace,
                image_ref,
                mode,
                deployer_config,
            )
        else:
            self._fail(
                "AI Model Hub model-server Kubernetes manifest not found",
                root_cause=(
                    f"Expected manifest at: {manifest_path}. "
                    "Set AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH when using a custom model server source."
                ),
            )

        manifest = manifest.replace("namespace: demo", f"namespace: {namespace}")
        manifest = manifest.replace("image: model-server:latest", f"image: {image_ref}")
        readiness_path = self._ai_model_hub_model_server_readiness_path(deployer_config)
        manifest = manifest.replace("path: /api/v1/health", f"path: {readiness_path}")
        return manifest

    def _ai_model_hub_model_server_connector_base_url(self, namespace, deployer_config):
        config = dict(deployer_config or {})
        explicit = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL")
            or config.get("MODEL_SERVER_CONNECTOR_BASE_URL")
            or config.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL")
            or config.get("MODEL_SERVER_CONNECTOR_URL")
            or ""
        ).strip()
        if explicit:
            return explicit.rstrip("/")
        return self._ai_model_hub_model_server_service_url(namespace)

    def _ai_model_hub_model_server_public_url(self, deployer_config):
        config = dict(deployer_config or {})
        explicit = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL")
            or config.get("MODEL_SERVER_PUBLIC_URL")
            or ""
        ).strip()
        if explicit:
            return explicit.rstrip("/")

        public_base = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL")
            or config.get("COMPONENTS_PUBLIC_BASE_URL")
            or ""
        ).strip().rstrip("/")
        if not public_base:
            return ""
        public_path = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH")
            or config.get("MODEL_SERVER_PUBLIC_PATH")
            or "/model-server"
        ).strip()
        if not public_path.startswith("/"):
            public_path = f"/{public_path}"
        return f"{public_base}{public_path.rstrip('/')}"

    def _ai_model_hub_model_server_public_ingress(self, namespace, deployer_config):
        public_url = self._ai_model_hub_model_server_public_url(deployer_config)
        if not public_url:
            return None
        parsed = urlsplit(public_url if "://" in public_url else f"http://{public_url}")
        host = str(parsed.netloc or parsed.path.split("/", 1)[0]).strip()
        path = str(parsed.path or "").strip().rstrip("/")
        if not host or not path:
            return None

        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": "model-server-public-path",
                "namespace": namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": "validation-environment",
                    "app.kubernetes.io/part-of": "vm-distributed",
                    "app.kubernetes.io/component": "model-server",
                },
                "annotations": {
                    "nginx.ingress.kubernetes.io/use-regex": "true",
                    "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
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
                                            "name": "model-server",
                                            "port": {"number": 8080},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        }

    def _sync_ai_model_hub_model_server_public_ingress(self, namespace, deployer_config):
        ingress = self._ai_model_hub_model_server_public_ingress(namespace, deployer_config)
        if not ingress:
            return ""
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                temp_path = handle.name
                json.dump(ingress, handle)
            temp_q = shlex.quote(temp_path)
            if self.run(f"kubectl apply -f {temp_q}", check=False) is None:
                self._fail("Failed to apply AI Model Hub model-server public ingress", root_cause=temp_path)
            public_url = self._ai_model_hub_model_server_public_url(deployer_config)
            print(f"AI Model Hub model-server public route synchronized: {public_url}")
            return public_url
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    def _ontology_hub_public_root_aliases_enabled(self, deployer_config):
        if not (self._is_vm_distributed_topology() or self._is_vm_single_topology()):
            return False
        config = dict(deployer_config or {})
        public_path = configured_component_public_path("ontology-hub", config)
        if not public_path:
            return False
        value = config.get("ONTOLOGY_HUB_PUBLIC_ROOT_ALIASES_ENABLED")
        if value is None:
            value = config.get("COMPONENTS_PUBLIC_ROOT_ALIASES_ENABLED")
        return self._parse_bool(value, default=True)

    @staticmethod
    def _ontology_hub_public_root_alias_paths(deployer_config):
        raw_aliases = str(
            (deployer_config or {}).get("ONTOLOGY_HUB_PUBLIC_ROOT_ALIASES")
            or "/dataset,/edition,/css,/js,/img"
        )
        aliases = []
        for token in raw_aliases.replace(";", ",").split(","):
            path = token.strip()
            if not path:
                continue
            if not path.startswith("/"):
                path = f"/{path}"
            path = path.rstrip("/") or "/"
            if path != "/" and path not in aliases:
                aliases.append(path)
        return aliases

    def _ontology_hub_public_root_alias_ingress(self, release_name, namespace, deployer_config):
        config = dict(deployer_config or {})
        if not self._ontology_hub_public_root_aliases_enabled(config):
            return None

        public_url = configured_component_public_url(
            "ontology-hub",
            config,
            dataspace_name=self._dataspace_name(),
        )
        if not public_url:
            return None

        parsed = urlsplit(public_url if "://" in public_url else f"http://{public_url}")
        host = str(parsed.netloc or parsed.path.split("/", 1)[0]).strip()
        public_path = str(parsed.path or configured_component_public_path("ontology-hub", config) or "").rstrip("/")
        if not host or not public_path:
            return None

        alias_paths = [
            alias
            for alias in self._ontology_hub_public_root_alias_paths(config)
            if alias != public_path and not alias.startswith(f"{public_path}/")
        ]
        if not alias_paths:
            return None
        topology = self._normalized_topology()

        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": f"{release_name}-public-root-aliases",
                "namespace": namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": "validation-environment",
                    "app.kubernetes.io/part-of": topology,
                    "app.kubernetes.io/component": "ontology-hub",
                    "app.kubernetes.io/route-kind": "public-root-aliases",
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
                                    "path": alias,
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": release_name,
                                            "port": {"number": 3333},
                                        }
                                    },
                                }
                                for alias in alias_paths
                            ]
                        },
                    }
                ],
            },
        }

    def _existing_ingress_route_owners(self):
        raw = self.run_silent("kubectl get ingress -A -o json") or ""
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return {}

        owners = {}
        for item in payload.get("items") or []:
            metadata = item.get("metadata") or {}
            namespace = str(metadata.get("namespace") or "").strip()
            name = str(metadata.get("name") or "").strip()
            owner = f"{namespace}/{name}" if namespace and name else name
            for rule in ((item.get("spec") or {}).get("rules") or []):
                host = str(rule.get("host") or "").strip()
                if not host:
                    continue
                paths = ((rule.get("http") or {}).get("paths")) or []
                for route in paths:
                    path = str(route.get("path") or "").strip()
                    if path:
                        owners[(host, path)] = owner
        return owners

    def _drop_ontology_hub_conflicting_alias_paths(self, ingress):
        if not ingress:
            return None, []

        metadata = ingress.get("metadata") or {}
        namespace = str(metadata.get("namespace") or "").strip()
        name = str(metadata.get("name") or "").strip()
        target_owner = f"{namespace}/{name}" if namespace and name else name
        owners = self._existing_ingress_route_owners()
        if not owners:
            return ingress, []

        skipped = []
        for rule in ((ingress.get("spec") or {}).get("rules") or []):
            host = str(rule.get("host") or "").strip()
            http = rule.get("http") or {}
            retained_paths = []
            for route in http.get("paths") or []:
                path = str(route.get("path") or "").strip()
                owner = owners.get((host, path))
                if owner and owner != target_owner:
                    skipped.append({"host": host, "path": path, "owner": owner})
                    continue
                retained_paths.append(route)
            http["paths"] = retained_paths

        remaining_paths = []
        for rule in ((ingress.get("spec") or {}).get("rules") or []):
            remaining_paths.extend(((rule.get("http") or {}).get("paths")) or [])
        if not remaining_paths:
            return None, skipped
        return ingress, skipped

    def _sync_ontology_hub_public_root_alias_ingress(self, release_name, namespace, deployer_config):
        ingress = self._ontology_hub_public_root_alias_ingress(release_name, namespace, deployer_config)
        if not ingress:
            return []

        temp_path = ""
        try:
            with self._temporary_component_kubeconfig(deployer_config):
                ingress, skipped = self._drop_ontology_hub_conflicting_alias_paths(ingress)
                if skipped:
                    skipped_summary = ", ".join(
                        f"{item['host']}{item['path']} ({item['owner']})"
                        for item in skipped
                    )
                    print(f"Ontology Hub public root alias paths already owned; skipping: {skipped_summary}")
                if not ingress:
                    print("Ontology Hub public root alias synchronization skipped: all alias paths are already owned.")
                    return []
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                    temp_path = handle.name
                    json.dump(ingress, handle)
                temp_q = shlex.quote(temp_path)
                if self.run(f"kubectl apply -f {temp_q}", check=False) is None:
                    self._fail("Failed to apply Ontology Hub public root alias ingress", root_cause=temp_path)
            public_url = configured_component_public_url(
                "ontology-hub",
                deployer_config,
                dataspace_name=self._dataspace_name(),
            )
            parsed = urlsplit(public_url if "://" in public_url else f"http://{public_url}")
            scheme = parsed.scheme or "http"
            host = ingress["spec"]["rules"][0]["host"]
            aliases = [f"{scheme}://{host}{path['path']}" for path in ingress["spec"]["rules"][0]["http"]["paths"]]
            print(f"Ontology Hub public root aliases synchronized: {', '.join(aliases)}")
            return aliases
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    def sync_validation_public_routes(self, components, *, ds_name=None, namespace=None, deployer_config=None):
        """Reconcile idempotent public routes required by component validation."""
        if not components:
            return []

        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        resolved_ds_name = str(ds_name or self._dataspace_name() or "").strip()
        resolved_namespace = self._resolve_components_namespace(
            ds_name=resolved_ds_name,
            namespace=namespace,
            deployer_config=resolved_config,
        )
        results = []
        for component in components:
            normalized = self._normalize_component_key(component)
            if normalized != "ontology-hub":
                continue
            release_name = resolve_component_release_name(
                normalized,
                dataspace_name=resolved_ds_name,
            )
            aliases = self._sync_ontology_hub_public_root_alias_ingress(
                release_name,
                resolved_namespace,
                resolved_config,
            )
            results.append(
                {
                    "component": normalized,
                    "public_root_aliases": aliases,
                }
            )
        return results

    def _prepare_ai_model_hub_model_server_image(self, image_ref, deployer_config):
        source_dir = self._ai_model_hub_model_server_source_dir(deployer_config)
        mode = self._ai_model_hub_model_server_mode(deployer_config)

        auto_build_flag = deployer_config.get("LEVEL5_AUTO_BUILD_LOCAL_IMAGES")
        if auto_build_flag is None:
            auto_build_flag = deployer_config.get("LEVEL6_AUTO_BUILD_LOCAL_IMAGES")
        if not self._parse_bool(auto_build_flag, default=True):
            print(
                "AI Model Hub model-server auto-build is disabled. "
                f"Assuming image '{image_ref}' is already available in the cluster runtime."
            )
            return False

        runtime = self._cluster_runtime(deployer_config)
        cluster_type = str(runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
        profile = (
            deployer_config.get("MINIKUBE_PROFILE")
            or getattr(self.config, "MINIKUBE_PROFILE", "minikube")
            or "minikube"
        ).strip() or "minikube"

        if cluster_type == "minikube" and not self._minikube_is_available(profile):
            self._fail(
                "Minikube profile is not available for AI Model Hub model-server deployment",
                root_cause=profile,
            )
        if cluster_type == "k3s":
            self._ensure_k3s_local_image_import_supported(image_ref, deployer_config)

        image_q = shlex.quote(image_ref)
        docker_q = shlex.quote(self._docker_cmd())
        build_context, generated_context = self._prepare_ai_model_hub_model_server_build_context(
            source_dir,
            mode,
            deployer_config,
        )
        try:
            print(f"\nBuilding local image on host: {image_ref}")
            if generated_context:
                print(f"Generated AI Model Hub model-server build context for mode '{mode}'.")
            if self.run(f"{docker_q} build -t {image_q} .", check=False, cwd=build_context) is None:
                self._fail("Failed to build AI Model Hub model-server image on host", root_cause=image_ref)
            self._load_image_into_cluster_runtime(cluster_type, profile, image_ref, deployer_config)
        finally:
            if generated_context:
                shutil.rmtree(build_context, ignore_errors=True)
        return True

    def _ensure_ai_model_hub_model_server(self, namespace, deployer_config):
        if not self._ai_model_hub_model_server_enabled(deployer_config):
            print("AI Model Hub model-server deployment disabled by configuration.")
            return {"enabled": False, "namespace": namespace}

        resolved_namespace = str(namespace or "").strip() or "components"
        mode = self._ai_model_hub_model_server_mode(deployer_config)
        service_url = self._ai_model_hub_model_server_service_url(resolved_namespace)
        connector_base_url = self._ai_model_hub_model_server_connector_base_url(
            resolved_namespace,
            deployer_config,
        )
        public_url = self._ai_model_hub_model_server_public_url(deployer_config)

        if mode == "external":
            if not connector_base_url or connector_base_url == service_url:
                self._fail(
                    "AI Model Hub external model-server URL is not configured",
                    root_cause=(
                        "Set AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL to the URL "
                        "reachable from connector runtimes."
                    ),
                )
            print(
                "AI Model Hub model-server deployment skipped: external mode. "
                f"Connector URL: {connector_base_url}"
            )
            return {
                "enabled": True,
                "mode": mode,
                "namespace": resolved_namespace,
                "image": "",
                "service": service_url,
                "connector_base_url": connector_base_url,
                "public_url": public_url,
                "built_local_image": False,
            }

        image_ref = self._ai_model_hub_model_server_image_ref(deployer_config)
        source_dir = self._ai_model_hub_model_server_source_dir(deployer_config)

        built_local_image = self._prepare_ai_model_hub_model_server_image(image_ref, deployer_config)

        ns_q = shlex.quote(resolved_namespace)
        if self.run(f"kubectl get namespace {ns_q}", check=False) is None:
            if self.run(f"kubectl create namespace {ns_q}", check=False) is None:
                self._fail("Failed to create namespace for AI Model Hub model-server", root_cause=resolved_namespace)

        manifest = self._render_ai_model_hub_model_server_manifest(
            source_dir,
            resolved_namespace,
            image_ref,
            mode,
            deployer_config,
        )

        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(prefix="pionera-model-server-", suffix=".yaml")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(manifest)
            temp_q = shlex.quote(temp_path)
            print(
                f"\nDeploying AI Model Hub model-server ({mode}) in namespace "
                f"'{resolved_namespace}'"
            )
            if self.run(f"kubectl apply -f {temp_q}", check=False) is None:
                self._fail("Failed to apply AI Model Hub model-server manifest", root_cause=temp_path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

        if not self._wait_for_component_rollout(
            resolved_namespace,
            "model-server",
            timeout_seconds=300,
            label="ai-model-hub model-server",
        ):
            self._fail("Timeout waiting for AI Model Hub model-server deployment rollout")

        public_url = self._sync_ai_model_hub_model_server_public_ingress(
            resolved_namespace,
            deployer_config,
        )
        return {
            "enabled": True,
            "mode": mode,
            "namespace": resolved_namespace,
            "image": image_ref,
            "service": service_url,
            "connector_base_url": connector_base_url,
            "public_url": public_url,
            "built_local_image": bool(built_local_image),
        }

    def _resolve_component_public_ingress_host(self, namespace, ingress_name):
        resolved_namespace = str(namespace or "").strip()
        resolved_ingress_name = str(ingress_name or "").strip()
        if not resolved_namespace or not resolved_ingress_name:
            return ""

        output = self.run_silent(
            f"kubectl get ingress {resolved_ingress_name} -n {resolved_namespace} "
            "-o jsonpath='{.spec.rules[0].host}'"
        )
        return str(output or "").strip().strip("'").strip('"')

    def _probe_component_public_url(self, url, *, expected_statuses, timeout_seconds=5):
        normalized_url = self._to_public_url(url)
        if not normalized_url:
            return False, "public URL is empty"

        try:
            response = requests.get(
                normalized_url,
                timeout=timeout_seconds,
                allow_redirects=False,
                headers={"Cache-Control": "no-store"},
            )
        except Exception as exc:
            return False, f"HTTP probe failed: {exc}"

        status_code = int(getattr(response, "status_code", 0) or 0)
        detail = f"HTTP {status_code}"
        location = str(getattr(response, "headers", {}).get("Location") or "").strip()
        if location:
            detail = f"{detail} -> {location}"
        return status_code in set(expected_statuses), detail

    def verify_component_publication(
        self,
        component,
        *,
        deployment_plan,
        namespace,
        timeout_seconds=90,
        poll_interval_seconds=3,
    ):
        normalized = self._normalize_component_key(component)
        if normalized not in {"ontology-hub", "ai-model-hub"}:
            return {
                "component": normalized,
                "verified": False,
                "skipped": True,
                "reason": "publication-gate-not-enabled",
            }

        plan = dict(deployment_plan or {})
        resolved_namespace = str(namespace or "").strip()
        release_name = str(plan.get("release_name") or "").strip()
        expected_host = str(plan.get("host") or "").strip()
        expected_public_url = str(plan.get("public_url") or "").strip()
        ingress_host = self._resolve_component_public_ingress_host(resolved_namespace, release_name)
        if not ingress_host:
            component_label = "Ontology Hub" if normalized == "ontology-hub" else "AI Model Hub"
            self._fail(
                f"{component_label} publication gate failed: ingress '{release_name}' is missing in namespace '{resolved_namespace}'"
            )
        if expected_host and ingress_host != expected_host:
            component_label = "Ontology Hub" if normalized == "ontology-hub" else "AI Model Hub"
            self._fail(
                f"{component_label} publication gate failed: ingress host does not match the inferred public host",
                root_cause=f"expected '{expected_host}', found '{ingress_host}'",
            )

        public_base_url = self._to_public_url(expected_public_url or expected_host or ingress_host)
        deadline = time.monotonic() + max(int(timeout_seconds or 0), 1)
        if normalized == "ontology-hub":
            dataset_url = f"{public_base_url}/dataset"
            edition_url = f"{public_base_url}/edition"
            dataset_detail = "not probed"
            edition_detail = "not probed"
        else:
            root_url = public_base_url
            config_url = f"{public_base_url}/config/app-config.json"
            root_detail = "not probed"
            config_detail = "not probed"
        while True:
            if normalized == "ontology-hub":
                dataset_ready, dataset_detail = self._probe_component_public_url(
                    dataset_url,
                    expected_statuses={200, 301, 302, 303, 307, 308},
                )
                edition_ready, edition_detail = self._probe_component_public_url(
                    edition_url,
                    expected_statuses={200, 301, 302, 303, 307, 308},
                )
                if dataset_ready and edition_ready:
                    return {
                        "component": normalized,
                        "verified": True,
                        "ingress_host": ingress_host,
                        "dataset_url": dataset_url,
                        "edition_url": edition_url,
                        "dataset_detail": dataset_detail,
                        "edition_detail": edition_detail,
                    }
            else:
                root_ready, root_detail = self._probe_component_public_url(
                    root_url,
                    expected_statuses={200},
                )
                config_ready, config_detail = self._probe_component_public_url(
                    config_url,
                    expected_statuses={200},
                )
                if root_ready and config_ready:
                    return {
                        "component": normalized,
                        "verified": True,
                        "ingress_host": ingress_host,
                        "root_url": root_url,
                        "config_url": config_url,
                        "root_detail": root_detail,
                        "config_detail": config_detail,
                    }
            if time.monotonic() >= deadline:
                break
            time.sleep(max(int(poll_interval_seconds or 0), 1))

        if normalized == "ontology-hub":
            self._fail(
                "Ontology Hub publication gate failed: public routes are not ready after deployment",
                root_cause=f"/dataset={dataset_detail}; /edition={edition_detail}",
            )

        self._fail(
            "AI Model Hub publication gate failed: public routes are not ready after deployment",
            root_cause=f"/={root_detail}; /config/app-config.json={config_detail}",
        )

    def deploy_shared_component_runtime(
        self,
        component,
        *,
        deployment_plan,
        namespace,
        deployer_config=None,
        prepared_execution=None,
    ):
        normalized = self._normalize_component_key(component)
        if normalized != "ontology-hub":
            return None

        plan = dict(deployment_plan or {})
        execution = dict(prepared_execution or {})
        if not execution:
            execution = self.prepare_component_runtime_execution(
                normalized,
                deployment_plan=plan,
                namespace=namespace,
                deployer_config=deployer_config,
            )
        execution.setdefault("release_name", str(plan.get("release_name") or "").strip())
        execution.setdefault("namespace", str(namespace or "").strip())
        execution.setdefault("deployer_config", dict(deployer_config or self.config_adapter.load_deployer_config() or {}))
        execution.setdefault("built_local_image", False)

        self.deploy_component_release(
            normalized,
            deployment_plan=plan,
            namespace=execution["namespace"],
            deployer_config=execution["deployer_config"],
        )
        finalization = self.finalize_component_runtime(
            normalized,
            release_name=execution["release_name"],
            namespace=execution["namespace"],
            built_local_image=execution["built_local_image"],
            deployer_config=execution["deployer_config"],
        )
        publication = self.verify_component_publication(
            normalized,
            deployment_plan=plan,
            namespace=execution["namespace"],
        )
        result = dict(finalization or {})
        result["publication"] = publication
        return result

    def describe(self) -> str:
        return (
            "SharedComponentsAdapter delegates Level 5 component operations "
            f"for the active adapter '{self.active_adapter}'."
        )
