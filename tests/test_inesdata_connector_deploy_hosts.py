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

    def script_dir(self):
        return self.root

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


class ConnectorLocalImageConfigAdapter(ConnectorDeployHostsConfigAdapter):
    @staticmethod
    def load_deployer_config():
        return {
            "DS_1_NAME": "pionera",
            "DS_1_NAMESPACE": "pionera",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            "COMPONENTS_NAMESPACE": "components-runtime",
        }

    @staticmethod
    def primary_dataspace_name():
        return "pionera"

    @staticmethod
    def primary_dataspace_namespace():
        return "pionera"


class RecordingInfrastructure:
    def __init__(self):
        self.recorded_hosts = None

    def manage_hosts_entries(self, entries, *args, **kwargs):
        del args, kwargs
        self.recorded_hosts = entries

    def ensure_vault_unsealed(self):
        return True


class ConnectorDeployHostsTests(unittest.TestCase):
    def test_deploy_connectors_adds_connector_hosts(self):
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
            def fake_create_connector(connector_name, *_args, **_kwargs):
                open(config.connector_values_file(connector_name), "w", encoding="utf-8").close()
                return True

            adapter.connector_already_exists = lambda *_args, **_kwargs: True
            adapter.connector_is_healthy = lambda *_args, **_kwargs: True
            adapter.connector_database_credentials_valid = lambda *_args, **_kwargs: True
            adapter.create_connector = fake_create_connector
            adapter._prepare_vault_management_access = lambda *_args, **_kwargs: True
            adapter.wait_for_all_connectors = lambda *_args, **_kwargs: True

            with mock.patch("adapters.inesdata.connectors.ensure_python_requirements"):
                deployed = adapter.deploy_connectors()

            self.assertEqual(deployed, ["conn-a-demo"])
            self.assertEqual(
                infrastructure.recorded_hosts,
                [
                    "127.0.0.1 conn-a-demo.example.local",
                ],
            )

    def test_local_image_build_patches_ontology_validator_temporarily(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorDeployHostsConfig(tmpdir)
            adapter_root = os.path.join(tmpdir, "adapters", "inesdata")
            connector_source = os.path.join(adapter_root, "sources", "inesdata-connector")
            interface_source = os.path.join(adapter_root, "sources", "inesdata-connector-interface")
            script_path = os.path.join(adapter_root, "scripts", "local_build_load_deploy.sh")
            java_path = os.path.join(
                connector_source,
                "extensions",
                "ontology-validator",
                "src",
                "main",
                "java",
                "org",
                "upm",
                "inesdata",
                "validator",
                "services",
                "impl",
                "JenaValidationService.java",
            )
            original_java = (
                "class JenaValidationService {\n"
                "    String transform(String url) {\n"
                "        return url.replace(\"{ONTOLOGY_HUB_BASE_URL}\", "
                "\"{ONTOLOGY_HUB_INTERNAL_URL}\");\n"
                "    }\n"
                "}\n"
            )
            os.makedirs(os.path.dirname(java_path), exist_ok=True)
            os.makedirs(interface_source, exist_ok=True)
            os.makedirs(os.path.dirname(script_path), exist_ok=True)
            with open(java_path, "w", encoding="utf-8") as handle:
                handle.write(original_java)
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\nexit 0\n")

            observed = {}

            def fake_run(*_args, **_kwargs):
                with open(java_path, encoding="utf-8") as handle:
                    observed["java_during_build"] = handle.read()
                return object()

            adapter = INESDataConnectorsAdapter(
                run=fake_run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=RecordingInfrastructure(),
                config_adapter=ConnectorLocalImageConfigAdapter(),
                config_cls=config,
            )

            self.assertTrue(adapter._maybe_prepare_level4_local_connector_images("pionera"))
            self.assertIn(
                'url.replace("http://ontology-hub-pionera.dev.ds.dataspaceunit.upm", '
                '"http://pionera-ontology-hub.components-runtime:3333")',
                observed["java_during_build"],
            )
            with open(java_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original_java)


if __name__ == "__main__":
    unittest.main()
