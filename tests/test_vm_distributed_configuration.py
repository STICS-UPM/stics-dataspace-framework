import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import main


class VmDistributedConfigurationTests(unittest.TestCase):
    def _running_ssh_process_result(self, pid=1234):
        process = mock.Mock()
        process.pid = pid
        process.poll.return_value = None
        process.terminate.return_value = None
        process.wait.return_value = None
        return mock.Mock(returncode=None, stdout="", stderr="", process=process)

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

    def test_preflight_accepts_multi_kubeconfig_level4(self):
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
                    "VM_SSH_USER": "ubuntu",
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

        self.assertEqual(preflight["status"], "ready")
        self.assertEqual(preflight["warnings"], [])
        checks = {item["name"]: item["status"] for item in preflight["checks"]}
        self.assertEqual(checks["Level 4 cluster scope"], "ready")
        details = {item["name"]: item["detail"] for item in preflight["checks"]}
        self.assertEqual(details["Level 4 cluster scope"], "multi-kubeconfig connector deployment enabled")

    def test_level4_preflight_starts_missing_loopback_k3s_tunnel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider_kubeconfig = os.path.join(tmpdir, "provider.yaml")
            with open(provider_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\nclusters:\n- cluster:\n    server: https://127.0.0.1:26443\n")

            config = {
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_USER": "jump",
                "SSH_BASTION_PORT": "2222",
                "SSH_IDENTITY_FILE": os.path.join(tmpdir, "id_ed25519_vm"),
            }
            tunnel_calls = []
            kubectl_calls = []

            def fake_start_tunnel(command, **_kwargs):
                tunnel_calls.append(command)
                return self._running_ssh_process_result()

            def fake_run(command, **_kwargs):
                kubectl_calls.append(command)
                return mock.Mock(returncode=0, stdout='{"gitVersion":"v1"}', stderr="")

            with mock.patch.object(
                main,
                "_load_effective_infrastructure_deployer_config",
                return_value=config,
            ), mock.patch.object(
                main,
                "_configured_vm_distributed_role_kubeconfigs",
                return_value={"provider": provider_kubeconfig},
            ), mock.patch.object(
                main,
                "_local_tcp_port_open",
                side_effect=[False, True],
            ), mock.patch.object(
                main,
                "_run_vm_distributed_background_ssh_command",
                side_effect=fake_start_tunnel,
            ), mock.patch.object(main.subprocess, "run", side_effect=fake_run):
                result = main._ensure_vm_distributed_level4_kubeconfig_supported()

            self.assertEqual(result["tunnels"][0]["status"], "started")
            tunnel_command = tunnel_calls[0]
            self.assertNotIn("-f", tunnel_command)
            self.assertIn("-L", tunnel_command)
            self.assertIn("127.0.0.1:26443:127.0.0.1:6443", tunnel_command)
            proxy_option = next(item for item in tunnel_command if str(item).startswith("ProxyCommand="))
            self.assertIn("-o IdentitiesOnly=yes", proxy_option)
            self.assertIn("-p 2222", proxy_option)
            self.assertIn(f"-i {os.path.join(tmpdir, 'id_ed25519_vm')}", proxy_option)
            self.assertIn("-W %h:%p jump@orion.example.test", proxy_option)
            self.assertEqual(kubectl_calls[0][:3], ["kubectl", "--kubeconfig", provider_kubeconfig])

    def test_level4_preflight_starts_background_ssh_tunnel_with_popen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider_kubeconfig = os.path.join(tmpdir, "provider.yaml")
            with open(provider_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\nclusters:\n- cluster:\n    server: https://127.0.0.1:26443\n")

            config = {
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
                "VM_DISTRIBUTED_K3S_TUNNEL_MODE": "auto",
            }

            with mock.patch.object(
                main,
                "_load_effective_infrastructure_deployer_config",
                return_value=config,
            ), mock.patch.object(
                main,
                "_configured_vm_distributed_role_kubeconfigs",
                return_value={"provider": provider_kubeconfig},
            ), mock.patch.object(
                main,
                "_local_tcp_port_open",
                side_effect=[False, True],
            ), mock.patch.object(
                main.subprocess,
                "Popen",
                return_value=self._running_ssh_process_result().process,
            ) as popen, mock.patch.object(
                main.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout='{"gitVersion":"v1"}', stderr=""),
            ) as run, mock.patch.object(main.time, "sleep"):
                main._ensure_vm_distributed_level4_kubeconfig_supported()

            tunnel_kwargs = popen.call_args.kwargs
            self.assertNotIn("capture_output", tunnel_kwargs)
            self.assertIs(tunnel_kwargs["stdin"], main.subprocess.DEVNULL)
            self.assertTrue(tunnel_kwargs["start_new_session"])
            self.assertTrue(hasattr(tunnel_kwargs["stdout"], "write"))
            self.assertTrue(hasattr(tunnel_kwargs["stderr"], "write"))
            self.assertEqual(run.call_args.args[0][:3], ["kubectl", "--kubeconfig", provider_kubeconfig])

    def test_level4_preflight_fails_before_kubectl_when_required_tunnel_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider_kubeconfig = os.path.join(tmpdir, "provider.yaml")
            with open(provider_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\nclusters:\n- cluster:\n    server: https://127.0.0.1:26443\n")

            config = {
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
                "VM_DISTRIBUTED_K3S_TUNNEL_MODE": "auto",
            }

            with mock.patch.object(
                main,
                "_load_effective_infrastructure_deployer_config",
                return_value=config,
            ), mock.patch.object(
                main,
                "_configured_vm_distributed_role_kubeconfigs",
                return_value={"provider": provider_kubeconfig},
            ), mock.patch.object(
                main,
                "_local_tcp_port_open",
                return_value=False,
            ), mock.patch.object(
                main,
                "_run_vm_distributed_background_ssh_command",
                return_value=mock.Mock(returncode=255, stdout="", stderr="Permission denied", process=None),
            ), mock.patch.object(
                main.subprocess,
                "run",
            ) as run:
                with self.assertRaisesRegex(RuntimeError, "Kubernetes API tunnels are not available"):
                    main._ensure_vm_distributed_level4_kubeconfig_supported()

            self.assertEqual(run.call_count, 0)

    def test_level4_preflight_reports_tunnel_timeout_without_leaking_subprocess_exception(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider_kubeconfig = os.path.join(tmpdir, "provider.yaml")
            with open(provider_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\nclusters:\n- cluster:\n    server: https://127.0.0.1:26443\n")

            config = {
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_USER": "jump",
                "SSH_IDENTITY_FILE": os.path.join(tmpdir, "id_ed25519_vm"),
            }

            with mock.patch.object(
                main,
                "_load_effective_infrastructure_deployer_config",
                return_value=config,
            ), mock.patch.object(
                main,
                "_configured_vm_distributed_role_kubeconfigs",
                return_value={"provider": provider_kubeconfig},
            ), mock.patch.object(
                main,
                "_local_tcp_port_open",
                return_value=False,
            ), mock.patch.object(
                main,
                "_run_vm_distributed_background_ssh_command",
                return_value=self._running_ssh_process_result(),
            ), mock.patch.object(main.time, "time", side_effect=[0, 21]):
                with self.assertRaisesRegex(RuntimeError, "ssh-tunnel-timeout") as raised:
                    main._ensure_vm_distributed_level4_kubeconfig_supported()

            self.assertNotIn("Command '['ssh'", str(raised.exception))

    def test_level4_preflight_accepts_background_tunnel_when_port_opens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider_kubeconfig = os.path.join(tmpdir, "provider.yaml")
            with open(provider_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\nclusters:\n- cluster:\n    server: https://127.0.0.1:26443\n")

            config = {
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
                "VM_DISTRIBUTED_K3S_TUNNEL_MODE": "auto",
            }

            with mock.patch.object(
                main,
                "_load_effective_infrastructure_deployer_config",
                return_value=config,
            ), mock.patch.object(
                main,
                "_configured_vm_distributed_role_kubeconfigs",
                return_value={"provider": provider_kubeconfig},
            ), mock.patch.object(
                main,
                "_local_tcp_port_open",
                side_effect=[False, True],
            ), mock.patch.object(
                main,
                "_run_vm_distributed_background_ssh_command",
                return_value=self._running_ssh_process_result(),
            ), mock.patch.object(
                main.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout='{"gitVersion":"v1"}', stderr=""),
            ):
                result = main._ensure_vm_distributed_level4_kubeconfig_supported()

            self.assertEqual(result["tunnels"][0]["status"], "started")
            self.assertEqual(result["tunnels"][0]["pid"], 1234)

    def test_level4_preflight_recreates_managed_loopback_tunnel_when_kubectl_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider_kubeconfig = os.path.join(tmpdir, "provider.yaml")
            with open(provider_kubeconfig, "w", encoding="utf-8") as handle:
                handle.write("apiVersion: v1\nclusters:\n- cluster:\n    server: https://127.0.0.1:26443\n")

            config = {
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
                "VM_DISTRIBUTED_K3S_TUNNEL_MODE": "auto",
                "VM_DISTRIBUTED_K3S_TUNNEL_RECREATE": "auto",
            }
            kubectl_results = [
                mock.Mock(returncode=1, stdout="", stderr="stale tunnel"),
                mock.Mock(returncode=0, stdout='{"gitVersion":"v1"}', stderr=""),
            ]

            def fake_run(command, **_kwargs):
                if command and command[0] == "kubectl":
                    return kubectl_results.pop(0)
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(
                main,
                "_load_effective_infrastructure_deployer_config",
                return_value=config,
            ), mock.patch.object(
                main,
                "_configured_vm_distributed_role_kubeconfigs",
                return_value={"provider": provider_kubeconfig},
            ), mock.patch.object(
                main,
                "_local_tcp_port_open",
                side_effect=[True, False, True],
            ), mock.patch.object(
                main,
                "_stop_vm_distributed_local_k3s_tunnel",
                return_value={"status": "stopped", "local_port": 26443, "pids": [1234]},
            ), mock.patch.object(
                main,
                "_run_vm_distributed_background_ssh_command",
                return_value=self._running_ssh_process_result(),
            ), mock.patch.object(main.subprocess, "run", side_effect=fake_run):
                result = main._ensure_vm_distributed_level4_kubeconfig_supported()

            self.assertEqual(result["checks"][0]["status"], "ready")
            self.assertEqual(result["tunnels"][0]["status"], "ready")
            self.assertEqual(result["tunnels"][1]["status"], "started")
            self.assertEqual(result["tunnels"][1]["recreated_from_pids"], [1234])

    def test_local_k3s_tunnel_process_detection_is_limited_to_ssh_forwarding(self):
        ps_output = "\n".join(
            [
                " 100 ssh -f -N -L 127.0.0.1:36443:127.0.0.1:6443 pionera@pionera3",
                " 101 ssh pionera@pionera3 hostname",
                " 102 python something 127.0.0.1:36443:127.0.0.1:6443",
            ]
        )
        with mock.patch.object(
            main.subprocess,
            "run",
            return_value=mock.Mock(returncode=0, stdout=ps_output, stderr=""),
        ):
            processes = main._vm_distributed_local_k3s_tunnel_processes(36443, "6443")

        self.assertEqual(processes, [{"pid": 100, "command": "ssh -f -N -L 127.0.0.1:36443:127.0.0.1:6443 pionera@pionera3"}])

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
        self.assertIn("VM_DISTRIBUTED_EXECUTION_HOST=auto", topology_config)
        self.assertIn("VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH=true", topology_config)
        self.assertIn("VM_DISTRIBUTED_INFER_LOCAL_WORKDIR=true", topology_config)
        self.assertIn("VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE=true", topology_config)
        self.assertIn("VM_DISTRIBUTED_KUBECONFIG_DIR=~/.kube", topology_config)
        self.assertIn("VM_DISTRIBUTED_KUBECONFIG_SYNC=auto", topology_config)
        self.assertIn("VM_DISTRIBUTED_REMOTE_KUBECONFIG=/etc/rancher/k3s/k3s.yaml", topology_config)
        self.assertIn("VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY=auto", topology_config)
        self.assertIn("VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE=manual", topology_config)
        self.assertIn("VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY=accept-new", topology_config)
        self.assertIn("VM_DISTRIBUTED_DEPLOYMENT_MODE=orchestrator", topology_config)
        self.assertIn("VM_DISTRIBUTED_PREFLIGHT_DRY_RUN=true", topology_config)
        self.assertIn("VM_COMMON_K3S_API_LOCAL_PORT=6443", topology_config)
        self.assertIn("VM_PROVIDER_K3S_API_LOCAL_PORT=26443", topology_config)
        self.assertIn("VM_CONSUMER_K3S_API_LOCAL_PORT=36443", topology_config)
        self.assertIn("VM_COMPONENTS_K3S_API_LOCAL_PORT=6443", topology_config)
        self.assertIn("VM_COMMON_HTTP_URL=http://10.0.0.10", topology_config)
        self.assertIn("VM_PROVIDER_HTTP_URL=http://10.0.0.20", topology_config)
        self.assertIn("VM_CONSUMER_HTTP_URL=http://10.0.0.30", topology_config)
        self.assertIn("VM_COMMON_PUBLIC_URL=https://org1.validation.example.local", topology_config)
        self.assertIn("VM_PROVIDER_PUBLIC_URL=https://org2.ds.validation.example.local", topology_config)
        self.assertIn("VM_CONSUMER_PUBLIC_URL=https://org3.ds.validation.example.local", topology_config)
        self.assertIn("KEYCLOAK_FRONTEND_URL=https://org1.validation.example.local/auth", topology_config)
        self.assertIn("MINIO_CONSOLE_PUBLIC_URL=https://org1.validation.example.local/s3-console", topology_config)
        self.assertIn("COMPONENTS_PUBLIC_BASE_URL=https://org1.validation.example.local", topology_config)
        self.assertIn("COMPONENTS_PUBLIC_PATH_REWRITE=true", topology_config)
        self.assertIn(common_kubeconfig, topology_config)

    def test_offer_vm_distributed_configuration_uses_plain_yes_no_prompt(self):
        with mock.patch.object(
            main,
            "_vm_distributed_configuration_needs_attention",
            return_value=True,
        ), mock.patch.object(
            main,
            "_interactive_read",
            return_value="n",
        ) as read_prompt, mock.patch.object(
            main,
            "_run_vm_distributed_configuration_wizard",
        ) as wizard:
            current_adapter, result = main._offer_vm_distributed_configuration(
                current_adapter="inesdata",
                adapter_registry={"inesdata": object()},
            )

        self.assertEqual(current_adapter, "inesdata")
        self.assertIsNone(result)
        wizard.assert_not_called()
        read_prompt.assert_called_once_with("Configure vm-distributed now? (Y/n): ")

    def test_offer_vm_distributed_configuration_waits_for_adapter_selection(self):
        with mock.patch.object(
            main,
            "_vm_distributed_configuration_needs_attention",
        ) as needs_attention, mock.patch.object(
            main,
            "_interactive_read",
        ) as read_prompt, mock.patch.object(
            main,
            "_run_vm_distributed_configuration_wizard",
        ) as wizard:
            current_adapter, result = main._offer_vm_distributed_configuration(
                current_adapter=None,
                adapter_registry={"inesdata": object(), "edc": object()},
            )

        self.assertIsNone(current_adapter)
        self.assertIsNone(result)
        needs_attention.assert_not_called()
        read_prompt.assert_not_called()
        wizard.assert_not_called()

    def test_wizard_intro_does_not_advertise_back_option(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infra_path = os.path.join(tmpdir, "infrastructure", "deployer.config")
            topology_path = os.path.join(tmpdir, "infrastructure", "topologies", "vm-distributed.config")
            adapter_path = os.path.join(tmpdir, "inesdata", "deployer.config")
            for path in (infra_path, topology_path, adapter_path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("")

            output = io.StringIO()
            with mock.patch("builtins.input", side_effect=KeyboardInterrupt), mock.patch.object(
                main,
                "_infrastructure_deployer_config_path",
                return_value=infra_path,
            ), mock.patch.object(
                main,
                "_infrastructure_topology_config_path",
                return_value=topology_path,
            ), mock.patch.object(
                main,
                "_adapter_deployer_config_path",
                return_value=adapter_path,
            ), redirect_stdout(output):
                with self.assertRaises(KeyboardInterrupt):
                    main._run_vm_distributed_configuration_wizard(
                        current_adapter="inesdata",
                        adapter_registry={"inesdata": object()},
                    )

        rendered = output.getvalue()
        self.assertNotIn("Type b in any field to go back without saving.", rendered)
        self.assertNotIn("b=back", rendered)

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

    def test_topology_plan_includes_idempotent_ssh_bootstrap_and_common_execution_host(self):
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
                "SSH_ACCESS_MODE": "direct",
                "SSH_IDENTITY_FILE": "/home/operator/.ssh/validation-env-vm",
                "VM_DISTRIBUTED_EXECUTION_HOST": "common-services",
                "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE": "plan",
                "VM_COMMON_REMOTE_WORKDIR": "/srv/validation-environment",
                "VM_COMMON_SSH_HOST": "common.example.test",
                "VM_COMMON_SSH_USER": "operator",
                "VM_PROVIDER_SSH_HOST": "provider.example.test",
                "VM_PROVIDER_SSH_USER": "operator",
                "VM_CONSUMER_SSH_HOST": "consumer.example.test",
                "VM_CONSUMER_SSH_USER": "operator",
            },
            {
                "DS_1_NAME": "pionera",
                "DS_1_CONNECTORS": "alpha,beta",
                "DS_1_CONNECTOR_NAMESPACES": "alpha:provider,beta:consumer",
                "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "full",
            },
        )

        self.assertEqual(plan["execution_host"], "common-services")
        self.assertEqual(plan["ssh"]["identity_file"], "/home/operator/.ssh/validation-env-vm")
        provider_vm = next(item for item in plan["vms"] if item["role"] == "provider-connectors")
        self.assertIn("-i /home/operator/.ssh/validation-env-vm", provider_vm["ssh"]["command"])
        self.assertEqual(plan["ssh_bootstrap"]["status"], "ready")
        self.assertEqual(plan["ssh_bootstrap"]["mode"], "plan")
        self.assertIn(
            "prepare_common_services_execution_host",
            [item["name"] for item in plan["ssh_bootstrap"]["actions"]],
        )

    def test_auto_execution_from_common_vm_uses_direct_ssh_and_local_workdir(self):
        with mock.patch.object(main, "_local_host_addresses", return_value={"10.0.0.10"}):
            plan = main._build_vm_distributed_topology_plan(
                {
                    "DOMAIN_BASE": "validation.example.local",
                    "DS_DOMAIN_BASE": "ds.validation.example.local",
                },
                {
                    "VM_COMMON_IP": "10.0.0.10",
                    "VM_PROVIDER_IP": "10.0.0.20",
                    "VM_CONSUMER_IP": "10.0.0.30",
                    "K3S_KUBECONFIG_COMMON": "/tmp/common.yaml",
                    "K3S_KUBECONFIG_PROVIDER": "/tmp/provider.yaml",
                    "K3S_KUBECONFIG_CONSUMER": "/tmp/consumer.yaml",
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_HOST": "bastion.example.test",
                    "SSH_BASTION_USER": "jump",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "auto",
                    "VM_PROVIDER_SSH_HOST": "provider-name",
                    "VM_CONSUMER_SSH_HOST": "consumer-name",
                    "VM_SSH_USER": "operator",
                },
                {
                    "DS_1_NAME": "pionera",
                    "DS_1_CONNECTORS": "alpha,beta",
                    "DS_1_CONNECTOR_NAMESPACES": "alpha:provider,beta:consumer",
                    "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "full",
                },
            )

        self.assertEqual(plan["execution_host"], "common-services")
        self.assertEqual(plan["ssh"]["mode"], "direct")
        common_vm = next(item for item in plan["vms"] if item["role_key"] == "common")
        provider_vm = next(item for item in plan["vms"] if item["role_key"] == "provider")
        self.assertEqual(common_vm["remote_workdir"], main._framework_root_dir())
        self.assertEqual(provider_vm["ssh"]["host"], "10.0.0.20")
        self.assertNotIn("ProxyCommand", provider_vm["ssh"]["command"])
        self.assertNotIn("-J", provider_vm["ssh"]["command"])

    def test_common_vm_preflight_localizes_role_kubeconfigs_from_configured_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kube_dir = os.path.join(tmpdir, ".kube")
            os.makedirs(kube_dir, exist_ok=True)
            common_kubeconfig = os.path.join(kube_dir, "pionera40.yaml")
            provider_kubeconfig = os.path.join(kube_dir, "pionera20.yaml")
            consumer_kubeconfig = os.path.join(kube_dir, "pionera3.yaml")
            for path in (common_kubeconfig, provider_kubeconfig, consumer_kubeconfig):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("apiVersion: v1\n")

            topology = {
                "VM_COMMON_IP": "10.0.0.10",
                "VM_PROVIDER_IP": "10.0.0.20",
                "VM_CONSUMER_IP": "10.0.0.30",
                "VM_SSH_USER": "operator",
                "VM_PROVIDER_K8S_NODE": "pionera20",
                "VM_CONSUMER_K8S_NODE": "pionera3",
                "VM_DISTRIBUTED_EXECUTION_HOST": "auto",
                "VM_DISTRIBUTED_KUBECONFIG_DIR": kube_dir,
                "K3S_KUBECONFIG_COMMON": "/home/other/.kube/pionera40.yaml",
                "K3S_KUBECONFIG_PROVIDER": "/home/other/.kube/pionera20.yaml",
                "K3S_KUBECONFIG_CONSUMER": "/home/other/.kube/pionera3.yaml",
            }

            with mock.patch.object(main, "_local_host_addresses", return_value={"10.0.0.10"}):
                preflight = main._vm_distributed_configuration_preflight(
                    {
                        "DOMAIN_BASE": "validation.example.local",
                        "DS_DOMAIN_BASE": "ds.validation.example.local",
                    },
                    topology,
                    {
                        "DS_1_NAME": "pionera",
                        "DS_1_CONNECTORS": "alpha,beta",
                        "DS_1_CONNECTOR_NAMESPACES": "alpha:provider,beta:consumer",
                        "DS_1_VALIDATION_PAIRS": "alpha>beta",
                        "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "full",
                    },
                )

        self.assertEqual(preflight["status"], "ready")
        self.assertEqual(preflight["warnings"], [])

    def test_common_vm_kubeconfig_sync_writes_missing_local_role_kubeconfigs(self):
        remote_kubeconfig = "\n".join(
            [
                "apiVersion: v1",
                "kind: Config",
                "clusters:",
                "- name: default",
                "  cluster:",
                "    server: https://127.0.0.1:6443",
                "users: []",
                "contexts: []",
                "current-context: default",
                "",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            kube_dir = os.path.join(tmpdir, ".kube")
            common_path = os.path.join(kube_dir, "pionera40.yaml")
            provider_path = os.path.join(kube_dir, "pionera20.yaml")
            consumer_path = os.path.join(kube_dir, "pionera3.yaml")
            topology = {
                "CLUSTER_TYPE": "k3s",
                "VM_DISTRIBUTED_EXECUTION_HOST": "common-services",
                "VM_COMMON_IP": "10.0.0.10",
                "VM_PROVIDER_IP": "10.0.0.20",
                "VM_CONSUMER_IP": "10.0.0.30",
                "VM_SSH_USER": "operator",
                "VM_DISTRIBUTED_KUBECONFIG_DIR": kube_dir,
                "K3S_KUBECONFIG_COMMON": common_path,
                "K3S_KUBECONFIG_PROVIDER": provider_path,
                "K3S_KUBECONFIG_CONSUMER": consumer_path,
                "VM_PROVIDER_K3S_API_LOCAL_PORT": "26443",
                "VM_CONSUMER_K3S_API_LOCAL_PORT": "36443",
            }

            calls = []

            def fake_runner(command, **kwargs):
                calls.append(list(command))
                return mock.Mock(returncode=0, stdout=remote_kubeconfig, stderr="")

            result = main._ensure_vm_distributed_local_kubeconfigs(
                topology,
                roles=("common", "provider", "consumer"),
                command_runner=fake_runner,
            )

            self.assertEqual(result["status"], "updated")
            self.assertEqual([item["status"] for item in result["items"]], ["written", "written", "written"])
            self.assertEqual(len(calls), 3)

            for path, expected_port in (
                (common_path, "6443"),
                (provider_path, "26443"),
                (consumer_path, "36443"),
            ):
                self.assertTrue(os.path.isfile(path))
                with open(path, encoding="utf-8") as handle:
                    content = handle.read()
                self.assertIn(f"server: https://127.0.0.1:{expected_port}", content)
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_kubeconfig_sync_auto_skips_when_execution_host_is_external(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = main._ensure_vm_distributed_local_kubeconfigs(
                {
                    "CLUSTER_TYPE": "k3s",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "external",
                    "K3S_KUBECONFIG_COMMON": os.path.join(tmpdir, "common.yaml"),
                },
                roles=("common",),
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "kubeconfig-sync-disabled")

    def test_reconcile_vm_distributed_ssh_access_installs_key_and_verifies_batchmode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            identity_file = os.path.join(tmpdir, "validation-env")
            public_key_file = f"{identity_file}.pub"
            with open(identity_file, "w", encoding="utf-8") as handle:
                handle.write("private\n")
            with open(public_key_file, "w", encoding="utf-8") as handle:
                handle.write("ssh-ed25519 AAAATEST validation\n")

            commands = []

            def runner(command, timeout):
                commands.append((command, timeout))
                rendered = " ".join(command)
                if "authorized_keys" in rendered:
                    return mock.Mock(returncode=0, stdout="authorized_keys=installed\n", stderr="")
                return mock.Mock(returncode=0, stdout="ssh_ready=1\n", stderr="")

            result = main._reconcile_vm_distributed_ssh_access(
                {
                    "execution_host": "external",
                    "ssh": {
                        "mode": "direct",
                        "connect_timeout_seconds": 5,
                        "known_hosts_strategy": "accept-new",
                        "bastion": {},
                    },
                    "ssh_bootstrap": {
                        "status": "ready",
                        "identity_file": identity_file,
                        "managed_marker": "validation-environment-vm-distributed",
                        "targets": [
                            {
                                "role": "provider-connectors",
                                "role_key": "provider",
                                "host": "provider.example.test",
                                "user": "operator",
                                "port": "22",
                                "identity_file": identity_file,
                                "needs_public_key": True,
                            }
                        ],
                    },
                },
                command_runner=runner,
            )

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["keypair"]["status"], "present")
        self.assertEqual(result["authorized_keys"][0]["state"], "installed")
        self.assertEqual(result["verification"][0]["status"], "passed")
        self.assertEqual(len(commands), 2)
        self.assertIn("-i", commands[0][0])
        self.assertIn(identity_file, commands[0][0])

    def test_reconcile_vm_distributed_ssh_access_creates_missing_keypair_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            identity_file = os.path.join(tmpdir, "validation-env")
            public_key_file = f"{identity_file}.pub"

            def runner(command, timeout):
                if command[:3] == ["ssh-keygen", "-t", "ed25519"]:
                    with open(identity_file, "w", encoding="utf-8") as handle:
                        handle.write("private\n")
                    with open(public_key_file, "w", encoding="utf-8") as handle:
                        handle.write("ssh-ed25519 AAAATEST validation\n")
                    return mock.Mock(returncode=0, stdout="", stderr="")
                if "authorized_keys" in " ".join(command):
                    return mock.Mock(returncode=0, stdout="authorized_keys=present\n", stderr="")
                return mock.Mock(returncode=0, stdout="ssh_ready=1\n", stderr="")

            result = main._reconcile_vm_distributed_ssh_access(
                {
                    "execution_host": "external",
                    "ssh": {"mode": "direct", "connect_timeout_seconds": 5, "bastion": {}},
                    "ssh_bootstrap": {
                        "status": "ready",
                        "identity_file": identity_file,
                        "key_comment": "validation",
                        "managed_marker": "validation",
                        "targets": [
                            {
                                "role": "common-services",
                                "host": "common.example.test",
                                "user": "operator",
                                "port": "22",
                                "identity_file": identity_file,
                                "needs_public_key": True,
                            }
                        ],
                    },
                },
                command_runner=runner,
            )

            self.assertTrue(os.path.isfile(identity_file))
            self.assertTrue(os.path.isfile(public_key_file))

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["keypair"]["status"], "created")
        self.assertTrue(result["keypair"]["changed"])

    def test_reconcile_vm_distributed_ssh_access_reports_initial_access_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            identity_file = os.path.join(tmpdir, "validation-env")
            with open(identity_file, "w", encoding="utf-8") as handle:
                handle.write("private\n")
            with open(f"{identity_file}.pub", "w", encoding="utf-8") as handle:
                handle.write("ssh-ed25519 AAAATEST validation\n")

            result = main._reconcile_vm_distributed_ssh_access(
                {
                    "execution_host": "external",
                    "ssh": {"mode": "direct", "connect_timeout_seconds": 5, "bastion": {}},
                    "ssh_bootstrap": {
                        "status": "ready",
                        "identity_file": identity_file,
                        "managed_marker": "validation",
                        "targets": [
                            {
                                "role": "consumer-connectors",
                                "host": "consumer.example.test",
                                "user": "operator",
                                "port": "22",
                                "identity_file": identity_file,
                                "needs_public_key": True,
                            }
                        ],
                    },
                },
                command_runner=lambda _command, timeout: mock.Mock(
                    returncode=255,
                    stdout="",
                    stderr="Permission denied",
                ),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["authorized_keys"][0]["reason"], "authorized-keys-sync-failed")
        self.assertIn("approved access path", result["authorized_keys"][0]["next_step"])

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

        def getter(url, timeout, allow_redirects, **kwargs):
            seen.append((url, timeout, allow_redirects, kwargs))
            return mock.Mock(status_code=404)

        result = main.run_vm_distributed_http_preflight(
            {"vms": [{"role": "common-services", "http_url": "http://192.0.2.10"}]},
            request_get=getter,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["vms"][0]["status_code"], 404)
        self.assertEqual(seen, [("http://192.0.2.10", 3, False, {})])

    def test_http_preflight_reports_self_signed_tls_as_warning_when_endpoint_is_reachable(self):
        seen = []

        def getter(url, timeout, allow_redirects, **kwargs):
            seen.append((url, kwargs.get("verify")))
            if kwargs.get("verify") is True:
                raise main.requests.exceptions.SSLError("self signed certificate")
            return mock.Mock(status_code=200)

        result = main.run_vm_distributed_http_preflight(
            {
                "http_preflight": {"tls_verify": "auto"},
                "vms": [{"role": "common-services", "http_url": "https://org1.example.test"}],
            },
            request_get=getter,
        )

        self.assertEqual(result["status"], "passed-with-warnings")
        self.assertEqual(result["vms"][0]["status"], "warning")
        self.assertEqual(result["vms"][0]["reason"], "tls-verification-failed")
        self.assertEqual(seen, [("https://org1.example.test", True), ("https://org1.example.test", False)])

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
            "status": "ready",
            "missing": [],
            "warnings": [],
            "checks": [
                {
                    "name": "Level 4 cluster scope",
                    "status": "ready",
                    "detail": "multi-kubeconfig connector deployment enabled",
                }
            ],
        }
        output = io.StringIO()

        with redirect_stdout(output):
            main._print_vm_distributed_preflight(preflight)

        text = output.getvalue()
        self.assertIn("Checklist:", text)
        self.assertIn("[ok] Level 4 cluster scope", text)


if __name__ == "__main__":
    unittest.main()
