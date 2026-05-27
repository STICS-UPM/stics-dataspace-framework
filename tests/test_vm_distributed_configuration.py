import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import main


class VmDistributedConfigurationTests(unittest.TestCase):
    def test_discovery_commands_include_ubuntu_kubeconfig_checks(self):
        commands = "\n".join(main._vm_distributed_discovery_commands("kubeconfig"))

        self.assertIn("/etc/rancher/k3s/k3s.yaml", commands)
        self.assertIn("kubectl --kubeconfig", commands)

    def test_discovery_help_explains_common_address_context(self):
        output = io.StringIO()

        with redirect_stdout(output):
            main._print_vm_distributed_discovery_help("common-address")

        text = output.getvalue()
        self.assertIn("What this value controls", text)
        self.assertIn("Keycloak", text)
        self.assertIn("How to choose it", text)
        self.assertIn("hostname -I", text)

    def test_connector_defaults_follow_user_inventory(self):
        connectors = "alpha,beta,gamma,delta"

        locations = main._default_vm_distributed_connector_locations(connectors)
        pairs = main._default_vm_distributed_validation_pairs(connectors)

        self.assertEqual(locations, "alpha:provider,beta:consumer,gamma:provider,delta:consumer")
        self.assertEqual(pairs, "alpha>beta")

    def test_preflight_reports_ready_when_required_values_are_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common_kubeconfig = os.path.join(tmpdir, "common.yaml")
            with open(common_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\n")

            preflight = main._vm_distributed_configuration_preflight(
                {
                    "DOMAIN_BASE": "stics.example.local",
                    "DS_DOMAIN_BASE": "ds.stics.example.local",
                },
                {
                    "VM_COMMON_IP": "10.0.0.10",
                    "VM_PROVIDER_IP": "10.0.0.20",
                    "VM_CONSUMER_IP": "10.0.0.30",
                    "K3S_KUBECONFIG_COMMON": common_kubeconfig,
                    "K3S_KUBECONFIG_PROVIDER": common_kubeconfig,
                    "K3S_KUBECONFIG_CONSUMER": common_kubeconfig,
                },
                {
                    "DS_1_NAME": "pionera",
                    "DS_1_CONNECTORS": "citycouncil,company,partnera",
                    "DS_1_CONNECTOR_NAMESPACES": "citycouncil:provider,company:consumer,partnera:provider",
                    "DS_1_VALIDATION_PAIRS": "citycouncil>company",
                    "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "full",
                },
            )

        self.assertEqual(preflight["status"], "ready")
        self.assertEqual(preflight["missing"], [])
        self.assertEqual(preflight["warnings"], [])

    def test_preflight_warns_about_multi_kubeconfig_level4(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common_kubeconfig = os.path.join(tmpdir, "common.yaml")
            provider_kubeconfig = os.path.join(tmpdir, "provider.yaml")
            consumer_kubeconfig = os.path.join(tmpdir, "consumer.yaml")
            for path in (common_kubeconfig, provider_kubeconfig, consumer_kubeconfig):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("apiVersion: v1\n")

            preflight = main._vm_distributed_configuration_preflight(
                {
                    "DOMAIN_BASE": "stics.example.local",
                    "DS_DOMAIN_BASE": "ds.stics.example.local",
                },
                {
                    "VM_COMMON_IP": "10.0.0.10",
                    "VM_PROVIDER_IP": "10.0.0.20",
                    "VM_CONSUMER_IP": "10.0.0.30",
                    "K3S_KUBECONFIG_COMMON": common_kubeconfig,
                    "K3S_KUBECONFIG_PROVIDER": provider_kubeconfig,
                    "K3S_KUBECONFIG_CONSUMER": consumer_kubeconfig,
                },
                {
                    "DS_1_NAME": "pionera",
                    "DS_1_CONNECTORS": "citycouncil,company",
                    "DS_1_CONNECTOR_NAMESPACES": "citycouncil:provider,company:consumer",
                    "DS_1_VALIDATION_PAIRS": "citycouncil>company",
                    "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "full",
                },
            )

        self.assertEqual(preflight["status"], "needs-review")
        self.assertTrue(
            any("multi-kubeconfig connector deployment" in warning for warning in preflight["warnings"])
        )

    def test_wizard_writes_ignored_config_files_with_dynamic_connector_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infra_path = os.path.join(tmpdir, "infrastructure", "deployer.config")
            infra_example_path = os.path.join(tmpdir, "infrastructure", "deployer.config.example")
            topology_path = os.path.join(tmpdir, "infrastructure", "topologies", "vm-distributed.config")
            topology_example_path = os.path.join(
                tmpdir,
                "infrastructure",
                "topologies",
                "vm-distributed.config.example",
            )
            adapter_path = os.path.join(tmpdir, "inesdata", "deployer.config")
            adapter_example_path = os.path.join(tmpdir, "inesdata", "deployer.config.example")
            common_kubeconfig = os.path.join(tmpdir, "common.yaml")

            for path in (infra_example_path, topology_example_path, adapter_example_path, common_kubeconfig):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(common_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\n")
            with open(infra_example_path, "w", encoding="utf-8") as handle:
                handle.write("DOMAIN_BASE=\nDS_DOMAIN_BASE=\n")
            with open(topology_example_path, "w", encoding="utf-8") as handle:
                handle.write("TOPOLOGY_ROUTING_MODE=host\n")
            with open(adapter_example_path, "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pionera\nDS_1_CONNECTORS=citycouncil,company\n")

            inputs = [
                "stics.example.local",
                "ds.stics.example.local",
                "",
                "10.0.0.10",
                "10.0.0.20",
                "10.0.0.30",
                "10.0.0.40",
                "10.0.0.10",
                common_kubeconfig,
                "",
                "",
                "",
                "",
                "alpha,beta,gamma",
                "",
                "",
                "additive",
                "",
            ]

            with mock.patch("builtins.input", side_effect=inputs), mock.patch.object(
                main,
                "_infrastructure_deployer_config_path",
                return_value=infra_path,
            ), mock.patch.object(
                main,
                "_infrastructure_deployer_config_example_path",
                return_value=infra_example_path,
            ), mock.patch.object(
                main,
                "_infrastructure_topology_config_path",
                return_value=topology_path,
            ), mock.patch.object(
                main,
                "_infrastructure_topology_config_example_path",
                return_value=topology_example_path,
            ), mock.patch.object(
                main,
                "_adapter_deployer_config_path",
                return_value=adapter_path,
            ), mock.patch.object(
                main,
                "_adapter_deployer_config_example_path",
                return_value=adapter_example_path,
            ):
                result = main._run_vm_distributed_configuration_wizard(
                    current_adapter="inesdata",
                    adapter_registry={"inesdata": object()},
                )

            self.assertEqual(result["status"], "prepared")
            with open(adapter_path, encoding="utf-8") as handle:
                adapter_config = handle.read()
            with open(topology_path, encoding="utf-8") as handle:
                topology_config = handle.read()

        self.assertIn("DS_1_CONNECTORS=alpha,beta,gamma", adapter_config)
        self.assertIn("DS_1_CONNECTOR_NAMESPACES=alpha:provider,beta:consumer,gamma:provider", adapter_config)
        self.assertIn("DS_1_VALIDATION_PAIRS=alpha>beta", adapter_config)
        self.assertIn("LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive", adapter_config)
        self.assertIn("K3S_KUBECONFIG_COMPONENTS=", topology_config)
        self.assertIn(common_kubeconfig, topology_config)

    def test_preflight_reports_incomplete_required_values(self):
        preflight = main._vm_distributed_configuration_preflight({}, {}, {})

        self.assertEqual(preflight["status"], "incomplete")
        self.assertIn("DOMAIN_BASE", preflight["missing"])
        self.assertIn("DS_DOMAIN_BASE", preflight["missing"])
        self.assertIn("VM_COMMON_IP", preflight["missing"])
        self.assertIn("VM_PROVIDER_IP", preflight["missing"])
        self.assertIn("VM_CONSUMER_IP", preflight["missing"])
        self.assertIn("DS_1_NAME", preflight["missing"])
        self.assertIn("DS_1_CONNECTORS", preflight["missing"])


if __name__ == "__main__":
    unittest.main()
