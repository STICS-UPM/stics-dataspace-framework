import json
import os
import shutil

from deployers.infrastructure.lib.config_loader import (
    INFRASTRUCTURE_MANAGED_KEYS,
    load_layered_deployer_config,
)
from deployers.shared.lib.cluster_runtime import build_cluster_runtime
from deployers.infrastructure.lib.public_hostnames import (
    clean_public_hostname,
    resolved_common_service_hostnames,
)
from deployers.infrastructure.lib.namespaces import (
    resolve_namespace_profile_plan,
)
from deployers.infrastructure.lib.paths import (
    legacy_deployer_artifact_dir,
    resolve_shared_artifact_dir,
    shared_artifact_dir,
    use_shared_deployer_artifacts,
)


class InesdataConfig:
    """Centralized INESData technical configuration."""

    REPO_DIR = os.path.join("deployers", "inesdata")
    ADAPTER_NAME = "inesdata"
    DS_NAME = "pionera"
    NS_COMMON = "common-srvs"

    HELM_REPOS = {
        "minio": "https://charts.min.io/",
        "hashicorp": "https://helm.releases.hashicorp.com"
    }

    MINIKUBE_DRIVER = "docker"
    MINIKUBE_CPUS = 4
    MINIKUBE_MEMORY = 12288
    MINIKUBE_PROFILE = "minikube"
    MINIKUBE_ADDONS = ["ingress"]
    MINIKUBE_IP = "192.168.49.2"
    CLUSTER_TYPE = "minikube"
    K3S_KUBECONFIG = "/etc/rancher/k3s/k3s.yaml"

    PORT_POSTGRES = 5432
    PORT_VAULT = 8200
    PORT_MINIO = 9000
    PORT_REGISTRATION_SERVICE = 18080

    TIMEOUT_POD_WAIT = 120
    TIMEOUT_PORT = 30
    TIMEOUT_NAMESPACE = 90

    PATH_VENV = ".venv"
    PATH_REQUIREMENTS = "requirements.txt"

    @classmethod
    def script_dir(cls):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    @classmethod
    def repo_dir(cls):
        return os.path.join(cls.script_dir(), cls.REPO_DIR)

    @classmethod
    def common_dir(cls):
        return resolve_shared_artifact_dir("common", required_file="Chart.yaml")

    @classmethod
    def values_path(cls):
        if cls.use_shared_deployer_artifacts():
            return os.path.join(cls.shared_deployment_runtime_dir("common"), "values.yaml")
        return os.path.join(cls.common_dir(), "values.yaml")

    @classmethod
    def common_values_source_path(cls):
        return os.path.join(cls.common_dir(), "values.yaml")

    @classmethod
    def ensure_common_values_file(cls):
        values_path = cls.values_path()
        if not cls.use_shared_deployer_artifacts():
            return values_path

        source_path = cls.common_values_source_path()
        if not os.path.exists(values_path) and os.path.exists(source_path):
            os.makedirs(os.path.dirname(values_path), exist_ok=True)
            shutil.copy2(source_path, values_path)
        return values_path

    @classmethod
    def deployer_config_path(cls):
        return os.path.join(cls.script_dir(), "deployers", cls.ADAPTER_NAME, "deployer.config")

    @classmethod
    def deployer_config_example_path(cls):
        return os.path.join(cls.script_dir(), "deployers", cls.ADAPTER_NAME, "deployer.config.example")

    @classmethod
    def infrastructure_deployer_config_path(cls):
        return os.path.join(cls.script_dir(), "deployers", "infrastructure", "deployer.config")

    @classmethod
    def infrastructure_deployer_config_example_path(cls):
        return os.path.join(cls.script_dir(), "deployers", "infrastructure", "deployer.config.example")

    @classmethod
    def legacy_deployer_config_path(cls):
        return os.path.join(cls.repo_dir(), "deployer.config")

    @classmethod
    def vault_keys_path(cls):
        if cls.use_shared_deployer_artifacts():
            return cls.vault_keys_runtime_path()
        return os.path.join(cls.common_dir(), "init-keys-vault.json")

    @classmethod
    def vault_keys_runtime_path(cls):
        return str(shared_artifact_dir("common", "init-keys-vault.json"))

    @classmethod
    def ensure_vault_keys_file(cls):
        vault_keys_path = cls.vault_keys_path()
        if not cls.use_shared_deployer_artifacts():
            return vault_keys_path

        return vault_keys_path

    @classmethod
    def adapter_name(cls):
        return str(getattr(cls, "ADAPTER_NAME", "inesdata") or "inesdata").strip().lower()

    @classmethod
    def use_shared_deployer_artifacts(cls):
        return use_shared_deployer_artifacts()

    @classmethod
    def deployment_environment_name(cls):
        adapter = INESDataConfigAdapter(cls)
        config = adapter.load_deployer_config()
        environment = str(config.get("ENVIRONMENT", "DEV")).strip().upper()
        return environment or "DEV"

    @classmethod
    def deployment_runtime_dir(cls):
        return os.path.join(
            cls.script_dir(),
            "deployers",
            cls.adapter_name(),
            "deployments",
            cls.deployment_environment_name(),
            cls.dataspace_name(),
        )

    @classmethod
    def shared_deployment_runtime_dir(cls, *parts):
        return os.path.join(
            cls.script_dir(),
            "deployers",
            "shared",
            "deployments",
            cls.deployment_environment_name(),
            *parts,
        )

    @classmethod
    def venv_path(cls):
        return os.path.join(cls.repo_dir(), cls.PATH_VENV)

    @classmethod
    def python_exec(cls):
        return os.path.join(cls.venv_path(), "bin", "python")

    @classmethod
    def repo_requirements_path(cls):
        return os.path.join(cls.repo_dir(), cls.PATH_REQUIREMENTS)

    @classmethod
    def helm_release_common(cls):
        return "common-srvs"

    @classmethod
    def dataspace_name(cls):
        adapter = INESDataConfigAdapter(cls)
        return adapter.primary_dataspace_name()

    @classmethod
    def dataspace_namespace(cls):
        adapter = INESDataConfigAdapter(cls)
        return adapter.primary_dataspace_namespace()

    @classmethod
    def helm_release_rs(cls):
        return f"{cls.dataspace_name()}-dataspace-rs"

    @classmethod
    def helm_release_public_portal(cls):
        return f"{cls.dataspace_name()}-dataspace-pp"

    @classmethod
    def deploy_public_portal_with_dataspace(cls):
        return True

    @classmethod
    def namespace_demo(cls):
        return cls.dataspace_namespace()

    @classmethod
    def registration_service_namespace(cls):
        adapter = INESDataConfigAdapter(cls)
        return adapter.primary_registration_service_namespace()

    @classmethod
    def registration_service_dir(cls):
        return resolve_shared_artifact_dir("dataspace", "registration-service", required_file="Chart.yaml")

    @classmethod
    def registration_values_file(cls):
        values_name = f"values-{cls.dataspace_name()}.yaml"
        if cls.use_shared_deployer_artifacts():
            return os.path.join(cls.deployment_runtime_dir(), "dataspace", "registration-service", values_name)
        return os.path.join(cls.registration_service_dir(), values_name)

    @classmethod
    def legacy_registration_service_dir(cls):
        return str(legacy_deployer_artifact_dir("inesdata", "dataspace", "registration-service"))

    @classmethod
    def legacy_registration_values_file(cls):
        return os.path.join(cls.legacy_registration_service_dir(), f"values-{cls.dataspace_name()}.yaml")

    @classmethod
    def ensure_registration_values_file(cls, refresh=False):
        values_file = cls.registration_values_file()
        if not cls.use_shared_deployer_artifacts():
            return values_file

        source_file = cls.legacy_registration_values_file()
        if (refresh or not os.path.exists(values_file)) and os.path.exists(source_file):
            os.makedirs(os.path.dirname(values_file), exist_ok=True)
            shutil.copy2(source_file, values_file)
        return values_file

    @classmethod
    def public_portal_dir(cls):
        return resolve_shared_artifact_dir("dataspace", "public-portal", required_file="Chart.yaml")

    @classmethod
    def public_portal_values_file(cls):
        values_name = f"values-{cls.dataspace_name()}.yaml"
        if cls.use_shared_deployer_artifacts():
            return os.path.join(cls.deployment_runtime_dir(), "dataspace", "public-portal", values_name)
        return os.path.join(cls.public_portal_dir(), values_name)

    @classmethod
    def legacy_public_portal_dir(cls):
        return str(legacy_deployer_artifact_dir("inesdata", "dataspace", "public-portal"))

    @classmethod
    def legacy_public_portal_values_file(cls):
        return os.path.join(cls.legacy_public_portal_dir(), f"values-{cls.dataspace_name()}.yaml")

    @classmethod
    def ensure_public_portal_values_file(cls, refresh=False):
        values_file = cls.public_portal_values_file()
        if not cls.use_shared_deployer_artifacts():
            return values_file

        source_file = cls.legacy_public_portal_values_file()
        if (refresh or not os.path.exists(values_file)) and os.path.exists(source_file):
            os.makedirs(os.path.dirname(values_file), exist_ok=True)
            shutil.copy2(source_file, values_file)
        return values_file

    @classmethod
    def sql_dataspace_name(cls):
        return cls.dataspace_name().replace("-", "_")

    @classmethod
    def registration_db_name(cls):
        return f"{cls.sql_dataspace_name()}_rs"

    @classmethod
    def registration_db_user(cls):
        return f"{cls.sql_dataspace_name()}_rsusr"

    @classmethod
    def webportal_db_name(cls):
        return f"{cls.sql_dataspace_name()}_wp"

    @classmethod
    def webportal_db_user(cls):
        return f"{cls.sql_dataspace_name()}_wpusr"

    @classmethod
    def connector_dir(cls):
        return os.path.join(cls.repo_dir(), "connector")

    @classmethod
    def connector_values_file(cls, connector_name):
        return os.path.join(cls.connector_dir(), f"values-{connector_name}.yaml")

    @classmethod
    def connector_credentials_path(cls, connector_name):
        return os.path.join(
            cls.repo_dir(),
            "deployments",
            "DEV",
            cls.dataspace_name(),
            f"credentials-connector-{connector_name}.json"
        )

    @classmethod
    def service_vault(cls):
        return f"{cls.NS_COMMON}-vault-0"

    @classmethod
    def service_postgres(cls):
        return f"{cls.NS_COMMON}-postgresql-0"

    @classmethod
    def service_minio(cls):
        return "minio"

    @classmethod
    def host_alias_domains(cls, ds_name=None, ds_namespace=None):
        adapter = INESDataConfigAdapter(cls)
        return adapter.host_alias_domains(ds_name=ds_name, ds_namespace=ds_namespace)

    @classmethod
    def ds_domain_base(cls):
        adapter = INESDataConfigAdapter(cls)
        return adapter.ds_domain_base()


