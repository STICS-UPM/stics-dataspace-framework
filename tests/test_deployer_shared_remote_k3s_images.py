import os
import unittest
from unittest import mock

from deployers.shared.lib.remote_k3s_images import (
    image_reference_candidates,
    remote_k3s_image_import_target,
    shell_join,
)


class RemoteK3sImagesTests(unittest.TestCase):
    def test_image_reference_candidates_include_kubernetes_docker_io_normalization(self):
        self.assertEqual(
            image_reference_candidates("validation-environment/edc-connector:local"),
            [
                "validation-environment/edc-connector:local",
                "docker.io/validation-environment/edc-connector:local",
            ],
        )
        self.assertEqual(
            image_reference_candidates("busybox:latest"),
            [
                "busybox:latest",
                "docker.io/library/busybox:latest",
            ],
        )
        self.assertEqual(
            image_reference_candidates("localhost/validation-environment/edc-connector:local"),
            ["localhost/validation-environment/edc-connector:local"],
        )

    def test_target_uses_role_specific_host_and_bastion(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
                "VM_PROVIDER_SSH_PORT": "22",
            },
            role="provider",
        )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "pionera20")
        self.assertEqual(target.destination, "pionera@pionera20")
        self.assertEqual(target.bastion_destination, "jump@orion.example.test:2222")
        self.assertIn("-J jump@orion.example.test:2222", shell_join(target.ssh_import_args("/tmp/image.tar")))

    def test_common_services_role_specific_direct_access_overrides_global_bastion_for_provider(self):
        with mock.patch(
            "deployers.shared.lib.remote_k3s_images._resolve_host_addresses",
            return_value=set(),
        ):
            target = remote_k3s_image_import_target(
                {
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "common-services",
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_HOST": "orion.example.test",
                    "SSH_BASTION_PORT": "2222",
                    "SSH_BASTION_USER": "jump",
                    "VM_PROVIDER_SSH_ACCESS_MODE": "direct",
                    "VM_PROVIDER_SSH_HOST": "pionera20",
                    "VM_PROVIDER_IP": "192.168.122.134",
                    "VM_PROVIDER_SSH_USER": "pionera",
                    "VM_PROVIDER_SSH_PORT": "22",
                },
                role="provider",
            )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "192.168.122.134")
        self.assertEqual(target.destination, "pionera@192.168.122.134")
        self.assertEqual(target.bastion_destination, "")
        self.assertNotIn("orion.example.test", shell_join(target.ssh_import_args("/tmp/image.tar")))

    def test_external_role_specific_direct_private_target_falls_back_to_global_bastion(self):
        with mock.patch(
            "deployers.shared.lib.remote_k3s_images._resolve_host_addresses",
            return_value=set(),
        ):
            target = remote_k3s_image_import_target(
                {
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "external",
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_HOST": "orion.example.test",
                    "SSH_BASTION_PORT": "2222",
                    "SSH_BASTION_USER": "jump",
                    "VM_PROVIDER_SSH_ACCESS_MODE": "direct",
                    "VM_PROVIDER_SSH_HOST": "pionera20",
                    "VM_PROVIDER_IP": "192.168.122.134",
                    "VM_PROVIDER_SSH_USER": "pionera",
                    "VM_PROVIDER_SSH_PORT": "22",
                },
                role="provider",
            )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "192.168.122.134")
        self.assertEqual(target.destination, "pionera@192.168.122.134")
        self.assertEqual(target.bastion_destination, "jump@orion.example.test:2222")
        self.assertIn("-J jump@orion.example.test:2222", shell_join(target.ssh_import_args("/tmp/image.tar")))

    def test_external_role_specific_direct_public_target_stays_direct(self):
        with mock.patch(
            "deployers.shared.lib.remote_k3s_images._resolve_host_addresses",
            return_value={"203.0.113.20"},
        ):
            target = remote_k3s_image_import_target(
                {
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "external",
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_HOST": "orion.example.test",
                    "SSH_BASTION_PORT": "2222",
                    "SSH_BASTION_USER": "jump",
                    "VM_PROVIDER_SSH_ACCESS_MODE": "direct",
                    "VM_PROVIDER_SSH_HOST": "provider.example.test",
                    "VM_PROVIDER_SSH_USER": "pionera",
                    "VM_PROVIDER_SSH_PORT": "22",
                },
                role="provider",
            )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "provider.example.test")
        self.assertEqual(target.bastion_destination, "")
        self.assertNotIn("orion.example.test", shell_join(target.ssh_import_args("/tmp/image.tar")))

    def test_role_specific_bastion_values_override_global_bastion_for_consumer(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "SSH_ACCESS_MODE": "direct",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "VM_CONSUMER_SSH_ACCESS_MODE": "bastion",
                "VM_CONSUMER_SSH_HOST": "pionera3",
                "VM_CONSUMER_SSH_USER": "pionera",
                "VM_CONSUMER_SSH_BASTION_HOST": "consumer-bastion.example.test",
                "VM_CONSUMER_SSH_BASTION_PORT": "2256",
                "VM_CONSUMER_SSH_BASTION_USER": "consumer-jump",
            },
            role="consumer",
        )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "pionera3")
        self.assertEqual(target.bastion_destination, "consumer-jump@consumer-bastion.example.test:2256")
        self.assertIn(
            "-J consumer-jump@consumer-bastion.example.test:2256",
            shell_join(target.ssh_import_args("/tmp/image.tar")),
        )

    def test_common_services_execution_uses_direct_ssh_even_when_bastion_is_configured(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_DISTRIBUTED_EXECUTION_HOST": "common-services",
                "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH": "true",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "VM_COMMON_SSH_HOST": "pionera40",
                "VM_COMMON_SSH_USER": "pionera",
                "VM_COMMON_SSH_PORT": "22",
            },
            role="common",
        )

        self.assertIsNotNone(target)
        self.assertEqual(target.destination, "pionera@pionera40")
        self.assertEqual(target.bastion_destination, "")
        self.assertNotIn("orion.example.test", shell_join(target.scp_upload_args("/tmp/image.tar", "/tmp/image.tar")))
        self.assertNotIn("orion.example.test", shell_join(target.ssh_import_args("/tmp/image.tar")))

    def test_auto_common_services_execution_uses_direct_ssh_for_remote_image_import(self):
        with mock.patch(
            "deployers.shared.lib.remote_k3s_images._vm_distributed_running_on_common_services",
            return_value=True,
        ):
            target = remote_k3s_image_import_target(
                {
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "auto",
                    "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH": "true",
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_HOST": "orion.example.test",
                    "SSH_BASTION_PORT": "2222",
                    "SSH_BASTION_USER": "jump",
                    "VM_COMMON_SSH_HOST": "pionera40",
                    "VM_COMMON_SSH_USER": "pionera",
                },
                role="common",
            )

        self.assertIsNotNone(target)
        self.assertEqual(target.bastion_destination, "")
        self.assertNotIn("orion.example.test", shell_join(target.scp_upload_args("/tmp/image.tar", "/tmp/image.tar")))

    def test_common_services_direct_import_uses_role_ip_when_hostname_does_not_resolve(self):
        with mock.patch(
            "deployers.shared.lib.remote_k3s_images._resolve_host_addresses",
            return_value=set(),
        ):
            target = remote_k3s_image_import_target(
                {
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "common-services",
                    "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH": "true",
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_HOST": "orion.example.test",
                    "SSH_BASTION_PORT": "2222",
                    "SSH_BASTION_USER": "jump",
                    "VM_PROVIDER_SSH_HOST": "pionera20",
                    "VM_PROVIDER_IP": "192.168.122.134",
                    "VM_PROVIDER_SSH_USER": "pionera",
                },
                role="provider",
            )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "192.168.122.134")
        self.assertEqual(target.destination, "pionera@192.168.122.134")
        self.assertEqual(target.bastion_destination, "")
        self.assertNotIn("pionera20", shell_join(target.scp_upload_args("/tmp/image.tar", "/tmp/image.tar")))

    def test_common_services_direct_import_keeps_resolvable_hostname(self):
        with mock.patch(
            "deployers.shared.lib.remote_k3s_images._resolve_host_addresses",
            return_value={"192.168.122.134"},
        ):
            target = remote_k3s_image_import_target(
                {
                    "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "common-services",
                    "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH": "true",
                    "SSH_ACCESS_MODE": "bastion",
                    "SSH_BASTION_HOST": "orion.example.test",
                    "VM_PROVIDER_SSH_HOST": "pionera20",
                    "VM_PROVIDER_IP": "192.168.122.134",
                    "VM_PROVIDER_SSH_USER": "pionera",
                },
                role="provider",
            )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "pionera20")

    def test_external_execution_keeps_bastion_for_remote_image_import(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_DISTRIBUTED_EXECUTION_HOST": "external",
                "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH": "true",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "VM_COMMON_SSH_HOST": "pionera40",
                "VM_COMMON_SSH_USER": "pionera",
            },
            role="common",
        )

        self.assertIsNotNone(target)
        self.assertEqual(target.bastion_destination, "jump@orion.example.test:2222")
        self.assertIn("-J jump@orion.example.test:2222", shell_join(target.ssh_import_args("/tmp/image.tar")))

    def test_components_role_falls_back_to_common_vm(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_COMMON_SSH_HOST": "pionera40",
                "VM_COMMON_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "pionera40")
        self.assertEqual(target.destination, "pionera@pionera40")

    def test_disabled_flag_returns_no_target(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "false",
                "VM_PROVIDER_SSH_HOST": "pionera20",
            },
            role="provider",
        )

        self.assertIsNone(target)

    def test_target_renders_remote_prune_environment(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE": "true",
                "VM_DISTRIBUTED_REMOTE_IMAGE_PRUNE_KEEP": "3",
                "VM_PROVIDER_SSH_HOST": "pionera20",
            },
            role="provider",
        )

        self.assertIsNotNone(target)
        env = target.shell_env()
        self.assertEqual(env["K3S_REMOTE_PRUNE_IMPORTED_IMAGES"], "true")
        self.assertEqual(env["K3S_REMOTE_PRUNE_KEEP"], "3")

    def test_target_renders_known_hosts_strategy_environment(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY": "accept-new",
                "VM_PROVIDER_SSH_HOST": "pionera20",
            },
            role="provider",
        )

        self.assertIsNotNone(target)
        env = target.shell_env()
        self.assertEqual(env["K3S_REMOTE_IMPORT_KNOWN_HOSTS_STRATEGY"], "accept-new")

    def test_identity_file_is_expanded_in_environment_and_commands(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_IDENTITY_FILE": "~/.ssh/id_ed25519_vm",
                "VM_PROVIDER_SSH_HOST": "pionera20",
                "VM_PROVIDER_SSH_USER": "pionera",
            },
            role="provider",
        )

        self.assertIsNotNone(target)
        expanded = os.path.expanduser("~/.ssh/id_ed25519_vm")
        self.assertEqual(target.shell_env()["K3S_REMOTE_IMPORT_IDENTITY_FILE"], expanded)
        self.assertIn(f"-i {expanded}", shell_join(target.scp_upload_args("/tmp/image.tar", "/tmp/image.tar")))
        self.assertIn(f"-i {expanded}", shell_join(target.ssh_import_args("/tmp/image.tar")))

    def test_identity_file_uses_proxy_command_for_bastion(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "SSH_IDENTITY_FILE": "/home/user/.ssh/id_ed25519_vm",
                "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY": "accept-new",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        scp_command = shell_join(target.scp_upload_args("/tmp/image.tar", "/tmp/image.tar"))
        ssh_command = shell_join(target.ssh_import_args("/tmp/image.tar"))

        self.assertIn("-i /home/user/.ssh/id_ed25519_vm", scp_command)
        self.assertIn("ProxyCommand=ssh", scp_command)
        self.assertIn("-W %h:%p", scp_command)
        self.assertIn("StrictHostKeyChecking=accept-new", scp_command)
        self.assertIn("-i /home/user/.ssh/id_ed25519_vm", ssh_command)
        self.assertIn("ProxyCommand=ssh", ssh_command)
        self.assertIn("StrictHostKeyChecking=accept-new", ssh_command)

    def test_import_command_cleans_archive_but_preserves_failure_status(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        remote_command = target.ssh_import_args("/tmp/image.tar")[-1]

        self.assertIn("status=$?", remote_command)
        self.assertIn("rm -f /tmp/image.tar", remote_command)
        self.assertIn("exit $status", remote_command)
        self.assertNotIn("-t", target.ssh_import_args("/tmp/image.tar"))

    def test_interactive_import_allocates_tty_and_allows_sudo_prompt(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE": "true",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND": "sudo -n k3s ctr -n k8s.io images import",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        self.assertTrue(target.interactive)
        self.assertTrue(target.allocate_tty)
        self.assertEqual(target.import_command, "sudo k3s ctr -n k8s.io images import")

        command = shell_join(target.ssh_import_args("/tmp/image.tar"))
        self.assertIn("ssh -tt", command)
        self.assertIn("sudo k3s ctr -n k8s.io images import", command)
        self.assertNotIn("sudo -n k3s", command)

    def test_auto_interactive_import_keeps_noninteractive_command_and_can_render_fallback(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE": "auto",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND": "sudo -n k3s ctr -n k8s.io images import",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        self.assertTrue(target.interactive)
        self.assertFalse(target.allocate_tty)
        self.assertEqual(target.interactive_mode, "auto")
        self.assertEqual(target.import_command, "sudo -n k3s ctr -n k8s.io images import")

        command = shell_join(target.ssh_import_args("/tmp/image.tar"))
        fallback = shell_join(target.ssh_import_args("/tmp/image.tar", interactive=True))

        self.assertNotIn("ssh -tt", command)
        self.assertIn("sudo -n k3s ctr -n k8s.io images import", command)
        self.assertIn("ssh -tt", fallback)
        self.assertIn("sudo k3s ctr -n k8s.io images import", fallback)
        self.assertIn("sudo -n k3s ctr -n k8s.io images ls -q", shell_join(target.ssh_sudo_probe_args()))

    def test_auto_interactive_import_can_render_stdin_sudo_password_command(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE": "auto",
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND": "sudo -n k3s ctr -n k8s.io images import",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        import_command = target.stdin_password_import_command()
        command = shell_join(target.ssh_import_args("/tmp/image.tar", sudo_stdin=True))

        self.assertNotIn("ssh -tt", command)
        self.assertEqual(import_command, "sudo -S -p '' k3s ctr -n k8s.io images import")
        self.assertIn("-n k8s.io", import_command)
        self.assertNotIn("sudo -n k3s", import_command)

    def test_target_renders_remote_probe_command_with_same_ssh_path(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_USER": "jump",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        command = shell_join(target.ssh_command_args("sudo -n true"))

        self.assertIn("ssh", command)
        self.assertIn("-J jump@orion.example.test:2222", command)
        self.assertIn("pionera@pionera40", command)
        self.assertIn("sudo -n true", command)

    def test_target_renders_remote_image_check_with_normalized_image_references(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        command = shell_join(target.ssh_image_check_args("validation-environment/edc-connector:local"))

        self.assertIn("k3s ctr -n k8s.io images ls -q", command)
        self.assertIn("validation-environment/edc-connector:local", command)
        self.assertIn("docker.io/validation-environment/edc-connector:local", command)
        self.assertIn("grep -Fx", command)

    def test_target_renders_remote_image_check_with_sudo_stdin(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "VM_COMPONENTS_SSH_HOST": "pionera40",
                "VM_COMPONENTS_SSH_USER": "pionera",
            },
            role="components",
        )

        self.assertIsNotNone(target)
        command = shell_join(
            target.ssh_image_check_args(
                "validation-environment/edc-dashboard:latest",
                sudo_stdin=True,
            )
        )

        self.assertIn("sudo -S", command)
        self.assertIn("k3s ctr -n k8s.io images ls -q", command)


if __name__ == "__main__":
    unittest.main()
