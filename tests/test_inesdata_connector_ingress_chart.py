import os
import shutil
import subprocess
import tempfile
import unittest

import yaml


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHART_DIR = os.path.join(REPO_ROOT, "deployers", "inesdata", "connector")


@unittest.skipUnless(shutil.which("helm"), "helm binary is required for chart rendering tests")
class InesdataConnectorIngressChartTests(unittest.TestCase):
    def _render_ingress(self):
        values = {
            "connector": {
                "name": "conn-org2-pionera",
                "dataspace": "pionera",
                "environment": "dev",
                "image": {
                    "name": "example/inesdata-connector",
                    "tag": "test",
                },
                "replicas": 1,
                "jvmArgs": "",
                "configuration": {
                    "configFilePath": "/opt/connector/config/connector-configuration.properties",
                    "vaultPath": "/tmp/vault.properties",
                },
                "ingress": {
                    "hostname": "org2.pionera.oeg.fi.upm.es",
                },
                "minio": {
                    "accesskey": "pionera/conn-org2-pionera/aws-access-key",
                    "secretkey": "pionera/conn-org2-pionera/aws-secret-key",
                },
                "modelExecution": {
                    "edrAttempts": 90,
                    "edrDelayMs": 1000,
                },
                "oauth2": {
                    "allowedRole1": "connector-admin",
                    "allowedRole2": "connector-management",
                    "allowedRole3": "connector-user",
                    "client": "conn-org2-pionera",
                    "privatekey": "pionera/conn-org2-pionera/private-key",
                    "publickey": "pionera/conn-org2-pionera/public-key",
                },
                "transfer": {
                    "privatekey": "pionera/conn-org2-pionera/private-key",
                    "publickey": "pionera/conn-org2-pionera/public-key",
                },
            },
            "connectorInterface": {
                "image": {
                    "name": "example/inesdata-connector-interface",
                    "tag": "test",
                },
                "branding": {},
                "ontologyHub": {
                    "url": "http://ontology-hub-pionera.example.org",
                },
                "modelObserver": {
                    "strapiUrl": "http://backend-pionera.example.org",
                    "proxyTarget": "http://backend-pionera.example.org",
                },
                "oauth2": {
                    "client": "dataspace-users",
                    "type": "code",
                    "scope": "openid profile email",
                },
            },
            "services": {
                "db": {
                    "hostname": "postgresql.example.svc",
                    "name": "connector_db",
                    "user": "connector_user",
                    "password": "connector_password",
                },
                "keycloak": {
                    "hostname": "keycloak.example.svc",
                    "external": "org1.pionera.oeg.fi.upm.es",
                    "protocol": "http",
                },
                "minio": {
                    "hostname": "minio.example.svc",
                    "bucket": "pionera-conn-org2-pionera",
                    "protocol": "http",
                },
                "registrationService": {
                    "hostname": "pionera-registration-service:8080",
                    "protocol": "http",
                },
                "vault": {
                    "url": "http://vault.example.svc:8200",
                    "token": "test-token",
                    "path": "pionera/conn-org2-pionera/",
                },
            },
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as handle:
            yaml.safe_dump(values, handle, sort_keys=False)
            values_file = handle.name

        try:
            rendered = subprocess.run(
                [
                    "helm",
                    "template",
                    "conn-org2-pionera",
                    CHART_DIR,
                    "-f",
                    values_file,
                    "--show-only",
                    "templates/connector-ingress.yaml",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            os.unlink(values_file)

        return yaml.safe_load(rendered.stdout)

    def test_connector_ingress_does_not_force_ssl_redirect_behind_public_proxy(self):
        ingress = self._render_ingress()

        self.assertEqual(ingress["kind"], "Ingress")
        self.assertEqual(ingress["metadata"]["annotations"]["nginx.ingress.kubernetes.io/ssl-redirect"], "false")
        self.assertEqual(
            ingress["metadata"]["annotations"]["nginx.ingress.kubernetes.io/force-ssl-redirect"],
            "false",
        )
