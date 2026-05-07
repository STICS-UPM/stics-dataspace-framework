import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.config import INESDataConfigAdapter


class ConnectorHostsConfig:
    DS_NAME = "demo"

    def __init__(self, root):
        self.root = root

    def deployer_config_path(self):
        return os.path.join(self.root, "deployer.config")


class ConnectorHostsTests(unittest.TestCase):
    def test_generate_hosts_includes_public_portal_endpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorHostsConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n")

            adapter = INESDataConfigAdapter(config)
            hosts = adapter.generate_hosts("demo")

            self.assertIn(
                "127.0.0.1 registration-service-demo.dev.ds.dataspaceunit.upm",
                hosts,
            )
            self.assertIn(
                "127.0.0.1 demo.dev.ds.dataspaceunit.upm",
                hosts,
            )
            self.assertIn(
                "127.0.0.1 backend-demo.dev.ds.dataspaceunit.upm",
                hosts,
            )

    def test_generate_connector_hosts_uses_ds_domain_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectorHostsConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n")

            adapter = INESDataConfigAdapter(config)
            hosts = adapter.generate_connector_hosts(["conn-a-demo", "conn-b-demo"])

            self.assertEqual(
                hosts,
                [
                    "127.0.0.1 conn-a-demo.dev.ds.dataspaceunit.upm",
                    "127.0.0.1 conn-b-demo.dev.ds.dataspaceunit.upm",
                ],
            )


if __name__ == "__main__":
    unittest.main()
