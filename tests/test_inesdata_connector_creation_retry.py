import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from unittest import mock
import requests
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.connectors import INESDataConnectorsAdapter


class ConnectorRetryConfig:
    DS_NAME = "demo"
    NS_COMMON = "common-srvs"
    PORT_KEYCLOAK = 18081

    def __init__(self, root):
        self.root = root

    def repo_dir(self):
        return self.root

    def venv_path(self):
        return os.path.join(self.root, ".venv")

    def python_exec(self):
        return "python3"

    def repo_requirements_path(self):
        return os.path.join(self.root, "requirements.txt")

    def registration_db_name(self):
        return "demo_rs"

    def connector_credentials_path(self, connector_name):
        return os.path.join(self.root, f"credentials-connector-{connector_name}.json")

    def connector_minio_policy_path(self, connector_name):
        return os.path.join(self.root, f"policy-{connector_name}.json")

    def connector_values_file(self, connector_name):
        return os.path.join(self.root, f"values-{connector_name}.yaml")

    def connector_dir(self):
        return self.root

    def namespace_demo(self):
        return "demo"

    def ds_domain_base(self):
        return "dev.ds.dataspaceunit.upm"

    def host_alias_domains(self):
        return []

    def service_minio(self):
        return "minio"


class ConnectorRetryConfigAdapter:
    def __init__(self, root):
        self.root = root

    def get_pg_credentials(self):
        return "localhost", "postgres", "secret"

    def ds_domain_base(self):
        return "dev.ds.dataspaceunit.upm"

    def load_deployer_config(self):
        return {
            "KC_URL": "http://keycloak-admin.local",
            "KC_USER": "admin",
            "KC_PASSWORD": "secret",
            "MINIO_USER": "admin",
            "MINIO_PASSWORD": "minio-secret",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
        }

    def generate_connector_hosts(self, _connectors):
        return []

    def registration_service_internal_hostname(self, **_kwargs):
        return "demo-registration-service:8080"

    def connector_minio_policy_path(self, connector_name, ds_name=None, for_write=False):
        ds_name = ds_name or "demo"
        return os.path.join(
            self.root,
            "deployments",
            "DEV",
            "vm-distributed",
            ds_name,
            "connectors",
            connector_name,
            "policy.json",
        )


class RoleAlignedConnectorRetryConfigAdapter(ConnectorRetryConfigAdapter):
    def load_deployer_config(self):
        config = super().load_deployer_config()
        config["NAMESPACE_PROFILE"] = "role-aligned"
        config["LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES"] = "true"
        return config


class AdditiveConnectorRetryConfigAdapter(ConnectorRetryConfigAdapter):
    def load_deployer_config(self):
        config = super().load_deployer_config()
        config["LEVEL4_CONNECTOR_RECONCILIATION_MODE"] = "additive"
        return config


class BrandingConnectorRetryConfigAdapter(ConnectorRetryConfigAdapter):
    def load_deployer_config(self):
        config = super().load_deployer_config()
        config.update(
            {
                "INESDATA_BRAND_ASSETS_DIR": "identity",
                "INESDATA_BRAND_LOGO_FILES": "logo.svg",
            }
        )
        return config


class VmDistributedConnectorRetryConfigAdapter(ConnectorRetryConfigAdapter):
    topology = "vm-distributed"

    def load_deployer_config(self):
        config = super().load_deployer_config()
        config.update(
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG_COMMON": "/clusters/common.yaml",
                "K3S_KUBECONFIG_PROVIDER": "/clusters/provider.yaml",
                "K3S_KUBECONFIG_CONSUMER": "/clusters/consumer.yaml",
                "NAMESPACE_PROFILE": "role-aligned",
                "LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES": "true",
                "VM_COMMON_IP": "192.168.122.64",
            }
        )
        config.update(getattr(self, "extra_config", {}))
        return config


class VmSinglePublicConnectorRetryConfigAdapter(ConnectorRetryConfigAdapter):
    topology = "vm-single"

    def load_deployer_config(self):
        config = super().load_deployer_config()
        config.pop("KC_URL", None)
        config.pop("KC_INTERNAL_URL", None)
        config.update(
            {
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
            }
        )
        return config


