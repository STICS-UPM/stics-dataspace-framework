import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.infrastructure import INESDataInfrastructureAdapter


class DeployerInfrastructureConfigLayeringTests(unittest.TestCase):
    def test_vault_token_sync_targets_shared_infrastructure_config_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infrastructure_config = os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config")
            adapter_config = os.path.join(tmpdir, "deployers", "edc", "deployer.config")
            os.makedirs(os.path.dirname(infrastructure_config), exist_ok=True)
            os.makedirs(os.path.dirname(adapter_config), exist_ok=True)
            with open(infrastructure_config, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=old\n")

            class Config:
                @staticmethod
                def infrastructure_deployer_config_path():
                    return infrastructure_config

                @staticmethod
                def deployer_config_path():
                    return adapter_config

            adapter = INESDataInfrastructureAdapter(
                run=lambda *_args, **_kwargs: None,
                run_silent=lambda *_args, **_kwargs: None,
                auto_mode_getter=lambda: True,
                config_cls=Config,
                config_adapter=object(),
            )

            self.assertEqual(adapter._vault_token_deployer_config_path(), infrastructure_config)

    def test_vault_token_sync_falls_back_to_adapter_config_when_shared_config_is_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infrastructure_config = os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config")
            adapter_config = os.path.join(tmpdir, "deployers", "edc", "deployer.config")

            class Config:
                @staticmethod
                def infrastructure_deployer_config_path():
                    return infrastructure_config

                @staticmethod
                def deployer_config_path():
                    return adapter_config

            adapter = INESDataInfrastructureAdapter(
                run=lambda *_args, **_kwargs: None,
                run_silent=lambda *_args, **_kwargs: None,
                auto_mode_getter=lambda: True,
                config_cls=Config,
                config_adapter=object(),
            )

            self.assertEqual(adapter._vault_token_deployer_config_path(), adapter_config)


if __name__ == "__main__":
    unittest.main()
