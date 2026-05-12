"""Stable INESData adapter facade import path."""

import json
import os
import shlex
import socket
import subprocess

from .config import INESDataConfigAdapter, InesdataConfig
from .connectors import INESDataConnectorsAdapter
from .deployment import INESDataDeploymentAdapter
from deployers.shared.lib.components import build_component_preview
from adapters.shared import SharedComponentsAdapter, SharedFoundationInfrastructureAdapter


class InesdataAdapter:
    """Facade for all INESData-specific deployment and cluster operations."""

    @staticmethod
    def _default_run(cmd, capture=False, silent=False, check=True, cwd=None):
        if not silent:
            print(f"\nExecuting: {cmd}")

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                text=True,
                capture_output=capture,
                cwd=cwd
            )

            if result.returncode != 0:
                if check:
                    print(f"Command failed with exit code {result.returncode}")
                return None

            if capture:
                return result.stdout.strip()

            return result
        except Exception as e:
            print(f"Execution error: {e}")
            return None

    @classmethod
    def _default_run_silent(cls, cmd, cwd=None):
        return cls._default_run(cmd, capture=True, silent=True, check=False, cwd=cwd)

    def __init__(
        self,
        run=None,
        run_silent=None,
        auto_mode_getter=lambda: False,
        config_cls=None,
        dry_run=False,
        topology="local",
    ):
        run = run or self._default_run
        run_silent = run_silent or self._default_run_silent
        self.run = run
        self.run_silent = run_silent
        self.auto_mode_getter = auto_mode_getter
        self.dry_run = dry_run
        self.topology = str(topology or "local").strip().lower() or "local"
        self.config = config_cls or InesdataConfig
        self.config_adapter = INESDataConfigAdapter(self.config, topology=self.topology)
        self.infrastructure = SharedFoundationInfrastructureAdapter(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            config_adapter=self.config_adapter,
            config_cls=self.config,
        )
        self.deployment = INESDataDeploymentAdapter(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            infrastructure_adapter=self.infrastructure,
            config_adapter=self.config_adapter,
            config_cls=self.config,
        )
        self.connectors = INESDataConnectorsAdapter(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            infrastructure_adapter=self.infrastructure,
            config_adapter=self.config_adapter,
            config_cls=self.config,
        )
        self.components = SharedComponentsAdapter(
            run=run,
            run_silent=run_silent,
            auto_mode_getter=auto_mode_getter,
            infrastructure_adapter=self.infrastructure,
            config_adapter=self.config_adapter,
            config_cls=self.config,
            active_adapter="inesdata",
        )
        self.deployment.connectors_adapter = self.connectors
        self.connectors.deployment_adapter = self.deployment

    def setup_cluster(self):
        return self.infrastructure.setup_cluster()

    def deploy_infrastructure(self):
        return self.infrastructure.deploy_infrastructure()

    def deploy_dataspace(self):
        return self.deployment.deploy_dataspace()

    def build_recreate_dataspace_plan(self):
        return self.deployment.build_recreate_dataspace_plan()

    def recreate_dataspace(self, confirm_dataspace=None):
        return self.deployment.recreate_dataspace(confirm_dataspace=confirm_dataspace)

    def deploy_connectors(self):
        return self.connectors.deploy_connectors()

    def wait_for_all_connectors(self, connectors):
        return self.connectors.wait_for_all_connectors(connectors)

    def get_cluster_connectors(self):
        return self.connectors.get_cluster_connectors()

    def load_deployer_config(self):
        return self.config_adapter.load_deployer_config()

    def load_connector_credentials(self, connector_name):
        return self.connectors.load_connector_credentials(connector_name)

    def build_connector_url(self, connector_name):
        return self.connectors.build_connector_url(connector_name)

    def cleanup_test_entities(self, connector_name):
        return self.connectors.cleanup_test_entities(connector_name)

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
        return self.config.namespace_demo()

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
        registration_pod = self.infrastructure.get_pod_by_name(namespace, "registration-service")
        pod_output = self.run_silent(f"kubectl get pods -n {namespace} --no-headers") or ""
        pod_names = []
        for line in pod_output.splitlines():
            columns = line.split()
            if columns:
                pod_names.append(columns[0])

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
            "dataspace": self.config_adapter.primary_dataspace_name(),
            "namespace": namespace,
            "registration_service_pod": registration_pod,
            "schema_ready": schema_ready,
            "pod_count": len(pod_names),
            "issues": issues,
        }

    def _preview_connectors(self):
        configured_connectors = []
        connector_layouts = {}
        dataspace_entries = []
        loader = getattr(self.connectors, "load_dataspace_connectors", None)
        if callable(loader):
            dataspaces = loader() or []
            for dataspace in dataspaces:
                dataspace_entries.append(
                    {
                        "name": dataspace.get("name"),
                        "namespace": dataspace.get("namespace"),
                        "namespace_profile": dataspace.get("namespace_profile", "compact"),
                        "namespace_roles": dict(dataspace.get("namespace_roles") or {}),
                        "planned_namespace_roles": dict(dataspace.get("planned_namespace_roles") or {}),
                        "connector_roles": dict(dataspace.get("connector_roles") or {}),
                    }
                )
                for detail in dataspace.get("connector_details") or []:
                    name = detail.get("name")
                    if name:
                        connector_layouts[name] = detail
                configured_connectors.extend(list(dataspace.get("connectors") or []))

        configured_connectors = list(dict.fromkeys(configured_connectors))
        cluster_connectors = set(self.get_cluster_connectors() or [])
        connector_entries = []
        all_ready = True
        for connector in configured_connectors:
            ready = connector in cluster_connectors
            layout = connector_layouts.get(connector, {})
            connector_entries.append(
                {
                    "name": connector,
                    "role": layout.get("role"),
                    "portal_url": self.build_connector_url(connector),
                    "target_namespace": self.connectors._connector_target_namespace(connector),
                    "active_namespace": layout.get("active_namespace", self.config.namespace_demo()),
                    "planned_namespace": layout.get("planned_namespace", self.config.namespace_demo()),
                    "registration_service_namespace": layout.get("registration_service_namespace"),
                    "planned_registration_service_namespace": layout.get("planned_registration_service_namespace"),
                    "status": "ready" if ready else "missing",
                    "issues": [] if ready else ["connector runtime pod not found in target namespace"],
                }
            )
            all_ready = all_ready and ready

        return {
            "status": "ready" if all_ready else "missing",
            "action": "reuse" if all_ready else "deploy_connectors",
            "namespace": self.config.namespace_demo(),
            "dataspaces": dataspace_entries,
            "connectors": connector_entries,
            "issues": [] if all_ready else ["One or more INESData connectors are not present in the cluster"],
        }

    def _preview_components(self):
        summary_getter = getattr(self.components, "configured_components_summary", None)
        if callable(summary_getter):
            summary = dict(summary_getter() or {})
        else:
            config = self.config_adapter.load_deployer_config() or {}
            configured = [token.strip() for token in str(config.get("COMPONENTS", "") or "").split(",") if token.strip()]
            summary = {
                "configured": configured,
                "deployable": configured,
                "pending_support": [],
                "unsupported": [],
                "unknown": [],
            }

        configured = list(summary.get("configured") or [])
        if not configured:
            return {
                "status": "not-applicable",
                "action": "skip",
                "components": [],
                "issues": [],
            }

        try:
            inferred_urls = self.components.infer_component_urls(summary.get("deployable") or [])
        except Exception as exc:
            inferred_urls = {}
            issues = [str(exc)]
        else:
            issues = []
        payload = build_component_preview(
            configured=configured,
            deployable=summary.get("deployable"),
            pending_support=summary.get("pending_support"),
            unsupported=summary.get("unsupported"),
            unknown=summary.get("unknown"),
            inferred_urls=inferred_urls,
        )
        payload["issues"] = issues
        return payload

    def preview_deploy(self):
        common_services = self._preview_common_services()
        dataspace = self._preview_dataspace()
        connectors = self._preview_connectors()
        components = self._preview_components()

        if common_services["status"] != "ready":
            status = "shared-services-required"
            next_step = "Deploy or repair the shared common services before running the INESData deployment."
        elif dataspace["status"] != "ready":
            status = "dataspace-required"
            next_step = "Deploy or repair the dataspace services before running the INESData connector deployment."
        elif connectors["status"] != "ready":
            status = "connectors-required"
            next_step = "Deploy or repair the INESData connectors before relying on this dataspace."
        else:
            status = "ready"
            next_step = "The local shared foundation and the INESData dataspace are ready."

        return {
            "status": status,
            "shared_common_services": common_services,
            "shared_dataspace": dataspace,
            "connectors": connectors,
            "components": components,
            "next_step": next_step,
        }

    def _kafka_runtime_config(self):
        loader = getattr(self.config_adapter, "kafka_runtime_config", None)
        if callable(loader):
            config = loader()
            if isinstance(config, dict):
                runtime = dict(config)
                dataspaces = self.connectors.load_dataspace_connectors() or []
                if len(dataspaces) == 1:
                    dataspace = dataspaces[0]
                    role_summary = dict(dataspace.get("connector_roles") or {})
                    provider_connector = role_summary.get("provider")
                    if (
                        provider_connector
                        and self.connectors._role_aligned_level4_namespaces_active(
                            dataspace,
                            dataspaces=dataspaces,
                        )
                    ):
                        target_namespace = self.connectors.connector_target_namespace(provider_connector)
                        if target_namespace:
                            runtime["k8s_namespace"] = target_namespace
                return runtime
        return {}

    def _kafka_container_name(self):
        return self._kafka_runtime_config().get("container_name", "kafka-local")

    def _kafka_bootstrap_servers(self):
        return self._kafka_runtime_config().get("bootstrap_servers", "localhost:9092")

    @staticmethod
    def _parse_kafka_address(address):
        address = str(address or "").strip()
        if "://" in address:
            address = address.split("://", 1)[1]
        if address.count(":") > 1 and address.startswith("["):
            host, _, port = address.rpartition(":")
            return host.strip("[]"), int(port or 9092)
        if ":" in address:
            host, port = address.rsplit(":", 1)
            return host, int(port or 9092)
        return address, 9092

    def _is_kafka_bootstrap_reachable(self):
        bootstrap_servers = self._kafka_bootstrap_servers()
        for candidate in str(bootstrap_servers or "").split(","):
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                host, port = self._parse_kafka_address(candidate)
                with socket.create_connection((host, port), timeout=2):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _load_kafka_admin_dependencies():
        from kafka.admin import KafkaAdminClient, NewTopic
        from kafka.errors import TopicAlreadyExistsError

        return KafkaAdminClient, NewTopic, TopicAlreadyExistsError

    def _kafka_admin_config(self):
        runtime = self.get_kafka_config()
        config = {
            "bootstrap_servers": runtime.get("bootstrap_servers", "localhost:9092"),
            "client_id": "inesdata-framework-topic-admin",
        }

        security_protocol = runtime.get("security_protocol")
        if security_protocol:
            config["security_protocol"] = security_protocol

        sasl_mechanism = runtime.get("sasl_mechanism")
        if sasl_mechanism:
            config["sasl_mechanism"] = sasl_mechanism

        username = runtime.get("username")
        password = runtime.get("password")
        if username not in (None, ""):
            config["sasl_plain_username"] = username
        if password not in (None, ""):
            config["sasl_plain_password"] = password

        return config

    def _ensure_kafka_topic_via_admin(self, topic_name):
        kafka_admin_client, new_topic_cls, topic_exists_exc = self._load_kafka_admin_dependencies()
        admin_client = kafka_admin_client(**self._kafka_admin_config())
        created = False

        try:
            existing_topics = set(admin_client.list_topics() or [])
            if topic_name in existing_topics:
                print(f"Kafka topic '{topic_name}' already exists")
                return True

            topic = new_topic_cls(name=topic_name, num_partitions=1, replication_factor=1)
            try:
                admin_client.create_topics([topic])
                created = True
            except topic_exists_exc:
                pass

            existing_topics = set(admin_client.list_topics() or [])
            if topic_name in existing_topics:
                if created:
                    print(f"Created Kafka topic: {topic_name}")
                else:
                    print(f"Kafka topic '{topic_name}' already exists")
                return True

            print(f"Kafka topic '{topic_name}' could not be verified after creation")
            return False
        finally:
            close_method = getattr(admin_client, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception:
                    pass

    def _resolve_kafka_container_id(self):
        container_name = self._kafka_container_name()
        result = self.run_silent(
            f"docker ps --filter name={shlex.quote(container_name)} --format '{{{{.ID}}}}'"
        )
        if not result:
            return None
        return result.splitlines()[0].strip() or None

    def is_kafka_available(self):
        """Check if Kafka container is running and accessible."""
        try:
            return self._is_kafka_bootstrap_reachable() or bool(self._resolve_kafka_container_id())
        except Exception:
            return False

    def ensure_kafka_topic(self, topic_name="kafka-stream-topic"):
        """Ensure Kafka topic exists, creating it when necessary."""
        try:
            return self._ensure_kafka_topic_via_admin(topic_name)
        except Exception as exc:
            print(f"Kafka admin topic ensure failed via bootstrap servers: {exc}")

        if not self.is_kafka_available():
            print("Kafka container not running")
            return False

        try:
            container_id = self._resolve_kafka_container_id()
            bootstrap_servers = self._kafka_bootstrap_servers()
            if not container_id:
                print("Kafka container id could not be resolved")
                return False

            result = self.run_silent(
                f"docker exec {shlex.quote(container_id)} "
                f"kafka-topics --list --bootstrap-server {shlex.quote(bootstrap_servers)}"
            )

            if result and topic_name in result:
                print(f"Kafka topic '{topic_name}' already exists")
                return True

            self.run_silent(
                f"docker exec {shlex.quote(container_id)} "
                f"kafka-topics --create --topic {shlex.quote(topic_name)} "
                f"--bootstrap-server {shlex.quote(bootstrap_servers)} "
                f"--partitions 1 --replication-factor 1"
            )

            print(f"Created Kafka topic: {topic_name}")
            return True
        except Exception as exc:
            print(f"Error managing Kafka topic: {exc}")
            return False

    def get_kafka_config(self):
        """Return centralized Kafka configuration for local INESData setups."""
        config = self._kafka_runtime_config()

        optional_env_mapping = {
            "security_protocol": "KAFKA_SECURITY_PROTOCOL",
            "sasl_mechanism": "KAFKA_SASL_MECHANISM",
            "username": "KAFKA_USERNAME",
            "password": "KAFKA_PASSWORD",
            "container_env_file": "KAFKA_CONTAINER_ENV_FILE",
        }
        for key, env_name in optional_env_mapping.items():
            value = os.getenv(env_name)
            if key not in config and value not in (None, ""):
                config[key] = value

        return config

    def describe(self) -> str:
        return (
            "InesdataAdapter encapsulates Kubernetes, Helm, Vault, MinIO, "
            "connector and deployers/inesdata logic for INESData."
        )


__all__ = [
    "InesdataAdapter",
    "InesdataConfig",
    "INESDataConfigAdapter",
    "INESDataInfrastructureAdapter",
    "INESDataDeploymentAdapter",
    "INESDataConnectorsAdapter",
]