class ConnectorCreationRetryTests(unittest.TestCase):
    def test_connector_branding_assets_do_not_import_bootstrap_click_dependency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            identity_dir = os.path.join(tmpdir, "identity")
            os.makedirs(identity_dir, exist_ok=True)
            with open(os.path.join(identity_dir, "logo.svg"), "w", encoding="utf-8") as handle:
                handle.write("<svg></svg>")

            commands = []

            def run(command, **_kwargs):
                commands.append(command)
                return object()

            def run_silent(command, **_kwargs):
                commands.append(command)
                if "kubectl get namespace" in command:
                    return "provider active"
                if "kubectl get configmap" in command:
                    return ""
                return ""

            adapter = INESDataConnectorsAdapter(
                run=run,
                run_silent=run_silent,
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=BrandingConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            original_import = __import__

            def import_without_click(name, *args, **kwargs):
                if name == "click":
                    raise ModuleNotFoundError("No module named 'click'")
                return original_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=import_without_click):
                applied = adapter._apply_connector_interface_branding_assets("conn-a-demo", "provider")

            self.assertTrue(applied)
            self.assertTrue(any("kubectl create -f" in command for command in commands))

    def test_vm_distributed_connector_urls_prefer_public_access_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            connector_name = "conn-org2-pionera"
            with open(os.path.join(tmpdir, f"credentials-connector-{connector_name}.json"), "w") as handle:
                json.dump(
                    {
                        "connector_user": {"user": "org2-user", "passwd": "secret"},
                        "public_access_urls": {
                            "connector_ingress": "https://org2.pionera.oeg.fi.upm.es",
                            "connector_interface_login": (
                                "https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/"
                            ),
                        },
                    },
                    handle,
                )
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmDistributedConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertEqual(
                adapter.connector_base_url(connector_name),
                "https://org2.pionera.oeg.fi.upm.es",
            )
            self.assertEqual(
                adapter.build_connector_url(connector_name),
                "https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/",
            )

    def test_connector_protocol_address_prefers_internal_access_url_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            connector_name = "conn-org2-pionera"
            with open(os.path.join(tmpdir, f"credentials-connector-{connector_name}.json"), "w") as handle:
                json.dump(
                    {
                        "connector_user": {"user": "org2-user", "passwd": "secret"},
                        "access_urls": {
                            "connector_protocol_api": (
                                "http://conn-org2-pionera.pionera.oeg.fi.upm.es/protocol"
                            ),
                        },
                        "public_access_urls": {
                            "connector_protocol_api": "https://org2.pionera.oeg.fi.upm.es/protocol",
                            "connector_ingress": "https://org2.pionera.oeg.fi.upm.es",
                        },
                    },
                    handle,
                )
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmDistributedConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertEqual(
                adapter.build_protocol_address(connector_name),
                "http://conn-org2-pionera.pionera.oeg.fi.upm.es/protocol",
            )
            self.assertEqual(
                adapter.build_public_protocol_address(connector_name),
                "https://org2.pionera.oeg.fi.upm.es/protocol",
            )

    def test_connector_protocol_address_can_use_public_mode(self):
        class PublicProtocolConfigAdapter(VmDistributedConnectorRetryConfigAdapter):
            def load_deployer_config(self):
                config = super().load_deployer_config()
                config["CONNECTOR_PROTOCOL_ADDRESS_MODE"] = "public"
                return config

        with tempfile.TemporaryDirectory() as tmpdir:
            connector_name = "conn-org2-pionera"
            with open(os.path.join(tmpdir, f"credentials-connector-{connector_name}.json"), "w") as handle:
                json.dump(
                    {
                        "connector_user": {"user": "org2-user", "passwd": "secret"},
                        "access_urls": {
                            "connector_protocol_api": (
                                "http://conn-org2-pionera.pionera.oeg.fi.upm.es/protocol"
                            ),
                        },
                        "public_access_urls": {
                            "connector_protocol_api": "https://org2.pionera.oeg.fi.upm.es/protocol",
                            "connector_ingress": "https://org2.pionera.oeg.fi.upm.es",
                        },
                    },
                    handle,
                )
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=PublicProtocolConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertEqual(
                adapter.build_protocol_address(connector_name),
                "https://org2.pionera.oeg.fi.upm.es/protocol",
            )

    def test_vm_single_connector_protocol_address_uses_public_path_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            connector_name = "conn-org2-pionera"
            with open(os.path.join(tmpdir, f"credentials-connector-{connector_name}.json"), "w") as handle:
                json.dump(
                    {
                        "connector_user": {"user": "org2-user", "passwd": "secret"},
                        "access_urls": {
                            "connector_protocol_api": (
                                "http://conn-org2-pionera.dev.ds.dataspaceunit.upm/protocol"
                            ),
                        },
                        "public_access_urls": {
                            "connector_ingress": "https://org4.pionera.oeg.fi.upm.es/c/org2",
                        },
                    },
                    handle,
                )
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertEqual(
                adapter.build_protocol_address(connector_name),
                "https://org4.pionera.oeg.fi.upm.es/c/org2/protocol",
            )

    def test_vm_single_connector_protocol_address_can_be_forced_internal(self):
        class InternalProtocolConfigAdapter(VmSinglePublicConnectorRetryConfigAdapter):
            def load_deployer_config(self):
                config = super().load_deployer_config()
                config["CONNECTOR_PROTOCOL_ADDRESS_MODE"] = "internal"
                return config

        with tempfile.TemporaryDirectory() as tmpdir:
            connector_name = "conn-org2-pionera"
            with open(os.path.join(tmpdir, f"credentials-connector-{connector_name}.json"), "w") as handle:
                json.dump(
                    {
                        "connector_user": {"user": "org2-user", "passwd": "secret"},
                        "access_urls": {
                            "connector_protocol_api": (
                                "http://conn-org2-pionera.dev.ds.dataspaceunit.upm/protocol"
                            ),
                        },
                        "public_access_urls": {
                            "connector_ingress": "https://org4.pionera.oeg.fi.upm.es/c/org2",
                        },
                    },
                    handle,
                )
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=InternalProtocolConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertEqual(
                adapter.build_protocol_address(connector_name),
                "http://conn-org2-pionera.dev.ds.dataspaceunit.upm/protocol",
            )

    def test_vm_distributed_keycloak_token_url_prefers_frontend_url(self):
        class PublicKeycloakConfigAdapter(VmDistributedConnectorRetryConfigAdapter):
            def load_deployer_config(self):
                config = super().load_deployer_config()
                config.update(
                    {
                        "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                        "KC_INTERNAL_URL": "http://auth.pionera.oeg.fi.upm.es",
                    }
                )
                return config

        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=PublicKeycloakConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertEqual(
                adapter._keycloak_token_url(),
                "https://org1.pionera.oeg.fi.upm.es/auth/realms/demo/protocol/openid-connect/token",
            )

    def test_bootstrap_connector_commands_include_active_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )
            adapter.config_adapter.topology = "vm-single"

            create_cmd = adapter._bootstrap_connector_create_command("python3", "conn-demo", "demo")
            delete_cmd = adapter._bootstrap_connector_delete_command("python3", "conn-demo", "demo")

        self.assertIn("PIONERA_TOPOLOGY=vm-single", create_cmd)
        self.assertIn("bootstrap.py connector create conn-demo demo", create_cmd)
        self.assertIn("PIONERA_TOPOLOGY=vm-single", delete_cmd)
        self.assertIn("bootstrap.py connector delete conn-demo demo", delete_cmd)

    def test_bootstrap_connector_create_command_passes_scoped_minio_policy_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )
            adapter.config_adapter.topology = "vm-distributed"

            create_cmd = adapter._bootstrap_connector_create_command("python3", "conn-demo", "demo")

        expected = (
            "PIONERA_CONNECTOR_MINIO_POLICY_PATH="
            "deployments/DEV/vm-distributed/demo/connectors/conn-demo/policy.json"
        )
        self.assertIn(expected, create_cmd)
        self.assertIn("bootstrap.py connector create conn-demo demo", create_cmd)

    def test_bootstrap_connector_commands_can_override_vault_url_for_host_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )
            adapter.config_adapter.topology = "vm-single"

            create_cmd = adapter._bootstrap_connector_create_command(
                "python3",
                "conn-demo",
                "demo",
                vault_url="http://127.0.0.1:19082/",
            )
            delete_cmd = adapter._bootstrap_connector_delete_command(
                "python3",
                "conn-demo",
                "demo",
                vault_url="http://127.0.0.1:19082/",
            )

        self.assertIn("PIONERA_TOPOLOGY=vm-single", create_cmd)
        self.assertIn("PIONERA_VT_URL=http://127.0.0.1:19082", create_cmd)
        self.assertIn("bootstrap.py connector create conn-demo demo", create_cmd)
        self.assertIn("PIONERA_VT_URL=http://127.0.0.1:19082", delete_cmd)
        self.assertIn("bootstrap.py connector delete conn-demo demo", delete_cmd)

    def test_bootstrap_connector_commands_can_override_keycloak_management_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )
            adapter.config_adapter.topology = "vm-distributed"

            create_cmd = adapter._bootstrap_connector_create_command(
                "python3",
                "conn-demo",
                "demo",
                keycloak_url="http://127.0.0.1:18081/",
            )
            delete_cmd = adapter._bootstrap_connector_delete_command(
                "python3",
                "conn-demo",
                "demo",
                keycloak_url="http://127.0.0.1:18081/",
            )

        self.assertIn("PIONERA_TOPOLOGY=vm-distributed", create_cmd)
        self.assertIn("PIONERA_KC_MANAGEMENT_URL=http://127.0.0.1:18081", create_cmd)
        self.assertIn("bootstrap.py connector create conn-demo demo", create_cmd)
        self.assertIn("PIONERA_KC_MANAGEMENT_URL=http://127.0.0.1:18081", delete_cmd)
        self.assertIn("bootstrap.py connector delete conn-demo demo", delete_cmd)

    def test_vault_dns_resolution_failure_from_ubuntu_triggers_local_fallback(self):
        message = (
            "HTTPConnectionPool(host='common-srvs-vault.common-srvs.svc', port=8200): "
            "Max retries exceeded with url: /v1/auth/token/lookup-self "
            "(Caused by NameResolutionError(\"HTTPConnection(host='common-srvs-vault.common-srvs.svc', "
            "port=8200): Failed to resolve 'common-srvs-vault.common-srvs.svc' "
            "([Errno -2] Name or service not known)\"))"
        )

        self.assertTrue(INESDataConnectorsAdapter._should_attempt_local_fallback(requests.ConnectionError(message)))

    def test_force_clean_postgres_db_retries_until_database_and_role_are_gone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infra = mock.Mock()
            infra.ensure_local_infra_access = mock.Mock(return_value=True)
            run_calls = []
            db_results = iter(["1\n", ""])
            role_results = iter(["1\n", ""])

            def fake_run(command, **_kwargs):
                run_calls.append(command)
                return object()

            def fake_run_silent(command, **_kwargs):
                if "FROM pg_database" in command:
                    return next(db_results)
                if "FROM pg_roles" in command:
                    return next(role_results)
                return ""

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=fake_run_silent,
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            with mock.patch("adapters.inesdata.connectors.time.sleep", return_value=None):
                cleaned = adapter.force_clean_postgres_db("demo_db", "demo_user")

        self.assertTrue(cleaned)
        self.assertEqual(len(run_calls), 6)
        infra.ensure_local_infra_access.assert_called_once()
        self.assertTrue(any("DROP DATABASE IF EXISTS demo_db WITH (FORCE)" in command for command in run_calls))

    def test_force_clean_postgres_db_preserves_explicit_postgres_endpoint_on_retry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infra = mock.Mock()
            infra.ensure_local_infra_access = mock.Mock(return_value=True)
            run_calls = []
            db_results = iter(["1\n", ""])
            role_results = iter(["1\n", ""])

            def fake_run(command, **_kwargs):
                run_calls.append(command)
                return object()

            def fake_run_silent(command, **_kwargs):
                if "FROM pg_database" in command:
                    return next(db_results)
                if "FROM pg_roles" in command:
                    return next(role_results)
                return ""

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=fake_run_silent,
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            with mock.patch("adapters.inesdata.connectors.time.sleep", return_value=None):
                cleaned = adapter.force_clean_postgres_db(
                    "demo_db",
                    "demo_user",
                    pg_host="127.0.0.1",
                    pg_port="15432",
                )

        self.assertTrue(cleaned)
        self.assertEqual(len(run_calls), 6)
        self.assertTrue(all("-h 127.0.0.1" in command for command in run_calls))
        self.assertTrue(all("-p 15432" in command for command in run_calls))
        self.assertTrue(any("DROP DATABASE IF EXISTS demo_db WITH (FORCE)" in command for command in run_calls))
        infra.ensure_local_infra_access.assert_not_called()

    def test_build_internal_protocol_address_uses_cross_namespace_service_fqdn_when_role_aligned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=lambda *args, **kwargs: None,
                run_silent=lambda *args, **kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=RoleAlignedConnectorRetryConfigAdapter(tmpdir),
                config_cls=lambda: None,
            )
            adapter.config = ConnectorRetryConfig(tmpdir)
            adapter.load_dataspace_connectors = mock.Mock(return_value=[
                {
                    "name": "roleedcprove",
                    "namespace": "roleedcprove",
                    "namespace_profile": "role-aligned",
                    "connectors": [
                        "conn-cityproof-roleedcprove",
                        "conn-companyproof-roleedcprove",
                    ],
                    "connector_roles": {
                        "provider": "conn-cityproof-roleedcprove",
                        "consumer": "conn-companyproof-roleedcprove",
                    },
                    "connector_details": [
                        {
                            "name": "conn-cityproof-roleedcprove",
                            "role": "provider",
                            "active_namespace": "roleedcprove",
                            "planned_namespace": "roleedcprove-provider",
                        },
                        {
                            "name": "conn-companyproof-roleedcprove",
                            "role": "consumer",
                            "active_namespace": "roleedcprove",
                            "planned_namespace": "roleedcprove-consumer",
                        },
                    ],
                }
            ])

            self.assertEqual(
                adapter.build_internal_protocol_address("conn-cityproof-roleedcprove"),
                "http://conn-cityproof-roleedcprove.roleedcprove-provider.svc.cluster.local:19194/protocol",
            )
            self.assertEqual(
                adapter.build_protocol_address("conn-cityproof-roleedcprove"),
                "http://conn-cityproof-roleedcprove.dev.ds.dataspaceunit.upm/protocol",
            )

    def test_update_connector_service_discovery_uses_cross_namespace_registration_service_hostname(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            captured = {}

            class RoleAlignedConfigAdapter(ConnectorRetryConfigAdapter):
                def registration_service_internal_hostname(self, **_kwargs):
                    captured.update(_kwargs)
                    return "demo-registration-service.demo-core.svc.cluster.local:8080"

            config_adapter = RoleAlignedConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-demo")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "services": {
                            "registrationService": {
                                "hostname": "demo-registration-service:8080",
                                "protocol": "http",
                            }
                        }
                    },
                    handle,
                    sort_keys=False,
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: False,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo", "conn-b-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                        }
                    ],
                }
            ]

            adapter.update_connector_service_discovery(values_path, "conn-a-demo")

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(
            rendered["services"]["registrationService"]["hostname"],
            "demo-registration-service.demo-core.svc.cluster.local:8080",
        )
        self.assertEqual(captured["connector_namespace"], "demo-provider")

    def test_vm_distributed_multicluster_rewrites_common_service_endpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class PioneraVmDistributedConfigAdapter(VmDistributedConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values["DS_DOMAIN_BASE"] = "pionera.oeg.fi.upm.es"
                    values["DOMAIN_BASE"] = "pionera.oeg.fi.upm.es"
                    values["VM_PROVIDER_IP"] = "192.168.122.134"
                    values["VM_CONSUMER_IP"] = "192.168.122.9"
                    values["VM_PROVIDER_PUBLIC_URL"] = "https://org2.pionera.oeg.fi.upm.es"
                    values["VM_CONSUMER_PUBLIC_URL"] = "https://org3.pionera.oeg.fi.upm.es"
                    return values

            config_adapter = PioneraVmDistributedConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-citycouncil-pionera")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "services": {
                            "db": {
                                "hostname": "common-srvs-postgresql.common-srvs.svc",
                            },
                            "vault": {
                                "url": "http://common-srvs-vault.common-srvs.svc:8200",
                            },
                            "registrationService": {
                                "hostname": "pionera-registration-service.core-control.svc.cluster.local:8080",
                                "protocol": "http",
                            },
                            "keycloak": {
                                "hostname": "auth.pionera.oeg.fi.upm.es",
                            },
                        }
                    },
                    handle,
                    sort_keys=False,
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: False,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            adapter.update_connector_multicluster_common_service_endpoints(
                values_path,
                "conn-citycouncil-pionera",
                ds_name="pionera",
            )

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(rendered["services"]["db"]["hostname"], "192.168.122.64")
        self.assertEqual(rendered["services"]["vault"]["url"], "http://192.168.122.64:8200")
        self.assertEqual(
            rendered["services"]["registrationService"]["hostname"],
            "registration-service-pionera.pionera.oeg.fi.upm.es",
        )
        self.assertEqual(rendered["services"]["keycloak"]["hostname"], "auth.pionera.oeg.fi.upm.es")

    def test_update_connector_host_aliases_uses_connector_dataspace_registration_hostname(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class DataspaceAwareConfigAdapter(ConnectorRetryConfigAdapter):
                def host_alias_domains(self, ds_name=None, ds_namespace=None):
                    del ds_namespace
                    return [
                        "keycloak.dev.ed.dataspaceunit.upm",
                        f"registration-service-{ds_name}.dev.ds.dataspaceunit.upm",
                    ]

            config_adapter = DataspaceAwareConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-pilot")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"hostAliases": []}, handle, sort_keys=False)

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pilot",
                    "namespace": "pilot",
                    "connectors": ["conn-a-pilot", "conn-b-pilot"],
                }
            ]

            adapter.update_connector_host_aliases(
                values_path,
                ["conn-a-pilot", "conn-b-pilot"],
                connector_name="conn-a-pilot",
            )

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(
            rendered["hostAliases"][0]["hostnames"],
            [
                "keycloak.dev.ed.dataspaceunit.upm",
                "registration-service-pilot.dev.ds.dataspaceunit.upm",
                "conn-a-pilot.dev.ds.dataspaceunit.upm",
                "conn-b-pilot.dev.ds.dataspaceunit.upm",
            ],
        )

    def test_update_connector_host_aliases_uses_vm_distributed_role_addresses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class PioneraVmDistributedConfigAdapter(VmDistributedConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values["DS_DOMAIN_BASE"] = "pionera.oeg.fi.upm.es"
                    values["DOMAIN_BASE"] = "pionera.oeg.fi.upm.es"
                    values["VM_PROVIDER_IP"] = "192.168.122.134"
                    values["VM_CONSUMER_IP"] = "192.168.122.9"
                    values["VM_PROVIDER_PUBLIC_URL"] = "https://org2.pionera.oeg.fi.upm.es"
                    values["VM_CONSUMER_PUBLIC_URL"] = "https://org3.pionera.oeg.fi.upm.es"
                    return values

            config_adapter = PioneraVmDistributedConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-pilot")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "hostAliases": [
                            {
                                "ip": "192.168.49.2",
                                "hostnames": ["auth.pionera.oeg.fi.upm.es"],
                            }
                        ]
                    },
                    handle,
                    sort_keys=False,
                )

            run = mock.Mock(return_value="192.168.49.2")
            adapter = INESDataConnectorsAdapter(
                run=run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pionera",
                    "namespace": "core-control",
                    "connectors": ["conn-a-pionera", "conn-b-pionera"],
                    "connector_details": [
                        {
                            "name": "conn-a-pionera",
                            "role": "provider",
                            "namespace_role": "provider",
                        },
                        {
                            "name": "conn-b-pionera",
                            "role": "consumer",
                            "namespace_role": "consumer",
                        },
                    ],
                }
            ]

            adapter.update_connector_host_aliases(
                values_path,
                ["conn-a-pionera", "conn-b-pionera"],
                connector_name="conn-a-pionera",
                ds_name="pionera",
            )

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        aliases = {entry["ip"]: entry["hostnames"] for entry in rendered["hostAliases"]}
        self.assertIn("auth.pionera.oeg.fi.upm.es", aliases["192.168.122.64"])
        self.assertIn("registration-service-pionera.pionera.oeg.fi.upm.es", aliases["192.168.122.64"])
        self.assertIn("ontology-hub-pionera.pionera.oeg.fi.upm.es", aliases["192.168.122.64"])
        self.assertIn("conn-a-pionera.pionera.oeg.fi.upm.es", aliases["192.168.122.134"])
        self.assertIn("org2.pionera.oeg.fi.upm.es", aliases["192.168.122.134"])
        self.assertIn("conn-b-pionera.pionera.oeg.fi.upm.es", aliases["192.168.122.9"])
        self.assertIn("org3.pionera.oeg.fi.upm.es", aliases["192.168.122.9"])
        run.assert_not_called()

    def test_update_connector_host_aliases_skips_vm_distributed_dns_role_addresses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class DnsVmDistributedConfigAdapter(VmDistributedConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values["DS_DOMAIN_BASE"] = "example.test"
                    values["DOMAIN_BASE"] = "example.test"
                    values["VM_COMMON_IP"] = "common.example.test"
                    values["VM_PROVIDER_IP"] = "provider.example.test"
                    values["VM_CONSUMER_IP"] = "consumer.example.test"
                    values["VM_PROVIDER_PUBLIC_URL"] = "https://provider.example.test"
                    values["VM_CONSUMER_PUBLIC_URL"] = "https://consumer.example.test"
                    return values

            config_adapter = DnsVmDistributedConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-demo")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "hostAliases": [
                            {
                                "ip": "provider.example.test",
                                "hostnames": ["stale.invalid.example"],
                            }
                        ]
                    },
                    handle,
                    sort_keys=False,
                )

            adapter = INESDataConnectorsAdapter(
                run=mock.Mock(return_value="192.168.49.2"),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "core-control",
                    "connectors": ["conn-a-demo", "conn-b-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "namespace_role": "provider",
                        },
                        {
                            "name": "conn-b-demo",
                            "role": "consumer",
                            "namespace_role": "consumer",
                        },
                    ],
                }
            ]

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                adapter.update_connector_host_aliases(
                    values_path,
                    ["conn-a-demo", "conn-b-demo"],
                    connector_name="conn-a-demo",
                    ds_name="demo",
                )

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(rendered["hostAliases"], [])
        self.assertIn("Skipping connector hostAliases", output.getvalue())
        self.assertIn("Public DNS will be used", output.getvalue())

    def test_update_connector_host_aliases_uses_vm_single_k3s_ingress_ip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class K3sConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-single"

                def load_deployer_config(self):
                    config_data = super().load_deployer_config()
                    config_data.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "VM_EXTERNAL_IP": "192.168.122.134",
                            "INGRESS_EXTERNAL_IP": "192.168.122.134",
                        }
                    )
                    return config_data

                def host_alias_domains(self, ds_name=None, ds_namespace=None):
                    del ds_namespace
                    return [
                        "auth.dev.ed.dataspaceunit.upm",
                        f"registration-service-{ds_name}.dev.ds.dataspaceunit.upm",
                    ]

            config_adapter = K3sConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-demo")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"hostAliases": []}, handle, sort_keys=False)

            run = mock.Mock(return_value="192.168.49.2")
            adapter = INESDataConnectorsAdapter(
                run=run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            adapter.update_connector_host_aliases(
                values_path,
                ["conn-a-demo", "conn-b-demo"],
                connector_name="conn-a-demo",
                ds_name="demo",
            )

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(rendered["hostAliases"][0]["ip"], "192.168.122.134")
        self.assertIn("auth.dev.ed.dataspaceunit.upm", rendered["hostAliases"][0]["hostnames"])
        self.assertIn("conn-a-demo.dev.ds.dataspaceunit.upm", rendered["hostAliases"][0]["hostnames"])
        run.assert_not_called()

    def test_wait_for_all_connectors_vm_distributed_uses_pod_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = VmDistributedConnectorRetryConfigAdapter(tmpdir)
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: (
                    "conn-a-pionera-abc 1/1 Running 0 1m\n"
                    "conn-a-pionera-inteface-def 1/1 Running 0 1m\n"
                ),
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pionera",
                    "namespace": "core-control",
                    "connectors": ["conn-a-pionera"],
                    "connector_details": [
                        {
                            "name": "conn-a-pionera",
                            "role": "provider",
                            "namespace_role": "provider",
                        }
                    ],
                }
            ]
            adapter.wait_for_connector_ready = mock.Mock(return_value=False)

            self.assertTrue(adapter.wait_for_all_connectors(["conn-a-pionera"]))

        adapter.wait_for_connector_ready.assert_not_called()

    def test_update_connector_layout_metadata_persists_namespace_plan_for_connector(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-pilot")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"connector": {"name": "conn-a-pilot"}}, handle, sort_keys=False)

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pilot",
                    "namespace": "pilot",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-pilot", "conn-b-pilot"],
                    "connector_details": [
                        {
                            "name": "conn-a-pilot",
                            "role": "provider",
                            "runtime_namespace": "pilot",
                            "active_namespace": "pilot",
                            "planned_namespace": "pilot-provider",
                            "registration_service_namespace": "pilot-core",
                            "planned_registration_service_namespace": "pilot-core",
                        }
                    ],
                }
            ]

            adapter.update_connector_layout_metadata(values_path, "conn-a-pilot")

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(
            rendered["connector"]["layout"],
            {
                "role": "provider",
                "namespaceProfile": "role-aligned",
                "runtimeNamespace": "pilot",
                "activeNamespace": "pilot",
                "plannedNamespace": "pilot-provider",
                "registrationServiceNamespace": "pilot-core",
                "plannedRegistrationServiceNamespace": "pilot-core",
            },
        )

    def test_update_connector_node_scheduling_pins_vm_distributed_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class VmDistributedConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-distributed"

                def load_deployer_config(self):
                    config_data = super().load_deployer_config()
                    config_data.update(
                        {
                            "NAMESPACE_PROFILE": "role-aligned",
                            "VM_PROVIDER_K8S_NODE": "pionera20",
                            "VM_CONSUMER_K8S_NODE": "pionera3",
                        }
                    )
                    return config_data

            config_adapter = VmDistributedConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-pilot")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "connector": {"name": "conn-a-pilot"},
                        "nodeSelector": {"disktype": "ssd"},
                    },
                    handle,
                    sort_keys=False,
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pilot",
                    "namespace": "pilot",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-pilot", "conn-b-pilot"],
                    "connector_details": [
                        {
                            "name": "conn-a-pilot",
                            "role": "provider",
                            "active_namespace": "provider",
                            "planned_namespace": "provider",
                        }
                    ],
                }
            ]

            adapter.update_connector_node_scheduling(values_path, "conn-a-pilot")

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(
            rendered["nodeSelector"],
            {
                "disktype": "ssd",
                "kubernetes.io/hostname": "pionera20",
            },
        )

    def test_update_connector_node_scheduling_skips_local_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-pilot")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"connector": {"name": "conn-a-pilot"}}, handle, sort_keys=False)

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            adapter.update_connector_node_scheduling(values_path, "conn-a-pilot")

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertNotIn("nodeSelector", rendered)

    def test_update_connector_public_ingress_config_adds_org_host_for_vm_distributed_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class VmDistributedConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-distributed"

                def load_deployer_config(self):
                    config_data = super().load_deployer_config()
                    config_data.update(
                        {
                            "NAMESPACE_PROFILE": "role-aligned",
                            "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                            "VM_PROVIDER_PUBLIC_URL": "https://org2.pionera.oeg.fi.upm.es",
                            "MINIO_API_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                        }
                    )
                    return config_data

            config_adapter = VmDistributedConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-pilot")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "connector": {
                            "name": "conn-a-pilot",
                            "ingress": {
                                "hostname": "conn-a-pilot.pionera.oeg.fi.upm.es",
                                "protocol": "http",
                            },
                        },
                        "services": {
                            "keycloak": {
                                "hostname": "auth.pionera.oeg.fi.upm.es",
                                "external": "auth.pionera.oeg.fi.upm.es",
                                "protocol": "http",
                            }
                        },
                    },
                    handle,
                    sort_keys=False,
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pilot",
                    "namespace": "pilot",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-pilot"],
                    "connector_details": [
                        {
                            "name": "conn-a-pilot",
                            "role": "provider",
                            "active_namespace": "provider",
                        }
                    ],
                }
            ]

            adapter.update_connector_public_ingress_config(values_path, "conn-a-pilot")

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        ingress = rendered["connector"]["ingress"]
        self.assertEqual(ingress["publicProtocol"], "https")
        self.assertEqual(ingress["publicHostname"], "org2.pionera.oeg.fi.upm.es")
        self.assertEqual(ingress["callbackProtocol"], "http")
        self.assertEqual(ingress["callbackHostname"], "org2.pionera.oeg.fi.upm.es")
        self.assertTrue(rendered["connector"]["tlsCacerts"]["enabled"])
        self.assertEqual(rendered["connector"]["tlsCacerts"]["secretName"], "common-tls-cacerts")
        self.assertIn("javax.net.ssl.trustStore=/opt/connector/tls-cacerts/cacerts.jks", rendered["connector"]["jvmArgs"])
        self.assertEqual(rendered["services"]["keycloak"]["protocol"], "http")
        self.assertEqual(rendered["services"]["keycloak"]["hostname"], "org1.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(rendered["services"]["keycloak"]["publicProtocol"], "https")
        self.assertEqual(rendered["services"]["keycloak"]["external"], "org1.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(rendered["services"]["minio"]["protocol"], "http")
        self.assertEqual(rendered["services"]["minio"]["hostname"], "org1.pionera.oeg.fi.upm.es")
        self.assertEqual(
            ingress["additionalHosts"],
            [
                {
                    "hostname": "org2.pionera.oeg.fi.upm.es",
                    "rootToInterface": True,
                }
            ],
        )

    def test_update_connector_public_ingress_config_uses_explicit_keycloak_frontend_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class VmDistributedConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-distributed"

                def load_deployer_config(self):
                    config_data = super().load_deployer_config()
                    config_data.update(
                        {
                            "VM_PROVIDER_PUBLIC_URL": "https://org2.pionera.oeg.fi.upm.es",
                            "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                        }
                    )
                    return config_data

            config_adapter = VmDistributedConfigAdapter(tmpdir)
            values_path = config.connector_values_file("conn-a-pilot")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "connector": {
                            "name": "conn-a-pilot",
                            "ingress": {
                                "hostname": "conn-a-pilot.pionera.oeg.fi.upm.es",
                                "protocol": "http",
                            },
                        },
                        "services": {
                            "keycloak": {
                                "hostname": "auth.pionera.oeg.fi.upm.es",
                                "external": "auth.pionera.oeg.fi.upm.es",
                                "protocol": "http",
                            }
                        },
                    },
                    handle,
                    sort_keys=False,
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pilot",
                    "namespace": "pilot",
                    "connectors": ["conn-a-pilot"],
                    "connector_details": [
                        {
                            "name": "conn-a-pilot",
                            "role": "provider",
                        }
                    ],
                }
            ]

            adapter.update_connector_public_ingress_config(values_path, "conn-a-pilot")

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        keycloak = rendered["services"]["keycloak"]
        self.assertEqual(keycloak["protocol"], "http")
        self.assertEqual(keycloak["hostname"], "org1.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(keycloak["publicProtocol"], "https")
        self.assertEqual(keycloak["external"], "org1.pionera.oeg.fi.upm.es/auth")
        ingress = rendered["connector"]["ingress"]
        self.assertEqual(ingress["callbackProtocol"], "http")
        self.assertEqual(ingress["callbackHostname"], "org2.pionera.oeg.fi.upm.es")
        self.assertTrue(rendered["connector"]["tlsCacerts"]["enabled"])
        self.assertIn("javax.net.ssl.trustStore=/opt/connector/tls-cacerts/cacerts.jks", rendered["connector"]["jvmArgs"])

    def test_update_connector_public_ingress_config_uses_vm_single_public_path_and_internal_services(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            values_path = config.connector_values_file("conn-org2-pionera")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "connector": {
                            "name": "conn-org2-pionera",
                            "dataspace": "pionera",
                            "ingress": {
                                "hostname": "conn-org2-pionera.pionera.oeg.fi.upm.es",
                                "protocol": "http",
                            },
                        },
                        "services": {
                            "keycloak": {"hostname": None, "external": None, "protocol": "http"},
                            "minio": {"hostname": None, "protocol": "http"},
                        },
                        "connectorInterface": {
                            "branding": {
                                "assetBaseUrl": "/inesdata-connector-interface/assets/branding",
                                "logoUrls": "/inesdata-connector-interface/assets/branding/pionera-logo.svg",
                                "footerLogoUrls": (
                                    "/inesdata-connector-interface/assets/branding/pionera-logo.svg,"
                                    "/inesdata-connector-interface/assets/branding/funding-logos.png"
                                ),
                                "poweredByLogoUrls": "/inesdata-connector-interface/assets/branding/inesdta.png",
                            }
                        },
                    },
                    handle,
                    sort_keys=False,
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            adapter.update_connector_public_ingress_config(values_path, "conn-org2-pionera")

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        ingress = rendered["connector"]["ingress"]
        connector_interface = rendered["connectorInterface"]
        branding = connector_interface["branding"]
        keycloak = rendered["services"]["keycloak"]
        minio = rendered["services"]["minio"]
        self.assertEqual(ingress["publicProtocol"], "https")
        self.assertEqual(ingress["publicHostname"], "org4.pionera.oeg.fi.upm.es/c/org2")
        self.assertEqual(ingress["callbackProtocol"], "https")
        self.assertEqual(ingress["callbackHostname"], "org4.pionera.oeg.fi.upm.es/c/org2")
        self.assertEqual(
            ingress["dataplanePublicBaseUrl"],
            "https://org4.pionera.oeg.fi.upm.es/c/org2/public",
        )
        self.assertNotIn("tlsCacerts", rendered["connector"])
        self.assertNotIn("additionalHosts", ingress)
        self.assertEqual(connector_interface["publicBasePath"], "/c/org2/inesdata-connector-interface")
        self.assertEqual(
            branding["assetBaseUrl"],
            "/c/org2/inesdata-connector-interface/assets/branding",
        )
        self.assertEqual(
            branding["logoUrls"],
            "/c/org2/inesdata-connector-interface/assets/branding/pionera-logo.svg",
        )
        self.assertEqual(
            branding["footerLogoUrls"],
            (
                "/c/org2/inesdata-connector-interface/assets/branding/pionera-logo.svg,"
                "/c/org2/inesdata-connector-interface/assets/branding/funding-logos.png"
            ),
        )
        self.assertEqual(
            branding["poweredByLogoUrls"],
            "/c/org2/inesdata-connector-interface/assets/branding/inesdta.png",
        )
        self.assertEqual(keycloak["hostname"], "common-srvs-keycloak.common-srvs.svc:80")
        self.assertEqual(keycloak["publicProtocol"], "https")
        self.assertEqual(keycloak["external"], "org4.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(minio["hostname"], "common-srvs-minio.common-srvs.svc:9000")

    def test_vm_single_connector_public_path_ingresses_route_connector_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "192.168.49.2",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            manifests = adapter._vm_single_connector_public_path_ingress_manifests(
                {
                    "connector": {
                        "name": "conn-org3-pionera",
                        "dataspace": "pionera",
                        "layout": {
                            "registrationServiceNamespace": "core-control",
                        },
                        "ingress": {
                            "publicHostname": "org4.pionera.oeg.fi.upm.es/c/org3",
                        },
                    }
                },
                "consumer",
            )

        self.assertEqual(len(manifests), 3)
        observer, routed, root = manifests
        self.assertEqual(observer["metadata"]["name"], "conn-org3-pionera-public-model-observer-ingress")
        self.assertEqual(observer["metadata"]["namespace"], "core-control")
        self.assertEqual(
            observer["metadata"]["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"],
            "/api/model-observer/$2",
        )
        observer_paths = observer["spec"]["rules"][0]["http"]["paths"]
        self.assertEqual(
            observer_paths[0]["path"],
            "/c/org3/inesdata-connector-interface/model-observer(/|$)(.*)",
        )
        self.assertEqual(
            observer_paths[0]["backend"]["service"],
            {"name": "pionera-public-portal-backend", "port": {"number": 1337}},
        )
        self.assertEqual(routed["metadata"]["name"], "conn-org3-pionera-public-path-ingress")
        self.assertEqual(routed["metadata"]["namespace"], "consumer")
        self.assertEqual(
            routed["metadata"]["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"],
            "/$2",
        )
        self.assertEqual(routed["spec"]["rules"][0]["host"], "org4.pionera.oeg.fi.upm.es")
        paths = routed["spec"]["rules"][0]["http"]["paths"]
        backends = {item["path"]: item["backend"]["service"] for item in paths}
        self.assertEqual(
            backends["/c/org3(/|$)(management.*)"],
            {"name": "conn-org3-pionera", "port": {"number": 19193}},
        )
        self.assertEqual(
            backends["/c/org3(/|$)(inesdata-connector-interface.*)"],
            {"name": "conn-org3-pionera-interface", "port": {"number": 8080}},
        )
        self.assertEqual(root["metadata"]["name"], "conn-org3-pionera-public-root-ingress")
        self.assertEqual(
            root["metadata"]["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"],
            "/inesdata-connector-interface/",
        )
        self.assertEqual(root["spec"]["rules"][0]["http"]["paths"][0]["path"], "/c/org3/?$")

    def test_sync_vm_single_connector_public_path_ingresses_applies_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            values_path = config.connector_values_file("conn-org3-pionera")
            with open(values_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "connector": {
                            "name": "conn-org3-pionera",
                            "dataspace": "pionera",
                            "layout": {
                                "registrationServiceNamespace": "core-control",
                            },
                            "ingress": {
                                "publicHostname": "org4.pionera.oeg.fi.upm.es/c/org3",
                            },
                        }
                    },
                    handle,
                    sort_keys=False,
                )

            commands = []
            applied_docs = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                if "kubectl apply -f" in command:
                    manifest_path = shlex.split(command)[-1]
                    with open(manifest_path, "r", encoding="utf-8") as handle:
                        applied_docs.extend(list(yaml.safe_load_all(handle)))
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            synced = adapter._sync_vm_single_connector_public_path_ingresses(values_path, "consumer")

        self.assertTrue(synced)
        self.assertTrue(any("kubectl apply -f" in command for command in commands))
        self.assertEqual([doc["kind"] for doc in applied_docs], ["Ingress", "Ingress", "Ingress"])
        self.assertEqual(applied_docs[0]["spec"]["rules"][0]["host"], "org4.pionera.oeg.fi.upm.es")

    def test_keycloak_readiness_uses_configured_hostname_without_port_forward(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)

            class RecordingInfra:
                def __init__(self):
                    self.calls = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

            infra = RecordingInfra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )

            def fake_post(*_args, **_kwargs):
                raise Exception("connection refused")

            with mock.patch("adapters.inesdata.connectors.requests.post", side_effect=fake_post):
                self.assertFalse(adapter.wait_for_keycloak_admin_ready(timeout=0.01, poll_interval=0))

            self.assertEqual(infra.calls, [])

    def test_keycloak_readiness_prefers_management_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.load_deployer_config = lambda: {
                "KC_URL": "http://admin.auth.example.test",
                "KC_MANAGEMENT_URL": "http://127.0.0.1:18081",
                "KC_USER": "admin",
                "KC_PASSWORD": "secret",
            }
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            with mock.patch(
                "adapters.inesdata.connectors.requests.post",
                return_value=mock.Mock(status_code=200, json=lambda: {"access_token": "token"}),
            ) as mocked_post:
                self.assertTrue(adapter.wait_for_keycloak_admin_ready(timeout=0.01, poll_interval=0))

            mocked_post.assert_called_once()
            self.assertEqual(
                mocked_post.call_args.args[0],
                "http://127.0.0.1:18081/realms/master/protocol/openid-connect/token",
            )

    def test_local_keycloak_readiness_prefers_internal_url_over_public_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.load_deployer_config = lambda: {
                "KEYCLOAK_FRONTEND_URL": "https://org1.dev.ed.dataspaceunit.upm/auth",
                "KEYCLOAK_PUBLIC_URL": "https://org1.dev.ed.dataspaceunit.upm/auth",
                "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "KC_URL": "http://admin.auth.dev.ed.dataspaceunit.upm",
                "KC_USER": "admin",
                "KC_PASSWORD": "secret",
            }
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            with mock.patch(
                "adapters.inesdata.connectors.requests.post",
                return_value=mock.Mock(status_code=200, json=lambda: {"access_token": "token"}),
            ) as mocked_post:
                self.assertTrue(adapter.wait_for_keycloak_admin_ready(timeout=0.01, poll_interval=0))

            mocked_post.assert_called_once()
            self.assertEqual(
                mocked_post.call_args.args[0],
                "http://auth.dev.ed.dataspaceunit.upm/realms/master/protocol/openid-connect/token",
            )

    def test_keycloak_readiness_infers_vm_single_public_auth_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            with mock.patch(
                "adapters.inesdata.connectors.requests.post",
                return_value=mock.Mock(status_code=200, json=lambda: {"access_token": "token"}),
            ) as mocked_post:
                self.assertTrue(adapter.wait_for_keycloak_admin_ready(timeout=0.01, poll_interval=0))

            mocked_post.assert_called_once()
            self.assertEqual(
                mocked_post.call_args.args[0],
                "https://org4.pionera.oeg.fi.upm.es/auth/realms/master/protocol/openid-connect/token",
            )

    def test_bootstrap_prefix_infers_vm_single_keycloak_management_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            prefix = adapter._bootstrap_connector_environment_prefix(
                vault_url="http://127.0.0.1:18200",
                pg_host="127.0.0.1",
                pg_port="15432",
            )

            self.assertIn("PIONERA_TOPOLOGY=vm-single", prefix)
            self.assertIn(
                "PIONERA_KC_MANAGEMENT_URL=https://org4.pionera.oeg.fi.upm.es/auth",
                prefix,
            )

    def test_cleanup_uninstalls_release_before_bootstrap_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            calls = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None

            adapter._cleanup_connector_state(
                "conn-a-demo",
                tmpdir,
                "demo",
                "python3",
                namespace="demo",
            )

            helm_index = next(i for i, call in enumerate(calls) if call.startswith("helm uninstall"))
            delete_index = next(i for i, call in enumerate(calls) if "bootstrap.py connector delete" in call)
            self.assertLess(helm_index, delete_index)

    def test_create_connector_uses_configured_keycloak_url_for_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            calls = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_credentials_path("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write(
                            "{"
                            '"database":{"name":"db","user":"db","passwd":"secret"},'
                            '"certificates":{"path":"certs","passwd":"secret"},'
                            '"connector_user":{"user":"user","passwd":"secret"},'
                            '"vault":{"path":"secret/data/demo/conn-a-demo","token":"token"},'
                            '"minio":{"user":"conn-a-demo","passwd":"secret","access_key":"access","secret_key":"secret"}'
                            "}"
                        )
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=type(
                    "Infra",
                    (),
                    {
                        "ensure_local_infra_access": staticmethod(lambda: True),
                        "ensure_vault_unsealed": staticmethod(lambda: True),
                        "deploy_helm_release": staticmethod(lambda *_args, **_kwargs: True),
                        "wait_for_namespace_pods": staticmethod(lambda *_args, **_kwargs: True),
                        "manage_hosts_entries": staticmethod(lambda *_args, **_kwargs: None),
                        "get_pod_by_name": staticmethod(lambda *_args, **_kwargs: "minio"),
                    },
                )(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                self.assertTrue(adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"]))

            create_calls = [call for call in calls if "bootstrap.py connector create" in call]
            delete_calls = [call for call in calls if "bootstrap.py connector delete" in call]
            self.assertEqual(len(create_calls), 1)
            self.assertFalse(create_calls[0].startswith("PIONERA_KC_URL="))
            self.assertEqual(len(delete_calls), 1)
            self.assertFalse(delete_calls[0].startswith("PIONERA_KC_URL="))

    def test_create_connector_overrides_cluster_vault_url_with_temporary_local_port_forward(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            calls = []

            class ConfigAdapterWithVault(ConnectorRetryConfigAdapter):
                def __init__(self, root):
                    super().__init__(root)
                    self.topology = "vm-single"

                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://common-srvs-vault.common-srvs.svc:8200",
                            "VT_TOKEN": "root-token",
                        }
                    )
                    return values

            class Infra:
                def __init__(self):
                    self.port_forwards = []
                    self.stops = []

                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                @staticmethod
                def deploy_helm_release(*_args, **_kwargs):
                    return True

                @staticmethod
                def wait_for_namespace_pods(*_args, **_kwargs):
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "minio"

                def port_forward_service(self, *args, **kwargs):
                    self.port_forwards.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_credentials_path("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write(
                            "{"
                            '"database":{"name":"db","user":"db","passwd":"secret"},'
                            '"certificates":{"path":"certs","passwd":"secret"},'
                            '"connector_user":{"user":"user","passwd":"secret"},'
                            '"vault":{"path":"secret/data/demo/conn-a-demo","token":"token"},'
                            '"minio":{"user":"conn-a-demo","passwd":"secret","access_key":"access","secret_key":"secret"}'
                            "}"
                        )
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with (
                mock.patch.object(adapter, "_reserve_local_port", side_effect=[19082, 15432]),
                mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None),
            ):
                self.assertTrue(adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"]))

            create_calls = [call for call in calls if "bootstrap.py connector create" in call]
            delete_calls = [call for call in calls if "bootstrap.py connector delete" in call]
            self.assertEqual(len(create_calls), 1)
            self.assertEqual(len(delete_calls), 1)
            self.assertIn("PIONERA_VT_URL=http://127.0.0.1:19082", create_calls[0])
            self.assertIn("PIONERA_VT_URL=http://127.0.0.1:19082", delete_calls[0])
            self.assertIn("PIONERA_PG_HOST=127.0.0.1", create_calls[0])
            self.assertIn("PIONERA_PG_PORT=15432", create_calls[0])
            self.assertIn("PIONERA_PG_HOST=127.0.0.1", delete_calls[0])
            self.assertIn("PIONERA_PG_PORT=15432", delete_calls[0])
            self.assertEqual(
                infra.port_forwards,
                [
                    (
                        ("common-srvs", "common-srvs-vault", 19082, 8200),
                        {"quiet": True},
                    ),
                    (
                        ("common-srvs", "common-srvs-postgresql", 15432, 5432),
                        {"quiet": True},
                    ),
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("common-srvs", "common-srvs-postgresql"),
                        {"quiet": True},
                    ),
                    (
                        ("common-srvs", "common-srvs-vault"),
                        {"quiet": True},
                    ),
                ],
            )

    def test_vm_distributed_create_connector_uses_keycloak_port_forward_when_admin_hostname_unresolved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            calls = []
            readiness_urls = []

            class ConfigAdapterWithVmDistributedKeycloak(VmDistributedConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "KC_URL": "http://admin.auth.pionera.oeg.fi.upm.es",
                            "COMMON_SERVICES_NAMESPACE": "common-srvs",
                        }
                    )
                    return values

            class Infra:
                def __init__(self):
                    self.port_forwards = []
                    self.stops = []

                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                @staticmethod
                def deploy_helm_release(*_args, **_kwargs):
                    return True

                @staticmethod
                def wait_for_namespace_pods(*_args, **_kwargs):
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "common-srvs-keycloak-0"

                def port_forward_service(self, *args, **kwargs):
                    self.port_forwards.append((args, kwargs, os.environ.get("KUBECONFIG")))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs, os.environ.get("KUBECONFIG")))
                    return True

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_credentials_path("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write(
                            "{"
                            '"database":{"name":"db","user":"db","passwd":"secret"},'
                            '"certificates":{"path":"certs","passwd":"secret"},'
                            '"connector_user":{"user":"user","passwd":"secret"},'
                            '"vault":{"path":"secret/data/demo/conn-a-demo","token":"token"},'
                            '"minio":{"user":"conn-a-demo","passwd":"secret","access_key":"access","secret_key":"secret"}'
                            "}"
                        )
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithVmDistributedKeycloak(tmpdir),
                config_cls=config,
            )

            def fake_wait(*_args, **kwargs):
                readiness_urls.append(kwargs.get("keycloak_url"))
                return True

            adapter.wait_for_keycloak_admin_ready = fake_wait
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with (
                mock.patch.object(adapter, "_reserve_local_port", side_effect=[15432, 18081]),
                mock.patch("adapters.inesdata.connectors.socket.getaddrinfo", side_effect=OSError("not found")),
                mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None),
            ):
                self.assertTrue(adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"]))

            create_calls = [call for call in calls if "bootstrap.py connector create" in call]
            delete_calls = [call for call in calls if "bootstrap.py connector delete" in call]
            self.assertEqual(readiness_urls[0], "http://127.0.0.1:18081")
            self.assertIn("PIONERA_PG_HOST=127.0.0.1", create_calls[0])
            self.assertIn("PIONERA_PG_PORT=15432", create_calls[0])
            self.assertIn("PIONERA_KC_MANAGEMENT_URL=http://127.0.0.1:18081", create_calls[0])
            self.assertIn("PIONERA_PG_HOST=127.0.0.1", delete_calls[0])
            self.assertIn("PIONERA_PG_PORT=15432", delete_calls[0])
            self.assertIn("PIONERA_KC_MANAGEMENT_URL=http://127.0.0.1:18081", delete_calls[0])
            self.assertEqual(
                infra.port_forwards,
                [
                    (
                        ("common-srvs", "common-srvs-postgresql", 15432, 5432),
                        {"quiet": True},
                        "/clusters/common.yaml",
                    ),
                    (
                        ("common-srvs", "common-srvs-keycloak", 18081, 8080),
                        {"quiet": True},
                        "/clusters/common.yaml",
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("common-srvs", "common-srvs-keycloak"),
                        {"quiet": True},
                        "/clusters/common.yaml",
                    ),
                    (
                        ("common-srvs", "common-srvs-postgresql"),
                        {"quiet": True},
                        "/clusters/common.yaml",
                    )
                ],
            )

    def test_vm_distributed_keycloak_bootstrap_port_forward_can_be_forced_by_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class ConfigAdapterWithForcedKeycloak(VmDistributedConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "KC_URL": "http://admin.auth.pionera.oeg.fi.upm.es",
                            "KEYCLOAK_BOOTSTRAP_PORT_FORWARD": "true",
                        }
                    )
                    return values

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConfigAdapterWithForcedKeycloak(tmpdir),
                config_cls=config,
            )

            with mock.patch("adapters.inesdata.connectors.socket.getaddrinfo", return_value=[]):
                self.assertTrue(adapter._vm_distributed_keycloak_admin_needs_port_forward())

    def test_connector_ready_uses_hostname_without_port_forward_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-inteface-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )

            with (
                mock.patch.dict(os.environ, {"PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK": "false"}),
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.get", side_effect=Exception("connection refused")),
            ):
                self.assertFalse(adapter.wait_for_connector_ready("conn-a-demo", timeout=0.01))

            self.assertEqual(infra.calls, [])

    def test_connector_ready_falls_back_to_local_interface_port_forward_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-inteface-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )

            responses = iter([
                Exception("connection refused"),
                mock.Mock(status_code=200),
            ])

            def fake_get(*_args, **_kwargs):
                item = next(responses)
                if isinstance(item, Exception):
                    raise item
                return item

            with (
                mock.patch.dict(os.environ, {"PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK": "true"}),
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.get", side_effect=fake_get),
                mock.patch.object(adapter, "_reserve_local_port", return_value=19080),
            ):
                self.assertTrue(adapter.wait_for_connector_ready("conn-a-demo", timeout=5))

            self.assertEqual(
                infra.calls,
                [
                    (
                        ("demo", "conn-a-demo-inteface-123", 19080, 8080),
                        {"quiet": True},
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("demo", "conn-a-demo-inteface-123"),
                        {"quiet": True},
                    )
                ],
            )

    def test_management_api_ready_uses_hostname_without_port_forward_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.get_management_api_headers = lambda *_args, **_kwargs: {"Authorization": "Bearer token"}
            adapter.invalidate_management_api_token = lambda *_args, **_kwargs: None

            with (
                mock.patch.dict(os.environ, {"PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK": "false"}),
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.post", side_effect=Exception("connection refused")),
            ):
                self.assertFalse(adapter.wait_for_management_api_ready("conn-a-demo", timeout=0.01, poll_interval=0))

            self.assertEqual(infra.calls, [])

    def test_management_api_ready_falls_back_to_local_runtime_port_forward_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.get_management_api_headers = lambda *_args, **_kwargs: {"Authorization": "Bearer token"}
            adapter.invalidate_management_api_token = lambda *_args, **_kwargs: None

            responses = iter([
                Exception("connection refused"),
                mock.Mock(status_code=200),
            ])

            def fake_post(*_args, **_kwargs):
                item = next(responses)
                if isinstance(item, Exception):
                    raise item
                return item

            with (
                mock.patch.dict(os.environ, {"PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK": "true"}),
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.post", side_effect=fake_post),
                mock.patch.object(adapter, "_reserve_local_port", return_value=19193),
            ):
                self.assertTrue(adapter.wait_for_management_api_ready("conn-a-demo", timeout=5, poll_interval=0))

            self.assertEqual(
                infra.calls,
                [
                    (
                        ("demo", "conn-a-demo-123", 19193, 19193),
                        {"quiet": True},
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("demo", "conn-a-demo-123"),
                        {"quiet": True},
                    )
                ],
            )

    def test_management_api_ready_falls_back_on_http_503_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.get_management_api_headers = lambda *_args, **_kwargs: {"Authorization": "Bearer token"}
            adapter.invalidate_management_api_token = lambda *_args, **_kwargs: None

            responses = iter([
                mock.Mock(status_code=503),
                mock.Mock(status_code=200),
            ])

            with (
                mock.patch.dict(os.environ, {"PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK": "true"}),
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.post", side_effect=lambda *_a, **_k: next(responses)),
                mock.patch.object(adapter, "_reserve_local_port", return_value=19193),
            ):
                self.assertTrue(adapter.wait_for_management_api_ready("conn-a-demo", timeout=5, poll_interval=0))

            self.assertEqual(
                infra.calls,
                [
                    (
                        ("demo", "conn-a-demo-123", 19193, 19193),
                        {"quiet": True},
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("demo", "conn-a-demo-123"),
                        {"quiet": True},
                    )
                ],
            )

    def test_management_api_ready_role_aligned_fallback_uses_planned_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = RoleAlignedConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "runtime_namespace": "demo",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                            "registration_service_namespace": "demo-core",
                            "planned_registration_service_namespace": "demo-core",
                        }
                    ],
                }
            ]
            adapter.get_management_api_headers = lambda *_args, **_kwargs: {"Authorization": "Bearer token"}
            adapter.invalidate_management_api_token = lambda *_args, **_kwargs: None

            responses = iter([
                mock.Mock(status_code=503),
                mock.Mock(status_code=200),
            ])

            with (
                mock.patch.dict(os.environ, {"PIONERA_ALLOW_CONNECTOR_PORT_FORWARD_FALLBACK": "true"}),
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.post", side_effect=lambda *_a, **_k: next(responses)),
                mock.patch.object(adapter, "_reserve_local_port", return_value=19193),
            ):
                self.assertTrue(adapter.wait_for_management_api_ready("conn-a-demo", timeout=5, poll_interval=0))

            self.assertEqual(
                infra.calls,
                [
                    (
                        ("demo-provider", "conn-a-demo-123", 19193, 19193),
                        {"quiet": True},
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("demo-provider", "conn-a-demo-123"),
                        {"quiet": True},
                    )
                ],
            )

    def test_management_api_ready_role_aligned_waits_for_public_ingress_before_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = RoleAlignedConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "runtime_namespace": "demo",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                            "registration_service_namespace": "demo-core",
                            "planned_registration_service_namespace": "demo-core",
                        }
                    ],
                }
            ]
            adapter.get_management_api_headers = lambda *_args, **_kwargs: {"Authorization": "Bearer token"}
            adapter.invalidate_management_api_token = lambda *_args, **_kwargs: None

            responses = iter([
                mock.Mock(status_code=503),
                mock.Mock(status_code=200),
            ])

            with (
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.post", side_effect=lambda *_a, **_k: next(responses)),
                mock.patch.object(adapter, "_reserve_local_port", return_value=19193),
            ):
                self.assertTrue(adapter.wait_for_management_api_ready("conn-a-demo", timeout=5, poll_interval=0))

            self.assertEqual(
                infra.calls,
                [],
            )
            self.assertEqual(
                infra.stops,
                [],
            )

    def test_management_api_ready_role_aligned_falls_back_after_stabilization_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = RoleAlignedConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "runtime_namespace": "demo",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                            "registration_service_namespace": "demo-core",
                            "planned_registration_service_namespace": "demo-core",
                        }
                    ],
                }
            ]
            adapter.get_management_api_headers = lambda *_args, **_kwargs: {"Authorization": "Bearer token"}
            adapter.invalidate_management_api_token = lambda *_args, **_kwargs: None

            responses = iter([
                mock.Mock(status_code=503),
                mock.Mock(status_code=200),
            ])

            with (
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.post", side_effect=lambda *_a, **_k: next(responses)),
                mock.patch.object(adapter, "_reserve_local_port", return_value=19193),
                mock.patch.object(adapter, "_connector_public_ingress_stabilization_timeout", return_value=0),
                mock.patch.object(adapter, "_connector_public_ingress_resync_wait_seconds", return_value=0),
            ):
                self.assertTrue(adapter.wait_for_management_api_ready("conn-a-demo", timeout=5, poll_interval=0))

            self.assertEqual(
                infra.calls,
                [
                    (
                        ("demo-provider", "conn-a-demo-123", 19193, 19193),
                        {"quiet": True},
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("demo-provider", "conn-a-demo-123"),
                        {"quiet": True},
                    )
                ],
            )

    def test_management_api_ready_role_aligned_resyncs_ingress_before_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = RoleAlignedConnectorRetryConfigAdapter(tmpdir)

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "conn-a-demo-123 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "runtime_namespace": "demo",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                            "registration_service_namespace": "demo-core",
                            "planned_registration_service_namespace": "demo-core",
                        }
                    ],
                }
            ]
            adapter.get_management_api_headers = lambda *_args, **_kwargs: {"Authorization": "Bearer token"}
            adapter.invalidate_management_api_token = lambda *_args, **_kwargs: None

            responses = iter([
                mock.Mock(status_code=503),
                mock.Mock(status_code=200),
            ])

            with (
                mock.patch("adapters.inesdata.connectors.socket.gethostbyname", return_value="127.0.0.1"),
                mock.patch("adapters.inesdata.connectors.requests.post", side_effect=lambda *_a, **_k: next(responses)),
                mock.patch.object(adapter, "_connector_public_ingress_stabilization_timeout", return_value=0),
                mock.patch.object(adapter, "_connector_public_ingress_resync_wait_seconds", return_value=5),
                mock.patch.object(adapter, "_trigger_connector_ingress_resync", return_value=True) as resync,
            ):
                self.assertTrue(adapter.wait_for_management_api_ready("conn-a-demo", timeout=5, poll_interval=0))

            resync.assert_called_once_with("conn-a-demo")
            self.assertEqual(infra.calls, [])
            self.assertEqual(infra.stops, [])

    def test_create_connector_aborts_before_cleanup_when_vault_token_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(config.venv_path(), exist_ok=True)

            class ConfigAdapterWithVault(ConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://vault.local:8200",
                            "VT_TOKEN": "stale-token",
                        }
                    )
                    return values

            class Infra:
                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                @staticmethod
                def sync_vault_token_to_deployer_config():
                    return True

            calls = []
            adapter = INESDataConnectorsAdapter(
                run=lambda cmd, **_kwargs: calls.append(cmd) or object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=Infra(),
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )

            output = io.StringIO()
            with mock.patch(
                "adapters.inesdata.connectors.requests.get",
                return_value=mock.Mock(status_code=403),
            ), contextlib.redirect_stdout(output):
                created = adapter.create_connector("conn-a-demo", ["conn-a-demo"])

            self.assertFalse(created)
            self.assertIn("Vault token validation failed", output.getvalue())
            self.assertFalse(any("bootstrap.py connector delete" in call for call in calls))
            self.assertFalse(any("bootstrap.py connector create" in call for call in calls))

    def test_vault_management_preflight_accepts_root_capabilities(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class ConfigAdapterWithVault(ConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://vault.local:8200",
                            "VT_TOKEN": "root-token",
                        }
                    )
                    return values

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )

            capabilities = {
                "sys/policy/inesdata-preflight-secrets-policy": ["root"],
                "auth/token/create": ["root"],
                "secret/data/demo/inesdata-preflight/public-key": ["root"],
            }
            with mock.patch(
                "adapters.inesdata.connectors.requests.get",
                return_value=mock.Mock(status_code=200),
            ), mock.patch(
                "adapters.inesdata.connectors.requests.post",
                return_value=mock.Mock(status_code=200, json=lambda: capabilities),
            ):
                self.assertTrue(adapter._verify_vault_management_token(ds_name="demo"))

    def test_vault_management_preflight_uses_port_forward_for_cluster_service_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class ConfigAdapterWithVault(ConnectorRetryConfigAdapter):
                def __init__(self, root):
                    super().__init__(root)
                    self.topology = "vm-single"

                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://common-srvs-vault.common-srvs.svc:8200",
                            "VT_TOKEN": "root-token",
                        }
                    )
                    return values

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "common-srvs-vault-0 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )

            capabilities = {
                "sys/policy/inesdata-preflight-secrets-policy": ["root"],
                "auth/token/create": ["root"],
                "secret/data/demo/inesdata-preflight/public-key": ["root"],
            }
            get_responses = iter(
                [
                    requests.ConnectionError("Name or service not known"),
                    mock.Mock(status_code=200),
                ]
            )

            def fake_get(*_args, **_kwargs):
                response = next(get_responses)
                if isinstance(response, Exception):
                    raise response
                return response

            with (
                mock.patch.object(adapter, "_reserve_local_port", return_value=19082),
                mock.patch("adapters.inesdata.connectors.requests.get", side_effect=fake_get),
                mock.patch(
                    "adapters.inesdata.connectors.requests.post",
                    return_value=mock.Mock(status_code=200, json=lambda: capabilities),
                ),
            ):
                self.assertTrue(adapter._verify_vault_management_token(ds_name="demo"))

            self.assertEqual(
                infra.calls,
                [
                    (
                        ("common-srvs", "common-srvs-vault", 19082, 8200),
                        {"quiet": True},
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("common-srvs", "common-srvs-vault"),
                        {"quiet": True},
                    )
                ],
            )

    def test_vault_bootstrap_access_uses_local_port_forward_for_cluster_service_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class ConfigAdapterWithVault(ConnectorRetryConfigAdapter):
                def __init__(self, root):
                    super().__init__(root)
                    self.topology = "vm-single"

                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://common-srvs-vault.common-srvs.svc:8200",
                            "VT_TOKEN": "root-token",
                        }
                    )
                    return values

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs))
                    return True

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "common-srvs-vault-0 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )

            with mock.patch.object(adapter, "_reserve_local_port", return_value=19082):
                bootstrap_access = adapter._start_vault_bootstrap_access()
                adapter._stop_vault_bootstrap_access(bootstrap_access)

            self.assertEqual(bootstrap_access["vault_url"], "http://127.0.0.1:19082")
            self.assertEqual(
                infra.calls,
                [
                    (
                        ("common-srvs", "common-srvs-vault", 19082, 8200),
                        {"quiet": True},
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("common-srvs", "common-srvs-vault"),
                        {"quiet": True},
                    )
                ],
            )

    def test_vm_distributed_vault_bootstrap_access_uses_common_kubeconfig(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class ConfigAdapterWithVault(VmDistributedConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://common-srvs-vault.common-srvs.svc:8200",
                            "VT_TOKEN": "root-token",
                        }
                    )
                    return values

            class Infra:
                def __init__(self):
                    self.calls = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.calls.append((args, kwargs, os.environ.get("KUBECONFIG")))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs, os.environ.get("KUBECONFIG")))
                    return True

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "common-srvs-vault-0 1/1 Running 0 1m",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )

            with mock.patch.object(adapter, "_reserve_local_port", return_value=19082):
                bootstrap_access = adapter._start_vault_bootstrap_access()
                adapter._stop_vault_bootstrap_access(bootstrap_access)

            self.assertEqual(bootstrap_access["vault_url"], "http://127.0.0.1:19082")
            self.assertEqual(
                infra.calls,
                [
                    (
                        ("common-srvs", "common-srvs-vault", 19082, 8200),
                        {"quiet": True},
                        "/clusters/common.yaml",
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("common-srvs", "common-srvs-vault"),
                        {"quiet": True},
                        "/clusters/common.yaml",
                    )
                ],
            )

    def test_vault_token_sync_policy_uses_available_runtime_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class ConfigWithDeployerPath(ConnectorRetryConfig):
                def deployer_config_path(self):
                    return os.path.join(self.root, "deployer.config")

            config = ConfigWithDeployerPath(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=dummy-token\n")

            for topology, expected in (
                ("local", True),
                ("vm-single", True),
                ("vm-distributed", True),
            ):
                with self.subTest(topology=topology):
                    config_adapter = ConnectorRetryConfigAdapter(tmpdir)
                    config_adapter.topology = topology
                    adapter = INESDataConnectorsAdapter(
                        run=lambda *_args, **_kwargs: object(),
                        run_silent=lambda *_args, **_kwargs: "",
                        auto_mode_getter=lambda: True,
                        infrastructure_adapter=mock.Mock(),
                        config_adapter=config_adapter,
                        config_cls=config,
                    )

                    self.assertEqual(adapter._should_sync_vault_token_to_deployer_config(), expected)

    def test_prepare_vault_management_access_for_vm_distributed_reconciles_runtime_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class ConfigWithDeployerPath(ConnectorRetryConfig):
                def deployer_config_path(self):
                    return os.path.join(self.root, "deployer.config")

            config = ConfigWithDeployerPath(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=dummy-token\n")

            class ConfigAdapterWithVault(ConnectorRetryConfigAdapter):
                def __init__(self, root):
                    super().__init__(root)
                    self.topology = "vm-distributed"

                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://common-srvs-vault.common-srvs.svc:8200",
                            "VT_TOKEN": "root-token",
                        }
                    )
                    return values

            infrastructure = mock.Mock()
            infrastructure.ensure_vault_unsealed.return_value = True
            infrastructure.reconcile_vault_state_for_local_runtime.return_value = True
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infrastructure,
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )

            with mock.patch.object(adapter, "_verify_vault_management_token", return_value=True):
                self.assertTrue(adapter._prepare_vault_management_access(ds_name="demo"))

            infrastructure.ensure_local_infra_access.assert_not_called()
            infrastructure.ensure_vault_unsealed.assert_called_once()
            infrastructure.reconcile_vault_state_for_local_runtime.assert_called_once()

    def test_prepare_vault_management_access_skips_local_infra_check_outside_local_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class ConfigAdapterWithVault(ConnectorRetryConfigAdapter):
                def __init__(self, root):
                    super().__init__(root)
                    self.topology = "vm-single"

                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "VT_URL": "http://vault.remote:8200",
                            "VT_TOKEN": "root-token",
                        }
                    )
                    return values

            class Infra:
                def __init__(self):
                    self.local_calls = 0
                    self.vault_calls = 0

                def ensure_local_infra_access(self):
                    self.local_calls += 1
                    return False

                def ensure_vault_unsealed(self):
                    self.vault_calls += 1
                    return True

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithVault(tmpdir),
                config_cls=config,
            )

            with mock.patch.object(adapter, "_verify_vault_management_token", return_value=True):
                self.assertTrue(adapter._prepare_vault_management_access(ds_name="demo"))

            self.assertEqual(infra.local_calls, 0)
            self.assertEqual(infra.vault_calls, 1)

    def test_level4_local_image_policy_enables_managed_minikube_topologies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "vm-single"
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            policy = adapter._resolve_level4_local_image_policy(
                mode="auto",
                label="INESData connector",
            )

            self.assertEqual(policy["topology"], "vm-single")
            self.assertTrue(policy["prepare_local_images"])
            self.assertTrue(policy["allow_local_image_overrides"])
            self.assertEqual(policy["message"], "")

    def test_level4_local_images_default_for_vm_topologies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for topology, expected_mode in (("vm-single", "auto"), ("vm-distributed", "disabled")):
                config = ConnectorRetryConfig(tmpdir)
                config_adapter = ConnectorRetryConfigAdapter(tmpdir)
                config_adapter.topology = topology
                adapter = INESDataConnectorsAdapter(
                    run=lambda *_args, **_kwargs: object(),
                    run_silent=lambda *_args, **_kwargs: "",
                    auto_mode_getter=lambda: True,
                    infrastructure_adapter=mock.Mock(),
                    config_adapter=config_adapter,
                    config_cls=config,
                )

                self.assertEqual(adapter._level4_local_images_mode(), expected_mode)

    def test_level4_local_images_default_to_auto_for_local_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "local"
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            self.assertEqual(adapter._level4_local_images_mode(), "auto")

    def test_level4_local_images_can_be_opted_in_for_vm_single(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "vm-single"
            config_adapter.load_deployer_config = lambda: {"INESDATA_LOCAL_IMAGES_MODE": "auto"}
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            self.assertEqual(adapter._level4_local_images_mode(), "auto")

    def test_local_connector_image_override_path_is_used_for_vm_single(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "vm-single"
            config_adapter.load_deployer_config = lambda: {"INESDATA_LOCAL_IMAGES_MODE": "auto"}
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            with (
                mock.patch("adapters.inesdata.connectors.os.path.isfile", return_value=True),
                mock.patch("adapters.inesdata.connectors.os.path.getsize", return_value=1),
            ):
                self.assertIsNotNone(adapter._local_connector_image_override_path())

    def test_local_connector_image_override_path_is_ignored_when_level4_local_images_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "vm-single"
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            with (
                mock.patch.object(adapter, "_level4_local_images_mode", return_value="disabled"),
                mock.patch("adapters.inesdata.connectors.os.path.isfile", return_value=True),
                mock.patch("adapters.inesdata.connectors.os.path.getsize", return_value=1),
            ):
                self.assertIsNone(adapter._local_connector_image_override_path())

    def test_explicit_connector_image_override_path_writes_runtime_override_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            fake_module_file = os.path.join(tmpdir, "connectors.py")
            with mock.patch.dict(
                os.environ,
                {
                    "PIONERA_INESDATA_CONNECTOR_IMAGE_NAME": "registry.example/inesdata-connector",
                    "PIONERA_INESDATA_CONNECTOR_IMAGE_TAG": "vm-single-fix",
                    "PIONERA_INESDATA_CONNECTOR_INTERFACE_IMAGE_NAME": "registry.example/inesdata-interface",
                    "PIONERA_INESDATA_CONNECTOR_INTERFACE_IMAGE_TAG": "vm-single-ui",
                },
                clear=False,
            ), mock.patch("adapters.inesdata.connectors.__file__", fake_module_file):
                override_path = adapter._explicit_connector_image_override_path()

            self.assertIsNotNone(override_path)
            with open(override_path, encoding="utf-8") as handle:
                override = yaml.safe_load(handle)

            self.assertEqual(
                override["connector"]["image"],
                {"name": "registry.example/inesdata-connector", "tag": "vm-single-fix"},
            )
            self.assertEqual(
                override["connectorInterface"]["image"],
                {"name": "registry.example/inesdata-interface", "tag": "vm-single-ui"},
            )

    def test_explicit_connector_image_override_path_fails_when_incomplete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            with mock.patch.dict(
                os.environ,
                {"PIONERA_INESDATA_CONNECTOR_IMAGE_NAME": "registry.example/inesdata-connector"},
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "INESData connector image override is incomplete"):
                    adapter._explicit_connector_image_override_path()

    def test_update_connector_model_observer_config_uses_public_backend_url_in_compact_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-a-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  name: conn-a-demo\n"
                    "  dataspace: demo\n"
                    "  ingress:\n"
                    "    protocol: http\n"
                    "    hostname: conn-a-demo.dev.ds.dataspaceunit.upm\n"
                    "connectorInterface:\n"
                    "  ontologyHub:\n"
                    "    url: http://ontology-hub-demo.dev.ds.dataspaceunit.upm\n"
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "connectors": ["conn-a-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "active_namespace": "demo",
                            "registration_service_namespace": "demo",
                        }
                    ],
                }
            ]

            adapter.update_connector_model_observer_config(values_file, "conn-a-demo", ds_name="demo", ds_namespace="demo")

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

            self.assertEqual(
                values["connectorInterface"]["modelObserver"],
                {
                    "proxyTarget": "http://backend-demo.dev.ds.dataspaceunit.upm",
                    "strapiUrl": "http://backend-demo.dev.ds.dataspaceunit.upm",
                },
            )

    def test_update_connector_ontology_hub_config_uses_vm_single_public_component_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-org2-pionera.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  name: conn-org2-pionera\n"
                    "  dataspace: pionera\n"
                    "connectorInterface:\n"
                    "  ontologyHub:\n"
                    "    url: http://ontology-hub-pionera.dev.ds.dataspaceunit.upm\n"
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            adapter.update_connector_ontology_hub_config(
                values_file,
                "conn-org2-pionera",
                ds_name="pionera",
            )

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

            self.assertEqual(
                values["connectorInterface"]["ontologyHub"]["url"],
                "https://org4.pionera.oeg.fi.upm.es/ontology-hub",
            )

    def test_update_connector_ontology_hub_config_keeps_local_url_without_public_component_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-a-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  name: conn-a-demo\n"
                    "  dataspace: demo\n"
                    "connectorInterface:\n"
                    "  ontologyHub:\n"
                    "    url: http://ontology-hub-demo.dev.ds.dataspaceunit.upm\n"
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            adapter.update_connector_ontology_hub_config(
                values_file,
                "conn-a-demo",
                ds_name="demo",
            )

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

            self.assertEqual(
                values["connectorInterface"]["ontologyHub"]["url"],
                "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
            )

    def test_update_connector_model_observer_config_keeps_public_backend_url_for_role_aligned_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-a-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  name: conn-a-demo\n"
                    "  dataspace: demo\n"
                    "  ingress:\n"
                    "    protocol: http\n"
                    "    hostname: conn-a-demo.dev.ds.dataspaceunit.upm\n"
                    "connectorInterface: {}\n"
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "active_namespace": "demo-provider",
                            "registration_service_namespace": "demo-core",
                        }
                    ],
                }
            ]

            adapter.update_connector_model_observer_config(values_file, "conn-a-demo", ds_name="demo", ds_namespace="demo")

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["proxyTarget"],
                "http://backend-demo.dev.ds.dataspaceunit.upm",
            )
            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["strapiUrl"],
                "http://backend-demo.dev.ds.dataspaceunit.upm",
            )

    def test_update_connector_model_observer_config_uses_vm_distributed_org1_backend_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-org3-pionera.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  name: conn-org3-pionera\n"
                    "  dataspace: pionera\n"
                    "  ingress:\n"
                    "    protocol: http\n"
                    "    hostname: conn-org3-pionera.pionera.oeg.fi.upm.es\n"
                    "connectorInterface: {}\n"
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmDistributedConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            adapter.update_connector_model_observer_config(
                values_file,
                "conn-org3-pionera",
                ds_name="pionera",
                ds_namespace="pionera",
            )

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["proxyTarget"],
                "https://org1.dev.ds.dataspaceunit.upm/public-portal-backend",
            )
            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["strapiUrl"],
                "https://org1.dev.ds.dataspaceunit.upm/public-portal-backend",
            )
            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["journalBaseUrl"],
                "http://org1.dev.ds.dataspaceunit.upm/public-portal-backend",
            )

    def test_update_connector_model_observer_config_uses_vm_single_internal_backend_service(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-org2-pionera.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  name: conn-org2-pionera\n"
                    "  dataspace: pionera\n"
                    "  ingress:\n"
                    "    protocol: http\n"
                    "    hostname: conn-org2-pionera.pionera.oeg.fi.upm.es\n"
                    "  layout:\n"
                    "    registrationServiceNamespace: core-control\n"
                    "connectorInterface: {}\n"
                )

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmSinglePublicConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            adapter.update_connector_model_observer_config(
                values_file,
                "conn-org2-pionera",
                ds_name="pionera",
                ds_namespace="pionera",
            )

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["proxyTarget"],
                "http://pionera-public-portal-backend.core-control.svc.cluster.local:1337",
            )
            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["strapiUrl"],
                "http://pionera-public-portal-backend.core-control.svc.cluster.local:1337",
            )

    def test_update_connector_model_observer_config_respects_explicit_journal_base_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-org2-pionera.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  name: conn-org2-pionera\n"
                    "  dataspace: pionera\n"
                    "  ingress:\n"
                    "    protocol: http\n"
                    "    hostname: conn-org2-pionera.pionera.oeg.fi.upm.es\n"
                    "connectorInterface: {}\n"
                )

            config_adapter = VmDistributedConnectorRetryConfigAdapter(tmpdir)
            config_adapter.extra_config = {
                "AI_MODEL_OBSERVER_JOURNAL_BASE_URL": "http://observer.internal/public-portal-backend",
            }
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            adapter.update_connector_model_observer_config(
                values_file,
                "conn-org2-pionera",
                ds_name="pionera",
                ds_namespace="pionera",
            )

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

            self.assertEqual(
                values["connectorInterface"]["modelObserver"]["journalBaseUrl"],
                "http://observer.internal/public-portal-backend",
            )

    def test_level4_local_connector_images_fail_when_required_outside_managed_minikube_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "vm-distributed"
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            with (
                mock.patch.object(adapter, "_level4_local_images_mode", return_value="required"),
                mock.patch.object(adapter, "_framework_root_dir") as root_dir_mock,
            ):
                self.assertFalse(adapter._maybe_prepare_level4_local_connector_images("demo"))

            root_dir_mock.assert_not_called()

    def test_level4_local_connector_images_allow_vm_distributed_remote_import(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class RemoteImportConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-distributed"

                def load_deployer_config(self):
                    config = super().load_deployer_config()
                    config.update(
                        {
                            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                            "VM_PROVIDER_SSH_HOST": "pionera20",
                            "VM_PROVIDER_SSH_USER": "pionera",
                            "VM_CONSUMER_SSH_HOST": "pionera3",
                            "VM_CONSUMER_SSH_USER": "pionera",
                        }
                    )
                    return config

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=RemoteImportConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            policy = adapter._resolve_level4_local_image_policy(
                mode="required",
                label="INESData connector",
            )

            self.assertTrue(policy["prepare_local_images"])
            self.assertTrue(policy["allow_local_image_overrides"])
            self.assertEqual(policy["error"], "")

    def test_create_connector_retries_after_initial_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            calls = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                if "bootstrap.py connector create" in cmd:
                    attempt = sum("bootstrap.py connector create" in item for item in calls)
                    if attempt == 1:
                        return None
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=type(
                    "Infra",
                    (),
                    {
                        "ensure_local_infra_access": staticmethod(lambda: True),
                        "ensure_vault_unsealed": staticmethod(lambda: True),
                        "deploy_helm_release": staticmethod(lambda *_args, **_kwargs: True),
                        "wait_for_namespace_pods": staticmethod(lambda *_args, **_kwargs: True),
                        "manage_hosts_entries": staticmethod(lambda *_args, **_kwargs: None),
                        "get_pod_by_name": staticmethod(lambda *_args, **_kwargs: "minio"),
                    },
                )(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                created = adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"])

            self.assertTrue(created)
            create_calls = [call for call in calls if "bootstrap.py connector create" in call]
            delete_calls = [call for call in calls if "bootstrap.py connector delete" in call]
            self.assertEqual(len(create_calls), 2)
            self.assertEqual(len(delete_calls), 2)

    def test_vm_distributed_cleanup_uses_connector_kubeconfig_only_for_cluster_operations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = VmDistributedConnectorRetryConfigAdapter(tmpdir)
            calls = []

            def record(label):
                calls.append((label, os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE")))

            def fake_run(cmd, **_kwargs):
                if cmd.startswith("helm uninstall"):
                    record("helm")
                elif "bootstrap.py connector delete" in cmd:
                    record("bootstrap-delete")
                elif "psql" in cmd:
                    record("registration-db")
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pionera",
                    "namespace": "core-control",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-citycouncil-pionera", "conn-company-pionera"],
                    "connector_details": [
                        {
                            "name": "conn-citycouncil-pionera",
                            "role": "provider",
                            "namespace_role": "provider",
                            "active_namespace": "provider",
                            "planned_namespace": "provider",
                        },
                        {
                            "name": "conn-company-pionera",
                            "role": "consumer",
                            "namespace_role": "consumer",
                            "active_namespace": "consumer",
                            "planned_namespace": "consumer",
                        },
                    ],
                    "namespace_roles": {
                        "provider_namespace": "provider",
                        "consumer_namespace": "consumer",
                    },
                    "planned_namespace_roles": {
                        "provider_namespace": "provider",
                        "consumer_namespace": "consumer",
                    },
                }
            ]
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: record("postgres-clean")

            with mock.patch.dict(
                os.environ,
                {"KUBECONFIG": "/clusters/common.yaml", "PIONERA_KUBECONFIG_ROLE": "common"},
            ):
                adapter._cleanup_connector_state(
                    "conn-citycouncil-pionera",
                    tmpdir,
                    "pionera",
                    "python3",
                    namespace="provider",
                )

            self.assertIn(("helm", "/clusters/provider.yaml", "provider"), calls)
            self.assertIn(("bootstrap-delete", "/clusters/common.yaml", "common"), calls)
            self.assertIn(("postgres-clean", "/clusters/common.yaml", "common"), calls)
            self.assertIn(("registration-db", "/clusters/common.yaml", "common"), calls)

    def test_vm_single_k3s_connector_operations_use_configured_kubeconfig(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class VmSingleK3sConfigAdapter(VmSinglePublicConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "K3S_KUBECONFIG": "/clusters/vm-single.yaml",
                        }
                    )
                    return values

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=VmSingleK3sConfigAdapter(tmpdir),
                config_cls=config,
            )

            with mock.patch.dict(
                os.environ,
                {"KUBECONFIG": "/clusters/local.yaml", "PIONERA_KUBECONFIG_ROLE": "local"},
            ):
                with adapter._temporary_connector_kubeconfig("conn-org2-pionera"):
                    observed = (
                        os.environ.get("KUBECONFIG"),
                        os.environ.get("PIONERA_KUBECONFIG_ROLE"),
                    )
                restored = (
                    os.environ.get("KUBECONFIG"),
                    os.environ.get("PIONERA_KUBECONFIG_ROLE"),
                )

            self.assertEqual(observed, ("/clusters/vm-single.yaml", "common"))
            self.assertEqual(restored, ("/clusters/local.yaml", "local"))

    def test_vm_single_k3s_postgres_bootstrap_uses_configured_kubeconfig(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)

            class VmSingleK3sConfigAdapter(VmSinglePublicConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "K3S_KUBECONFIG": "/clusters/vm-single.yaml",
                        }
                    )
                    return values

            class Infra:
                def __init__(self):
                    self.port_forwards = []
                    self.stops = []

                def port_forward_service(self, *args, **kwargs):
                    self.port_forwards.append((args, kwargs, os.environ.get("KUBECONFIG")))
                    return True

                def stop_port_forward_service(self, *args, **kwargs):
                    self.stops.append((args, kwargs, os.environ.get("KUBECONFIG")))
                    return True

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=VmSingleK3sConfigAdapter(tmpdir),
                config_cls=config,
            )

            with (
                mock.patch.object(adapter, "_reserve_local_port", return_value=15432),
                mock.patch.dict(
                    os.environ,
                    {"KUBECONFIG": "/clusters/local.yaml", "PIONERA_KUBECONFIG_ROLE": "local"},
                ),
            ):
                access = adapter._start_postgres_bootstrap_access()
                adapter._stop_postgres_bootstrap_access(access)
                restored = (
                    os.environ.get("KUBECONFIG"),
                    os.environ.get("PIONERA_KUBECONFIG_ROLE"),
                )

            self.assertEqual(access["pg_host"], "127.0.0.1")
            self.assertEqual(access["pg_port"], "15432")
            self.assertEqual(
                infra.port_forwards,
                [
                    (
                        ("common-srvs", "common-srvs-postgresql", 15432, 5432),
                        {"quiet": True},
                        "/clusters/vm-single.yaml",
                    )
                ],
            )
            self.assertEqual(
                infra.stops,
                [
                    (
                        ("common-srvs", "common-srvs-postgresql"),
                        {"quiet": True},
                        "/clusters/vm-single.yaml",
                    )
                ],
            )
            self.assertEqual(restored, ("/clusters/local.yaml", "local"))

    def test_local_postgres_bootstrap_does_not_open_port_forward(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            infrastructure = mock.Mock()
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infrastructure,
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            access = adapter._start_postgres_bootstrap_access()

            self.assertEqual(access, {"pg_host": None, "pg_port": None, "port_forward": None})
            infrastructure.port_forward_service.assert_not_called()

    def test_level4_registration_schema_check_uses_vm_single_bootstrap_database_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            observed = {}

            class VmSingleK3sConfigAdapter(VmSinglePublicConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "K3S_KUBECONFIG": "/clusters/vm-single.yaml",
                        }
                    )
                    return values

            class Infra:
                def verify_dataspace_ready_for_level4(self):
                    observed["kubeconfig"] = os.environ.get("KUBECONFIG")
                    observed["role"] = os.environ.get("PIONERA_KUBECONFIG_ROLE")
                    observed["pg_host"] = os.environ.get("PIONERA_PG_HOST")
                    observed["pg_port"] = os.environ.get("PIONERA_PG_PORT")
                    return True, None

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=Infra(),
                config_adapter=VmSingleK3sConfigAdapter(tmpdir),
                config_cls=config,
            )

            with mock.patch.dict(
                os.environ,
                {"KUBECONFIG": "/clusters/local.yaml", "PIONERA_KUBECONFIG_ROLE": "local"},
            ):
                ready = adapter._ensure_registration_service_schema_ready_for_level4(
                    "pionera",
                    pg_host="127.0.0.1",
                    pg_port="15432",
                )
                restored = (
                    os.environ.get("KUBECONFIG"),
                    os.environ.get("PIONERA_KUBECONFIG_ROLE"),
                    os.environ.get("PIONERA_PG_HOST"),
                    os.environ.get("PIONERA_PG_PORT"),
                )

            self.assertTrue(ready)
            self.assertEqual(
                observed,
                {
                    "kubeconfig": "/clusters/vm-single.yaml",
                    "role": "common",
                    "pg_host": "127.0.0.1",
                    "pg_port": "15432",
                },
            )
            self.assertEqual(restored, ("/clusters/local.yaml", "local", None, None))

    def test_level4_registration_schema_check_fails_before_connector_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            calls = []

            class VmSingleK3sConfigAdapter(VmSinglePublicConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    values = super().load_deployer_config()
                    values.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "K3S_KUBECONFIG": "/clusters/vm-single.yaml",
                        }
                    )
                    return values

            class Infra:
                @staticmethod
                def ensure_vault_unsealed():
                    return True

                def port_forward_service(self, *_args, **_kwargs):
                    return True

                def stop_port_forward_service(self, *_args, **_kwargs):
                    return True

                def verify_dataspace_ready_for_level4(self):
                    return False, "registration-service schema was not ready"

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=Infra(),
                config_adapter=VmSingleK3sConfigAdapter(tmpdir),
                config_cls=config,
            )
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with (
                mock.patch.object(adapter, "_reserve_local_port", side_effect=[19082, 15432]),
                mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None),
            ):
                self.assertFalse(adapter.create_connector("conn-org2-pionera", ["conn-org2-pionera"]))

            self.assertFalse(any("bootstrap.py connector create" in call for call in calls))
            self.assertFalse(any("bootstrap.py connector delete" in call for call in calls))

    def test_vm_distributed_create_connector_deploys_provider_release_with_provider_kubeconfig(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = VmDistributedConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(config.venv_path(), exist_ok=True)
            calls = []

            def fake_run(cmd, **_kwargs):
                if "bootstrap.py connector create" in cmd:
                    calls.append(("bootstrap-create", os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE")))
                    with open(config.connector_values_file("conn-citycouncil-pionera"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            class RecordingInfra:
                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                def deploy_helm_release(self, *_args, **_kwargs):
                    calls.append(("helm-deploy", os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE")))
                    return True

                def wait_for_deployment_rollout(self, *_args, **_kwargs):
                    calls.append(("rollout", os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE")))
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "minio"

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=RecordingInfra(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "pionera",
                    "namespace": "core-control",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-citycouncil-pionera", "conn-company-pionera"],
                    "connector_details": [
                        {
                            "name": "conn-citycouncil-pionera",
                            "role": "provider",
                            "namespace_role": "provider",
                            "active_namespace": "provider",
                            "planned_namespace": "provider",
                        }
                    ],
                    "namespace_roles": {
                        "provider_namespace": "provider",
                        "consumer_namespace": "consumer",
                    },
                    "planned_namespace_roles": {
                        "provider_namespace": "provider",
                        "consumer_namespace": "consumer",
                    },
                }
            ]
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with mock.patch.dict(
                os.environ,
                {"KUBECONFIG": "/clusters/common.yaml", "PIONERA_KUBECONFIG_ROLE": "common"},
            ):
                created = adapter.create_connector(
                    "conn-citycouncil-pionera",
                    ["conn-citycouncil-pionera", "conn-company-pionera"],
                )

            self.assertTrue(created)
            self.assertIn(("bootstrap-create", "/clusters/common.yaml", "common"), calls)
            self.assertIn(("helm-deploy", "/clusters/provider.yaml", "provider"), calls)
            self.assertTrue(
                any(call == ("rollout", "/clusters/provider.yaml", "provider") for call in calls)
            )

    def test_create_connector_retries_after_partial_credentials_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            calls = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                if "bootstrap.py connector create" in cmd:
                    attempt = sum("bootstrap.py connector create" in item for item in calls)
                    creds_path = config.connector_credentials_path("conn-a-demo")
                    if attempt == 1:
                        with open(creds_path, "w", encoding="utf-8") as handle:
                            handle.write('{"database":{"name":"db","user":"db","passwd":"secret"}}')
                    else:
                        with open(creds_path, "w", encoding="utf-8") as handle:
                            handle.write(
                                "{"
                                '"database":{"name":"db","user":"db","passwd":"secret"},'
                                '"certificates":{"path":"certs","passwd":"secret"},'
                                '"connector_user":{"user":"user","passwd":"secret"},'
                                '"vault":{"path":"secret/data/demo/conn-a-demo","token":"token"},'
                                '"minio":{"user":"conn-a-demo","passwd":"secret","access_key":"access","secret_key":"secret"}'
                                "}"
                            )
                        with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                            handle.write("hostAliases: []\n")
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=type(
                    "Infra",
                    (),
                    {
                        "ensure_local_infra_access": staticmethod(lambda: True),
                        "ensure_vault_unsealed": staticmethod(lambda: True),
                        "deploy_helm_release": staticmethod(lambda *_args, **_kwargs: True),
                        "wait_for_namespace_pods": staticmethod(lambda *_args, **_kwargs: True),
                        "manage_hosts_entries": staticmethod(lambda *_args, **_kwargs: None),
                        "get_pod_by_name": staticmethod(lambda *_args, **_kwargs: "minio"),
                    },
                )(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                created = adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"])

            self.assertTrue(created)
            create_calls = [call for call in calls if "bootstrap.py connector create" in call]
            self.assertEqual(len(create_calls), 2)

    def test_create_connector_waits_for_runtime_and_interface_rollouts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(config.venv_path(), exist_ok=True)

            def fake_run(cmd, **_kwargs):
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            class RecordingInfra:
                def __init__(self):
                    self.rollout_calls = []
                    self.namespace_wait_calls = []

                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                @staticmethod
                def deploy_helm_release(*_args, **_kwargs):
                    return True

                def wait_for_deployment_rollout(self, *args, **kwargs):
                    self.rollout_calls.append((args, kwargs))
                    return True

                def wait_for_namespace_pods(self, *args, **kwargs):
                    self.namespace_wait_calls.append((args, kwargs))
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "minio"

            infra = RecordingInfra()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            created = adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"])

            self.assertTrue(created)
            self.assertEqual(
                infra.rollout_calls,
                [
                    (
                        ("demo", "conn-a-demo"),
                        {"timeout_seconds": 180, "label": "connector runtime 'conn-a-demo'"},
                    ),
                    (
                        ("demo", "conn-a-demo-inteface"),
                        {"timeout_seconds": 180, "label": "connector interface 'conn-a-demo'"},
                    ),
                ],
            )
            self.assertEqual(infra.namespace_wait_calls, [])

    def test_wait_for_connector_deployments_recovers_stalled_init_pod_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            commands = []

            class RecoveringInfra:
                def __init__(self):
                    self.rollout_calls = []
                    self.rollout_results = [False, True, True]

                def wait_for_deployment_rollout(self, *args, **kwargs):
                    self.rollout_calls.append((args, kwargs))
                    return self.rollout_results.pop(0)

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                return object()

            def fake_run_silent(cmd, **_kwargs):
                if "kubectl get pods" in cmd and "service=conn-a-demo" in cmd:
                    return "conn-a-demo-123 0/1 Init:0/1 0 3m\n"
                return ""

            infra = RecoveringInfra()
            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=fake_run_silent,
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertTrue(adapter._wait_for_connector_deployments("conn-a-demo", namespace="demo", timeout=180))
            self.assertEqual(
                commands,
                ["kubectl delete pod conn-a-demo-123 -n demo --wait=false"],
            )
            self.assertEqual(
                infra.rollout_calls,
                [
                    (
                        ("demo", "conn-a-demo"),
                        {"timeout_seconds": 180, "label": "connector runtime 'conn-a-demo'"},
                    ),
                    (
                        ("demo", "conn-a-demo"),
                        {
                            "timeout_seconds": 300,
                            "label": "connector runtime 'conn-a-demo' after stalled init pod recovery",
                        },
                    ),
                    (
                        ("demo", "conn-a-demo-inteface"),
                        {"timeout_seconds": 180, "label": "connector interface 'conn-a-demo'"},
                    ),
                ],
            )

    def test_wait_for_connector_deployments_does_not_recover_running_unready_pod(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            commands = []

            class FailingInfra:
                def __init__(self):
                    self.rollout_calls = []

                def wait_for_deployment_rollout(self, *args, **kwargs):
                    self.rollout_calls.append((args, kwargs))
                    return False

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                return object()

            def fake_run_silent(cmd, **_kwargs):
                if "kubectl get pods" in cmd and "service=conn-a-demo" in cmd:
                    return "conn-a-demo-123 0/1 Running 0 3m\n"
                return ""

            infra = FailingInfra()
            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=fake_run_silent,
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=ConnectorRetryConfig(tmpdir),
            )

            self.assertFalse(adapter._wait_for_connector_deployments("conn-a-demo", namespace="demo", timeout=180))
            self.assertEqual(commands, [])
            self.assertEqual(len(infra.rollout_calls), 1)

    def test_create_connector_uses_planned_namespace_when_level4_role_aligned_opt_in_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = RoleAlignedConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(config.venv_path(), exist_ok=True)

            def fake_run(cmd, **_kwargs):
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            class RecordingInfra:
                def __init__(self):
                    self.deploy_calls = []
                    self.rollout_calls = []

                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                def deploy_helm_release(self, *args, **kwargs):
                    self.deploy_calls.append((args, kwargs))
                    return True

                def wait_for_deployment_rollout(self, *args, **kwargs):
                    self.rollout_calls.append((args, kwargs))
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "minio"

            infra = RecordingInfra()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo", "conn-b-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "runtime_namespace": "demo",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                            "registration_service_namespace": "demo-core",
                            "planned_registration_service_namespace": "demo-core",
                        }
                    ],
                }
            ]
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            created = adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"])

            self.assertTrue(created)
            self.assertEqual(infra.deploy_calls[0][0][1], "demo-provider")
            self.assertEqual(
                infra.rollout_calls,
                [
                    (
                        ("demo-provider", "conn-a-demo"),
                        {"timeout_seconds": 180, "label": "connector runtime 'conn-a-demo'"},
                    ),
                    (
                        ("demo-provider", "conn-a-demo-inteface"),
                        {"timeout_seconds": 180, "label": "connector interface 'conn-a-demo'"},
                    ),
                ],
            )

    def test_deploy_connectors_recreates_healthy_existing_connectors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                handle.write("hostAliases: []\n")

            class Infra:
                def __init__(self):
                    self.host_entries = None

                def manage_hosts_entries(self, entries):
                    self.host_entries = entries
                    return None

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "connectors": ["conn-a-demo"],
                }
            ]
            adapter.connector_already_exists = lambda *_args, **_kwargs: True
            adapter.connector_is_healthy = lambda *_args, **_kwargs: True
            adapter.connector_database_credentials_valid = lambda *_args, **_kwargs: True
            adapter.create_connector = mock.Mock()
            adapter.wait_for_all_connectors = mock.Mock(return_value=True)
            adapter.validate_connectors_with_stabilization = mock.Mock(return_value=True)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            adapter.create_connector.assert_called_once_with("conn-a-demo", ["conn-a-demo"])
            adapter.wait_for_all_connectors.assert_called_once_with(["conn-a-demo"])
            self.assertEqual(infra.host_entries, [])

    def test_deploy_connectors_additive_mode_preserves_healthy_existing_connectors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = AdditiveConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            class Infra:
                def __init__(self):
                    self.host_entries = None

                def manage_hosts_entries(self, entries):
                    self.host_entries = entries
                    return None

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "connectors": ["conn-a-demo"],
                }
            ]
            adapter.connector_already_exists = lambda *_args, **_kwargs: True
            adapter.connector_is_healthy = lambda *_args, **_kwargs: True
            adapter.connector_database_credentials_valid = lambda *_args, **_kwargs: True
            adapter.create_connector = mock.Mock()
            adapter.wait_for_all_connectors = mock.Mock(return_value=True)
            adapter.validate_connectors_with_stabilization = mock.Mock(return_value=True)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            adapter.create_connector.assert_not_called()
            adapter.wait_for_all_connectors.assert_called_once_with(["conn-a-demo"])
            self.assertEqual(infra.host_entries, [])

    def test_deploy_connectors_skips_host_sync_for_vm_single(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "vm-single"
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                handle.write("hostAliases: []\n")

            class Infra:
                def __init__(self):
                    self.host_entries = None
                    self.host_calls = 0

                def manage_hosts_entries(self, entries):
                    self.host_calls += 1
                    self.host_entries = entries
                    return None

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "connectors": ["conn-a-demo"],
                }
            ]
            adapter.connector_already_exists = lambda *_args, **_kwargs: True
            adapter.connector_is_healthy = lambda *_args, **_kwargs: True
            adapter.connector_database_credentials_valid = lambda *_args, **_kwargs: True
            adapter.create_connector = mock.Mock()
            adapter.wait_for_all_connectors = mock.Mock(return_value=True)
            adapter.validate_connectors_with_stabilization = mock.Mock(return_value=True)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            adapter.wait_for_all_connectors.assert_called_once_with(["conn-a-demo"])
            adapter.validate_connectors_with_stabilization.assert_called_once()
            self.assertEqual(infra.host_calls, 0)
            self.assertIsNone(infra.host_entries)

    def test_deploy_connectors_prepares_local_images_before_creating_connectors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class LocalImagesConfig(ConnectorRetryConfig):
                def script_dir(self):
                    return self.root

            config = LocalImagesConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector"), exist_ok=True)
            os.makedirs(
                os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector-interface"),
                exist_ok=True,
            )
            script_path = os.path.join(tmpdir, "adapters", "inesdata", "scripts", "local_build_load_deploy.sh")
            open(script_path, "w", encoding="utf-8").close()
            events = []

            class Infra:
                def __init__(self):
                    self.host_entries = None

                def manage_hosts_entries(self, entries):
                    self.host_entries = entries
                    return None

            def fake_run(cmd, **_kwargs):
                if "local_build_load_deploy.sh" in cmd:
                    events.append(("prepare-images", cmd))
                return object()

            infra = Infra()
            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "connectors": ["conn-a-demo"],
                }
            ]
            adapter.connector_already_exists = lambda *_args, **_kwargs: False
            adapter.wait_for_all_connectors = mock.Mock(return_value=True)
            adapter.validate_connectors_with_stabilization = mock.Mock(return_value=True)

            def create_connector(connector, _connectors):
                events.append(("create-connector", connector))
                with open(config.connector_values_file(connector), "w", encoding="utf-8") as handle:
                    handle.write("hostAliases: []\n")
                return True

            adapter.create_connector = mock.Mock(side_effect=create_connector)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            self.assertEqual(events[0][0], "prepare-images")
            self.assertEqual(events[1], ("create-connector", "conn-a-demo"))
            self.assertIn("--deploy-target connectors", events[0][1])
            self.assertIn("--minikube-profile minikube", events[0][1])
            self.assertIn("--cluster-runtime minikube", events[0][1])
            self.assertIn("--skip-deploy", events[0][1])
            adapter.wait_for_all_connectors.assert_called_once_with(["conn-a-demo"])
            adapter.validate_connectors_with_stabilization.assert_called_once_with(
                ["conn-a-demo"],
                retries=1,
                wait_seconds=30,
                check_database_credentials=True,
            )

    def test_deploy_connectors_prepares_local_images_with_k3s_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class LocalImagesConfig(ConnectorRetryConfig):
                def script_dir(self):
                    return self.root

            class K3sConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-single"

                def load_deployer_config(self):
                    config = super().load_deployer_config()
                    config["CLUSTER_TYPE"] = "k3s"
                    config["INESDATA_LOCAL_IMAGES_MODE"] = "auto"
                    return config

            config = LocalImagesConfig(tmpdir)
            config_adapter = K3sConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector"), exist_ok=True)
            os.makedirs(
                os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector-interface"),
                exist_ok=True,
            )
            script_path = os.path.join(tmpdir, "adapters", "inesdata", "scripts", "local_build_load_deploy.sh")
            open(script_path, "w", encoding="utf-8").close()
            events = []

            class Infra:
                def manage_hosts_entries(self, _entries):
                    return None

            def fake_run(cmd, **_kwargs):
                if "local_build_load_deploy.sh" in cmd:
                    events.append(cmd)
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=Infra(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "connectors": ["conn-a-demo"],
                }
            ]
            adapter.connector_already_exists = lambda *_args, **_kwargs: False

            def create_connector(connector, _connectors):
                with open(config.connector_values_file(connector), "w", encoding="utf-8") as handle:
                    handle.write("hostAliases: []\n")
                return True

            adapter.create_connector = mock.Mock(side_effect=create_connector)
            adapter.wait_for_all_connectors = mock.Mock(return_value=True)
            adapter.validate_connectors_with_stabilization = mock.Mock(return_value=True)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            self.assertEqual(len(events), 1)
            self.assertIn("--cluster-runtime k3s", events[0])
            self.assertIn("--minikube-profile minikube", events[0])
            adapter.wait_for_all_connectors.assert_called_once_with(["conn-a-demo"])
            adapter.validate_connectors_with_stabilization.assert_called_once()

    def test_level4_vm_single_k3s_uses_remote_import_env_when_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class LocalImagesConfig(ConnectorRetryConfig):
                def script_dir(self):
                    return self.root

            class RemoteImportConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-single"

                def load_deployer_config(self):
                    config = super().load_deployer_config()
                    config.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "VM_EXTERNAL_IP": "192.168.122.52",
                            "VM_SINGLE_SSH_HOST": "192.168.122.52",
                            "VM_SINGLE_SSH_USER": "pionera",
                            "VM_SINGLE_SSH_PORT": "22",
                            "SSH_ACCESS_MODE": "bastion",
                            "SSH_BASTION_HOST": "orion.example.test",
                            "SSH_BASTION_USER": "pionera",
                            "SSH_BASTION_PORT": "2222",
                            "SSH_IDENTITY_FILE": "/home/operator/.ssh/vm-single",
                            "VM_SINGLE_REMOTE_IMAGE_IMPORT": "auto",
                            "VM_SINGLE_REMOTE_IMAGE_IMPORT_INTERACTIVE": "auto",
                            "INESDATA_LOCAL_IMAGES_MODE": "auto",
                        }
                    )
                    return config

            config = LocalImagesConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector"), exist_ok=True)
            os.makedirs(
                os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector-interface"),
                exist_ok=True,
            )
            script_path = os.path.join(tmpdir, "adapters", "inesdata", "scripts", "local_build_load_deploy.sh")
            open(script_path, "w", encoding="utf-8").close()
            events = []

            adapter = INESDataConnectorsAdapter(
                run=lambda cmd, **_kwargs: events.append(cmd) or object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=RemoteImportConfigAdapter(tmpdir),
                config_cls=config,
            )

            self.assertTrue(adapter._maybe_prepare_level4_local_connector_images("demo"))

            self.assertEqual(len(events), 1)
            self.assertIn("K3S_REMOTE_IMPORT_HOST=192.168.122.52", events[0])
            self.assertIn("K3S_REMOTE_IMPORT_USER=pionera", events[0])
            self.assertIn("K3S_REMOTE_IMPORT_BASTION_HOST=orion.example.test", events[0])
            self.assertIn("K3S_REMOTE_IMPORT_INTERACTIVE=auto", events[0])
            self.assertIn("--cluster-runtime k3s", events[0])

    def test_level4_vm_distributed_remote_import_env_targets_connector_namespace_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class LocalImagesConfig(ConnectorRetryConfig):
                def script_dir(self):
                    return self.root

            class RemoteImportConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-distributed"

                def load_deployer_config(self):
                    config = super().load_deployer_config()
                    config.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                            "SSH_ACCESS_MODE": "bastion",
                            "SSH_BASTION_HOST": "orion.example.test",
                            "SSH_BASTION_PORT": "2222",
                            "SSH_BASTION_USER": "jump",
                            "VM_PROVIDER_SSH_HOST": "pionera20",
                            "VM_PROVIDER_SSH_USER": "pionera",
                            "VM_PROVIDER_SSH_PORT": "22",
                            "VM_CONSUMER_SSH_HOST": "pionera3",
                            "VM_CONSUMER_SSH_USER": "pionera",
                            "VM_CONSUMER_SSH_PORT": "22",
                            "INESDATA_LOCAL_IMAGES_MODE": "auto",
                        }
                    )
                    return config

            config = LocalImagesConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector"), exist_ok=True)
            os.makedirs(
                os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector-interface"),
                exist_ok=True,
            )
            script_path = os.path.join(tmpdir, "adapters", "inesdata", "scripts", "local_build_load_deploy.sh")
            open(script_path, "w", encoding="utf-8").close()
            events = []

            adapter = INESDataConnectorsAdapter(
                run=lambda cmd, **_kwargs: events.append(cmd) or object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=RemoteImportConfigAdapter(tmpdir),
                config_cls=config,
            )

            self.assertTrue(adapter._maybe_prepare_level4_local_connector_images("provider"))

            self.assertEqual(len(events), 1)
            self.assertIn("K3S_REMOTE_IMPORT_HOST=pionera20", events[0])
            self.assertIn("K3S_REMOTE_IMPORT_USER=pionera", events[0])
            self.assertIn("K3S_REMOTE_IMPORT_BASTION_HOST=orion.example.test", events[0])
            self.assertIn("--cluster-runtime k3s", events[0])

    def test_level4_vm_distributed_builds_once_and_reuses_manifest_for_second_cluster(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class LocalImagesConfig(ConnectorRetryConfig):
                def script_dir(self):
                    return self.root

            class RemoteImportConfigAdapter(ConnectorRetryConfigAdapter):
                topology = "vm-distributed"

                def load_deployer_config(self):
                    config = super().load_deployer_config()
                    config.update(
                        {
                            "CLUSTER_TYPE": "k3s",
                            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                            "VM_PROVIDER_SSH_HOST": "pionera20",
                            "VM_PROVIDER_SSH_USER": "pionera",
                            "VM_CONSUMER_SSH_HOST": "pionera3",
                            "VM_CONSUMER_SSH_USER": "pionera",
                            "INESDATA_LOCAL_IMAGES_MODE": "auto",
                        }
                    )
                    return config

            config = LocalImagesConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector"), exist_ok=True)
            os.makedirs(
                os.path.join(tmpdir, "adapters", "inesdata", "sources", "inesdata-connector-interface"),
                exist_ok=True,
            )
            script_path = os.path.join(tmpdir, "adapters", "inesdata", "scripts", "local_build_load_deploy.sh")
            open(script_path, "w", encoding="utf-8").close()
            events = []

            def fake_run(cmd, **_kwargs):
                events.append(cmd)
                parts = shlex.split(cmd)
                if "--manifest" in parts and "--skip-build" not in parts:
                    manifest_path = parts[parts.index("--manifest") + 1]
                    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
                    with open(manifest_path, "w", encoding="utf-8") as handle:
                        handle.write("component\trepo_dir\timage\ttag\tfull_image\tbuild_cmd\n")
                        handle.write(
                            "connector\t.\tlocal/inesdata/inesdata-connector\ttag1\t"
                            "local/inesdata/inesdata-connector:tag1\tbuild\n"
                        )
                        handle.write(
                            "connector-interface\t.\tlocal/inesdata/inesdata-connector-interface\ttag1\t"
                            "local/inesdata/inesdata-connector-interface:tag1\tbuild\n"
                        )
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=RemoteImportConfigAdapter(tmpdir),
                config_cls=config,
            )

            self.assertTrue(
                adapter._prepare_level4_local_connector_images_for_namespaces(["provider", "consumer"])
            )

            self.assertEqual(len(events), 2)
            first_parts = shlex.split(events[0])
            second_parts = shlex.split(events[1])
            first_manifest = first_parts[first_parts.index("--manifest") + 1]
            second_manifest = second_parts[second_parts.index("--manifest") + 1]

            self.assertEqual(first_manifest, second_manifest)
            self.assertNotIn("--skip-build", first_parts)
            self.assertIn("--skip-build", second_parts)
            self.assertIn("K3S_REMOTE_IMPORT_HOST=pionera20", events[0])
            self.assertIn("K3S_REMOTE_IMPORT_HOST=pionera3", events[1])

    def test_deploy_connectors_prepares_vm_distributed_images_for_provider_and_consumer_clusters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = VmDistributedConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)
            prepared_namespaces = []

            class Infra:
                def manage_hosts_entries(self, _entries):
                    return None

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=Infra(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo-core",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo", "conn-b-demo"],
                    "planned_namespace_roles": {
                        "provider_namespace": "demo-provider",
                        "consumer_namespace": "demo-consumer",
                    },
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "active_namespace": "demo-provider",
                            "namespace_role": "provider",
                        },
                        {
                            "name": "conn-b-demo",
                            "active_namespace": "demo-consumer",
                            "namespace_role": "consumer",
                        },
                    ],
                }
            ]
            adapter._maybe_prepare_level4_local_connector_images = lambda namespace: prepared_namespaces.append(namespace) or True
            adapter.connector_already_exists = lambda *_args, **_kwargs: False
            adapter.wait_for_all_connectors = mock.Mock(return_value=True)
            adapter.validate_connectors_with_stabilization = mock.Mock(return_value=True)

            def create_connector(connector, _connectors):
                with open(config.connector_values_file(connector), "w", encoding="utf-8") as handle:
                    handle.write("hostAliases: []\n")
                return True

            adapter.create_connector = mock.Mock(side_effect=create_connector)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertCountEqual(deployed, ["conn-a-demo", "conn-b-demo"])
            self.assertEqual(prepared_namespaces, ["demo-provider", "demo-consumer"])

    def test_deploy_connectors_cleans_stale_connectors_in_discovered_target_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            class Infra:
                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                @staticmethod
                def manage_hosts_entries(_entries):
                    return None

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=Infra(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "runtime_namespace": "demo",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                            "registration_service_namespace": "demo-core",
                            "planned_registration_service_namespace": "demo-core",
                        }
                    ],
                }
            ]
            adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
            adapter._maybe_prepare_level4_local_connector_images = lambda _namespace: True
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True
            discovery_calls = []

            def discover_existing(ds_name, namespace, include_runtime_artifacts=True):
                discovery_calls.append((ds_name, namespace, include_runtime_artifacts))
                return {"conn-stale-demo"} if namespace == "demo-provider" else set()

            adapter._discover_existing_connectors = discover_existing
            cleanup_calls = []
            adapter._cleanup_connector_state = lambda connector, repo_dir, ds_name, python_exec, namespace=None: cleanup_calls.append(
                (connector, namespace)
            )
            adapter.connector_already_exists = lambda *_args, **_kwargs: False
            def create_connector(connector, _connectors):
                with open(config.connector_values_file(connector), "w", encoding="utf-8") as handle:
                    handle.write("hostAliases: []\n")
                return True

            adapter.create_connector = mock.Mock(side_effect=create_connector)
            adapter.wait_for_all_connectors = mock.Mock()
            adapter.validate_connectors_with_stabilization = mock.Mock(return_value=True)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            self.assertEqual(
                discovery_calls,
                [
                    ("demo", "demo-provider", False),
                ],
            )
            self.assertEqual(cleanup_calls, [("conn-stale-demo", "demo-provider")])
            adapter.create_connector.assert_called_once_with("conn-a-demo", ["conn-a-demo"])
            adapter.wait_for_all_connectors.assert_called_once_with(["conn-a-demo"])
            adapter.validate_connectors_with_stabilization.assert_called_once_with(
                ["conn-a-demo"],
                retries=1,
                wait_seconds=30,
                check_database_credentials=True,
            )

    def test_vm_distributed_stale_cleanup_uses_bootstrap_access_and_namespace_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = VmDistributedConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            class Infra:
                @staticmethod
                def ensure_vault_unsealed():
                    return True

                @staticmethod
                def manage_hosts_entries(_entries):
                    return None

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=Infra(),
                config_adapter=config_adapter,
                config_cls=config,
            )
            dataspaces = [
                {
                    "name": "pionera",
                    "namespace": "core-control",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-org2-pionera", "conn-org3-pionera"],
                    "connector_details": [
                        {
                            "name": "conn-org2-pionera",
                            "role": "provider",
                            "namespace_role": "provider",
                            "active_namespace": "provider",
                            "planned_namespace": "provider",
                        },
                        {
                            "name": "conn-org3-pionera",
                            "role": "consumer",
                            "namespace_role": "consumer",
                            "active_namespace": "consumer",
                            "planned_namespace": "consumer",
                        },
                    ],
                    "namespace_roles": {
                        "provider_namespace": "provider",
                        "consumer_namespace": "consumer",
                    },
                    "planned_namespace_roles": {
                        "provider_namespace": "provider",
                        "consumer_namespace": "consumer",
                    },
                }
            ]
            adapter.load_dataspace_connectors = lambda: dataspaces
            adapter._maybe_prepare_level4_local_connector_images = lambda _namespace: True
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True
            adapter._start_level4_connector_bootstrap_access = mock.Mock(
                return_value={
                    "vault_url": "http://127.0.0.1:19082",
                    "keycloak_url": "http://127.0.0.1:18081",
                    "pg_host": "127.0.0.1",
                    "pg_port": "15432",
                }
            )
            adapter._ensure_level4_keycloak_ready = mock.Mock(return_value=True)
            adapter._stop_level4_connector_bootstrap_access = mock.Mock()

            def discover_existing(_ds_name, namespace, include_runtime_artifacts=True):
                if namespace == "provider":
                    return {"conn-citycouncil-pionera"}
                if namespace == "consumer":
                    return {"conn-company-pionera"}
                return set()

            adapter._discover_existing_connectors = discover_existing
            cleanup_calls = []

            def cleanup(connector, repo_dir, ds_name, python_exec, **kwargs):
                cleanup_calls.append((connector, kwargs))

            adapter._cleanup_connector_state = cleanup
            adapter.connector_already_exists = lambda *_args, **_kwargs: False

            def create_connector(connector, _connectors):
                with open(config.connector_values_file(connector), "w", encoding="utf-8") as handle:
                    handle.write("hostAliases: []\n")
                return True

            adapter.create_connector = mock.Mock(side_effect=create_connector)
            adapter.wait_for_all_connectors = mock.Mock(return_value=True)

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertCountEqual(deployed, ["conn-org2-pionera", "conn-org3-pionera"])
            self.assertEqual(
                cleanup_calls,
                [
                    (
                        "conn-citycouncil-pionera",
                        {
                            "namespace": "provider",
                            "dataspace": dataspaces[0],
                            "kubeconfig_role": "provider",
                            "vault_url": "http://127.0.0.1:19082",
                            "keycloak_url": "http://127.0.0.1:18081",
                            "pg_host": "127.0.0.1",
                            "pg_port": "15432",
                        },
                    ),
                    (
                        "conn-company-pionera",
                        {
                            "namespace": "consumer",
                            "dataspace": dataspaces[0],
                            "kubeconfig_role": "consumer",
                            "vault_url": "http://127.0.0.1:19082",
                            "keycloak_url": "http://127.0.0.1:18081",
                            "pg_host": "127.0.0.1",
                            "pg_port": "15432",
                        },
                    ),
                ],
            )
            adapter._start_level4_connector_bootstrap_access.assert_called_once()
            adapter._ensure_level4_keycloak_ready.assert_called_once()
            adapter._stop_level4_connector_bootstrap_access.assert_called_once()

    def test_discover_existing_connectors_can_ignore_runtime_artifacts_for_namespace_scoped_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            creds_dir = os.path.join(tmpdir, "deployments", "DEV", "demo")
            os.makedirs(creds_dir, exist_ok=True)
            with open(
                os.path.join(creds_dir, "credentials-connector-conn-stale-demo.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("{}")

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=ConnectorRetryConfigAdapter(tmpdir),
                config_cls=config,
            )

            with_runtime_artifacts = adapter._discover_existing_connectors("demo", "demo-provider")
            namespace_scoped = adapter._discover_existing_connectors(
                "demo",
                "demo-provider",
                include_runtime_artifacts=False,
            )

            self.assertEqual(with_runtime_artifacts, {"conn-stale-demo"})
            self.assertEqual(namespace_scoped, set())

    def test_get_cluster_connectors_prefers_namespace_scoped_discovery_for_role_aligned_dataspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: "",
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=RoleAlignedConnectorRetryConfigAdapter(tmpdir),
                config_cls=lambda: None,
            )
            adapter.config = ConnectorRetryConfig(tmpdir)
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo", "conn-b-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                        },
                        {
                            "name": "conn-b-demo",
                            "role": "consumer",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-consumer",
                        },
                    ],
                }
            ]
            adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
            discovery_calls = []

            def discover_existing(ds_name, namespace, include_runtime_artifacts=True):
                discovery_calls.append((ds_name, namespace, include_runtime_artifacts))
                if namespace == "demo-provider":
                    return {"conn-a-demo"}
                if namespace == "demo-consumer":
                    return {"conn-b-demo"}
                return set()

            adapter._discover_existing_connectors = discover_existing

            connectors = adapter.get_cluster_connectors()

            self.assertEqual(connectors, ["conn-a-demo", "conn-b-demo"])
            self.assertEqual(
                discovery_calls,
                [
                    ("demo", "demo-provider", False),
                    ("demo", "demo-consumer", False),
                ],
            )

    def test_show_connector_logs_prefers_namespace_scoped_role_aligned_listing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = INESDataConnectorsAdapter(
                run=mock.Mock(),
                run_silent=lambda cmd, **_kwargs: {
                    "kubectl get pods -n demo-provider --no-headers": (
                        "conn-a-demo-6bf9f7c9c8-abcd1 1/1 Running 0 1m\n"
                    ),
                    "kubectl get pods -n demo-consumer --no-headers": (
                        "conn-b-demo-7cf8d8d5bd-efgh2 1/1 Running 0 1m\n"
                    ),
                }.get(cmd, ""),
                auto_mode_getter=lambda: True,
                infrastructure_adapter=mock.Mock(),
                config_adapter=RoleAlignedConnectorRetryConfigAdapter(tmpdir),
                config_cls=lambda: None,
            )
            adapter.config = ConnectorRetryConfig(tmpdir)
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "namespace_profile": "role-aligned",
                    "connectors": ["conn-a-demo", "conn-b-demo"],
                    "connector_details": [
                        {
                            "name": "conn-a-demo",
                            "role": "provider",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-provider",
                        },
                        {
                            "name": "conn-b-demo",
                            "role": "consumer",
                            "active_namespace": "demo",
                            "planned_namespace": "demo-consumer",
                        },
                    ],
                }
            ]
            adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
            discovery_calls = []

            def discover_existing(ds_name, namespace, include_runtime_artifacts=True):
                discovery_calls.append((ds_name, namespace, include_runtime_artifacts))
                if namespace == "demo-provider":
                    return {"conn-a-demo"}
                if namespace == "demo-consumer":
                    return {"conn-b-demo"}
                return set()

            adapter._discover_existing_connectors = discover_existing

            output = io.StringIO()
            with contextlib.redirect_stdout(output), mock.patch(
                "builtins.input",
                side_effect=["2", "N"],
            ):
                adapter.show_connector_logs()

            self.assertEqual(
                discovery_calls,
                [
                    ("demo", "demo-provider", False),
                    ("demo", "demo-consumer", False),
                ],
            )
            rendered = output.getvalue()
            self.assertIn("1 - conn-a-demo (demo-provider) -> conn-a-demo-6bf9f7c9c8-abcd1", rendered)
            self.assertIn("2 - conn-b-demo (demo-consumer) -> conn-b-demo-7cf8d8d5bd-efgh2", rendered)
            adapter.run.assert_called_once_with(
                "kubectl logs conn-b-demo-7cf8d8d5bd-efgh2 -n demo-consumer",
                check=False,
            )

    def test_deploy_connectors_aborts_after_failed_recreation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            class Infra:
                def __init__(self):
                    self.host_entries = None

                def manage_hosts_entries(self, entries):
                    self.host_entries = entries
                    return None

            infra = Infra()

            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demo",
                    "namespace": "demo",
                    "connectors": ["conn-a-demo", "conn-b-demo"],
                }
            ]
            adapter.connector_already_exists = lambda *_args, **_kwargs: True
            adapter.connector_is_healthy = lambda *_args, **_kwargs: True
            adapter.connector_database_credentials_valid = lambda *_args, **_kwargs: True
            adapter.create_connector = mock.Mock(return_value=False)
            adapter.wait_for_all_connectors = mock.Mock()

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, [])
            adapter.create_connector.assert_called_once_with("conn-a-demo", ["conn-a-demo", "conn-b-demo"])
            adapter.wait_for_all_connectors.assert_not_called()
            self.assertIsNone(infra.host_entries)

    def test_create_connector_uses_detected_local_image_override_during_initial_deploy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            def fake_run(cmd, **_kwargs):
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            class ConfigAdapterWithoutExplicitImageOverrides(ConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    return {
                        "KC_URL": "http://keycloak-admin.local",
                        "KC_USER": "admin",
                        "KC_PASSWORD": "secret",
                    }

            class RecordingInfra:
                def __init__(self):
                    self.deploy_calls = []

                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                def deploy_helm_release(self, *args, **kwargs):
                    self.deploy_calls.append((args, kwargs))
                    return True

                @staticmethod
                def wait_for_namespace_pods(*_args, **_kwargs):
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "minio"

            infra = RecordingInfra()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithoutExplicitImageOverrides(tmpdir),
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            override_path = os.path.join(tmpdir, "connector-local-overrides.yaml")
            with open(override_path, "w", encoding="utf-8") as handle:
                handle.write("connector:\n  image:\n    name: local/inesdata/inesdata-connector\n    tag: dev\n")

            with (
                mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None),
                mock.patch.object(adapter, "_local_connector_image_override_path", return_value=override_path),
            ):
                created = adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"])

            self.assertTrue(created)
            self.assertEqual(len(infra.deploy_calls), 1)
            args, kwargs = infra.deploy_calls[0]
            self.assertEqual(args[0], "conn-a-demo-demo")
            self.assertEqual(args[1], "demo")
            self.assertEqual(args[2], ["values-conn-a-demo.yaml", override_path])
            self.assertEqual(kwargs["cwd"], config.connector_dir())

    def test_create_connector_uses_explicit_image_override_during_initial_deploy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            def fake_run(cmd, **_kwargs):
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            class ConfigAdapterWithoutExplicitImageOverrides(ConnectorRetryConfigAdapter):
                def load_deployer_config(self):
                    return {
                        "KC_URL": "http://keycloak-admin.local",
                        "KC_USER": "admin",
                        "KC_PASSWORD": "secret",
                    }

            class RecordingInfra:
                def __init__(self):
                    self.deploy_calls = []

                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                def deploy_helm_release(self, *args, **kwargs):
                    self.deploy_calls.append((args, kwargs))
                    return True

                @staticmethod
                def wait_for_namespace_pods(*_args, **_kwargs):
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "minio"

            infra = RecordingInfra()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=ConfigAdapterWithoutExplicitImageOverrides(tmpdir),
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: True
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            override_path = os.path.join(tmpdir, "connector-image-overrides.yaml")
            with open(override_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "connector:\n"
                    "  image:\n"
                    "    name: registry.example/inesdata-connector\n"
                    "    tag: vm-single-fix\n"
                )

            with (
                mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None),
                mock.patch.object(adapter, "_local_connector_image_override_path", return_value=None),
                mock.patch.object(adapter, "_explicit_connector_image_override_path", return_value=override_path),
            ):
                created = adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"])

            self.assertTrue(created)
            self.assertEqual(len(infra.deploy_calls), 1)
            args, kwargs = infra.deploy_calls[0]
            self.assertEqual(args[0], "conn-a-demo-demo")
            self.assertEqual(args[1], "demo")
            self.assertEqual(args[2], ["values-conn-a-demo.yaml", override_path])
            self.assertEqual(kwargs["cwd"], config.connector_dir())

    def test_setup_minio_bucket_fails_when_admin_alias_cannot_be_configured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            creds_path = config.connector_credentials_path("conn-a-demo")
            with open(creds_path, "w", encoding="utf-8") as handle:
                handle.write(
                    '{"minio":{"passwd":"connector-pass","access_key":"access","secret_key":"secret"}}'
                )

            def fake_run(cmd, **_kwargs):
                if "mc alias set minio" in cmd:
                    return None
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=type(
                    "Infra",
                    (),
                    {
                        "get_pod_by_name": staticmethod(lambda *_args, **_kwargs: "minio-pod"),
                    },
                )(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            self.assertFalse(
                adapter.setup_minio_bucket("common-srvs", "demo", "conn-a-demo", creds_path)
            )

    def test_setup_minio_bucket_captures_idempotent_policy_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            creds_path = config.connector_credentials_path("conn-a-demo")
            with open(creds_path, "w", encoding="utf-8") as handle:
                handle.write(
                    '{"minio":{"passwd":"connector-pass","access_key":"access","secret_key":"secret"}}'
                )

            policy_path = config_adapter.connector_minio_policy_path("conn-a-demo", ds_name="demo")
            os.makedirs(os.path.dirname(policy_path), exist_ok=True)
            with open(policy_path, "w", encoding="utf-8") as handle:
                handle.write('{"Version":"2012-10-17","Statement":[]}')

            calls = []
            user_info_calls = 0

            def fake_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                return "" if kwargs.get("capture") else object()

            def fake_run_silent(cmd, **_kwargs):
                nonlocal user_info_calls
                if "mc admin user svcacct list" in cmd:
                    return "access"
                if "mc admin user info" in cmd:
                    user_info_calls += 1
                    if user_info_calls == 1:
                        return ""
                    return "policy-demo-conn-a-demo"
                return ""

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=fake_run_silent,
                auto_mode_getter=lambda: True,
                infrastructure_adapter=type(
                    "Infra",
                    (),
                    {
                        "get_pod_by_name": staticmethod(lambda *_args, **_kwargs: "minio-pod"),
                    },
                )(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            self.assertTrue(
                adapter.setup_minio_bucket("common-srvs", "demo", "conn-a-demo", creds_path)
            )

            policy_calls = [
                kwargs
                for cmd, kwargs in calls
                if "mc admin policy create" in cmd or "mc admin policy attach" in cmd
            ]
            self.assertEqual(len(policy_calls), 2)
            self.assertTrue(all(kwargs.get("capture") for kwargs in policy_calls))
            self.assertTrue(all(kwargs.get("silent") for kwargs in policy_calls))
            self.assertTrue(all(kwargs.get("check") is False for kwargs in policy_calls))

    def test_setup_minio_bucket_reports_already_attached_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            creds_path = config.connector_credentials_path("conn-a-demo")
            with open(creds_path, "w", encoding="utf-8") as handle:
                handle.write(
                    '{"minio":{"passwd":"connector-pass","access_key":"access","secret_key":"secret"}}'
                )

            policy_path = config_adapter.connector_minio_policy_path("conn-a-demo", ds_name="demo")
            os.makedirs(os.path.dirname(policy_path), exist_ok=True)
            with open(policy_path, "w", encoding="utf-8") as handle:
                handle.write('{"Version":"2012-10-17","Statement":[]}')

            calls = []

            def fake_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                return "" if kwargs.get("capture") else object()

            def fake_run_silent(cmd, **_kwargs):
                if "mc admin user svcacct list" in cmd:
                    return "access"
                if "mc admin user info" in cmd:
                    return "policy-demo-conn-a-demo"
                return ""

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=fake_run_silent,
                auto_mode_getter=lambda: True,
                infrastructure_adapter=type(
                    "Infra",
                    (),
                    {
                        "get_pod_by_name": staticmethod(lambda *_args, **_kwargs: "minio-pod"),
                    },
                )(),
                config_adapter=config_adapter,
                config_cls=config,
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                configured = adapter.setup_minio_bucket("common-srvs", "demo", "conn-a-demo", creds_path)

            self.assertTrue(configured)
            self.assertIn(
                "MinIO policy 'policy-demo-conn-a-demo' already attached to 'conn-a-demo'",
                output.getvalue(),
            )
            self.assertFalse(any("mc admin policy attach" in cmd for cmd, _kwargs in calls))

    def test_create_connector_aborts_when_minio_configuration_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()
            os.makedirs(config.venv_path(), exist_ok=True)

            def fake_run(cmd, **_kwargs):
                if "bootstrap.py connector create" in cmd:
                    with open(config.connector_values_file("conn-a-demo"), "w", encoding="utf-8") as handle:
                        handle.write("hostAliases: []\n")
                return object()

            class RecordingInfra:
                def __init__(self):
                    self.deploy_calls = []

                @staticmethod
                def ensure_local_infra_access():
                    return True

                @staticmethod
                def ensure_vault_unsealed():
                    return True

                def deploy_helm_release(self, *args, **kwargs):
                    self.deploy_calls.append((args, kwargs))
                    return True

                @staticmethod
                def wait_for_namespace_pods(*_args, **_kwargs):
                    return True

                @staticmethod
                def manage_hosts_entries(*_args, **_kwargs):
                    return None

                @staticmethod
                def get_pod_by_name(*_args, **_kwargs):
                    return "minio"

            infra = RecordingInfra()
            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infra,
                config_adapter=config_adapter,
                config_cls=config,
            )
            adapter.wait_for_keycloak_admin_ready = lambda *_args, **_kwargs: True
            adapter.setup_minio_bucket = lambda *_args, **_kwargs: False
            adapter.force_clean_postgres_db = lambda *_args, **_kwargs: None
            adapter.update_connector_host_aliases = lambda *_args, **_kwargs: None
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements", lambda *_args, **_kwargs: None):
                created = adapter.create_connector("conn-a-demo", ["conn-a-demo", "conn-b-demo"])

            self.assertFalse(created)
            self.assertEqual(infra.deploy_calls, [])


if __name__ == "__main__":
    unittest.main()
