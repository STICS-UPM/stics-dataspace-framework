import unittest
from unittest import mock

from deployers.inesdata.deployer import InesdataDeployer


class InesdataLevel5ComponentsTests(unittest.TestCase):
    def test_deployer_deploy_components_uses_configured_components_without_prompt(self):
        components_adapter = _FakeComponentsAdapter()
        deployer = InesdataDeployer(
            adapter=_FakeAdapter(),
            components_adapter=components_adapter,
            config_cls=_FakeConfig,
        )
        context = deployer.resolve_context()

        with mock.patch("builtins.input") as mock_input:
            result = deployer.deploy_components(context)

        self.assertEqual(result["deployed"], ["ontology-hub"])
        self.assertEqual(
            result["urls"]["ontology-hub"],
            "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
        )
        self.assertEqual(
            components_adapter.calls,
            [
                {
                    "components": ["ontology-hub"],
                    "kwargs": {
                        "ds_name": "demo",
                        "namespace": "components",
                        "deployer_config": context.config,
                    },
                }
            ],
        )
        mock_input.assert_not_called()


class _FakeConfig:
    REPO_DIR = "deployers/inesdata"
    NS_COMMON = "common-srvs"

    @staticmethod
    def repo_dir():
        return "/tmp/deployers/inesdata"


class _FakeConfigAdapter:
    def load_deployer_config(self):
        return {
            "ENVIRONMENT": "DEV",
            "DS_1_NAME": "demo",
            "DS_1_NAMESPACE": "demo",
            "DS_1_CONNECTORS": "citycouncil,company",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            "COMPONENTS": "ontology-hub",
        }

    def primary_dataspace_name(self):
        return "demo"

    def primary_dataspace_namespace(self):
        return "demo"

    def ds_domain_base(self):
        return "dev.ds.dataspaceunit.upm"


class _FakeConnectors:
    def load_dataspace_connectors(self):
        return [
            {
                "name": "demo",
                "namespace": "demo",
                "connectors": ["conn-citycouncil-demo", "conn-company-demo"],
            }
        ]


class _FakeAdapter:
    def __init__(self):
        self.config_adapter = _FakeConfigAdapter()
        self.connectors = _FakeConnectors()
        self.run = mock.Mock()
        self.run_silent = mock.Mock()
        self.infrastructure = mock.Mock()

    def get_cluster_connectors(self):
        return ["conn-citycouncil-demo", "conn-company-demo"]


class _FakeComponentsAdapter:
    def __init__(self):
        self.calls = []

    def deploy_components(self, components, **kwargs):
        self.calls.append(
            {
                "components": list(components),
                "kwargs": dict(kwargs),
            }
        )
        return {
            "deployed": list(components),
            "urls": {
                "ontology-hub": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
            },
        }


if __name__ == "__main__":
    unittest.main()
