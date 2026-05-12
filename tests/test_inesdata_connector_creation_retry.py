import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock
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


class RoleAlignedConnectorRetryConfigAdapter(ConnectorRetryConfigAdapter):
    def load_deployer_config(self):
        config = super().load_deployer_config()
        config["NAMESPACE_PROFILE"] = "role-aligned"
        config["LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES"] = "true"
        return config


class ConnectorCreationRetryTests(unittest.TestCase):
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

    def test_update_connector_host_aliases_skips_vm_distributed_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorRetryConfig(tmpdir)
            config_adapter = ConnectorRetryConfigAdapter(tmpdir)
            config_adapter.topology = "vm-distributed"
            values_path = config.connector_values_file("conn-a-pilot")
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
                ["conn-a-pilot", "conn-b-pilot"],
                connector_name="conn-a-pilot",
            )

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(rendered["hostAliases"], [])
        run.assert_not_called()

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

    def test_local_connector_image_override_path_is_used_for_vm_single(self):
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
                mock.patch("adapters.inesdata.connectors.os.path.isfile", return_value=True),
                mock.patch("adapters.inesdata.connectors.os.path.getsize", return_value=1),
            ):
                self.assertIsNotNone(adapter._local_connector_image_override_path())

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

            policy_dir = os.path.join(tmpdir, "deployments", "DEV", "demo")
            os.makedirs(policy_dir, exist_ok=True)
            with open(os.path.join(policy_dir, "policy-demo-conn-a-demo.json"), "w", encoding="utf-8") as handle:
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

            policy_dir = os.path.join(tmpdir, "deployments", "DEV", "demo")
            os.makedirs(policy_dir, exist_ok=True)
            with open(os.path.join(policy_dir, "policy-demo-conn-a-demo.json"), "w", encoding="utf-8") as handle:
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
