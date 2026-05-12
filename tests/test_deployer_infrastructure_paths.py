import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.infrastructure.lib import paths


class DeployerInfrastructurePathsTests(unittest.TestCase):
    def test_resolve_shared_artifact_dir_falls_back_when_shared_artifact_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_common = root / "deployers" / "inesdata" / "common"
            legacy_common.mkdir(parents=True)
            (legacy_common / "Chart.yaml").write_text("name: common\n", encoding="utf-8")

            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {},
                clear=True,
            ):
                resolved = paths.resolve_shared_artifact_dir("common", required_file="Chart.yaml")

        self.assertEqual(resolved, str(legacy_common))

    def test_resolve_shared_artifact_dir_prefers_shared_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_common = root / "deployers" / "shared" / "common"
            shared_common.mkdir(parents=True)
            (shared_common / "Chart.yaml").write_text("name: common\n", encoding="utf-8")
            legacy_common = root / "deployers" / "inesdata" / "common"
            legacy_common.mkdir(parents=True)
            (legacy_common / "Chart.yaml").write_text("name: legacy-common\n", encoding="utf-8")

            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {},
                clear=True,
            ):
                resolved = paths.resolve_shared_artifact_dir("common", required_file="Chart.yaml")

        self.assertEqual(resolved, str(shared_common))

    def test_resolve_shared_artifact_dir_prefers_ready_shared_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_common = root / "deployers" / "shared" / "common"
            shared_common.mkdir(parents=True)
            (shared_common / "Chart.yaml").write_text("name: common\n", encoding="utf-8")
            legacy_common = root / "deployers" / "inesdata" / "common"
            legacy_common.mkdir(parents=True)
            (legacy_common / "Chart.yaml").write_text("name: legacy-common\n", encoding="utf-8")

            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "true"},
                clear=True,
            ):
                resolved = paths.resolve_shared_artifact_dir("common", required_file="Chart.yaml")

        self.assertEqual(resolved, str(shared_common))

    def test_shared_artifact_roots_uses_shared_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_components = root / "deployers" / "shared" / "components"
            shared_components.mkdir(parents=True)
            legacy_components = root / "deployers" / "inesdata" / "components"
            legacy_components.mkdir(parents=True)

            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {},
                clear=True,
            ):
                roots = paths.shared_artifact_roots("components")

        self.assertEqual(roots, [str(shared_components), str(legacy_components)])

    def test_shared_artifact_roots_can_use_deployer_artifacts_when_shared_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_components = root / "deployers" / "shared" / "components"
            shared_components.mkdir(parents=True)
            legacy_components = root / "deployers" / "inesdata" / "components"
            legacy_components.mkdir(parents=True)

            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "false"},
                clear=True,
            ):
                roots = paths.shared_artifact_roots("components")

        self.assertEqual(roots, [str(legacy_components)])

    def test_deployer_config_paths_are_scoped_by_deployer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with mock.patch.object(paths, "project_root", return_value=root):
                self.assertEqual(
                    paths.infrastructure_deployer_config_path(),
                    root / "deployers" / "infrastructure" / "deployer.config",
                )
                self.assertEqual(
                    paths.infrastructure_deployer_config_example_path(),
                    root / "deployers" / "infrastructure" / "deployer.config.example",
                )
                self.assertEqual(
                    paths.deployer_config_path("inesdata"),
                    root / "deployers" / "inesdata" / "deployer.config",
                )
                self.assertEqual(
                    paths.deployer_config_example_path("inesdata"),
                    root / "deployers" / "inesdata" / "deployer.config.example",
                )


if __name__ == "__main__":
    unittest.main()
