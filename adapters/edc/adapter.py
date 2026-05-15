"""Stable generic EDC adapter facade import path."""

import json
import os
import sys

from adapters.inesdata.adapter import InesdataAdapter
from adapters.shared import SharedComponentsAdapter, SharedFoundationInfrastructureAdapter

from .config import EDCConfigAdapter, EdcConfig
from .connectors import EDCConnectorsAdapter
from .deployment import EDCDeploymentAdapter


class EdcAdapter(InesdataAdapter):
    """Facade for generic EDC deployment and validation integration."""

    def __init__(self, run=None, run_silent=None, auto_mode_getter=lambda: False, config_cls=None, dry_run=False, topology="local"):
        resolved_config = config_cls or EdcConfig
        super().__init__(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            config_cls=resolved_config,
            dry_run=dry_run,
        )

        self.topology = topology or resolved_config.DEFAULT_TOPOLOGY
        self.config = resolved_config
        self.config_adapter = EDCConfigAdapter(self.config, topology=self.topology)
        self.infrastructure = SharedFoundationInfrastructureAdapter(
            run=self.run,
            run_silent=self.run_silent,
            auto_mode_getter=self.auto_mode_getter,
            config_adapter=self.config_adapter,
            config_cls=self.config,
        )
        self.deployment = EDCDeploymentAdapter(
            run=self.run,
            run_silent=self.run_silent,
            auto_mode_getter=self.auto_mode_getter,
            infrastructure_adapter=self.infrastructure,
            config_adapter=self.config_adapter,
            config_cls=self.config,
            topology=self.topology,
        )
        self.connectors = EDCConnectorsAdapter(
            run=self.run,
            run_silent=self.run_silent,
            auto_mode_getter=self.auto_mode_getter,
            infrastructure_adapter=self.infrastructure,
            config_adapter=self.config_adapter,
            config_cls=self.config,
            topology=self.topology,
        )
        self.components = SharedComponentsAdapter(
            run=self.run,
            run_silent=self.run_silent,
            auto_mode_getter=self.auto_mode_getter,
            infrastructure_adapter=self.infrastructure,
            config_adapter=self.config_adapter,
            config_cls=self.config,
            active_adapter="edc",
        )
        self.deployment.connectors_adapter = self.connectors
        self.connectors.deployment_adapter = self.deployment

    def deploy_infrastructure(self):
        common_ready, _ = self.infrastructure.verify_common_services_ready_for_level3()
        if common_ready:
            self.infrastructure.announce_level(2, "DEPLOY COMMON SERVICES")
            print(
                "Existing shared common services are already ready for Level 3. "
                "Reusing them for the shared local foundation."
            )
            self.infrastructure.complete_level(2)
            return True
        return self.infrastructure.deploy_infrastructure()

    @staticmethod
    def _truthy(value):
        return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}

    def _is_level4_common_services_repairable_error(self, error_message):
        if str(getattr(self, "topology", "local") or "local").strip().lower() != "local":
            return False

        code = getattr(self.connectors, "_last_runtime_prerequisite_code", None)
        if code in {"vault_token_mismatch", "vault_token_invalid"}:
            return True

        normalized = str(error_message or "").lower()
        return (
            "local vault token does not match" in normalized
            or "valid vault management token" in normalized
        )

    def _level4_common_services_repair_approved(self, error_message):
        env_value = os.getenv("PIONERA_LEVEL4_REPAIR_COMMON_SERVICES")
        if env_value is not None:
            return self._truthy(env_value)

        print(
            "\nEDC Level 4 detected that the local Vault token no longer matches "
            "the running shared common services."
        )
        print(
            "Repair requires recreating the local common-srvs namespace, regenerating "
            "Vault credentials, rerunning Level 2, rerunning Level 3, and retrying Level 4."
        )
        print("This is only offered for local topology and can affect both EDC and INESData local deployments.")
        print(f"Original error: {error_message}")

        if not sys.stdin.isatty():
            print(
                "Non-interactive execution detected. Set "
                "PIONERA_LEVEL4_REPAIR_COMMON_SERVICES=true to allow this local repair explicitly."
            )
            return False

        response = input("Type RECREATE COMMON SERVICES to continue: ").strip()
        return response == "RECREATE COMMON SERVICES"

    def deploy_connectors(self):
        try:
            return self.connectors.deploy_connectors()
        except RuntimeError as exc:
            if not self._is_level4_common_services_repairable_error(str(exc)):
                raise

            if not self._level4_common_services_repair_approved(str(exc)):
                raise

            resetter = getattr(self.infrastructure, "reset_local_shared_common_services", None)
            if not callable(resetter):
                resetter = getattr(self.infrastructure, "reset_common_services_for_level4_repair", None)
            if not callable(resetter):
                raise RuntimeError(
                    "EDC Level 4 cannot repair shared common services because the infrastructure "
                    "adapter does not expose a controlled reset operation."
                ) from exc

            finalizer = getattr(self.infrastructure, "finalize_local_common_services_reset", None)
            if not callable(finalizer):
                finalizer = getattr(self.infrastructure, "finalize_common_services_level4_repair", None)
            try:
                print("\nRepairing local shared common services before retrying EDC Level 4...")
                if not resetter(reason=str(exc)):
                    raise RuntimeError("EDC Level 4 could not reset local shared common services safely.") from exc

                print("\nRerunning Level 2 after common services repair...")
                level2_result = self.deploy_infrastructure()
                if level2_result is False:
                    raise RuntimeError("EDC Level 4 repair failed while rerunning Level 2.") from exc

                print("\nRerunning Level 3 after common services repair...")
                level3_result = self.deploy_dataspace()
                if level3_result is False:
                    raise RuntimeError("EDC Level 4 repair failed while rerunning Level 3.") from exc

                print("\nRetrying EDC Level 4 after common services repair...")
                result = self.connectors.deploy_connectors()
            except Exception:
                if callable(finalizer):
                    finalizer(success=False)
                raise

            if callable(finalizer):
                finalizer(success=True)
            return result

    def supports_kafka_transfer_validation(self):
        """The generic EDC connector includes the Kafka data-plane extension.

        Level 6 still keeps Kafka transfer validation opt-in because the suite is
        comparatively slow; this hook only advertises that EDC can run it when
        explicitly enabled.
        """
        return True

    def _preview_common_services(self):
        namespace = self.config.NS_COMMON
        pod_output = self.run_silent(f"kubectl get pods -n {namespace} --no-headers") or ""
        release_status_getter = getattr(self.infrastructure, "common_services_release_status", None)
        release_status = release_status_getter() if callable(release_status_getter) else None
        release_name_getter = getattr(self.config, "helm_release_common", None)
        release_name = release_name_getter() if callable(release_name_getter) else "common-srvs"
        ignored_hook_pod = getattr(self.infrastructure, "_is_ignored_transient_hook_pod", None)
        services = {
            "keycloak": {"pod": None, "status": "missing", "ready": False},
            "minio": {"pod": None, "status": "missing", "ready": False},
            "postgresql": {"pod": None, "status": "missing", "ready": False},
            "vault": {"pod": None, "status": "missing", "ready": False},
        }
        prefixes = {
            "keycloak": "common-srvs-keycloak-",
            "minio": "common-srvs-minio-",
            "postgresql": "common-srvs-postgresql-",
            "vault": "common-srvs-vault-",
        }

        for line in pod_output.splitlines():
            columns = line.split()
            if len(columns) < 3:
                continue

            pod_name = columns[0]
            ready = columns[1]
            status = columns[2]

            if callable(ignored_hook_pod) and ignored_hook_pod(namespace, pod_name):
                continue

            for service_name, prefix in prefixes.items():
                if not pod_name.startswith(prefix):
                    continue
                ready_flag = False
                if "/" in ready:
                    ready_current, ready_total = ready.split("/", 1)
                    ready_flag = status == "Running" and ready_current == ready_total

                candidate = {
                    "pod": pod_name,
                    "status": status,
                    "ready": ready_flag,
                }
                current = services[service_name]
                if current["pod"] is None or candidate["ready"] or (
                    not current["ready"]
                    and candidate["status"] == "Running"
                    and current["status"] != "Running"
                ):
                    services[service_name] = candidate
                break

        vault_state = {
            "pod": services["vault"]["pod"],
            "initialized": None,
            "sealed": None,
            "ready": False,
        }
        if services["vault"]["pod"]:
            raw_status = self.run_silent(
                f"kubectl exec {services['vault']['pod']} -n {namespace} -- vault status -format=json"
            )
            if raw_status:
                try:
                    payload = json.loads(raw_status)
                except json.JSONDecodeError:
                    payload = None
                if payload:
                    vault_state["initialized"] = bool(payload.get("initialized"))
                    vault_state["sealed"] = bool(payload.get("sealed"))
                    vault_state["ready"] = vault_state["initialized"] and not vault_state["sealed"]

        issues = []
        for service_name, state in services.items():
            if not state["pod"]:
                issues.append(f"{service_name} pod not found in namespace {namespace}")
            elif not state["ready"] and service_name != "vault":
                issues.append(f"{service_name} pod is not ready (status={state['status']})")

        if services["vault"]["pod"] and not vault_state["ready"]:
            issues.append("Vault is present but not initialized/unsealed")

        if release_status and release_status != "deployed":
            issues.append(f"common services Helm release is {release_status}")

        ready = (
            services["keycloak"]["ready"]
            and services["minio"]["ready"]
            and services["postgresql"]["ready"]
            and services["vault"]["pod"] is not None
            and vault_state["ready"]
            and (not release_status or release_status == "deployed")
        )

        return {
            "status": "ready" if ready else "missing",
            "action": "reuse" if ready else "deploy_infrastructure",
            "namespace": namespace,
            "helm_release": {"name": release_name, "status": release_status or "missing"},
            "services": services,
            "vault": vault_state,
            "issues": issues,
        }

    def _preview_dataspace(self):
        namespace = self._registration_service_namespace()
        ds_name = self.config.dataspace_name()
        pod_output = self.run_silent(f"kubectl get pods -n {namespace} --no-headers") or ""
        pod_names = []
        for line in pod_output.splitlines():
            columns = line.split()
            if columns:
                pod_names.append(columns[0])

        registration_pod = self.infrastructure.get_pod_by_name(namespace, "registration-service")
        schema_ready = False
        if registration_pod:
            schema_ready = bool(
                self.infrastructure.wait_for_registration_service_schema(
                    timeout=1,
                    poll_interval=1,
                    quiet=True,
                )
            )

        issues = []
        if not pod_names:
            issues.append(f"No pods detected in namespace {namespace}")
        if not registration_pod:
            issues.append("registration-service pod not found")
        elif not schema_ready:
            issues.append("registration-service schema is not ready yet")

        ready = bool(pod_names) and bool(registration_pod) and schema_ready
        return {
            "status": "ready" if ready else "missing",
            "action": "reuse" if ready else "deploy_dataspace",
            "dataspace": ds_name,
            "namespace": namespace,
            "registration_service_pod": registration_pod,
            "schema_ready": schema_ready,
            "pod_count": len(pod_names),
            "issues": issues,
        }

    def preview_deploy(self):
        common_services = self._preview_common_services()
        dataspace = self._preview_dataspace()
        connectors = self.connectors.preview_deploy_connectors()

        if connectors.get("status") == "blocked":
            status = "blocked"
            next_step = "Use an isolated dataspace configuration or remove the conflicting runtime resources before deploying EDC."
        elif common_services["status"] != "ready":
            status = "shared-services-required"
            next_step = "Deploy or repair the shared common services before running the EDC connector deployment."
        elif dataspace["status"] != "ready":
            status = "dataspace-required"
            next_step = "Deploy or repair the shared dataspace services before running the EDC connector deployment."
        elif connectors.get("status") == "bootstrap-required":
            status = "bootstrap-required"
            next_step = "Create the connector bootstrap artifacts first so the final EDC values files can be rendered."
        else:
            status = "ready"
            next_step = "The local shared foundation is reusable and the EDC connector chart is ready to deploy."

        return {
            "status": status,
            "topology": self.topology,
            "shared_common_services": common_services,
            "shared_dataspace": dataspace,
            "connectors": connectors,
            "next_step": next_step,
        }
