import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.connectors import INESDataConnectorsAdapter


class ConnectorDeployHostsConfig:
    DS_NAME = "demo"

    def __init__(self, root):
        self.root = root

    def repo_dir(self):
        return self.root

    def python_exec(self):
        return "python3"

    def venv_path(self):
        return os.path.join(self.root, ".venv")

    def repo_requirements_path(self):
        return os.path.join(self.root, "requirements.txt")

    def connector_values_file(self, connector_name):
        return os.path.join(self.root, f"values-{connector_name}.yaml")


class ConnectorDeployHostsConfigAdapter:
    @staticmethod
    def load_deployer_config():
        return {}

    @staticmethod
    def generate_hosts(ds_name):
        return [
            f"127.0.0.1 {ds_name}.example.local",
            f"127.0.0.1 backend-{ds_name}.example.local",
        ]

    @staticmethod
    def generate_connector_hosts(connectors):
        return [f"127.0.0.1 {connector}.example.local" for connector in connectors]


class RecordingInfrastructure:
    def __init__(self):
        self.recorded_hosts = None

    def manage_hosts_entries(self, entries, *args, **kwargs):
        del args, kwargs
        self.recorded_hosts = entries

    def ensure_vault_unsealed(self):
        return True


class ConnectorDeployHostsTests(unittest.TestCase):
    def test_deploy_connectors_adds_dataspace_and_connector_hosts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorDeployHostsConfig(tmpdir)
            os.makedirs(config.repo_dir(), exist_ok=True)
            os.makedirs(config.venv_path(), exist_ok=True)
            open(config.repo_requirements_path(), "w", encoding="utf-8").close()

            infrastructure = RecordingInfrastructure()
            adapter = INESDataConnectorsAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infrastructure,
                config_adapter=ConnectorDeployHostsConfigAdapter(),
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
            adapter.create_connector = lambda *_args, **_kwargs: True
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True
            adapter.wait_for_all_connectors = lambda *_args, **_kwargs: None

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements"):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            self.assertEqual(
                infrastructure.recorded_hosts,
                [
                    "127.0.0.1 demo.example.local",
                    "127.0.0.1 backend-demo.example.local",
                    "127.0.0.1 conn-a-demo.example.local",
                ],
            )


if __name__ == "__main__":
    unittest.main()
