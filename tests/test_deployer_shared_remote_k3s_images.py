import unittest
from unittest import mock

from deployers.shared.lib.remote_k3s_images import (
    remote_k3s_image_import_target,
    shell_join,
)


class RemoteK3sImagesTests(unittest.TestCase):
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

    def test_identity_file_uses_proxy_command_for_bastion(self):
        target = remote_k3s_image_import_target(
            {
                "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "orion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "SSH_IDENTITY_FILE": "/home/user/.ssh/id_ed25519_vm",
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
        self.assertIn("-i /home/user/.ssh/id_ed25519_vm", ssh_command)
        self.assertIn("ProxyCommand=ssh", ssh_command)

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


if __name__ == "__main__":
    unittest.main()
