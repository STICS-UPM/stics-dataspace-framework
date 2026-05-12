import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.topology import (
    ROLE_COMMON,
    ROLE_COMPONENTS,
    ROLE_CONNECTORS,
    ROLE_REGISTRATION_SERVICE,
    build_topology_profile,
)


class SharedTopologyTests(unittest.TestCase):
    def test_local_topology_defaults_to_loopback(self):
        profile = build_topology_profile("local", {})

        self.assertEqual(profile.name, "local")
        self.assertEqual(profile.default_address, "127.0.0.1")
        self.assertEqual(profile.address_for(ROLE_COMMON), "127.0.0.1")

    def test_local_topology_uses_local_specific_addresses_when_configured(self):
        profile = build_topology_profile(
            "local",
            {
                "LOCAL_HOSTS_ADDRESS": "192.168.49.2",
                "LOCAL_INGRESS_EXTERNAL_IP": "192.168.49.2",
            },
        )

        self.assertEqual(profile.default_address, "192.168.49.2")
        self.assertEqual(profile.ingress_external_ip, "192.168.49.2")
        self.assertEqual(profile.address_for(ROLE_COMMON), "192.168.49.2")

    def test_vm_single_requires_an_external_address(self):
        with self.assertRaises(ValueError) as error:
            build_topology_profile("vm-single", {})

        self.assertIn("VM_EXTERNAL_IP", str(error.exception))

    def test_vm_single_uses_one_address_for_all_roles(self):
        profile = build_topology_profile("vm-single", {"VM_EXTERNAL_IP": "192.0.2.10"})

        self.assertEqual(profile.default_address, "192.0.2.10")
        self.assertEqual(profile.ingress_external_ip, "192.0.2.10")
        self.assertEqual(profile.address_for(ROLE_COMMON), "192.0.2.10")
        self.assertEqual(profile.address_for(ROLE_REGISTRATION_SERVICE), "192.0.2.10")
        self.assertEqual(profile.address_for(ROLE_CONNECTORS), "192.0.2.10")
        self.assertEqual(profile.address_for(ROLE_COMPONENTS), "192.0.2.10")

    def test_vm_single_treats_placeholder_address_as_unconfigured(self):
        with self.assertRaises(ValueError) as error:
            build_topology_profile("vm-single", {"VM_EXTERNAL_IP": "X", "INGRESS_EXTERNAL_IP": "X"})

        self.assertIn("VM_EXTERNAL_IP", str(error.exception))

    def test_vm_distributed_supports_role_specific_addresses(self):
        profile = build_topology_profile(
            "vm-distributed",
            {
                "VM_COMMON_IP": "192.0.2.10",
                "VM_DATASPACE_IP": "192.0.2.11",
                "VM_CONNECTORS_IP": "192.0.2.12",
                "VM_COMPONENTS_IP": "192.0.2.13",
            },
        )

        self.assertEqual(profile.address_for(ROLE_COMMON), "192.0.2.10")
        self.assertEqual(profile.address_for(ROLE_REGISTRATION_SERVICE), "192.0.2.11")
        self.assertEqual(profile.address_for(ROLE_CONNECTORS), "192.0.2.12")
        self.assertEqual(profile.address_for(ROLE_COMPONENTS), "192.0.2.13")


if __name__ == "__main__":
    unittest.main()
