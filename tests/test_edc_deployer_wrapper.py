import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.edc.deployer import EdcDeployer


class FakeConfig:
    NS_COMMON = "common-srvs"


class FakeConfigAdapter:
    def load_deployer_config(self):
        return {
            "ENVIRONMENT": "DEV",
            "DS_1_NAME": "demoedc",
            "DS_1_NAMESPACE": "demoedc",
            "DS_1_CONNECTORS": "citycounciledc,companyedc",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            "COMPONENTS": "ontology-hub,ai-model-hub",
        }

    @staticmethod
    def primary_dataspace_name():
        return "demoedc"

    @staticmethod
    def primary_dataspace_namespace():
        return "demoedc"

    @staticmethod
    def ds_domain_base():
        return "dev.ds.dataspaceunit.upm"

    @staticmethod
    def deployment_environment_name():
        return "DEV"

    @staticmethod
    def edc_dataspace_runtime_dir(ds_name=None):
        return f"/tmp/deployers/edc/deployments/DEV/{ds_name or 'demoedc'}"


class RoleAlignedConfigAdapter(FakeConfigAdapter):
    def load_deployer_config(self):
        config = super().load_deployer_config()
        config["NAMESPACE_PROFILE"] = "role-aligned"
        return config


class FakeConnectors:
    @staticmethod
    def load_dataspace_connectors():
        return [
            {
                "name": "demoedc",
                "namespace": "demoedc",
                "connectors": ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
            }
        ]


class FakeAdapter:
    def __init__(self):
        self.config = FakeConfig
        self.config_adapter = FakeConfigAdapter()
        self.connectors = FakeConnectors()
        self.calls = []

    def deploy_infrastructure(self):
        self.calls.append("deploy_infrastructure")
        return True

    def deploy_dataspace(self):
        self.calls.append("deploy_dataspace")
        return True

    def deploy_connectors(self):
        self.calls.append("deploy_connectors")
        return ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"]

    def get_cluster_connectors(self):
        self.calls.append("get_cluster_connectors")
        return ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"]


class FailedConnectorAdapter(FakeAdapter):
    def deploy_connectors(self):
        self.calls.append("deploy_connectors")
        return []


class EdcDeployerWrapperTests(unittest.TestCase):
    def test_name_and_supported_topologies_are_stable(self):
        deployer = EdcDeployer(adapter=FakeAdapter(), config_cls=FakeConfig, topology="local")

        self.assertEqual(deployer.name(), "edc")
        self.assertEqual(deployer.supported_topologies(), ["local", "vm-single", "vm-distributed"])

    def test_resolve_context_uses_existing_edc_conventions(self):
        deployer = EdcDeployer(adapter=FakeAdapter(), config_cls=FakeConfig, topology="local")

        context = deployer.resolve_context(topology="local")

        self.assertEqual(context.deployer, "edc")
        self.assertEqual(context.topology, "local")
        self.assertEqual(context.environment, "DEV")
        self.assertEqual(context.dataspace_name, "demoedc")
        self.assertEqual(context.ds_domain_base, "dev.ds.dataspaceunit.upm")
        self.assertEqual(
            context.connectors,
            ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
        )
        self.assertEqual(context.components, [])
        self.assertEqual(context.namespace_roles.registration_service_namespace, "demoedc")
        self.assertTrue(context.runtime_dir.endswith("/tmp/deployers/edc/deployments/DEV/demoedc"))

    def test_deploy_methods_delegate_to_existing_adapter(self):
        adapter = FakeAdapter()
        deployer = EdcDeployer(adapter=adapter, config_cls=FakeConfig, topology="local")
        context = deployer.resolve_context(topology="local")

        self.assertTrue(deployer.deploy_infrastructure(context))
        self.assertTrue(deployer.deploy_dataspace(context))
        self.assertEqual(
            deployer.deploy_connectors(context),
            ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
        )
        self.assertEqual(
            adapter.calls,
            ["deploy_infrastructure", "deploy_dataspace", "deploy_connectors"],
        )

    def test_deploy_connectors_raises_when_adapter_reports_no_deployed_connectors(self):
        deployer = EdcDeployer(adapter=FailedConnectorAdapter(), config_cls=FakeConfig, topology="local")
        context = deployer.resolve_context(topology="local")

        with self.assertRaises(RuntimeError) as ctx:
            deployer.deploy_connectors(context)

        self.assertIn("EDC connector deployment finished without deployed connectors", str(ctx.exception))
        self.assertIn("conn-citycounciledc-demoedc", str(ctx.exception))

    def test_deploy_components_is_clean_noop_in_current_phase(self):
        deployer = EdcDeployer(adapter=FakeAdapter(), config_cls=FakeConfig, topology="local")
        context = deployer.resolve_context(topology="local")

        result = deployer.deploy_components(context)

        self.assertEqual(result["deployed"], [])
        self.assertEqual(result["urls"], {})
        self.assertEqual(result["configured"], ["ontology-hub", "ai-model-hub"])
        self.assertEqual(result["deployable"], [])
        self.assertEqual(result["pending_support"], ["ontology-hub", "ai-model-hub"])

    def test_resolve_context_can_plan_role_aligned_namespaces_without_changing_execution_roles(self):
        adapter = FakeAdapter()
        adapter.config_adapter = RoleAlignedConfigAdapter()
        deployer = EdcDeployer(adapter=adapter, config_cls=FakeConfig, topology="local")

        context = deployer.resolve_context(topology="local")

        self.assertEqual(context.namespace_profile, "role-aligned")
        self.assertEqual(context.namespace_roles.registration_service_namespace, "demoedc-core")
        self.assertEqual(context.namespace_roles.provider_namespace, "demoedc")
        self.assertEqual(context.planned_namespace_roles.registration_service_namespace, "demoedc-core")
        self.assertEqual(context.planned_namespace_roles.provider_namespace, "demoedc-provider")
        self.assertEqual(context.planned_namespace_roles.consumer_namespace, "demoedc-consumer")

    def test_validation_profile_matches_current_edc_ui_suite(self):
        deployer = EdcDeployer(adapter=FakeAdapter(), config_cls=FakeConfig, topology="local")
        context = deployer.resolve_context(topology="local")

        profile = deployer.get_validation_profile(context)

        self.assertTrue(profile.newman_enabled)
        self.assertTrue(profile.test_data_cleanup_enabled)
        self.assertTrue(profile.playwright_enabled)
        self.assertEqual(profile.playwright_config, "validation/ui/playwright.edc.config.ts")
        self.assertFalse(profile.component_validation_enabled)
        self.assertEqual(profile.component_groups, [])


if __name__ == "__main__":
    unittest.main()
