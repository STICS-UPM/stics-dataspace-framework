import tempfile
import unittest
import os
from pathlib import Path
from unittest import mock

from deployers.shared.lib import runtime_artifacts


class RuntimeArtifactsTests(unittest.TestCase):
    def test_local_without_deployment_id_keeps_legacy_connector_credentials_path(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {
                "PIONERA_DEPLOYMENT_ID": "",
                "PIONERA_RUNTIME_ARTIFACT_LAYOUT": "",
            },
        ):
            path = runtime_artifacts.connector_credentials_path(
                "inesdata",
                "DEV",
                "pionera",
                "conn-org2-pionera",
                topology="local",
                root=tmpdir,
            )

        self.assertEqual(
            path,
            Path(tmpdir)
            / "deployers"
            / "inesdata"
            / "deployments"
            / "DEV"
            / "pionera"
            / "credentials-connector-conn-org2-pionera.json",
        )

    def test_vm_single_connector_credentials_are_topology_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = runtime_artifacts.connector_credentials_path(
                "inesdata",
                "DEV",
                "pionera",
                "conn-org4-pionera",
                topology="vm-single",
                root=tmpdir,
            )

        self.assertEqual(
            path,
            Path(tmpdir)
            / "deployers"
            / "inesdata"
            / "deployments"
            / "DEV"
            / "vm-single"
            / "pionera"
            / "connectors"
            / "conn-org4-pionera"
            / "credentials.json",
        )

    def test_local_without_deployment_id_keeps_legacy_minio_policy_path(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {
                "PIONERA_DEPLOYMENT_ID": "",
                "PIONERA_RUNTIME_ARTIFACT_LAYOUT": "",
            },
        ):
            path = runtime_artifacts.connector_minio_policy_path(
                "inesdata",
                "DEV",
                "pionera",
                "conn-org2-pionera",
                topology="local",
                root=tmpdir,
            )

        self.assertEqual(
            path,
            Path(tmpdir)
            / "deployers"
            / "inesdata"
            / "deployments"
            / "DEV"
            / "pionera"
            / "policy-pionera-conn-org2-pionera.json",
        )

    def test_vm_distributed_minio_policy_is_topology_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = runtime_artifacts.connector_minio_policy_path(
                "inesdata",
                "DEV",
                "pionera",
                "conn-org2-pionera",
                topology="vm-distributed",
                root=tmpdir,
            )

        self.assertEqual(
            path,
            Path(tmpdir)
            / "deployers"
            / "inesdata"
            / "deployments"
            / "DEV"
            / "vm-distributed"
            / "pionera"
            / "connectors"
            / "conn-org2-pionera"
            / "policy.json",
        )

    def test_deployment_id_adds_an_extra_runtime_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"PIONERA_DEPLOYMENT_ID": "pionera4-single"},
        ):
            path = runtime_artifacts.vault_keys_path(
                "DEV",
                topology="vm-single",
                root=tmpdir,
            )

        self.assertEqual(
            path,
            Path(tmpdir)
            / "deployers"
            / "shared"
            / "deployments"
            / "DEV"
            / "vm-single"
            / "pionera4-single"
            / "common"
            / "init-keys-vault.json",
        )

    def test_vm_distributed_prefer_existing_does_not_read_legacy_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = (
                Path(tmpdir)
                / "deployers"
                / "shared"
                / "common"
                / "init-keys-vault.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text("{}\n", encoding="utf-8")

            path = runtime_artifacts.vault_keys_path(
                "DEV",
                topology="vm-distributed",
                root=tmpdir,
                prefer_existing=True,
            )

        self.assertEqual(
            path,
            Path(tmpdir)
            / "deployers"
            / "shared"
            / "deployments"
            / "DEV"
            / "vm-distributed"
            / "common"
            / "init-keys-vault.json",
        )

    def test_explicit_legacy_fallback_can_read_legacy_before_scoped_when_scoped_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"PIONERA_RUNTIME_ARTIFACT_LEGACY_FALLBACK": "true"},
        ):
            legacy_path = (
                Path(tmpdir)
                / "deployers"
                / "shared"
                / "common"
                / "init-keys-vault.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text("{}\n", encoding="utf-8")

            path = runtime_artifacts.vault_keys_path(
                "DEV",
                topology="vm-distributed",
                root=tmpdir,
                prefer_existing=True,
            )

        self.assertEqual(path, legacy_path)

    def test_vm_single_connector_credentials_ignore_legacy_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = (
                Path(tmpdir)
                / "deployers"
                / "inesdata"
                / "deployments"
                / "DEV"
                / "pionera"
                / "credentials-connector-conn-org4-pionera.json"
            )
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text("{}\n", encoding="utf-8")

            path = runtime_artifacts.connector_credentials_path(
                "inesdata",
                "DEV",
                "pionera",
                "conn-org4-pionera",
                topology="vm-single",
                root=tmpdir,
                prefer_existing=True,
            )

        self.assertEqual(
            path,
            Path(tmpdir)
            / "deployers"
            / "inesdata"
            / "deployments"
            / "DEV"
            / "vm-single"
            / "pionera"
            / "connectors"
            / "conn-org4-pionera"
            / "credentials.json",
        )


if __name__ == "__main__":
    unittest.main()
