import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class InesdataBuildImagesScriptTests(unittest.TestCase):
    def _copy_build_script(self, root: Path) -> Path:
        source_script = Path(__file__).resolve().parents[1] / "adapters" / "inesdata" / "scripts" / "build_images.sh"
        script_dir = root / "adapters" / "inesdata" / "scripts"
        script_dir.mkdir(parents=True)
        script_path = script_dir / "build_images.sh"
        shutil.copyfile(source_script, script_path)
        script_path.chmod(0o755)
        return script_path

    def _create_connector_source(self, root: Path) -> Path:
        connector_dir = root / "adapters" / "inesdata" / "sources" / "inesdata-connector"
        (connector_dir / "docker").mkdir(parents=True)
        (connector_dir / "docker" / "Dockerfile").write_text(
            "FROM alpine:3.20\n"
            "RUN adduser --no-create-home --disabled-password --ingroup app app\n"
            "COPY launchers/connector/build/libs/connector-app.jar /app/connector-app.jar\n",
            encoding="utf-8",
        )
        (connector_dir / "launchers" / "connector" / "build" / "libs").mkdir(parents=True)
        (connector_dir / "launchers" / "connector" / "build" / "libs" / "connector-app.jar").write_text(
            "placeholder",
            encoding="utf-8",
        )
        return connector_dir

    def test_local_dockerfile_fixups_stay_inside_component_build_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_path = self._copy_build_script(root)
            connector_dir = self._create_connector_source(root)
            manifest = root / "manifests" / "images.tsv"
            env = {
                **os.environ,
                "MANIFESTS_DIR": str(root / "manifests"),
                "DOCKER_CMD": "docker",
            }

            completed = subprocess.run(
                [
                    "bash",
                    str(script_path),
                    "--target",
                    "connector",
                    "--manifest",
                    str(manifest),
                    "--registry-host",
                    "local",
                    "--namespace",
                    "inesdata",
                ],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            manifest_text = manifest.read_text(encoding="utf-8")
            self.assertIn("docker build -f docker/.pionera-connector.Dockerfile", completed.stdout)
            self.assertIn("docker/.pionera-connector.Dockerfile", manifest_text)
            self.assertNotIn("/tmp/inesdata-manifests/dockerfiles", completed.stdout)
            self.assertNotIn("/tmp/inesdata-manifests/dockerfiles", manifest_text)
            self.assertFalse((connector_dir / "docker" / ".pionera-connector.Dockerfile").exists())


if __name__ == "__main__":
    unittest.main()
