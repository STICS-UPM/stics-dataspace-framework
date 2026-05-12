import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.config import InesdataConfig
from adapters.edc.config import EdcConfig
from deployers.infrastructure.lib import paths


class InesdataSharedRuntimeValuesTests(unittest.TestCase):
    def test_common_values_use_shared_runtime_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_chart(root / "deployers" / "shared" / "common")
            self._write_chart(root / "deployers" / "inesdata" / "common")

            config = self._config_for(root)
            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {},
                clear=True,
            ):
                values_path = Path(config.ensure_common_values_file())

        self.assertEqual(
            values_path,
            root / "deployers" / "shared" / "deployments" / "DEV" / "common" / "values.yaml",
        )

    def test_common_values_are_copied_to_shared_runtime_when_shared_artifacts_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_common = root / "deployers" / "shared" / "common"
            self._write_chart(shared_common, values="postgresql:\n  auth: {}\n")
            self._write_chart(root / "deployers" / "inesdata" / "common", values="deployer: true\n")

            config = self._config_for(root)
            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "true"},
                clear=True,
            ):
                values_path = Path(config.ensure_common_values_file())
                copied_values = values_path.read_text(encoding="utf-8")
                source_values = (shared_common / "values.yaml").read_text(encoding="utf-8")

            self.assertEqual(
                values_path,
                root / "deployers" / "shared" / "deployments" / "DEV" / "common" / "values.yaml",
            )
            self.assertEqual(copied_values, "postgresql:\n  auth: {}\n")
            self.assertEqual(source_values, "postgresql:\n  auth: {}\n")

    def test_registration_values_are_copied_to_runtime_when_shared_artifacts_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_chart(root / "deployers" / "shared" / "dataspace" / "registration-service")
            legacy_registration = root / "deployers" / "inesdata" / "dataspace" / "registration-service"
            self._write_chart(legacy_registration)
            (legacy_registration / "values-demo.yaml").write_text(
                "dataspace:\n  name: demo\n",
                encoding="utf-8",
            )

            config = self._config_for(root)
            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "true"},
                clear=True,
            ):
                values_path = Path(config.ensure_registration_values_file(refresh=True))
                copied_values = values_path.read_text(encoding="utf-8")

            self.assertEqual(
                values_path,
                root
                / "deployers"
                / "inesdata"
                / "deployments"
                / "DEV"
                / "demo"
                / "dataspace"
                / "registration-service"
                / "values-demo.yaml",
            )
            self.assertEqual(copied_values, "dataspace:\n  name: demo\n")

    def test_public_portal_values_are_copied_to_runtime_when_shared_artifacts_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_chart(root / "deployers" / "shared" / "dataspace" / "public-portal")
            legacy_public_portal = root / "deployers" / "inesdata" / "dataspace" / "public-portal"
            self._write_chart(legacy_public_portal)
            (legacy_public_portal / "values-demo.yaml").write_text(
                "dataspace:\n  name: demo\nbackend:\n  catalog: {}\n",
                encoding="utf-8",
            )

            config = self._config_for(root)
            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "true"},
                clear=True,
            ):
                values_path = Path(config.ensure_public_portal_values_file(refresh=True))
                copied_values = values_path.read_text(encoding="utf-8")

            self.assertEqual(
                values_path,
                root
                / "deployers"
                / "inesdata"
                / "deployments"
                / "DEV"
                / "demo"
                / "dataspace"
                / "public-portal"
                / "values-demo.yaml",
            )
            self.assertEqual(copied_values, "dataspace:\n  name: demo\nbackend:\n  catalog: {}\n")

    def test_vault_keys_use_shared_common_without_copying_legacy_runtime_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_chart(root / "deployers" / "shared" / "common")
            legacy_common = root / "deployers" / "inesdata" / "common"
            self._write_chart(legacy_common)
            (legacy_common / "init-keys-vault.json").write_text(
                '{"root_token": "token", "unseal_keys_hex": ["key"]}\n',
                encoding="utf-8",
            )

            config = self._config_for(root)
            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "true"},
                clear=True,
            ):
                vault_path = Path(config.ensure_vault_keys_file())

            self.assertEqual(
                vault_path,
                root / "deployers" / "shared" / "common" / "init-keys-vault.json",
            )
            self.assertFalse(vault_path.exists())

    def test_edc_vault_keys_runtime_uses_shared_common_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_chart(root / "deployers" / "shared" / "common")
            legacy_common = root / "deployers" / "inesdata" / "common"
            self._write_chart(legacy_common)
            (legacy_common / "init-keys-vault.json").write_text(
                '{"root_token": "token", "unseal_keys_hex": ["key"]}\n',
                encoding="utf-8",
            )

            class TestEdcConfig(EdcConfig):
                @classmethod
                def script_dir(cls):
                    return str(root)

                @classmethod
                def repo_dir(cls):
                    return str(root / "deployers" / "edc")

                @classmethod
                def dataspace_name(cls):
                    return "demoedc"

                @classmethod
                def deployment_environment_name(cls):
                    return "DEV"

            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "true"},
                clear=True,
            ):
                vault_path = Path(TestEdcConfig.ensure_vault_keys_file())

            self.assertEqual(
                vault_path,
                root / "deployers" / "shared" / "common" / "init-keys-vault.json",
            )

    def test_edc_vault_keys_do_not_migrate_from_previous_deployer_runtime_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_chart(root / "deployers" / "shared" / "common")
            previous_runtime_common = (
                root
                / "deployers"
                / "edc"
                / "deployments"
                / "DEV"
                / "demoedc"
                / "shared"
                / "common"
            )
            previous_runtime_common.mkdir(parents=True, exist_ok=True)
            (previous_runtime_common / "init-keys-vault.json").write_text(
                '{"root_token": "edc-token", "unseal_keys_hex": ["edc-key"]}\n',
                encoding="utf-8",
            )

            class TestEdcConfig(EdcConfig):
                @classmethod
                def script_dir(cls):
                    return str(root)

                @classmethod
                def repo_dir(cls):
                    return str(root / "deployers" / "edc")

                @classmethod
                def dataspace_name(cls):
                    return "demoedc"

                @classmethod
                def deployment_environment_name(cls):
                    return "DEV"

            with mock.patch.object(paths, "project_root", return_value=root), mock.patch.dict(
                os.environ,
                {"PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS": "true"},
                clear=True,
            ):
                vault_path = Path(TestEdcConfig.ensure_vault_keys_file())

            self.assertEqual(
                vault_path,
                root / "deployers" / "shared" / "common" / "init-keys-vault.json",
            )
            self.assertFalse(vault_path.exists())

    @staticmethod
    def _write_chart(path: Path, values: str = "name: value\n"):
        path.mkdir(parents=True, exist_ok=True)
        (path / "Chart.yaml").write_text("apiVersion: v2\nname: test\n", encoding="utf-8")
        (path / "values.yaml").write_text(values, encoding="utf-8")

    @staticmethod
    def _config_for(root: Path):
        class TestConfig(InesdataConfig):
            @classmethod
            def script_dir(cls):
                return str(root)

            @classmethod
            def repo_dir(cls):
                return str(root / "deployers" / "inesdata")

            @classmethod
            def dataspace_name(cls):
                return "demo"

            @classmethod
            def deployment_environment_name(cls):
                return "DEV"

        return TestConfig


if __name__ == "__main__":
    unittest.main()
