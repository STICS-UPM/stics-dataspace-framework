import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.edc import bootstrap as edc_bootstrap


class BootstrapConfigLoaderTests(unittest.TestCase):
    def _clear_pionera_overrides(self):
        keys = [key for key in os.environ if key.startswith("PIONERA_")]
        previous = {key: os.environ.get(key) for key in keys}
        for key in keys:
            os.environ.pop(key, None)
        return previous

    @staticmethod
    def _restore_environment(previous):
        for key in [key for key in os.environ if key.startswith("PIONERA_")]:
            os.environ.pop(key, None)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_edc_bootstrap_load_config_uses_topology_overlays(self):
        previous = self._clear_pionera_overrides()
        os.environ["PIONERA_TOPOLOGY"] = "vm-single"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                deployment_dir = root / "deployers" / "edc"
                (root / "deployers" / "inesdata").mkdir(parents=True, exist_ok=True)
                (root / "deployers" / "infrastructure" / "topologies").mkdir(parents=True, exist_ok=True)
                (deployment_dir / "topologies").mkdir(parents=True, exist_ok=True)
                (deployment_dir / "deployer.config").write_text("EDC_DASHBOARD_ENABLED=false\n", encoding="utf-8")
                (root / "deployers" / "inesdata" / "deployer.config").write_text(
                    "KC_URL=http://legacy-keycloak\n",
                    encoding="utf-8",
                )
                (root / "deployers" / "infrastructure" / "deployer.config").write_text(
                    "KC_URL=http://shared-keycloak\n",
                    encoding="utf-8",
                )
                (root / "deployers" / "edc" / "deployer.config").write_text(
                    "DS_1_NAME=demoedc\nEDC_DASHBOARD_ENABLED=false\n",
                    encoding="utf-8",
                )
                (root / "deployers" / "infrastructure" / "topologies" / "vm-single.config").write_text(
                    "VM_EXTERNAL_IP=192.0.2.10\n",
                    encoding="utf-8",
                )
                with mock.patch.object(edc_bootstrap, "project_root", return_value=root), mock.patch.object(
                    edc_bootstrap,
                    "deployment_root",
                    return_value=deployment_dir,
                ):
                    config = edc_bootstrap.load_config()
        finally:
            self._restore_environment(previous)

        self.assertEqual(config["KC_URL"], "http://shared-keycloak")
        self.assertEqual(config["VM_EXTERNAL_IP"], "192.0.2.10")
        self.assertEqual(config["DS_1_NAME"], "demoedc")
        self.assertEqual(config["EDC_DASHBOARD_ENABLED"], "false")

    def test_inesdata_bootstrap_load_effective_config_uses_topology_overlays(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            adapter_dir = root / "deployers" / "inesdata"
            infrastructure_dir = root / "deployers" / "infrastructure"
            (adapter_dir / "topologies").mkdir(parents=True, exist_ok=True)
            (infrastructure_dir / "topologies").mkdir(parents=True, exist_ok=True)
            (infrastructure_dir / "deployer.config").write_text(
                "KC_URL=http://shared-keycloak\nVT_TOKEN=shared-token\n",
                encoding="utf-8",
            )
            (infrastructure_dir / "topologies" / "vm-single.config").write_text(
                "VM_EXTERNAL_IP=192.0.2.10\n",
                encoding="utf-8",
            )
            (adapter_dir / "deployer.config").write_text(
                "DS_1_NAME=demo\nVT_TOKEN=X\n",
                encoding="utf-8",
            )
            code = f"""
import json
import os
import sys
sys.path.insert(0, {repr(str(root.parent))})
sys.path.insert(0, {repr('/home/avargas/TEST_DSQA_AI_MODEL_HUB/Validation-Environment')})
os.environ['PIONERA_TOPOLOGY'] = 'vm-single'
import deployers.inesdata.bootstrap as bootstrap
bootstrap._bootstrap_root_dir = lambda: {repr(str(adapter_dir))}
print(json.dumps(bootstrap.load_effective_deployer_config(), sort_keys=True))
"""
            completed = subprocess.run(
                ["python3", "-c", code],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.strip())
        self.assertEqual(payload["KC_URL"], "http://shared-keycloak")
        self.assertEqual(payload["VM_EXTERNAL_IP"], "192.0.2.10")
        self.assertEqual(payload["DS_1_NAME"], "demo")
        self.assertEqual(payload["VT_TOKEN"], "shared-token")

    def test_inesdata_bootstrap_script_can_run_from_its_own_directory(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        script_path = os.path.join(repo_root, "deployers", "inesdata", "bootstrap.py")
        script_dir = os.path.dirname(script_path)

        completed = subprocess.run(
            ["python3", script_path, "--help"],
            cwd=script_dir,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Usage:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
