"""Configuration primitives for the generic EDC adapter."""

import os
import sys

from adapters.inesdata.config import INESDataConfigAdapter, InesdataConfig
from deployers.infrastructure.lib.config_loader import (
    apply_topology_runtime_defaults,
    load_deployer_config,
    resolve_deployer_config_layer_paths,
)
from deployers.shared.lib import runtime_artifacts


class EdcConfig(InesdataConfig):
    """Centralized configuration for the generic EDC adapter."""

    ADAPTER_NAME = "edc"
    REPO_DIR = os.path.join("deployers", "edc")
    DS_NAME = "pionera-edc"
    DEFAULT_TOPOLOGY = "local"
    EDC_NATIVE_BOOTSTRAP = True
    EDC_REFERENCE_REPO_URL = "https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"
    EDC_REFERENCE_REPO_SUBDIR = "asset-filter-template"
    EDC_DASHBOARD_REPO_URL = "https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"
    EDC_DASHBOARD_REPO_REF = "a4cb3e659e1fd3abfa9516a036c261b19432ec13"
    EDC_MANAGEMENT_PORT = 19193
    EDC_PROTOCOL_PORT = 19194
    EDC_MANAGEMENT_PATH = "/management"
    EDC_PROTOCOL_PATH = "/protocol"
    EDC_CONNECTOR_IMAGE_NAME = "ghcr.io/proyectopionera/edc-connector"
    EDC_CONNECTOR_IMAGE_TAG = "latest"
    EDC_CONNECTOR_IMAGE_PULL_POLICY = "IfNotPresent"
    EDC_DASHBOARD_IMAGE_NAME = "validation-environment/edc-dashboard"
    EDC_DASHBOARD_IMAGE_TAG = "latest"
    EDC_DASHBOARD_IMAGE_PULL_POLICY = "IfNotPresent"
    EDC_DASHBOARD_PROXY_IMAGE_NAME = "validation-environment/edc-dashboard-proxy"
    EDC_DASHBOARD_PROXY_IMAGE_TAG = "latest"
    EDC_DASHBOARD_PROXY_IMAGE_PULL_POLICY = "IfNotPresent"
    EDC_DASHBOARD_PROXY_AUTH_MODE = "service-account"
    EDC_DASHBOARD_PROXY_CLIENT_ID = "dataspace-users"
    EDC_DASHBOARD_PROXY_SCOPE = "openid profile email"
    EDC_DASHBOARD_PROXY_COOKIE_NAME = "edc_dashboard_session"
    EDC_DASHBOARD_ENABLED = False
    EDC_DASHBOARD_BASE_HREF = "/edc-dashboard/"
    EDC_SQL_SCHEMA_AUTOCREATE = True
    EDC_MANAGED_LABEL = "edc"

    @classmethod
    def deploy_public_portal_with_dataspace(cls):
        return False

    @classmethod
    def deployer_config_path(cls):
        return os.path.join(cls.script_dir(), "deployers", cls.ADAPTER_NAME, "deployer.config")

    @classmethod
    def deployer_config_example_path(cls):
        return os.path.join(cls.script_dir(), "deployers", cls.ADAPTER_NAME, "deployer.config.example")

    @classmethod
    def python_exec(cls):
        return os.getenv("PIONERA_EDC_BOOTSTRAP_PYTHON", sys.executable)

    @classmethod
    def edc_deployment_dir(cls):
        return cls.repo_dir()

    @classmethod
    def deployment_environment_name(cls):
        adapter = EDCConfigAdapter(cls)
        config = adapter.load_deployer_config()
        environment = str(config.get("ENVIRONMENT", "DEV")).strip().upper()
        return environment or "DEV"

    @classmethod
    def dataspace_name(cls):
        return EDCConfigAdapter(cls).primary_dataspace_name()

    @classmethod
    def dataspace_namespace(cls):
        return EDCConfigAdapter(cls).primary_dataspace_namespace()

    @classmethod
    def ds_domain_base(cls):
        return EDCConfigAdapter(cls).ds_domain_base()

    @classmethod
    def edc_deployments_dir(cls):
        return os.path.join(cls.edc_deployment_dir(), "deployments")

    @classmethod
    def edc_dataspace_runtime_dir(cls):
        return os.path.join(
            cls.edc_deployments_dir(),
            cls.deployment_environment_name(),
            cls.dataspace_name(),
        )

    @classmethod
    def connector_credentials_path(cls, connector_name):
        return os.path.join(
            cls.edc_dataspace_runtime_dir(),
            f"credentials-connector-{connector_name}.json",
        )

    @classmethod
    def connector_certificates_dir(cls):
        return os.path.join(
            cls.edc_dataspace_runtime_dir(),
            "certs",
        )


