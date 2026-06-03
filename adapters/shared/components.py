"""Shared Level 5 component facade reused by multiple adapters."""

from contextlib import contextmanager
import json
import os
import shlex
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
        if not self._is_vm_distributed_topology():
            yield
            return

        kubeconfig = self._vm_distributed_role_kubeconfig("components", deployer_config)
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

    def _ai_model_hub_model_server_enabled(self, deployer_config):
        config = dict(deployer_config or {})
        flag = config.get("AI_MODEL_HUB_MODEL_SERVER_ENABLED")
        if flag is None:
            flag = config.get("LEVEL5_AI_MODEL_HUB_MODEL_SERVER_ENABLED")
        return self._parse_bool(flag, default=True)

    def _ai_model_hub_model_server_source_dir(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(project_root, "adapters", "inesdata", "sources", "model-server")

    def _ai_model_hub_model_server_image_ref(self, deployer_config):
        return str((deployer_config or {}).get("AI_MODEL_HUB_MODEL_SERVER_IMAGE") or "model-server:latest").strip()

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
        if not self._is_vm_distributed_topology():
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

        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": f"{release_name}-public-root-aliases",
                "namespace": namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": "validation-environment",
                    "app.kubernetes.io/part-of": "vm-distributed",
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
        source_dir = self._ai_model_hub_model_server_source_dir()
        dockerfile_path = os.path.join(source_dir, "Dockerfile")
        if not os.path.isfile(dockerfile_path):
            self._fail(
                "AI Model Hub model-server Dockerfile not found",
                root_cause=(
                    f"Expected Dockerfile at: {dockerfile_path}. "
                    "Level 5 needs this deterministic fixture for A5.2 model execution and benchmarking validation."
                ),
            )

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
        print(f"\nBuilding local image on host: {image_ref}")
        if self.run(f"{docker_q} build -t {image_q} .", check=False, cwd=source_dir) is None:
            self._fail("Failed to build AI Model Hub model-server image on host", root_cause=image_ref)
        self._load_image_into_cluster_runtime(cluster_type, profile, image_ref, deployer_config)
        return True

    def _ensure_ai_model_hub_model_server(self, namespace, deployer_config):
        if not self._ai_model_hub_model_server_enabled(deployer_config):
            print("AI Model Hub model-server deployment disabled by configuration.")
            return {"enabled": False, "namespace": namespace}

        resolved_namespace = str(namespace or "").strip() or "components"
        image_ref = self._ai_model_hub_model_server_image_ref(deployer_config)
        source_dir = self._ai_model_hub_model_server_source_dir()
        manifest_path = os.path.join(source_dir, "k8s-model-server.yaml")
        if not os.path.isfile(manifest_path):
            self._fail(
                "AI Model Hub model-server Kubernetes manifest not found",
                root_cause=manifest_path,
            )

        built_local_image = self._prepare_ai_model_hub_model_server_image(image_ref, deployer_config)

        ns_q = shlex.quote(resolved_namespace)
        if self.run(f"kubectl get namespace {ns_q}", check=False) is None:
            if self.run(f"kubectl create namespace {ns_q}", check=False) is None:
                self._fail("Failed to create namespace for AI Model Hub model-server", root_cause=resolved_namespace)

        with open(manifest_path, encoding="utf-8") as handle:
            manifest = handle.read()
        manifest = manifest.replace("namespace: demo", f"namespace: {resolved_namespace}")
        manifest = manifest.replace("image: model-server:latest", f"image: {image_ref}")

        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(prefix="pionera-model-server-", suffix=".yaml")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(manifest)
            temp_q = shlex.quote(temp_path)
            print(f"\nDeploying AI Model Hub model-server fixture in namespace '{resolved_namespace}'")
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
            "namespace": resolved_namespace,
            "image": image_ref,
            "service": f"http://model-server.{resolved_namespace}.svc.cluster.local:8080",
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
