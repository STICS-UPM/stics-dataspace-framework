import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.connectors import INESDataConnectorsAdapter


class ConnectorReadinessConfig:
    DS_NAME = "demo"

    @staticmethod
    def namespace_demo():
        return "demo"

    @staticmethod
    def ds_domain_base():
        return "dev.ds.dataspaceunit.upm"


class ConnectorReadinessConfigAdapter:
    topology = "local"

    @staticmethod
    def ds_domain_base():
        return "dev.ds.dataspaceunit.upm"

    @staticmethod
    def load_deployer_config():
        return {
            "DS_1_NAME": "demo",
            "DS_1_NAMESPACE": "demo",
            "DS_1_CONNECTORS": "a,b",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
        }

    @staticmethod
    def get_pg_credentials():
        return "localhost", "postgres", "secret"

    @staticmethod
    def get_pg_port():
        return "5432"


class ConnectorManagementReadinessTests(unittest.TestCase):
    @staticmethod
    def _run(*_args, **_kwargs):
        return object()

    @staticmethod
    def _run_silent(*_args, **_kwargs):
        return "conn-a-demo-123 1/1 Running 0 1m\nconn-b-demo-123 1/1 Running 0 1m"

    def _make_adapter(self):
        return INESDataConnectorsAdapter(
            run=self._run,
            run_silent=self._run_silent,
            auto_mode_getter=lambda: True,
            infrastructure_adapter=None,
            config_adapter=ConnectorReadinessConfigAdapter(),
            config_cls=ConnectorReadinessConfig,
        )

    def test_validate_connectors_deployment_requires_management_api(self):
        adapter = self._make_adapter()
        adapter.wait_for_connector_ready = lambda connector: True
        calls = []

        def fake_management_ready(connector):
            calls.append(connector)
            return connector != "conn-b"

        adapter.wait_for_management_api_ready = fake_management_ready

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = adapter.validate_connectors_deployment(["conn-a", "conn-b"])

        self.assertFalse(result)
        self.assertEqual(calls, ["conn-a", "conn-b"])
        self.assertIn("Management API not reachable: conn-b", output.getvalue())

    def test_validate_connectors_deployment_succeeds_when_management_api_is_ready(self):
        adapter = self._make_adapter()
        adapter.wait_for_connector_ready = lambda connector: True
        adapter.wait_for_management_api_ready = lambda connector: True

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = adapter.validate_connectors_deployment(["conn-a", "conn-b"])

        self.assertTrue(result)
        self.assertIn("All connectors reachable", output.getvalue())

    def test_validate_connectors_deployment_can_require_database_credentials(self):
        adapter = self._make_adapter()
        adapter.wait_for_connector_ready = lambda connector: True
        adapter.wait_for_management_api_ready = lambda connector: True
        adapter.connector_database_credentials_valid = lambda connector: connector == "conn-a"

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = adapter.validate_connectors_deployment(
                ["conn-a", "conn-b"],
                check_database_credentials=True,
            )

        self.assertFalse(result)
        self.assertIn("Checking database credential consistency: conn-b", output.getvalue())
        self.assertIn(
            "Connector database credentials do not match the deployed state: conn-b",
            output.getvalue(),
        )

    def test_connector_database_credentials_valid_uses_temporary_postgres_for_vm_single_k3s(self):
        config_adapter = ConnectorReadinessConfigAdapter()
        config_adapter.topology = "vm-single"
        config_adapter.cluster_runtime = lambda: {"cluster_type": "k3s"}
        infrastructure = mock.Mock()
        infrastructure.port_forward_service.return_value = True
        infrastructure.stop_port_forward_service.return_value = True
        commands = []

        def fake_run_silent(cmd, *_args, **_kwargs):
            commands.append(cmd)
            return "1"

        adapter = INESDataConnectorsAdapter(
            run=self._run,
            run_silent=fake_run_silent,
            auto_mode_getter=lambda: True,
            infrastructure_adapter=infrastructure,
            config_adapter=config_adapter,
            config_cls=ConnectorReadinessConfig,
        )
        adapter.load_connector_credentials = lambda _connector: {
            "database": {"name": "conn_org3_pionera", "user": "conn_org3_pionera", "passwd": "secret"}
        }

        with mock.patch.object(adapter, "_reserve_local_port", return_value=15432):
            result = adapter.connector_database_credentials_valid("conn-org3-pionera")

        self.assertTrue(result)
        self.assertEqual(len(commands), 1)
        self.assertIn("psql -h 127.0.0.1 -p 15432", commands[0])
        infrastructure.port_forward_service.assert_called_once_with(
            "common-srvs",
            "common-srvs-postgresql",
            15432,
            5432,
            quiet=True,
        )
        infrastructure.stop_port_forward_service.assert_called_once_with(
            "common-srvs",
            "common-srvs-postgresql",
            quiet=True,
        )

    def test_validate_connectors_deployment_ignores_interface_rollout_pods(self):
        def run_silent_with_interface_rollout(_cmd, cwd=None):
            del cwd
            return (
                "conn-a-demo-111 1/1 Running 0 1m\n"
                "conn-b-demo-222 1/1 Running 0 1m\n"
                "conn-a-demo-interface-aaa 1/1 Terminating 0 10s\n"
                "conn-b-demo-inteface-bbb 1/1 Terminating 0 10s"
            )

        adapter = INESDataConnectorsAdapter(
            run=self._run,
            run_silent=run_silent_with_interface_rollout,
            auto_mode_getter=lambda: True,
            infrastructure_adapter=None,
            config_adapter=ConnectorReadinessConfigAdapter(),
            config_cls=ConnectorReadinessConfig,
        )
        adapter.wait_for_connector_ready = lambda connector: True
        adapter.wait_for_management_api_ready = lambda connector: True

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = adapter.validate_connectors_deployment(["conn-a", "conn-b"])

        self.assertTrue(result)
        self.assertNotIn("Connector pod not running", output.getvalue())


if __name__ == "__main__":
    unittest.main()
