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


if __name__ == "__main__":
    unittest.main()
