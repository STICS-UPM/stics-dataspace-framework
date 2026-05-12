import os
import sys
import unittest
from unittest import mock

import click
from click.testing import CliRunner

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.inesdata import bootstrap


class InesdataBootstrapVaultPreflightTests(unittest.TestCase):
    def test_validate_vault_management_access_rejects_invalid_token(self):
        response = mock.Mock(status_code=403)

        with mock.patch("deployers.inesdata.bootstrap.requests.get", return_value=response):
            with self.assertRaises(click.ClickException) as ctx:
                bootstrap.validate_vault_management_access(
                    "stale-token",
                    "http://vault.local:8200",
                    "conn-citycouncil-demo",
                    "demo",
                )

        self.assertIn("token is not valid", str(ctx.exception))

    def test_create_connector_vault_runs_preflight_before_hvac_side_effects(self):
        with (
            mock.patch(
                "deployers.inesdata.bootstrap.validate_vault_management_access",
                side_effect=click.ClickException("Vault preflight failed"),
            ) as preflight,
            mock.patch("deployers.inesdata.bootstrap.hvac.Client") as hvac_client,
        ):
            with self.assertRaises(click.ClickException):
                bootstrap.create_connector_vault(
                    "stale-token",
                    "http://vault.local:8200",
                    "conn-citycouncil-demo",
                    "demo",
                    "DEV",
                )

        preflight.assert_called_once()
        hvac_client.assert_not_called()

    def test_connector_create_aborts_before_side_effects_when_vault_preflight_fails(self):
        runner = CliRunner()

        with (
            mock.patch(
                "deployers.inesdata.bootstrap.validate_vault_management_access",
                side_effect=click.ClickException("Vault preflight failed"),
            ) as preflight,
            mock.patch("deployers.inesdata.bootstrap.create_password_file") as create_password_file,
        ):
            result = runner.invoke(
                bootstrap.cli,
                ["connector", "create", "conn-citycouncil-demo", "demo"],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Vault preflight failed", result.output)
        preflight.assert_called_once()
        create_password_file.assert_not_called()

    def test_validate_vault_management_access_accepts_root_capabilities(self):
        lookup = mock.Mock(status_code=200)
        capabilities = mock.Mock(
            status_code=200,
            json=lambda: {
                "capabilities": {
                    "sys/policy/conn-citycouncil-demo-secrets-policy": ["root"],
                    "sys/policies/acl/conn-citycouncil-demo-secrets-policy": ["root"],
                    "auth/token/create": ["root"],
                    "secret/data/demo/conn-citycouncil-demo/public-key": ["root"],
                }
            },
        )

        with (
            mock.patch("deployers.inesdata.bootstrap.requests.get", return_value=lookup),
            mock.patch("deployers.inesdata.bootstrap.requests.post", return_value=capabilities),
        ):
            bootstrap.validate_vault_management_access(
                "root-token",
                "http://vault.local:8200",
                "conn-citycouncil-demo",
                "demo",
            )


if __name__ == "__main__":
    unittest.main()
