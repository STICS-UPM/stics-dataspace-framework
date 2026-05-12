import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEPLOYER_PATH = os.path.join(ROOT_DIR, "deployers", "edc", "bootstrap.py")

spec = importlib.util.spec_from_file_location("edc_native_deployer", DEPLOYER_PATH)
edc_native_deployer = importlib.util.module_from_spec(spec)
sys.modules["edc_native_deployer"] = edc_native_deployer
spec.loader.exec_module(edc_native_deployer)


class EdcNativeDeployerTests(unittest.TestCase):
    def test_keycloak_certificate_upload_declares_pem_keystore_format(self):
        admin = edc_native_deployer.KeycloakAdmin.__new__(edc_native_deployer.KeycloakAdmin)
        admin.base_url = "http://keycloak.local"
        admin.realm = "edcisotest"
        admin.token = "admin-token"
        admin.request = mock.Mock(return_value=mock.Mock(json=lambda: [{"id": "internal-client-id"}]))

        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "connector-public.crt")
            with open(cert_path, "w", encoding="utf-8") as handle:
                handle.write("-----BEGIN CERTIFICATE-----\nMIID\n-----END CERTIFICATE-----\n")

            response = mock.Mock(status_code=200, text="")
            with mock.patch.object(edc_native_deployer.requests, "post", return_value=response) as post_mock:
                admin.ensure_client("conn-cityedciso-edcisotest", edc_native_deployer.Path(cert_path))

        post_mock.assert_called_once()
        kwargs = post_mock.call_args.kwargs
        self.assertEqual(kwargs["data"], {"keystoreFormat": "Certificate PEM"})
        self.assertIn("file", kwargs["files"])


if __name__ == "__main__":
    unittest.main()
