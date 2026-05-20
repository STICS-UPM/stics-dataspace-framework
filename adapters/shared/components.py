"""Shared Level 5 component facade reused by multiple adapters."""

import os
import shlex
import tempfile
import time

import requests

from adapters.inesdata.components import INESDataComponentsAdapter
from deployers.shared.lib.components import (
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
        return {
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
        return {
            "component": component,
            "normalized_component": normalized,
            "chart_dir": metadata["chart_dir"],
            "values_file": metadata["values_file"],
            "host": metadata.get("host"),
            "release_name": metadata["release_name"],
            "override_plan": override_plan,
        }

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
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})

        if built_local_image:
            print(f"Restarting deployment/{resolved_release_name} to pick up local image...\n")
            self.run(
                f"kubectl rollout restart deployment/{resolved_release_name} -n {resolved_namespace}",
                check=False,
            )

        waited_for_rollout = False
        if normalized == "ontology-hub":
            timeout_seconds = 1800
            if not self._wait_for_component_rollout(
                resolved_namespace,
                resolved_release_name,
                timeout_seconds=timeout_seconds,
                label=normalized,
            ):
                self._fail(f"Timeout waiting for component '{normalized}' deployment rollout")
            waited_for_rollout = True

        model_server = None
        if normalized == "ai-model-hub":
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
        if model_server:
            result["model_server"] = model_server
        return result

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

        image_q = shlex.quote(image_ref)
        print(f"\nBuilding local image on host: {image_ref}")
        if self.run(f"docker build -t {image_q} .", check=False, cwd=source_dir) is None:
            self._fail("Failed to build AI Model Hub model-server image on host", root_cause=image_ref)
        self._load_image_into_cluster_runtime(cluster_type, profile, image_ref)
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

        return {
            "enabled": True,
            "namespace": resolved_namespace,
            "image": image_ref,
            "service": f"http://model-server.{resolved_namespace}.svc.cluster.local:8080",
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
        normalized_url = self._to_http_url(url)
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

        public_base_url = self._to_http_url(expected_host or ingress_host)
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
    ):
        normalized = self._normalize_component_key(component)
        if normalized != "ontology-hub":
            return None

        plan = dict(deployment_plan or {})
        execution = self.prepare_component_runtime_execution(
            normalized,
            deployment_plan=plan,
            namespace=namespace,
            deployer_config=deployer_config,
        )

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
