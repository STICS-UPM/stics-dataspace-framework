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

    def test_common_service_public_updates_replace_generated_default_hostnames(self):
        updates = main._vm_distributed_common_service_public_updates(
            "pionera.example.test",
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KC_URL": "http://admin.auth.dev.ed.dataspaceunit.upm",
                "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "KEYCLOAK_HOSTNAME": "auth.dev.ed.dataspaceunit.upm",
                "KEYCLOAK_ADMIN_HOSTNAME": "admin.auth.dev.ed.dataspaceunit.upm",
                "MINIO_HOSTNAME": "minio.dev.ed.dataspaceunit.upm",
                "MINIO_CONSOLE_HOSTNAME": "console.minio-s3.dev.ed.dataspaceunit.upm",
            },
        )

        self.assertEqual(updates["KC_URL"], "http://admin.auth.pionera.example.test")
        self.assertEqual(updates["KC_INTERNAL_URL"], "http://auth.pionera.example.test")
        self.assertEqual(updates["KEYCLOAK_HOSTNAME"], "auth.pionera.example.test")
        self.assertEqual(updates["MINIO_HOSTNAME"], "minio.pionera.example.test")

    def test_common_service_public_updates_preserve_custom_hostnames(self):
        updates = main._vm_distributed_common_service_public_updates(
            "pionera.example.test",
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KC_URL": "http://custom-admin.example.test",
                "KC_INTERNAL_URL": "http://custom-auth.example.test",
                "KEYCLOAK_HOSTNAME": "custom-auth.example.test",
                "KEYCLOAK_ADMIN_HOSTNAME": "custom-admin.example.test",
                "MINIO_HOSTNAME": "custom-minio.example.test",
                "MINIO_CONSOLE_HOSTNAME": "custom-console.example.test",
            },
        )

        self.assertEqual(updates, {})

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
                    "DOMAIN_BASE": "validation.example.local",
                    "DS_DOMAIN_BASE": "ds.validation.example.local",
                },
                {
                    "VM_COMMON_IP": "10.0.0.10",
                    "VM_PROVIDER_IP": "10.0.0.20",
                    "VM_CONSUMER_IP": "10.0.0.30",
                    "VM_SSH_USER": "ubuntu",
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
        checks = {item["name"]: item["status"] for item in preflight["checks"]}
        self.assertEqual(checks["Domains"], "ready")
        self.assertEqual(checks["Kubeconfigs"], "ready")
        self.assertEqual(checks["Level 4 cluster scope"], "ready")

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
                    "DOMAIN_BASE": "validation.example.local",
                    "DS_DOMAIN_BASE": "ds.validation.example.local",
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
        checks = {item["name"]: item["status"] for item in preflight["checks"]}
        self.assertEqual(checks["Level 4 cluster scope"], "blocked")

    def test_preflight_reports_incomplete_ssh_metadata_without_running_ssh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common_kubeconfig = os.path.join(tmpdir, "common.yaml")
            with open(common_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\n")

            preflight = main._vm_distributed_configuration_preflight(
                {
                    "DOMAIN_BASE": "validation.example.local",
                    "DS_DOMAIN_BASE": "ds.validation.example.local",
                },
                {
                    "VM_COMMON_IP": "192.0.2.10",
                    "VM_PROVIDER_IP": "192.0.2.20",
                    "VM_CONSUMER_IP": "192.0.2.30",
                    "K3S_KUBECONFIG_COMMON": common_kubeconfig,
                    "K3S_KUBECONFIG_PROVIDER": common_kubeconfig,
                    "K3S_KUBECONFIG_CONSUMER": common_kubeconfig,
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_PORT": "2222",
                    "VM_COMMON_SSH_HOST": "common.example.test",
                    "VM_PROVIDER_SSH_HOST": "provider.example.test",
                    "VM_CONSUMER_SSH_HOST": "consumer.example.test",
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
        self.assertTrue(any("SSH_BASTION_HOST" in warning for warning in preflight["warnings"]))
        checks = {item["name"]: item["status"] for item in preflight["checks"]}
        self.assertEqual(checks["SSH access"], "needs-review")

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
                handle.write(
                    "DOMAIN_BASE=dev.ed.dataspaceunit.upm\n"
                    "DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n"
                    "KC_URL=http://admin.auth.dev.ed.dataspaceunit.upm\n"
                    "KC_INTERNAL_URL=http://auth.dev.ed.dataspaceunit.upm\n"
                    "KEYCLOAK_HOSTNAME=auth.dev.ed.dataspaceunit.upm\n"
                    "KEYCLOAK_ADMIN_HOSTNAME=admin.auth.dev.ed.dataspaceunit.upm\n"
                    "MINIO_HOSTNAME=minio.dev.ed.dataspaceunit.upm\n"
                    "MINIO_CONSOLE_HOSTNAME=console.minio-s3.dev.ed.dataspaceunit.upm\n"
                )
            with open(topology_example_path, "w", encoding="utf-8") as handle:
                handle.write("TOPOLOGY_ROUTING_MODE=host\n")
            with open(adapter_example_path, "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pionera\nDS_1_CONNECTORS=citycouncil,company\n")

            inputs = [
                "validation.example.local",
                "ds.validation.example.local",
                "",
                "10.0.0.10",
                "10.0.0.20",
                "10.0.0.30",
                "10.0.0.40",
                "10.0.0.10",
                "ubuntu",
                "",
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
            with open(infra_path, encoding="utf-8") as handle:
                infra_config = handle.read()

        self.assertIn("KC_URL=http://admin.auth.validation.example.local", infra_config)
        self.assertIn("KC_INTERNAL_URL=http://auth.validation.example.local", infra_config)
        self.assertIn("KEYCLOAK_HOSTNAME=auth.validation.example.local", infra_config)
        self.assertIn("MINIO_HOSTNAME=minio.validation.example.local", infra_config)
        self.assertIn("MINIO_CONSOLE_HOSTNAME=console.minio-s3.validation.example.local", infra_config)
        self.assertIn("DS_1_CONNECTORS=alpha,beta,gamma", adapter_config)
        self.assertIn("DS_1_CONNECTOR_NAMESPACES=alpha:provider,beta:consumer,gamma:provider", adapter_config)
        self.assertIn("DS_1_VALIDATION_PAIRS=alpha>beta", adapter_config)
        self.assertIn("LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive", adapter_config)
        self.assertIn("VM_SSH_USER=ubuntu", topology_config)
        self.assertIn("K3S_KUBECONFIG_COMPONENTS=", topology_config)
        self.assertIn("SSH_ACCESS_MODE=", topology_config)
        self.assertIn("SSH_CONNECT_TIMEOUT_SECONDS=5", topology_config)
        self.assertIn("VM_DISTRIBUTED_DEPLOYMENT_MODE=orchestrator", topology_config)
        self.assertIn("VM_DISTRIBUTED_PREFLIGHT_DRY_RUN=true", topology_config)
        self.assertIn("VM_COMMON_HTTP_URL=http://10.0.0.10", topology_config)
        self.assertIn("VM_PROVIDER_HTTP_URL=http://10.0.0.20", topology_config)
        self.assertIn("VM_CONSUMER_HTTP_URL=http://10.0.0.30", topology_config)
        self.assertIn(common_kubeconfig, topology_config)

    def test_topology_plan_builds_bastion_ssh_commands_and_connector_locations(self):
        plan = main._build_vm_distributed_topology_plan(
            {
                "DOMAIN_BASE": "validation.example.local",
                "DS_DOMAIN_BASE": "ds.validation.example.local",
            },
            {
                "VM_COMMON_IP": "192.0.2.10",
                "VM_PROVIDER_IP": "192.0.2.20",
                "VM_CONSUMER_IP": "192.0.2.30",
                "K3S_KUBECONFIG_COMMON": "/tmp/common.yaml",
                "K3S_KUBECONFIG_PROVIDER": "/tmp/common.yaml",
                "K3S_KUBECONFIG_CONSUMER": "/tmp/common.yaml",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "bastion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "SSH_CONNECT_TIMEOUT_SECONDS": "7",
                "VM_COMMON_SSH_HOST": "common.example.test",
                "VM_COMMON_SSH_USER": "operator",
                "VM_PROVIDER_SSH_HOST": "provider.example.test",
                "VM_CONSUMER_SSH_HOST": "consumer.example.test",
                "VM_REMOTE_WORKDIR": "/srv/validation-environment",
            },
            {
                "DS_1_NAME": "pionera",
                "DS_1_CONNECTORS": "alpha,beta",
                "DS_1_CONNECTOR_NAMESPACES": "alpha:provider,beta:consumer",
                "DS_1_VALIDATION_PAIRS": "alpha>beta",
                "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "full",
            },
        )

        self.assertEqual(plan["ssh"]["mode"], "bastion")
        self.assertEqual(plan["ssh"]["connect_timeout_seconds"], 7)
        common_vm = next(item for item in plan["vms"] if item["role"] == "common-services")
        self.assertTrue(common_vm["ssh"]["configured"])
        self.assertIn("-J jump@bastion.example.test:2222", common_vm["ssh"]["command"])
        self.assertIn("operator@common.example.test", common_vm["ssh"]["command"])
        self.assertEqual(common_vm["remote_workdir"], "/srv/validation-environment")
        self.assertIn(
            {"connector": "conn-alpha-pionera", "location": "provider"},
            plan["connectors"],
        )
        self.assertEqual(
            plan["validation_pairs"],
            [{"source": "conn-alpha-pionera", "target": "conn-beta-pionera"}],
        )

    def test_remote_preflight_uses_injected_runner_and_parses_facts(self):
        commands = []

        def runner(command, timeout):
            commands.append((command, timeout))
            return mock.Mock(
                returncode=0,
                stdout="hostname=common-vm\nuser=operator\nos=Ubuntu 22.04\nhttp_local=200\n",
                stderr="",
            )

        plan = {
            "ssh": {
                "mode": "direct",
                "connect_timeout_seconds": 5,
                "bastion": {},
            },
            "vms": [
                {
                    "role": "common-services",
                    "remote_workdir": "/srv/validation-environment",
                    "ssh": {
                        "configured": True,
                        "host": "common.example.test",
                        "port": "22",
                        "user": "operator",
                    },
                }
            ],
        }

        result = main.run_vm_distributed_remote_preflight(plan, command_runner=runner)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["vms"][0]["facts"]["hostname"], "common-vm")
        self.assertEqual(result["vms"][0]["facts"]["http_local"], "200")
        self.assertEqual(commands[0][1], 25)
        self.assertIn("BatchMode=yes", commands[0][0])
        self.assertIn("operator@common.example.test", commands[0][0])
        self.assertEqual(commands[0][0][-1].split(" ", 2)[:2], ["sh", "-lc"])
        self.assertNotIn("hostname_value", result["vms"][0]["command"])

    def test_http_preflight_marks_http_responses_below_500_as_reachable(self):
        seen = []

        def getter(url, timeout, allow_redirects):
            seen.append((url, timeout, allow_redirects))
            return mock.Mock(status_code=404)

        result = main.run_vm_distributed_http_preflight(
            {"vms": [{"role": "common-services", "http_url": "http://192.0.2.10"}]},
            request_get=getter,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["vms"][0]["status_code"], 404)
        self.assertEqual(seen, [("http://192.0.2.10", 3, False)])

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
        checks = {item["name"]: item["status"] for item in preflight["checks"]}
        self.assertEqual(checks["Domains"], "missing")
        self.assertEqual(checks["VM addresses"], "missing")
        self.assertEqual(checks["Hosts plan"], "missing")

    def test_preflight_prints_readiness_checklist(self):
        preflight = {
            "status": "needs-review",
            "missing": [],
            "warnings": ["multi-kubeconfig connector deployment is blocked safely."],
            "checks": [
                {
                    "name": "Level 4 cluster scope",
                    "status": "blocked",
                    "detail": "single logical kubeconfig supported",
                }
            ],
        }
        output = io.StringIO()

        with redirect_stdout(output):
            main._print_vm_distributed_preflight(preflight)

        text = output.getvalue()
        self.assertIn("Checklist:", text)
        self.assertIn("[blocked] Level 4 cluster scope", text)


if __name__ == "__main__":
    unittest.main()
