import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.contracts import DeploymentContext
from deployers.shared.lib.orchestrator import DeployerOrchestrator


class FakeDeployer:
    def __init__(self):
        self.calls = []

    def name(self):
        return "edc"

    def supported_topologies(self):
        return ["local"]

    def load_config(self):
        self.calls.append("load_config")
        return {"DS_1_NAME": "demoedc"}

    def resolve_context(self, topology="local"):
        self.calls.append(("resolve_context", topology))
        return DeploymentContext.from_mapping(
            {
                "deployer": "edc",
                "topology": topology,
                "environment": "DEV",
                "dataspace_name": "demoedc",
                "ds_domain_base": "dev.ds.dataspaceunit.upm",
                "connectors": ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
                "components": ["ontology-hub"],
                "namespace_roles": {
                    "registration_service_namespace": "demoedc",
                    "provider_namespace": "demoedc",
                    "consumer_namespace": "demoedc",
                },
                "runtime_dir": "/tmp/demoedc",
                "config": {"DS_1_NAME": "demoedc"},
            }
        )

    def deploy_infrastructure(self, context):
        self.calls.append(("deploy_infrastructure", context.dataspace_name))
        return {"status": "ok"}

    def deploy_dataspace(self, context):
        self.calls.append(("deploy_dataspace", context.dataspace_name))
        return {"status": "ok"}

    def deploy_connectors(self, context):
        self.calls.append(("deploy_connectors", context.dataspace_name))
        return list(context.connectors)

    def deploy_components(self, context):
        self.calls.append(("deploy_components", context.dataspace_name))
        return {"deployed": list(context.components)}

    def get_cluster_connectors(self, context=None):
        self.calls.append(("get_cluster_connectors", context.dataspace_name if context else None))
        return ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"]

    def get_validation_profile(self, context):
        self.calls.append(("get_validation_profile", context.dataspace_name))
        return {
            "adapter": "edc",
            "newman_enabled": True,
            "playwright_enabled": True,
            "playwright_config": "validation/ui/playwright.edc.config.ts",
        }


class SharedOrchestratorTests(unittest.TestCase):
    def test_deploy_executes_all_deployment_blocks(self):
        deployer = FakeDeployer()
        orchestrator = DeployerOrchestrator(deployer)

        result = orchestrator.deploy(topology="local")

        self.assertEqual(result["context"].dataspace_name, "demoedc")
        self.assertEqual(result["infrastructure"], {"status": "ok"})
        self.assertEqual(result["dataspace"], {"status": "ok"})
        self.assertEqual(
            result["connectors"],
            ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
        )
        self.assertEqual(result["components"], {"deployed": ["ontology-hub"]})

    def test_validate_uses_profile_and_connectors(self):
        captured = {}

        def fake_validator(*, deployer, context, profile, connectors):
            captured["deployer"] = deployer.name()
            captured["context"] = context.dataspace_name
            captured["profile"] = profile.playwright_config
            captured["connectors"] = list(connectors)
            return {"status": "validated"}

        orchestrator = DeployerOrchestrator(FakeDeployer(), validation_executor=fake_validator)
        result = orchestrator.validate(topology="local")

        self.assertEqual(result["profile"].adapter, "edc")
        self.assertEqual(result["validation"], {"status": "validated"})
        self.assertEqual(captured["deployer"], "edc")
        self.assertEqual(captured["context"], "demoedc")
        self.assertEqual(captured["profile"], "validation/ui/playwright.edc.config.ts")
        self.assertEqual(
            captured["connectors"],
            ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
        )

    def test_unsupported_topology_raises_clear_error(self):
        orchestrator = DeployerOrchestrator(FakeDeployer())

        with self.assertRaises(ValueError) as error:
            orchestrator.resolve_context(topology="vm-single")

        self.assertIn("Unsupported topology 'vm-single'", str(error.exception))


if __name__ == "__main__":
    unittest.main()
