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
    configured_component_host,
    configured_component_public_path,
    configured_component_public_url,
    infer_component_hostname,
    resolve_component_release_name,
    summarize_components_for_adapter,
)
from deployers.shared.lib import ai_model_hub_model_server as model_server
from deployers.shared.lib import image_runtime
from deployers.shared.lib.topology import VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY, normalize_topology


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
        component_ds_name = self._component_release_dataspace_name(
            resolved_ds_name,
            resolved_config,
            normalized_component=normalized,
        )

        chart_dir = self._resolve_component_chart_dir(normalized)
        values_file = self._resolve_component_values_file(
            chart_dir,
            ds_name=component_ds_name,
            namespace=resolved_namespace,
        )
        public_url = configured_component_public_url(
            normalized,
            resolved_config,
            dataspace_name=component_ds_name,
        )
        metadata_payload = {
            "component": component,
            "normalized_component": normalized,
            "dataspace_name": resolved_ds_name,
            "component_dataspace_name": component_ds_name,
            "namespace": resolved_namespace,
            "chart_dir": chart_dir,
            "values_file": values_file,
            "host": self._infer_component_hostname_for_dataspace(
                normalized,
                values_file,
                resolved_config,
                dataspace_name=component_ds_name,
            ),
            "release_name": resolve_component_release_name(
                normalized,
                dataspace_name=component_ds_name,
            ),
        }
        if public_url:
            metadata_payload["public_url"] = public_url
        return metadata_payload

    def _component_release_dataspace_name(self, ds_name=None, deployer_config=None, normalized_component=None):
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        resolved_ds_name = str(
            ds_name
            or resolved_config.get("DS_1_NAME")
            or self._dataspace_name()
            or ""
        ).strip()
        explicit = str(
            resolved_config.get("COMPONENTS_RELEASE_DATASPACE_NAME")
            or resolved_config.get("COMPONENTS_HELM_RELEASE_DATASPACE_NAME")
            or ""
        ).strip()
        if explicit:
            return explicit

        scope = str(resolved_config.get("COMPONENTS_RELEASE_SCOPE") or "auto").strip().lower()
        if scope in {"dataspace", "adapter", "per-adapter", "adapter-dataspace"}:
            return resolved_ds_name
        if scope in {"shared", "base", "common", "common-dataspace"}:
            return self._component_base_dataspace_name(resolved_ds_name)

        if (
            self.active_adapter == "edc"
            and self._component_uses_shared_release_scope(normalized_component, resolved_config)
        ):
            return self._component_base_dataspace_name(resolved_ds_name)
        return resolved_ds_name

    def _component_uses_shared_release_scope(self, normalized_component, deployer_config=None):
        normalized = self._normalize_component_key(normalized_component)
        if not normalized:
            return False

        raw_value = str(
            (deployer_config or {}).get("COMPONENTS_SHARED_RELEASE_COMPONENTS")
            or "ontology-hub,ai-model-hub,semantic-virtualization"
        ).strip()
        lowered = raw_value.lower()
        if lowered in {"*", "all"}:
            return True
        if lowered in {"", "none", "false", "no", "0"}:
            return False

        configured = {
            self._normalize_component_key(token)
            for token in raw_value.split(",")
            if str(token or "").strip()
        }
        return normalized in configured

    @staticmethod
    def _component_base_dataspace_name(ds_name):
        resolved = str(ds_name or "").strip()
        for suffix in ("-edc", "_edc"):
            if resolved.lower().endswith(suffix):
                return resolved[: -len(suffix)] or resolved
        return resolved

    def _resolve_component_release_name(self, normalized_component: str) -> str:
        deployer_config = dict(self.config_adapter.load_deployer_config() or {})
        registration_release_getter = getattr(self.config, "helm_release_rs", None)
        return resolve_component_release_name(
            normalized_component,
            dataspace_name=self._component_release_dataspace_name(
                deployer_config=deployer_config,
                normalized_component=normalized_component,
            ),
            registration_service_release_name=(
                registration_release_getter() if callable(registration_release_getter) else ""
            ),
        )

    def _component_release_cleanup_names(self, normalized_component, primary_release_name):
        deployer_config = dict(self.config_adapter.load_deployer_config() or {})
        ds_name = str(deployer_config.get("DS_1_NAME") or self._dataspace_name() or "").strip()
        names = [str(primary_release_name or "").strip()]
        release_dataspaces = [
            self._component_release_dataspace_name(
                ds_name,
                deployer_config,
                normalized_component=normalized_component,
            ),
        ]
        if self._component_uses_shared_release_scope(normalized_component, deployer_config):
            release_dataspaces.extend([ds_name, self._component_base_dataspace_name(ds_name)])
        registration_release_getter = getattr(self.config, "helm_release_rs", None)
        registration_release_name = registration_release_getter() if callable(registration_release_getter) else ""
        for release_ds_name in release_dataspaces:
            release_name = resolve_component_release_name(
                normalized_component,
                dataspace_name=release_ds_name,
                registration_service_release_name=registration_release_name,
            )
            if release_name and release_name not in names:
                names.append(release_name)
        return [name for name in names if name]

    def _component_config_dataspace_name(self, normalized_component, deployer_config=None):
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        ds_name = str(resolved_config.get("DS_1_NAME") or self._dataspace_name() or "").strip()
        return self._component_release_dataspace_name(
            ds_name,
            resolved_config,
            normalized_component=normalized_component,
        )

    def _configured_component_host(self, normalized_component: str, deployer_config: dict) -> str:
        normalized = self._normalize_component_key(normalized_component)
        return configured_component_host(
            normalized,
            deployer_config,
            dataspace_name=self._component_config_dataspace_name(normalized, deployer_config),
        )

    def _configured_component_public_url(self, normalized_component: str, deployer_config: dict) -> str:
        normalized = self._normalize_component_key(normalized_component)
        return configured_component_public_url(
            normalized,
            deployer_config,
            dataspace_name=self._component_config_dataspace_name(normalized, deployer_config),
        )

    def _existing_component_release_values(self, normalized_component, deployer_config=None):
        normalized = self._normalize_component_key(normalized_component)
        resolved_config = dict(deployer_config or self.config_adapter.load_deployer_config() or {})
        release_ds_name = self._component_release_dataspace_name(
            deployer_config=resolved_config,
            normalized_component=normalized,
        )
        release_name = resolve_component_release_name(
            normalized,
            dataspace_name=release_ds_name,
        )
        namespace = self._resolve_components_namespace(
            ds_name=release_ds_name,
            deployer_config=resolved_config,
        )
        if not release_name or not namespace:
            return {}

        release_q = shlex.quote(release_name)
        namespace_q = shlex.quote(namespace)
        raw_values = self.run_silent(f"helm get values {release_q} -n {namespace_q} -o json")
        if not raw_values:
            return {}
        try:
            payload = json.loads(raw_values)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _ai_model_hub_connector_config_key(entry):
        if not isinstance(entry, dict):
            return None
        url_key = tuple(
            str(entry.get(key) or "").strip()
            for key in ("managementUrl", "defaultUrl", "protocolUrl")
        )
        if any(url_key):
            return url_key
        connector_name = str(entry.get("connectorName") or "").strip()
        return ("connectorName", connector_name) if connector_name else None

    def _merge_ai_model_hub_connector_config(self, existing_values, payload):
        existing_config = ((existing_values or {}).get("config") or {}).get("edcConnectorConfig") or []
        next_config = ((payload or {}).get("config") or {}).get("edcConnectorConfig") or []
        if not isinstance(existing_config, list):
            existing_config = []
        if not isinstance(next_config, list):
            next_config = []
        if not existing_config:
            return payload

        merged = []
        positions = {}
        for entry in existing_config + next_config:
            if not isinstance(entry, dict):
                continue
            key = self._ai_model_hub_connector_config_key(entry)
            if key is None:
                merged.append(dict(entry))
                continue
            if key in positions:
                merged[positions[key]] = dict(entry)
                continue
            positions[key] = len(merged)
            merged.append(dict(entry))

        if merged:
            payload.setdefault("config", {})["edcConnectorConfig"] = merged
        return payload

    def _merge_existing_shared_component_values(self, existing_values, payload):
        existing = existing_values if isinstance(existing_values, dict) else {}
        current = payload if isinstance(payload, dict) else {}
        if not existing:
            return current
        merged = dict(existing)
        for key, value in current.items():
            existing_value = merged.get(key)
            if isinstance(existing_value, dict) and isinstance(value, dict):
                merged[key] = self._merge_existing_shared_component_values(existing_value, value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _split_config_list(raw_value):
        return [
            str(token or "").strip()
            for token in str(raw_value or "").split(",")
            if str(token or "").strip()
        ]

    @staticmethod
    def _normalize_public_url(value):
        resolved = str(value or "").strip().rstrip("/")
        if not resolved:
            return ""
        if resolved.startswith(("http://", "https://")):
            return resolved
        return f"http://{resolved}"

    @staticmethod
    def _join_url_path(base_url, *segments):
        base = str(base_url or "").strip().rstrip("/")
        if not base:
            return ""
        cleaned_segments = [
            str(segment or "").strip().strip("/")
            for segment in segments
            if str(segment or "").strip().strip("/")
        ]
        if not cleaned_segments:
            return base
        return f"{base}/{'/'.join(cleaned_segments)}"

    @staticmethod
    def _edc_vm_distributed_public_path_prefix(deployer_config):
        for key in (
            "EDC_VM_DISTRIBUTED_CONNECTOR_PUBLIC_PATH_PREFIX",
            "VM_DISTRIBUTED_EDC_CONNECTOR_PUBLIC_PATH_PREFIX",
            "EDC_CONNECTOR_PUBLIC_PATH_PREFIX",
        ):
            raw_value = str((deployer_config or {}).get(key) or "").strip()
            if not raw_value:
                continue
            if raw_value in {"/", ".", "root"}:
                return ""
            return f"/{raw_value.strip('/')}"
        return "/edc"

    @staticmethod
    def _edc_vm_single_connector_public_path_prefix(deployer_config):
        for key in (
            "EDC_VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX",
            "VM_SINGLE_EDC_CONNECTOR_PUBLIC_PATH_PREFIX",
            "EDC_CONNECTOR_PUBLIC_PATH_PREFIX",
        ):
            raw_value = str((deployer_config or {}).get(key) or "").strip()
            if raw_value:
                prefix = raw_value
                break
        else:
            prefix = "/edc/c"
        if prefix in {"/", ".", "root"}:
            return ""
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        return prefix.rstrip("/")

    @staticmethod
    def _edc_connector_short_name(connector_id, dataspace):
        short_name = str(connector_id or "").strip()
        if short_name.startswith("conn-"):
            short_name = short_name[len("conn-"):]
        suffix = f"-{dataspace}"
        if dataspace and short_name.endswith(suffix):
            short_name = short_name[: -len(suffix)]
        return short_name

    def _edc_dataspace_name(self, deployer_config):
        return str(
            (deployer_config or {}).get("DS_1_NAME")
            or self._dataspace_name()
            or ""
        ).strip()

    def _edc_connector_ids(self, deployer_config, dataspace):
        connector_ids = []
        for token in self._split_config_list((deployer_config or {}).get("DS_1_CONNECTORS")):
            if token.startswith("conn-"):
                connector_ids.append(token)
            elif dataspace:
                connector_ids.append(f"conn-{token}-{dataspace}")
        return connector_ids

    def _edc_connector_matches_configured_name(self, connector_id, dataspace, configured_name):
        configured = str(configured_name or "").strip()
        if not configured:
            return False
        aliases = {
            str(connector_id or "").strip(),
            self._edc_connector_short_name(connector_id, dataspace),
        }
        if dataspace and not configured.startswith("conn-"):
            aliases.add(f"conn-{configured}-{dataspace}")
        return configured in aliases

    def _edc_connector_role(self, connector_id, dataspace, deployer_config, index):
        role_options = (
            ("provider", "VM_PROVIDER_CONNECTORS"),
            ("consumer", "VM_CONSUMER_CONNECTORS"),
        )
        for role, connectors_key in role_options:
            for configured_connector in self._split_config_list((deployer_config or {}).get(connectors_key)):
                if self._edc_connector_matches_configured_name(connector_id, dataspace, configured_connector):
                    return role
        if index == 0:
            return "provider"
        if index == 1:
            return "consumer"
        return ""

    def _edc_connector_public_base_url(self, connector_id, deployer_config, *, dataspace, role=""):
        topology = normalize_topology(
            (deployer_config or {}).get("TOPOLOGY")
            or (deployer_config or {}).get("PIONERA_TOPOLOGY")
            or self._normalized_topology()
        )
        if topology == VM_SINGLE_TOPOLOGY:
            common_base = self._normalize_public_url(
                (deployer_config or {}).get("VM_SINGLE_PUBLIC_URL")
                or (deployer_config or {}).get("VM_SINGLE_HTTP_URL")
                or (deployer_config or {}).get("VM_COMMON_PUBLIC_URL")
                or (deployer_config or {}).get("VM_COMMON_HTTP_URL")
            )
            short_name = self._edc_connector_short_name(connector_id, dataspace)
            path_prefix = self._edc_vm_single_connector_public_path_prefix(deployer_config)
            if common_base and short_name:
                return self._join_url_path(common_base, path_prefix, short_name)
            return ""

        if topology == VM_DISTRIBUTED_TOPOLOGY:
            role_key = {
                "provider": ("VM_PROVIDER_PUBLIC_URL", "VM_PROVIDER_HTTP_URL"),
                "consumer": ("VM_CONSUMER_PUBLIC_URL", "VM_CONSUMER_HTTP_URL"),
            }.get(str(role or "").strip().lower(), ())
            for key in role_key:
                public_url = self._normalize_public_url((deployer_config or {}).get(key))
                if public_url:
                    return public_url
            return ""

        return ""

    def _edc_connector_public_api_base_url(self, connector_id, deployer_config, *, dataspace, role=""):
        base_url = self._edc_connector_public_base_url(
            connector_id,
            deployer_config,
            dataspace=dataspace,
            role=role,
        )
        if not base_url:
            return ""
        topology = normalize_topology(
            (deployer_config or {}).get("TOPOLOGY")
            or (deployer_config or {}).get("PIONERA_TOPOLOGY")
            or self._normalized_topology()
        )
        if topology == VM_DISTRIBUTED_TOPOLOGY:
            return self._join_url_path(base_url, self._edc_vm_distributed_public_path_prefix(deployer_config))
        return base_url

    def _edc_ai_model_hub_connector_config(self, deployer_config):
        dataspace = self._edc_dataspace_name(deployer_config)
        connector_ids = self._edc_connector_ids(deployer_config, dataspace)
        if not connector_ids:
            return []

        entries = []
        for index, connector_id in enumerate(connector_ids[:2]):
            role = self._edc_connector_role(connector_id, dataspace, deployer_config, index)
            public_api_base = self._edc_connector_public_api_base_url(
                connector_id,
                deployer_config,
                dataspace=dataspace,
                role=role,
            )
            if not public_api_base:
                continue
            label = "Provider" if role == "provider" else "Consumer" if role == "consumer" else connector_id
            entries.append(
                {
                    "connectorName": label,
                    "managementUrl": f"{public_api_base}/management",
                    "defaultUrl": f"{public_api_base}/api",
                    "protocolUrl": f"{public_api_base}/protocol",
                    "controlUrl": f"{public_api_base}/control",
                    "federatedCatalogEnabled": False,
                }
            )
        return entries

    def _component_values_override_payload(self, normalized_component: str, deployer_config: dict) -> dict:
        normalized = self._normalize_component_key(normalized_component)
        payload = super()._component_values_override_payload(normalized, deployer_config)
        existing_values = {}
        if self._component_uses_shared_release_scope(normalized, deployer_config):
            existing_values = self._existing_component_release_values(normalized, deployer_config)
            payload = self._merge_existing_shared_component_values(existing_values, payload)
        if normalized == "ai-model-hub":
            if self.active_adapter == "edc":
                edc_connector_config = self._edc_ai_model_hub_connector_config(deployer_config)
                if edc_connector_config:
                    payload.setdefault("config", {})["edcConnectorConfig"] = edc_connector_config
            payload = self._merge_ai_model_hub_connector_config(existing_values, payload)
        return payload

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
        image_deployments = {}
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
            for image_ref in image_runtime.rendered_local_image_refs(raw_images):
                if image_ref not in images_to_import:
                    images_to_import.append(image_ref)
                    image_labels[image_ref] = str(label or "").strip()
                    image_deployments[image_ref] = deployment

        if not images_to_import:
            return False

        auto_build_enabled = self._level5_auto_build_local_images(resolved_config)
        print(
            "Ensuring vm-single local component image(s) are available in k3s before rollout: "
            f"{', '.join(images_to_import)}"
        )
        if auto_build_enabled:
            print(
                "LEVEL5_AUTO_BUILD_LOCAL_IMAGES is enabled; rebuilding local component "
                "image(s) before importing them into k3s."
            )
            for image_ref in images_to_import:
                self._ensure_k3s_local_image_import_supported(image_ref, resolved_config)
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

        missing_images = []
        for image_ref in images_to_import:
            if self._k3s_runtime_has_image(image_ref, resolved_config):
                print(f"Verified k3s runtime already has local image '{image_ref}'.")
                continue
            deployment = image_deployments.get(image_ref, "")
            if self._deployment_has_ready_image(deployment, resolved_namespace, image_ref):
                print(
                    f"Verified deployment/{deployment} is already running "
                    f"with local image '{image_ref}'."
                )
                continue
            missing_images.append(image_ref)

        if not missing_images:
            return False

        for image_ref in missing_images:
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
            missing_images,
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
        image_refs = image_runtime.rendered_local_image_refs(image_ref)
        if not image_refs:
            return False
        image_ref = image_refs[0]

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
        return model_server.model_server_enabled(deployer_config)

    @staticmethod
    def _normalize_ai_model_hub_model_server_mode(mode):
        return model_server.normalize_model_server_mode(mode)

    def _ai_model_hub_model_server_mode(self, deployer_config):
        mode, raw_mode = model_server.model_server_mode(deployer_config)
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
        mode = self._ai_model_hub_model_server_mode(config)
        if mode == "mock":
            return os.path.join(self._project_root_dir(), "adapters", "inesdata", "sources", "model-server")

        explicit = str(
            config.get("AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR")
            or config.get("MODEL_SERVER_SOURCE_DIR")
            or ""
        ).strip()
        if explicit:
            source_dir = self._resolve_project_path(explicit)
            repository_url = model_server.explicit_source_repository(config)
            if repository_url:
                return self._ensure_ai_model_hub_model_server_source_checkout(
                    source_dir,
                    repository_url,
                    config,
                )
            return source_dir

        if mode in {"use-cases", "combined"}:
            real_source = str(
                config.get("AI_MODEL_HUB_REAL_MODEL_SERVER_SOURCE_DIR")
                or config.get("AI_MODEL_HUB_USE_CASE_MODEL_SERVER_SOURCE_DIR")
                or config.get("MODEL_SERVER_REAL_SOURCE_DIR")
                or ""
            ).strip()
            if real_source:
                source_dir = self._resolve_project_path(real_source)
                repository_url = model_server.explicit_source_repository(config)
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
        return model_server.source_repository(deployer_config)

    @staticmethod
    def _ai_model_hub_model_server_source_ref(deployer_config):
        return model_server.source_ref(deployer_config)

    @staticmethod
    def _ai_model_hub_model_server_source_refresh_enabled(deployer_config):
        return model_server.source_refresh_enabled(deployer_config)

    @staticmethod
    def _git_stdout(args):
        try:
            result = subprocess.run(
                list(args),
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return ""
        return str(result.stdout or "").strip()

    def _ai_model_hub_model_server_source_metadata(self, source_dir, deployer_config):
        resolved_source_dir = os.path.abspath(os.path.expanduser(str(source_dir or "").strip()))
        repository_url = self._ai_model_hub_model_server_source_repository(deployer_config)
        source_ref = self._ai_model_hub_model_server_source_ref(deployer_config)
        resolved_commit = ""
        git_branch = ""
        dirty = None
        if resolved_source_dir and os.path.isdir(os.path.join(resolved_source_dir, ".git")):
            resolved_commit = self._git_stdout(["git", "-C", resolved_source_dir, "rev-parse", "HEAD"])
            git_branch = self._git_stdout(["git", "-C", resolved_source_dir, "rev-parse", "--abbrev-ref", "HEAD"])
            dirty = bool(self._git_stdout(["git", "-C", resolved_source_dir, "status", "--short"]))

        warnings = []
        reproducibility = "resolved" if resolved_commit else "unresolved"
        if repository_url and source_ref and not resolved_commit:
            warnings.append("Could not resolve the checked-out model-server source commit.")
        if dirty:
            warnings.append("The model-server source checkout has uncommitted changes.")

        return {
            "source_dir": resolved_source_dir,
            "source_repository": repository_url,
            "source_ref": source_ref,
            "resolved_commit": resolved_commit,
            "git_branch": git_branch,
            "dirty": dirty,
            "reproducibility": reproducibility,
            "warnings": warnings,
        }

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
        refresh_enabled = self._ai_model_hub_model_server_source_refresh_enabled(deployer_config)
        if refresh_enabled or source_ref:
            if not os.path.isdir(os.path.join(resolved_source_dir, ".git")):
                self._fail(
                    "AI Model Hub model-server source directory is not usable",
                    root_cause=(
                        f"Expected a Git working tree at {resolved_source_dir}. "
                        "Move it away so Level 5 can clone the configured source, or disable "
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REFRESH."
                    ),
                )
            status = self._run_git_capture(
                ["git", "-C", resolved_source_dir, "status", "--porcelain", "--untracked-files=no"]
            )
            if status.returncode != 0:
                self._fail(
                    "AI Model Hub model-server source directory is not usable",
                    root_cause=f"Could not inspect Git status in {resolved_source_dir}",
                )
            if str(status.stdout or "").strip():
                self._fail(
                    "AI Model Hub model-server source directory has local tracked changes",
                    root_cause=(
                        f"Commit, stash or move {resolved_source_dir} before Level 5 can refresh "
                        "or switch AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF."
                    ),
                )
            subprocess.run(
                ["git", "-C", resolved_source_dir, "remote", "set-url", "origin", resolved_repository_url],
                check=False,
            )
            if refresh_enabled:
                print(f"Refreshing AI Model Hub model-server source from {resolved_repository_url} ...")
                fetch = self._run_git_capture(
                    ["git", "-C", resolved_source_dir, "fetch", "origin", "--tags", "--prune"]
                )
                if fetch.returncode != 0:
                    self._fail(
                        "Could not refresh AI Model Hub model-server source repository",
                        root_cause=(fetch.stderr or fetch.stdout or resolved_repository_url).strip(),
                    )

        if source_ref:
            commit = self._resolve_component_source_ref_commit(
                resolved_source_dir,
                source_ref,
                refresh_enabled,
            )
            if not commit:
                self._fail(
                    "Could not resolve AI Model Hub model-server source ref",
                    root_cause=f"{source_ref} in {resolved_source_dir}",
                )
            current = self._run_git_capture(["git", "-C", resolved_source_dir, "rev-parse", "HEAD"])
            if current.returncode == 0 and str(current.stdout or "").strip() == commit:
                print(f"AI Model Hub model-server source already at requested ref {source_ref}.")
            else:
                print(f"Checking out AI Model Hub model-server source ref {source_ref} ...")
                checkout = self._run_git_capture(["git", "-C", resolved_source_dir, "checkout", "--detach", commit])
                if checkout.returncode != 0:
                    self._fail(
                        "Could not checkout AI Model Hub model-server source ref",
                        root_cause=(checkout.stderr or checkout.stdout or source_ref).strip(),
                    )
        elif not refresh_enabled:
            print(
                "AI Model Hub model-server source ref not configured; using the repository default branch "
                "and recording the resolved commit as deployment evidence."
            )

        return resolved_source_dir

    def _ai_model_hub_model_server_image_ref(self, deployer_config):
        return model_server.image_ref(deployer_config)

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
        explicit = model_server.manifest_path(deployer_config)
        return self._resolve_project_path(explicit) if explicit else ""

    def _ai_model_hub_model_server_readiness_path(self, deployer_config):
        return model_server.readiness_path(
            deployer_config,
            self._ai_model_hub_model_server_mode(deployer_config),
        )

    def _ai_model_hub_model_server_service_url(self, namespace):
        return model_server.service_url(namespace)

    @staticmethod
    def _ai_model_hub_model_server_container_port(deployer_config):
        return model_server.container_port(deployer_config)

    @staticmethod
    def _ai_model_hub_model_server_docker_base_image(deployer_config):
        return model_server.docker_base_image(deployer_config)

    @staticmethod
    def _ai_model_hub_model_server_torch_package(deployer_config):
        return model_server.torch_package(deployer_config)

    @staticmethod
    def _ai_model_hub_model_server_torch_index_url(deployer_config):
        return model_server.torch_index_url(deployer_config)

    @staticmethod
    def _ai_model_hub_model_server_uvicorn_app(deployer_config, mode):
        return model_server.uvicorn_app(deployer_config, mode)

    @staticmethod
    def _ai_model_hub_model_server_image_pull_policy(image_ref, deployer_config):
        return model_server.image_pull_policy(image_ref, deployer_config)

    @staticmethod
    def _ai_model_hub_model_server_copy_excludes(deployer_config):
        return model_server.copy_excludes(deployer_config)

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

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse


DEFAULT_MOCK_HTTP_COUNT = 0
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
    return max(0, min(count, MAX_MOCK_HTTP_COUNT))


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


def _dataset_file_map() -> Dict[str, str]:
    server_dir = _use_case_server_dir()
    candidates = {
        "segments_test.csv": os.path.join(server_dir, "data", "mobility-datasets", "segments_test.csv"),
        "5w1h_subtarea_1_test.json": os.path.join(server_dir, "data", "flares-datasets", "5w1h_subtarea_1_test.json"),
        "5w1h_subtarea_2_test.json": os.path.join(server_dir, "data", "flares-datasets", "5w1h_subtarea_2_test.json"),
    }
    return {name: path for name, path in candidates.items() if os.path.isfile(path)}


@app.get("/datasets")
def datasets() -> Dict[str, Any]:
    return {
        "datasets": [
            {"name": name, "url": f"/datasets/{name}"}
            for name in sorted(_dataset_file_map())
        ]
    }


@app.get("/datasets/{filename}")
def dataset_file(filename: str):
    files = _dataset_file_map()
    path = files.get(filename)
    if not path:
        raise HTTPException(status_code=404, detail="dataset not found")
    media_type = "text/csv" if filename.endswith(".csv") else "application/x-ndjson"
    return FileResponse(path, media_type=media_type, filename=filename)


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
        torch_package = shlex.quote(self._ai_model_hub_model_server_torch_package(deployer_config))
        torch_index_url = shlex.quote(self._ai_model_hub_model_server_torch_index_url(deployer_config))
        dockerfile_lines = [
            f"FROM {self._ai_model_hub_model_server_docker_base_image(deployer_config)}",
            "ENV PYTHONUNBUFFERED=1",
            "ENV PIP_NO_CACHE_DIR=1",
            "WORKDIR /app",
            "RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*",
            "COPY use_cases/requirements.txt /tmp/use-case-requirements.txt",
            (
                "RUN python -m pip install --upgrade pip && "
                "grep -v -E '^torch([<>=~! ].*)?$' /tmp/use-case-requirements.txt "
                "> /tmp/use-case-requirements-no-torch.txt && "
                f"python -m pip install --no-deps --index-url {torch_index_url} {torch_package} && "
                "python -m pip install -r /tmp/use-case-requirements-no-torch.txt"
            ),
            "COPY use_cases /app/use_cases",
            "RUN if [ -d /app/use_cases/models ]; then cp -a /app/use_cases/models /app/models; fi",
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
        return model_server.generated_manifest(
            namespace,
            image_ref,
            mode,
            deployer_config,
        )

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
        return model_server.connector_base_url(namespace, deployer_config)

    def _ai_model_hub_model_server_public_url(self, deployer_config):
        return model_server.public_url(deployer_config)

    def _ai_model_hub_model_server_public_ingress(self, namespace, deployer_config):
        return model_server.public_ingress(
            namespace,
            deployer_config,
            topology=self._normalized_topology(),
        )

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

        runtime = self._cluster_runtime(deployer_config)
        cluster_type = str(runtime.get("cluster_type") or "minikube").strip().lower() or "minikube"
        profile = (
            deployer_config.get("MINIKUBE_PROFILE")
            or getattr(self.config, "MINIKUBE_PROFILE", "minikube")
            or "minikube"
        ).strip() or "minikube"
        pull_policy = self._ai_model_hub_model_server_image_pull_policy(image_ref, deployer_config)
        k3s_import_prerequisites_checked = False

        if not self._level5_auto_build_local_images(deployer_config):
            if cluster_type == "k3s" and pull_policy == "Never":
                if self._k3s_runtime_has_image(image_ref, deployer_config):
                    print(
                        "AI Model Hub model-server auto-build is disabled. "
                        f"Verified k3s runtime already has image '{image_ref}'."
                    )
                    return False
                self._ensure_k3s_local_image_import_supported(image_ref, deployer_config)
                k3s_import_prerequisites_checked = True
                if self._host_has_image(image_ref):
                    print(
                        "AI Model Hub model-server auto-build is disabled, but the image is "
                        f"missing in k3s. Importing host image '{image_ref}' into k3s."
                    )
                    self._load_image_into_cluster_runtime(cluster_type, profile, image_ref, deployer_config)
                    return True
                print(
                    "AI Model Hub model-server image is missing in k3s and uses imagePullPolicy Never. "
                    "Building it from the configured source."
                )
            else:
                print(
                    "AI Model Hub model-server auto-build is disabled. "
                    f"Assuming image '{image_ref}' is already available in the cluster runtime."
                )
                return False

        if cluster_type == "minikube" and not self._minikube_is_available(profile):
            self._fail(
                "Minikube profile is not available for AI Model Hub model-server deployment",
                root_cause=profile,
            )
        if cluster_type == "k3s" and not k3s_import_prerequisites_checked:
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
            self._remove_host_image_if_present(image_ref)
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
        source_metadata = self._ai_model_hub_model_server_source_metadata(source_dir, deployer_config)
        if source_metadata.get("resolved_commit"):
            print(
                "AI Model Hub model-server source commit: "
                f"{source_metadata['resolved_commit']}"
            )
        for warning in source_metadata.get("warnings") or []:
            print(f"Warning: {warning}")

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
            if built_local_image:
                namespace_q = shlex.quote(resolved_namespace)
                if self.run(
                    f"kubectl rollout restart deployment/model-server -n {namespace_q}",
                    check=False,
                ) is None:
                    self._fail("Failed to restart AI Model Hub model-server after image rebuild")
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
            "source": source_metadata,
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

    def _probe_component_public_url(self, url, *, expected_statuses, timeout_seconds=5, follow_redirects=False):
        normalized_url = self._to_public_url(url)
        if not normalized_url:
            return False, "public URL is empty"

        try:
            response = requests.get(
                normalized_url,
                timeout=timeout_seconds,
                allow_redirects=bool(follow_redirects),
                headers={"Cache-Control": "no-store"},
            )
        except Exception as exc:
            return False, f"HTTP probe failed: {exc}"

        status_code = int(getattr(response, "status_code", 0) or 0)
        detail = f"HTTP {status_code}"
        raw_history = getattr(response, "history", []) or []
        history = raw_history if isinstance(raw_history, (list, tuple)) else []
        if follow_redirects and history:
            detail = f"{detail} after {len(history)} redirect(s)"
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
                    follow_redirects=True,
                )
                config_ready, config_detail = self._probe_component_public_url(
                    config_url,
                    expected_statuses={200},
                    follow_redirects=True,
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
