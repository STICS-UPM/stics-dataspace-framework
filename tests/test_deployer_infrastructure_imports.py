import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.infrastructure.lib.config_loader import iter_dataspace_slots
from deployers.infrastructure.lib.contracts import DeploymentContext, NamespaceRoles
from deployers.infrastructure.lib.hosts_manager import HostEntry, render_managed_block
from deployers.infrastructure.lib.orchestrator import DeployerOrchestrator
from deployers.shared.lib.contracts import DeploymentContext as SharedDeploymentContext


class DeployerInfrastructureImportTests(unittest.TestCase):
    def test_infrastructure_contracts_are_compatible_with_shared_imports(self):
        self.assertIs(DeploymentContext, SharedDeploymentContext)

    def test_infrastructure_helpers_are_importable_from_stable_path(self):
        slots = iter_dataspace_slots({"DS_1_NAME": "demoedc"})
        block = render_managed_block("dataspace demoedc", [HostEntry("127.0.0.1", "example.local")])
        context = DeploymentContext(
            deployer="edc",
            topology="local",
            environment="DEV",
            dataspace_name="demoedc",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            namespace_roles=NamespaceRoles(registration_service_namespace="demoedc"),
        )

        self.assertEqual(slots, [{"slot": "1", "NAME": "demoedc"}])
        self.assertIn("example.local", block)
        self.assertEqual(context.deployer, "edc")
        self.assertTrue(callable(DeployerOrchestrator))


if __name__ == "__main__":
    unittest.main()
