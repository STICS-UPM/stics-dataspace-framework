import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


class EdcDashboardProxyRewriteTests(unittest.TestCase):
    def _load_proxy_module(self, tmpdir):
        config_path = Path(tmpdir) / "proxy-config.json"
        auth_path = Path(tmpdir) / "proxy-auth.json"
        config_path.write_text(
            json.dumps(
                {
                    "connectors": [
                        {
                            "connectorName": "conn-companyedc-pionera-edc",
                            "managementTarget": "http://management.internal/management",
                            "defaultTarget": "http://api.internal/api",
                            "controlTarget": "http://control.internal/control",
                            "protocolTarget": "http://protocol.internal/protocol",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        auth_path.write_text(json.dumps({"connectors": []}), encoding="utf-8")

        previous_config = os.environ.get("PROXY_CONFIG_FILE")
        previous_auth = os.environ.get("PROXY_AUTH_FILE")
        os.environ["PROXY_CONFIG_FILE"] = str(config_path)
        os.environ["PROXY_AUTH_FILE"] = str(auth_path)
        try:
            module_path = (
                Path(__file__).resolve().parents[1]
                / "adapters"
                / "edc"
                / "build"
                / "dashboard-proxy"
                / "server.py"
            )
            module_name = f"edc_dashboard_proxy_test_{id(self)}"
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        finally:
            if previous_config is None:
                os.environ.pop("PROXY_CONFIG_FILE", None)
            else:
                os.environ["PROXY_CONFIG_FILE"] = previous_config
            if previous_auth is None:
                os.environ.pop("PROXY_AUTH_FILE", None)
            else:
                os.environ["PROXY_AUTH_FILE"] = previous_auth

    def test_rewrites_connector_proxy_url_with_vm_single_public_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            module = self._load_proxy_module(tmpdir)
            handler = object.__new__(module.DashboardProxyHandler)

            result = handler._rewrite_dashboard_proxy_url(
                "/c/companyedc/edc-dashboard-api/connectors/"
                "conn-companyedc-pionera-edc/protocol"
            )

        self.assertEqual(result, "http://protocol.internal/protocol")

    def test_rewrites_absolute_connector_proxy_url_with_public_prefix_and_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            module = self._load_proxy_module(tmpdir)
            handler = object.__new__(module.DashboardProxyHandler)

            result = handler._rewrite_dashboard_proxy_url(
                "https://org4.example.test/c/companyedc/edc-dashboard-api/connectors/"
                "conn-companyedc-pionera-edc/api/filter/catalog?profile=daimo"
            )

        self.assertEqual(result, "http://api.internal/api/filter/catalog?profile=daimo")

    def test_keeps_legacy_connector_proxy_url_rewrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            module = self._load_proxy_module(tmpdir)
            handler = object.__new__(module.DashboardProxyHandler)

            result = handler._rewrite_dashboard_proxy_url(
                "/edc-dashboard-api/connectors/conn-companyedc-pionera-edc/management/v3/assets"
            )

        self.assertEqual(result, "http://management.internal/management/v3/assets")

    def test_leaves_non_connector_proxy_url_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            module = self._load_proxy_module(tmpdir)
            handler = object.__new__(module.DashboardProxyHandler)

            result = handler._rewrite_dashboard_proxy_url(
                "/c/companyedc/edc-dashboard-api/components/ontology-hub"
            )

        self.assertEqual(result, "/c/companyedc/edc-dashboard-api/components/ontology-hub")


if __name__ == "__main__":
    unittest.main()
