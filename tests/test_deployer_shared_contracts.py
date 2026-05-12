import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.contracts import DeploymentContext, NamespaceRoles, TopologyProfile, ValidationProfile


class SharedContractsTests(unittest.TestCase):
    def test_namespace_roles_from_mapping_applies_defaults(self):
        roles = NamespaceRoles.from_mapping(
            {
                "registration_service_namespace": "demoedc",
                "provider_namespace": "provider",
                "consumer_namespace": "consumer",
            }
        )

        self.assertEqual(roles.common_services_namespace, "common-srvs")
        self.assertEqual(roles.components_namespace, "components")
        self.assertEqual(roles.registration_service_namespace, "demoedc")
        self.assertEqual(roles.provider_namespace, "provider")
        self.assertEqual(roles.consumer_namespace, "consumer")

    def test_validation_profile_from_mapping_preserves_component_groups(self):
        profile = ValidationProfile.from_mapping(
            {
                "adapter": "edc",
                "test_data_cleanup_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.edc.config.ts",
                "component_groups": ["ontology-hub"],
            }
        )

        self.assertEqual(profile.adapter, "edc")
        self.assertTrue(profile.newman_enabled)
        self.assertTrue(profile.test_data_cleanup_enabled)
        self.assertTrue(profile.playwright_enabled)
        self.assertEqual(profile.playwright_config, "validation/ui/playwright.edc.config.ts")
        self.assertEqual(profile.component_groups, ["ontology-hub"])

    def test_deployment_context_from_mapping_wraps_namespace_roles(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "edc",
                "topology": "local",
                "environment": "DEV",
                "dataspace_name": "demoedc",
                "ds_domain_base": "dev.ds.dataspaceunit.upm",
                "connectors": ["conn-a", "conn-b"],
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

        self.assertEqual(context.deployer, "edc")
        self.assertEqual(context.dataspace_name, "demoedc")
        self.assertEqual(context.connectors, ["conn-a", "conn-b"])
        self.assertEqual(context.components, ["ontology-hub"])
        self.assertIsInstance(context.namespace_roles, NamespaceRoles)
        self.assertEqual(context.namespace_roles.registration_service_namespace, "demoedc")
        self.assertEqual(context.namespace_profile, "compact")
        self.assertEqual(context.planned_namespace_roles.registration_service_namespace, "demoedc")
        self.assertEqual(context.config["DS_1_NAME"], "demoedc")

    def test_deployment_context_from_mapping_wraps_planned_namespace_roles(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "edc",
                "topology": "local",
                "environment": "DEV",
                "dataspace_name": "demoedc",
                "ds_domain_base": "dev.ds.dataspaceunit.upm",
                "namespace_profile": "role-aligned",
                "namespace_roles": {
                    "registration_service_namespace": "demoedc",
                    "provider_namespace": "demoedc",
                    "consumer_namespace": "demoedc",
                },
                "planned_namespace_roles": {
                    "registration_service_namespace": "demoedc-core",
                    "provider_namespace": "demoedc-provider",
                    "consumer_namespace": "demoedc-consumer",
                },
            }
        )

        self.assertEqual(context.namespace_profile, "role-aligned")
        self.assertEqual(context.namespace_roles.registration_service_namespace, "demoedc")
        self.assertEqual(context.planned_namespace_roles.registration_service_namespace, "demoedc-core")
        self.assertEqual(context.planned_namespace_roles.provider_namespace, "demoedc-provider")

    def test_deployment_context_from_mapping_wraps_topology_profile(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "edc",
                "topology": "vm-single",
                "environment": "DEV",
                "dataspace_name": "demoedc",
                "ds_domain_base": "dev.ds.dataspaceunit.upm",
                "topology_profile": {
                    "name": "vm-single",
                    "default_address": "192.0.2.10",
                    "role_addresses": {"components": "192.0.2.20"},
                    "ingress_external_ip": "192.0.2.10",
                    "routing_mode": "host",
                },
            }
        )

        self.assertIsInstance(context.topology_profile, TopologyProfile)
        self.assertEqual(context.topology_profile.name, "vm-single")
        self.assertEqual(context.topology_profile.address_for("common"), "192.0.2.10")
        self.assertEqual(context.topology_profile.address_for("components"), "192.0.2.20")


if __name__ == "__main__":
    unittest.main()