class INESDataConfigAdapter:
    """Contains INESData configuration access logic."""

    def __init__(self, config_cls=None, topology="local"):
        self.config = config_cls or InesdataConfig
        self.topology = str(topology or "local").strip().lower() or "local"

    def copy_local_deployer_config(self):
        local_config = self.config.deployer_config_path()
        repo_config = self.config.legacy_deployer_config_path()

        if not os.path.exists(local_config):
            print(f"Local INESData deployer.config not found: {local_config}. Skipping copy.")
            return False

        if os.path.abspath(local_config) == os.path.abspath(repo_config):
            return True

        try:
            os.makedirs(os.path.dirname(repo_config), exist_ok=True)
            shutil.copy2(local_config, repo_config)
            print("Local INESData deployer.config copied into repository\n")
            return True
        except Exception as e:
            print(f"Error copying deployer.config: {e}")
            return False

    def _infrastructure_deployer_config_path(self):
        resolver = getattr(self.config, "infrastructure_deployer_config_path", None)
        if callable(resolver):
            return resolver()
        script_dir = getattr(self.config, "script_dir", None)
        if callable(script_dir):
            return os.path.join(script_dir(), "deployers", "infrastructure", "deployer.config")
        return ""

    def load_deployer_config(self):
        adapter_config_path = self.config.deployer_config_path()
        return load_layered_deployer_config(
            [
                self._infrastructure_deployer_config_path(),
                adapter_config_path,
            ],
            protected_keys=INFRASTRUCTURE_MANAGED_KEYS,
            topology=self.topology,
        )

    @staticmethod
    def _normalized_string(value, fallback):
        normalized = str(value or "").strip()
        if normalized:
            return normalized
        return str(fallback or "").strip()

    @staticmethod
    def _normalized_positive_int_string(value, fallback):
        fallback_value = str(fallback or "").strip() or "0"
        try:
            parsed = int(str(value or "").strip())
        except (TypeError, ValueError):
            return fallback_value
        if parsed <= 0:
            return fallback_value
        return str(parsed)

    def foundation_minikube_runtime(self):
        """Return shared Level 1 Minikube runtime settings with config/env overrides."""
        config = self.load_deployer_config()
        topology = str(getattr(self, "topology", "local") or "local").strip().lower()
        default_cpus = 8 if topology == "vm-single" else getattr(self.config, "MINIKUBE_CPUS", 4)
        default_memory = 24576 if topology == "vm-single" else getattr(self.config, "MINIKUBE_MEMORY", 12288)
        return {
            "driver": self._normalized_string(
                config.get("MINIKUBE_DRIVER"),
                getattr(self.config, "MINIKUBE_DRIVER", "docker"),
            ),
            "cpus": self._normalized_positive_int_string(
                config.get("MINIKUBE_CPUS"),
                default_cpus,
            ),
            "memory": self._normalized_positive_int_string(
                config.get("MINIKUBE_MEMORY"),
                default_memory,
            ),
            "profile": self._normalized_string(
                config.get("MINIKUBE_PROFILE"),
                getattr(self.config, "MINIKUBE_PROFILE", "minikube"),
            ),
            "local_resource_profile": self._normalized_string(
                config.get("LOCAL_RESOURCE_PROFILE"),
                "",
            ),
        }

    def cluster_runtime(self):
        """Return the configured cluster runtime without changing current defaults."""
        config = self.load_deployer_config()
        runtime = build_cluster_runtime(config, topology=self.topology)
        return {
            **runtime,
            "k3s_kubeconfig": self._normalized_string(
                runtime.get("k3s_kubeconfig"),
                getattr(self.config, "K3S_KUBECONFIG", "/etc/rancher/k3s/k3s.yaml"),
            ),
        }

    @staticmethod
    def _resolve_optional_path(base_dir, raw_path):
        if not raw_path:
            return None

        candidate = str(raw_path).strip()
        if not candidate:
            return None

        if os.path.isabs(candidate):
            return candidate

        return os.path.abspath(os.path.join(base_dir, candidate))

    def kafka_runtime_config(self):
        """Return centralized Kafka runtime settings sourced from deployer.config."""
        config = self.load_deployer_config()
        base_dir = self.config.script_dir()
        configured_probe_namespaces = config.get("KAFKA_K8S_PROBE_NAMESPACES")
        default_probe_namespaces = ",".join(
            namespace
            for namespace in dict.fromkeys(
                [
                    self.primary_provider_namespace(),
                    self.primary_consumer_namespace(),
                    self.primary_dataspace_namespace(),
                ]
            )
            if namespace
        )

        kafka_provisioner = config.get("KAFKA_PROVISIONER", "kubernetes")
        default_validation_backend = (
            "kubernetes-exec"
            if str(kafka_provisioner or "").strip().lower().startswith("kubernetes")
            else "python-client"
        )

        runtime = {
            "provisioner": kafka_provisioner,
            "bootstrap_servers": config.get("KAFKA_BOOTSTRAP_SERVERS", ""),
            "topic_name": config.get("KAFKA_TOPIC_NAME", "kafka-stream-topic"),
            "topic_strategy": config.get("KAFKA_TOPIC_STRATEGY", "STATIC_TOPIC"),
            "security_protocol": config.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
            "container_name": config.get("KAFKA_CONTAINER_NAME", "kafka-local"),
            "container_image": config.get("KAFKA_CONTAINER_IMAGE", "confluentinc/cp-kafka:7.5.2"),
            "k8s_namespace": config.get("KAFKA_K8S_NAMESPACE") or self.primary_dataspace_namespace(),
            "k8s_probe_namespaces": configured_probe_namespaces or default_probe_namespaces,
            "k8s_service_name": config.get("KAFKA_K8S_SERVICE_NAME", "framework-kafka"),
            "k8s_local_port": config.get("KAFKA_K8S_LOCAL_PORT", "39092"),
            "minikube_profile": config.get("KAFKA_MINIKUBE_PROFILE", "minikube"),
            "topology": self.topology,
            "validation_backend": config.get(
                "KAFKA_EDC_VALIDATION_BACKEND",
                default_validation_backend,
            ),
        }

        optional_mapping = {
            "sasl_mechanism": "KAFKA_SASL_MECHANISM",
            "username": "KAFKA_USERNAME",
            "password": "KAFKA_PASSWORD",
            "cluster_bootstrap_servers": "KAFKA_CLUSTER_BOOTSTRAP_SERVERS",
            "cluster_advertised_host": "KAFKA_CLUSTER_ADVERTISED_HOST",
            "k8s_nodeport": "KAFKA_K8S_NODEPORT",
            "message_count": "KAFKA_MESSAGE_COUNT",
            "message_size_bytes": "KAFKA_MESSAGE_SIZE_BYTES",
            "poll_timeout_seconds": "KAFKA_POLL_TIMEOUT_SECONDS",
            "consumer_group_prefix": "KAFKA_CONSUMER_GROUP_PREFIX",
            "request_timeout_ms": "KAFKA_REQUEST_TIMEOUT_MS",
            "api_timeout_ms": "KAFKA_API_TIMEOUT_MS",
            "max_block_ms": "KAFKA_MAX_BLOCK_MS",
            "consumer_request_timeout_ms": "KAFKA_CONSUMER_REQUEST_TIMEOUT_MS",
            "topic_ready_timeout_seconds": "KAFKA_TOPIC_READY_TIMEOUT_SECONDS",
            "validation_backend": "KAFKA_EDC_VALIDATION_BACKEND",
        }
        for key, config_key in optional_mapping.items():
            value = config.get(config_key)
            if value not in (None, ""):
                runtime[key] = value

        container_env_file = self._resolve_optional_path(base_dir, config.get("KAFKA_CONTAINER_ENV_FILE"))
        if container_env_file:
            runtime["container_env_file"] = container_env_file

        return runtime

    def get_pg_credentials(self):
        config = self.load_deployer_config()
        return (
            config.get("PG_HOST", "localhost"),
            config.get("PG_USER", "postgres"),
            config.get("PG_PASSWORD")
        )

    def get_pg_port(self):
        config = self.load_deployer_config()
        return str(config.get("PG_PORT") or "5432").strip() or "5432"

    def primary_dataspace_name(self):
        config = self.load_deployer_config()
        configured = (config.get("DS_1_NAME") or "").strip()
        if configured:
            return configured
        fallback = getattr(self.config, "DS_NAME", "pionera")
        return (fallback or "pionera").strip() or "pionera"

    def primary_dataspace_namespace(self):
        config = self.load_deployer_config()
        configured = (config.get("DS_1_NAMESPACE") or "").strip()
        if configured:
            return configured
        return self.primary_dataspace_name()

    def primary_registration_service_namespace(self):
        return self.namespace_plan_for_dataspace(ds_index=1)["namespace_roles"].registration_service_namespace

    def primary_provider_namespace(self):
        return self.namespace_plan_for_dataspace(ds_index=1)["namespace_roles"].provider_namespace

    def primary_consumer_namespace(self):
        return self.namespace_plan_for_dataspace(ds_index=1)["namespace_roles"].consumer_namespace

    def dataspace_index(self, ds_name=None, ds_namespace=None):
        config = self.load_deployer_config()
        target_name = str(ds_name or "").strip()
        target_namespace = str(ds_namespace or "").strip()

        index = 1
        while True:
            configured_name = str(config.get(f"DS_{index}_NAME") or "").strip()
            configured_namespace = str(config.get(f"DS_{index}_NAMESPACE") or configured_name).strip()
            if not configured_name:
                break
            if target_name and configured_name == target_name:
                return index
            if target_namespace and configured_namespace == target_namespace:
                return index
            index += 1
        return 1

    @staticmethod
    def registration_service_service_name(ds_name):
        normalized_name = str(ds_name or "").strip()
        return f"{normalized_name}-registration-service" if normalized_name else "registration-service"

    def registration_service_internal_hostname(
        self,
        *,
        ds_name=None,
        ds_namespace=None,
        connector_namespace=None,
        ds_index=None,
        include_port=True,
    ):
        resolved_name = str(ds_name or self.primary_dataspace_name()).strip() or self.primary_dataspace_name()
        resolved_namespace = str(ds_namespace or self.primary_dataspace_namespace()).strip() or self.primary_dataspace_namespace()
        resolved_index = ds_index or self.dataspace_index(resolved_name, resolved_namespace)
        namespace_plan = self.namespace_plan_for_dataspace(
            ds_name=resolved_name,
            ds_namespace=resolved_namespace,
            ds_index=resolved_index,
        )
        runtime_roles = namespace_plan["namespace_roles"]
        registration_namespace = runtime_roles.registration_service_namespace or resolved_namespace
        active_connector_namespace = str(
            connector_namespace
            or runtime_roles.provider_namespace
            or resolved_namespace
        ).strip() or resolved_namespace
        service_name = self.registration_service_service_name(resolved_name)
        if registration_namespace and registration_namespace != active_connector_namespace:
            hostname = f"{service_name}.{registration_namespace}.svc.cluster.local"
        else:
            hostname = service_name
        if include_port:
            return f"{hostname}:8080"
        return hostname

    def namespace_plan_for_dataspace(self, *, ds_name=None, ds_namespace=None, ds_index=1):
        config = dict(self.load_deployer_config() or {})
        ds_name = str(ds_name or self.primary_dataspace_name()).strip() or self.primary_dataspace_name()
        ds_namespace = str(ds_namespace or self.primary_dataspace_namespace()).strip() or self.primary_dataspace_namespace()

        try:
            resolved_index = int(ds_index)
        except (TypeError, ValueError):
            resolved_index = 1
        if resolved_index < 1:
            resolved_index = 1

        if resolved_index != 1:
            for suffix in (
                "REGISTRATION_NAMESPACE",
                "PROVIDER_NAMESPACE",
                "CONSUMER_NAMESPACE",
            ):
                primary_key = f"DS_1_{suffix}"
                scoped_key = f"DS_{resolved_index}_{suffix}"
                config.pop(primary_key, None)
                scoped_value = str(config.get(scoped_key) or "").strip()
                if scoped_value:
                    config[primary_key] = scoped_value

        return resolve_namespace_profile_plan(
            config,
            dataspace_name=ds_name,
            dataspace_namespace=ds_namespace,
            common_default=getattr(self.config, "NS_COMMON", "common-srvs"),
            components_default="components",
        )

    def generate_hosts(self, ds_name=None):
        config = self.load_deployer_config()
        ds_name = ds_name or self.primary_dataspace_name()
        hosts = []

        for hostname in self._common_service_host_alias_domains(config):
            hosts.append(f"127.0.0.1 {hostname}")

        ds_domain = config.get("DS_DOMAIN_BASE")

        if ds_domain and ds_name:
            hosts.append(f"127.0.0.1 {ds_name}.{ds_domain}")
            hosts.append(f"127.0.0.1 backend-{ds_name}.{ds_domain}")
            hosts.append(f"127.0.0.1 registration-service-{ds_name}.{ds_domain}")

        return hosts

    def host_alias_domains(self, ds_name=None, ds_namespace=None):
        resolved_name = str(ds_name or self.primary_dataspace_name()).strip() or self.primary_dataspace_name()
        del ds_namespace
        ds_domain = self.ds_domain_base() or "dev.ds.dataspaceunit.upm"
        hostnames = self._common_service_host_alias_domains(self.load_deployer_config())
        hostnames.append(f"{resolved_name}.{ds_domain}")
        hostnames.append(f"backend-{resolved_name}.{ds_domain}")
        hostnames.append(f"registration-service-{resolved_name}.{ds_domain}")
        return hostnames

    @staticmethod
    def _clean_hostname(value):
        return clean_public_hostname(value)

    def _common_service_host_alias_domains(self, config):
        hostnames = list(resolved_common_service_hostnames(config).values())
        deduped = []
        for hostname in hostnames:
            if hostname and hostname not in deduped:
                deduped.append(hostname)
        return deduped

    def generate_connector_hosts(self, connectors):
        config = self.load_deployer_config()
        ds_domain = config.get("DS_DOMAIN_BASE")
        if not ds_domain:
            return []

        hosts = []
        for connector in connectors or []:
            hosts.append(f"127.0.0.1 {connector}.{ds_domain}")
        return hosts

    def ds_domain_base(self):
        config = self.load_deployer_config()
        return config.get("DS_DOMAIN_BASE")

    def describe(self) -> str:
        return "INESDataConfigAdapter contains configuration logic for INESData."

