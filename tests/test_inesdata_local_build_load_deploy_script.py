import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REL_PATH = Path("adapters/inesdata/scripts/local_build_load_deploy.sh")


class INESDataLocalBuildLoadDeployScriptTests(unittest.TestCase):
    def test_dataspace_values_are_resolved_before_role_aligned_namespace_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script_path = root / SCRIPT_REL_PATH
            script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / SCRIPT_REL_PATH, script_path)

            platform_dir = root / "deployers" / "inesdata"
            values_dir = platform_dir / "dataspace" / "registration-service"
            values_dir.mkdir(parents=True, exist_ok=True)
            (platform_dir / "deployer.config").write_text(
                "DS_1_NAME=pionera\nDS_1_NAMESPACE=core-control\n",
                encoding="utf-8",
            )
            (values_dir / "values-pionera.yaml").write_text("registration: {}\n", encoding="utf-8")

            manifest = root / "manifest.tsv"
            manifest.write_text(
                "\t".join(["component", "repo_dir", "image", "tag", "full_image", "build_cmd"])
                + "\n"
                + "\t".join(
                    [
                        "registration-service",
                        ".",
                        "local/registration-service",
                        "local",
                        "local/registration-service:local",
                        "build",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--skip-build",
                    "--manifest",
                    str(manifest),
                    "--platform-dir",
                    str(platform_dir),
                    "--namespace",
                    "core-control",
                    "--component",
                    "registration-service",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dataspace name: pionera", result.stdout)
        self.assertIn("values-pionera.yaml", result.stdout)
        self.assertNotIn("values-core-control.yaml", result.stderr + result.stdout)

    def test_namespace_is_resolved_from_deployer_config_when_not_passed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script_path = root / SCRIPT_REL_PATH
            script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / SCRIPT_REL_PATH, script_path)

            platform_dir = root / "deployers" / "inesdata"
            values_dir = platform_dir / "dataspace" / "registration-service"
            values_dir.mkdir(parents=True, exist_ok=True)
            (platform_dir / "deployer.config").write_text(
                "DS_1_NAME=pionera\nDS_1_NAMESPACE=core-control\n",
                encoding="utf-8",
            )
            (values_dir / "values-pionera.yaml").write_text("registration: {}\n", encoding="utf-8")

            manifest = root / "manifest.tsv"
            manifest.write_text(
                "\t".join(["component", "repo_dir", "image", "tag", "full_image", "build_cmd"])
                + "\n"
                + "\t".join(
                    [
                        "registration-service",
                        ".",
                        "local/registration-service",
                        "local",
                        "local/registration-service:local",
                        "build",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--skip-build",
                    "--manifest",
                    str(manifest),
                    "--platform-dir",
                    str(platform_dir),
                    "--component",
                    "registration-service",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Dataspace name: pionera", result.stdout)
        self.assertIn("K8s namespace: core-control", result.stdout)

    def test_k3s_remote_import_dry_run_prints_scp_and_ssh_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script_path = root / SCRIPT_REL_PATH
            script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / SCRIPT_REL_PATH, script_path)

            platform_dir = root / "deployers" / "inesdata"
            platform_dir.mkdir(parents=True, exist_ok=True)

            manifest = root / "manifest.tsv"
            manifest.write_text(
                "\t".join(["component", "repo_dir", "image", "tag", "full_image", "build_cmd"])
                + "\n"
                + "\t".join(
                    [
                        "connector-interface",
                        ".",
                        "local/inesdata-connector-interface",
                        "local",
                        "local/inesdata-connector-interface:local",
                        "build",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            env = dict(os.environ)
            env.update(
                {
                    "K3S_REMOTE_IMPORT_HOST": "pionera20",
                    "K3S_REMOTE_IMPORT_USER": "pionera",
                    "K3S_REMOTE_IMPORT_PORT": "22",
                    "K3S_REMOTE_IMPORT_BASTION_HOST": "orion.example.test",
                    "K3S_REMOTE_IMPORT_BASTION_USER": "jump",
                    "K3S_REMOTE_IMPORT_BASTION_PORT": "2222",
                    "K3S_REMOTE_PRUNE_IMPORTED_IMAGES": "true",
                    "K3S_REMOTE_PRUNE_KEEP": "2",
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--skip-build",
                    "--manifest",
                    str(manifest),
                    "--platform-dir",
                    str(platform_dir),
                    "--namespace",
                    "provider",
                    "--component",
                    "connector-interface",
                    "--cluster-runtime",
                    "k3s",
                    "--skip-deploy",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("K3s remote import target: pionera@pionera20", result.stdout)
        self.assertIn("K3s remote prune imported images: yes", result.stdout)
        self.assertIn("K3s remote prune keep: 2", result.stdout)
        self.assertIn("scp -P 22 -o ProxyJump=jump@orion.example.test:2222", result.stdout)
        self.assertIn("ssh -p 22 -J jump@orion.example.test:2222", result.stdout)
        self.assertIn("sudo k3s ctr -n k8s.io images import", result.stdout)
        self.assertIn("Pruning\\ old\\ k3s\\ images", result.stdout)

    def test_k3s_remote_import_uses_identity_file_for_bastion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script_path = root / SCRIPT_REL_PATH
            script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / SCRIPT_REL_PATH, script_path)

            platform_dir = root / "deployers" / "inesdata"
            platform_dir.mkdir(parents=True, exist_ok=True)

            manifest = root / "manifest.tsv"
            manifest.write_text(
                "\t".join(["component", "repo_dir", "image", "tag", "full_image", "build_cmd"])
                + "\n"
                + "\t".join(
                    [
                        "connector",
                        ".",
                        "local/inesdata-connector",
                        "local",
                        "local/inesdata-connector:local",
                        "build",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            env = dict(os.environ)
            env.update(
                {
                    "K3S_REMOTE_IMPORT_HOST": "pionera20",
                    "K3S_REMOTE_IMPORT_USER": "pionera",
                    "K3S_REMOTE_IMPORT_PORT": "22",
                    "K3S_REMOTE_IMPORT_BASTION_HOST": "orion.example.test",
                    "K3S_REMOTE_IMPORT_BASTION_USER": "jump",
                    "K3S_REMOTE_IMPORT_BASTION_PORT": "2222",
                    "K3S_REMOTE_IMPORT_IDENTITY_FILE": "/home/user/.ssh/id_ed25519_vm",
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--skip-build",
                    "--manifest",
                    str(manifest),
                    "--platform-dir",
                    str(platform_dir),
                    "--namespace",
                    "provider",
                    "--component",
                    "connector",
                    "--cluster-runtime",
                    "k3s",
                    "--skip-deploy",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("scp -o BatchMode=yes -o IdentitiesOnly=yes -i /home/user/.ssh/id_ed25519_vm", result.stdout)
        self.assertIn("ssh -o BatchMode=yes -o IdentitiesOnly=yes -i /home/user/.ssh/id_ed25519_vm", result.stdout)
        self.assertIn("ProxyCommand=ssh", result.stdout)
        self.assertIn("-W\\ %h:%p\\ jump@orion.example.test", result.stdout)
        self.assertNotIn("ProxyJump=jump@orion.example.test:2222", result.stdout)

    def test_k3s_remote_import_auto_prints_probe_and_interactive_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script_path = root / SCRIPT_REL_PATH
            script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / SCRIPT_REL_PATH, script_path)

            platform_dir = root / "deployers" / "inesdata"
            platform_dir.mkdir(parents=True, exist_ok=True)

            manifest = root / "manifest.tsv"
            manifest.write_text(
                "\t".join(["component", "repo_dir", "image", "tag", "full_image", "build_cmd"])
                + "\n"
                + "\t".join(
                    [
                        "connector",
                        ".",
                        "local/inesdata-connector",
                        "local",
                        "local/inesdata-connector:local",
                        "build",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            env = dict(os.environ)
            env.update(
                {
                    "K3S_REMOTE_IMPORT_HOST": "pionera20",
                    "K3S_REMOTE_IMPORT_USER": "pionera",
                    "K3S_REMOTE_IMPORT_PORT": "22",
                    "K3S_REMOTE_IMPORT_INTERACTIVE": "auto",
                    "K3S_IMAGE_IMPORT_COMMAND": "sudo -n k3s ctr -n k8s.io images import",
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--skip-build",
                    "--manifest",
                    str(manifest),
                    "--platform-dir",
                    str(platform_dir),
                    "--namespace",
                    "provider",
                    "--component",
                    "connector",
                    "--cluster-runtime",
                    "k3s",
                    "--skip-deploy",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("sudo\\ -n\\ k3s\\ ctr\\ -n\\ k8s.io\\ images\\ ls\\ -q", result.stdout)
        self.assertIn("sudo\\ k3s\\ ctr\\ -n\\ k8s.io\\ images\\ import", result.stdout)
        self.assertIn("fallback when sudo -n is not available", result.stdout)

    def test_k3s_remote_import_auto_can_use_batch_sudo_secret_without_printing_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script_path = root / SCRIPT_REL_PATH
            script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / SCRIPT_REL_PATH, script_path)

            platform_dir = root / "deployers" / "inesdata"
            platform_dir.mkdir(parents=True, exist_ok=True)

            manifest = root / "manifest.tsv"
            manifest.write_text(
                "\t".join(["component", "repo_dir", "image", "tag", "full_image", "build_cmd"])
                + "\n"
                + "\t".join(
                    [
                        "connector",
                        ".",
                        "local/inesdata-connector",
                        "local",
                        "local/inesdata-connector:local",
                        "build",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            env = dict(os.environ)
            env.update(
                {
                    "K3S_REMOTE_IMPORT_HOST": "pionera20",
                    "K3S_REMOTE_IMPORT_USER": "pionera",
                    "K3S_REMOTE_IMPORT_PORT": "22",
                    "K3S_REMOTE_IMPORT_INTERACTIVE": "auto",
                    "K3S_REMOTE_IMPORT_SUDO_PASSWORD": "do-not-print-this",
                    "K3S_IMAGE_IMPORT_COMMAND": "sudo -n k3s ctr -n k8s.io images import",
                }
            )
            result = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--skip-build",
                    "--manifest",
                    str(manifest),
                    "--platform-dir",
                    str(platform_dir),
                    "--namespace",
                    "provider",
                    "--component",
                    "connector",
                    "--cluster-runtime",
                    "k3s",
                    "--skip-deploy",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("sudo\\ -S\\ -p", result.stdout)
        self.assertIn("k3s\\ ctr\\ -n\\ k8s.io\\ images\\ import", result.stdout)
        self.assertIn("fallback using batch sudo secret when sudo -n is not available", result.stdout)
        self.assertNotIn("do-not-print-this", result.stdout + result.stderr)

    def test_connector_preserve_values_uses_dataspace_release_suffix_for_role_aligned_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script_path = root / SCRIPT_REL_PATH
            script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / SCRIPT_REL_PATH, script_path)

            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_helm = fake_bin / "helm"
            fake_helm.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"status\" && \"$2\" == \"conn-org2-pionera-pionera\" ]]; then exit 0; fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake_helm.chmod(0o755)

            platform_dir = root / "deployers" / "inesdata"
            connector_dir = platform_dir / "connector"
            connector_dir.mkdir(parents=True, exist_ok=True)
            (connector_dir / "values-conn-org2-pionera.yaml").write_text("connector: {}\n", encoding="utf-8")

            manifest = root / "manifest.tsv"
            manifest.write_text(
                "\t".join(["component", "repo_dir", "image", "tag", "full_image", "build_cmd"])
                + "\n"
                + "\t".join(
                    [
                        "connector",
                        ".",
                        "local/inesdata-connector",
                        "local",
                        "local/inesdata-connector:local",
                        "build",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
            result = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--skip-build",
                    "--manifest",
                    str(manifest),
                    "--platform-dir",
                    str(platform_dir),
                    "--namespace",
                    "provider",
                    "--dataspace",
                    "pionera",
                    "--component",
                    "connector",
                    "--preserve-values",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('helm upgrade --install "conn-org2-pionera-pionera"', result.stdout)
        self.assertNotIn("conn-org2-pionera-provider", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