class EDCConfigAdapter(INESDataConfigAdapter):
    """Configuration access logic for the generic EDC adapter."""

    def __init__(self, config_cls=None, topology="local"):
        super().__init__(config_cls or EdcConfig)
        self.topology = topology or EdcConfig.DEFAULT_TOPOLOGY

    def edc_reference_repo_url(self):
        return self.config.EDC_REFERENCE_REPO_URL

    def edc_reference_repo_subdir(self):
        config = self.load_deployer_config()
        subdir = str(
            config.get("EDC_REFERENCE_REPO_SUBDIR", self.config.EDC_REFERENCE_REPO_SUBDIR)
        ).strip().strip("/")
        return subdir or self.config.EDC_REFERENCE_REPO_SUBDIR

    @staticmethod
    def _read_config_file(path):
        values = {}
        if not path or not os.path.isfile(path):
            return values
        try:
            with open(path, encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
        except OSError:
            return values
        return values

    @staticmethod
    def _apply_environment_overrides(values):
        for env_key, env_value in os.environ.items():
            if not env_key.startswith("PIONERA_"):
                continue
            override_key = env_key[len("PIONERA_"):].strip()
            if not override_key or env_value in (None, ""):
                continue
            values[override_key] = env_value
        return values

    def _edc_default_deployer_values(self):
        return {
            "DS_1_NAME": getattr(self.config, "DS_NAME", "pionera-edc"),
            "DS_1_NAMESPACE": "edc-control",
            "NAMESPACE_PROFILE": "role-aligned",
            "DS_1_REGISTRATION_NAMESPACE": "edc-control",
            "DS_1_PROVIDER_NAMESPACE": "edc-provider",
            "DS_1_CONSUMER_NAMESPACE": "edc-consumer",
            "COMMON_SERVICES_NAMESPACE": "common-srvs",
            "DS_1_CONNECTORS": "citycounciledc,companyedc",
            "COMPONENTS": "",
            "EDC_DASHBOARD_ENABLED": "true",
            "EDC_DASHBOARD_PROXY_AUTH_MODE": "oidc-bff",
            "EDC_SQL_SCHEMA_AUTOCREATE": "true",
        }

    def _legacy_shared_deployer_config_path(self):
        return os.path.join(self.config.script_dir(), "deployers", "inesdata", "deployer.config")

    def load_deployer_config(self):
        values = {}
        # Transitional fallback: keep old local environments working until
        # deployers/infrastructure/deployer.config becomes the common source.
        for path in resolve_deployer_config_layer_paths(
            self._legacy_shared_deployer_config_path(),
            topology=self.topology,
        ):
            values.update(load_deployer_config(path))
        values.update(self._edc_default_deployer_values())
        for path in resolve_deployer_config_layer_paths(
            self._infrastructure_deployer_config_path(),
            topology=self.topology,
        ):
            values.update(load_deployer_config(path))
        for path in resolve_deployer_config_layer_paths(
            self.config.deployer_config_path(),
            topology=self.topology,
        ):
            values.update(load_deployer_config(path))
        apply_topology_runtime_defaults(values, self.topology)
        return self._apply_environment_overrides(values)

    def edc_dashboard_repo_url(self):
        return self.config.EDC_DASHBOARD_REPO_URL

    def edc_dashboard_repo_ref(self):
        config = self.load_deployer_config()
        return str(config.get("EDC_DASHBOARD_REPO_REF", self.config.EDC_DASHBOARD_REPO_REF)).strip()

    def edc_adapter_dir(self):
        return os.path.join(self.config.script_dir(), "adapters", "edc")

    def edc_scripts_dir(self):
        return os.path.join(self.edc_adapter_dir(), "scripts")

    def edc_sources_dir(self):
        return os.path.join(self.edc_adapter_dir(), "sources")

    def edc_connector_source_dir(self):
        return os.path.join(self.edc_sources_dir(), "connector")

    def edc_dashboard_source_dir(self):
        return os.path.join(self.edc_sources_dir(), "dashboard")

    def edc_build_dir(self):
        return os.path.join(self.edc_adapter_dir(), "build")

    def edc_build_docker_dir(self):
        return os.path.join(self.edc_build_dir(), "docker")

    def edc_connector_dockerfile(self):
        return os.path.join(self.edc_build_docker_dir(), "connector.Dockerfile")

    def edc_dashboard_dockerfile(self):
        return os.path.join(self.edc_build_docker_dir(), "dashboard.Dockerfile")

    def edc_dashboard_proxy_dockerfile(self):
        return os.path.join(self.edc_build_docker_dir(), "dashboard-proxy.Dockerfile")

    def edc_local_overrides_dir(self):
        return os.path.join(self.edc_build_dir(), "local-overrides")

    def edc_connector_local_override_file(self):
        return os.path.join(self.edc_local_overrides_dir(), "connector-local-overrides.yaml")

    def edc_dashboard_local_override_file(self):
        return os.path.join(self.edc_local_overrides_dir(), "dashboard-local-overrides.yaml")

    def edc_dashboard_proxy_local_override_file(self):
        return os.path.join(self.edc_local_overrides_dir(), "dashboard-proxy-local-overrides.yaml")

    def edc_deployment_dir(self):
        return self.config.repo_dir()

    def edc_bootstrap_script(self):
        return os.path.join(self.edc_deployment_dir(), "bootstrap.py")

    def deployment_environment_name(self):
        config = self.load_deployer_config()
        environment = str(config.get("ENVIRONMENT", "DEV")).strip().upper()
        return environment or "DEV"

    def edc_deployments_dir(self):
        return os.path.join(self.edc_deployment_dir(), "deployments")

    def edc_dataspace_runtime_dir(self, ds_name=None):
        config = self.load_deployer_config()
        return str(
            runtime_artifacts.dataspace_runtime_dir(
                self.config.ADAPTER_NAME,
                self.deployment_environment_name(),
                ds_name or self.primary_dataspace_name(),
                topology=self.topology,
                config=config,
                root=self.config.script_dir(),
            )
        )

    def edc_connector_dir(self):
        return os.path.join(self.edc_deployment_dir(), "connector")

    def edc_dashboard_runtime_dir(self, connector_name, ds_name=None):
        return os.path.join(
            self.edc_dataspace_runtime_dir(ds_name=ds_name),
            "dashboard",
            connector_name,
        )

    def edc_dashboard_app_config_file(self, connector_name, ds_name=None):
        return os.path.join(
            self.edc_dashboard_runtime_dir(connector_name, ds_name=ds_name),
            "app-config.json",
        )

    def edc_dashboard_connector_config_file(self, connector_name, ds_name=None):
        return os.path.join(
            self.edc_dashboard_runtime_dir(connector_name, ds_name=ds_name),
            "edc-connector-config.json",
        )

    def edc_dashboard_base_href_file(self, connector_name, ds_name=None):
        return os.path.join(
            self.edc_dashboard_runtime_dir(connector_name, ds_name=ds_name),
            "APP_BASE_HREF.txt",
        )

    def edc_connector_values_file(self, connector_name, ds_name=None):
        return os.path.join(
            self.edc_dataspace_runtime_dir(ds_name=ds_name),
            f"values-{connector_name}.yaml",
        )

    def edc_connector_credentials_path(self, connector_name, ds_name=None, for_write=False):
        config = self.load_deployer_config()
        return str(
            runtime_artifacts.connector_credentials_path(
                self.config.ADAPTER_NAME,
                self.deployment_environment_name(),
                ds_name or self.primary_dataspace_name(),
                connector_name,
                topology=self.topology,
                config=config,
                root=self.config.script_dir(),
                prefer_existing=not for_write,
            )
        )

    def connector_credentials_path(self, connector_name, ds_name=None, for_write=False):
        return self.edc_connector_credentials_path(connector_name, ds_name=ds_name, for_write=for_write)

    def edc_connector_certs_dir(self, ds_name=None):
        config = self.load_deployer_config()
        return str(
            runtime_artifacts.connector_certificates_dir(
                self.config.ADAPTER_NAME,
                self.deployment_environment_name(),
                ds_name or self.primary_dataspace_name(),
                None,
                topology=self.topology,
                config=config,
                root=self.config.script_dir(),
            )
        )

    def connector_certificates_dir(self, connector_name=None, ds_name=None):
        del connector_name
        return self.edc_connector_certs_dir(ds_name=ds_name)

    def edc_dataspace_credentials_file(self, ds_name=None):
        return os.path.join(
            self.edc_dataspace_runtime_dir(ds_name=ds_name),
            f"credentials-dataspace-{ds_name or self.primary_dataspace_name()}.json",
        )

    def edc_connector_policy_file(self, connector_name, ds_name=None):
        dataspace = ds_name or self.primary_dataspace_name()
        return os.path.join(
            self.edc_dataspace_runtime_dir(ds_name=dataspace),
            f"policy-{dataspace}-{connector_name}.json",
        )

    def edc_connector_image_name(self):
        config = self.load_deployer_config()
        return config.get("EDC_CONNECTOR_IMAGE_NAME", self.config.EDC_CONNECTOR_IMAGE_NAME)

    def edc_connector_image_tag(self):
        config = self.load_deployer_config()
        return config.get("EDC_CONNECTOR_IMAGE_TAG", self.config.EDC_CONNECTOR_IMAGE_TAG)

    def edc_connector_image_pull_policy(self):
        config = self.load_deployer_config()
        return config.get("EDC_CONNECTOR_IMAGE_PULL_POLICY", self.config.EDC_CONNECTOR_IMAGE_PULL_POLICY)

    def edc_dashboard_image_name(self):
        config = self.load_deployer_config()
        return config.get("EDC_DASHBOARD_IMAGE_NAME", self.config.EDC_DASHBOARD_IMAGE_NAME)

    def edc_dashboard_image_tag(self):
        config = self.load_deployer_config()
        return config.get("EDC_DASHBOARD_IMAGE_TAG", self.config.EDC_DASHBOARD_IMAGE_TAG)

    def edc_dashboard_image_pull_policy(self):
        config = self.load_deployer_config()
        return config.get("EDC_DASHBOARD_IMAGE_PULL_POLICY", self.config.EDC_DASHBOARD_IMAGE_PULL_POLICY)

    def edc_dashboard_proxy_image_name(self):
        config = self.load_deployer_config()
        return config.get("EDC_DASHBOARD_PROXY_IMAGE_NAME", self.config.EDC_DASHBOARD_PROXY_IMAGE_NAME)

    def edc_dashboard_proxy_image_tag(self):
        config = self.load_deployer_config()
        return config.get("EDC_DASHBOARD_PROXY_IMAGE_TAG", self.config.EDC_DASHBOARD_PROXY_IMAGE_TAG)

    def edc_dashboard_proxy_image_pull_policy(self):
        config = self.load_deployer_config()
        return config.get(
            "EDC_DASHBOARD_PROXY_IMAGE_PULL_POLICY",
            self.config.EDC_DASHBOARD_PROXY_IMAGE_PULL_POLICY,
        )

    def edc_dashboard_proxy_auth_mode(self):
        config = self.load_deployer_config()
        return str(
            config.get("EDC_DASHBOARD_PROXY_AUTH_MODE", self.config.EDC_DASHBOARD_PROXY_AUTH_MODE)
        ).strip() or self.config.EDC_DASHBOARD_PROXY_AUTH_MODE

    def edc_dashboard_proxy_client_id(self):
        config = self.load_deployer_config()
        return str(
            config.get("EDC_DASHBOARD_PROXY_CLIENT_ID", self.config.EDC_DASHBOARD_PROXY_CLIENT_ID)
        ).strip() or self.config.EDC_DASHBOARD_PROXY_CLIENT_ID

    def edc_dashboard_proxy_scope(self):
        config = self.load_deployer_config()
        return str(
            config.get("EDC_DASHBOARD_PROXY_SCOPE", self.config.EDC_DASHBOARD_PROXY_SCOPE)
        ).strip() or self.config.EDC_DASHBOARD_PROXY_SCOPE

    def edc_dashboard_proxy_cookie_name(self):
        config = self.load_deployer_config()
        return str(
            config.get("EDC_DASHBOARD_PROXY_COOKIE_NAME", self.config.EDC_DASHBOARD_PROXY_COOKIE_NAME)
        ).strip() or self.config.EDC_DASHBOARD_PROXY_COOKIE_NAME

    def edc_dashboard_enabled(self):
        config = self.load_deployer_config()
        raw_value = str(
            config.get("EDC_DASHBOARD_ENABLED", self.config.EDC_DASHBOARD_ENABLED)
        ).strip().lower()
        return raw_value in ("1", "true", "yes", "on")

    def edc_sql_schema_autocreate(self):
        config = self.load_deployer_config()
        raw_value = str(
            config.get("EDC_SQL_SCHEMA_AUTOCREATE", self.config.EDC_SQL_SCHEMA_AUTOCREATE)
        ).strip().lower()
        return raw_value in ("1", "true", "yes", "on")

    def edc_dashboard_base_href(self):
        config = self.load_deployer_config()
        base_href = str(
            config.get("EDC_DASHBOARD_BASE_HREF", self.config.EDC_DASHBOARD_BASE_HREF)
        ).strip() or self.config.EDC_DASHBOARD_BASE_HREF
        if not base_href.startswith("/"):
            base_href = f"/{base_href}"
        if not base_href.endswith("/"):
            base_href = f"{base_href}/"
        return base_href
