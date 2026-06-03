import os
import sys
import unittest
from urllib.parse import urljoin
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.inesdata import bootstrap


class FakeCursor:
    def __init__(self, fetch_results):
        self.fetch_results = list(fetch_results)
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if not self.fetch_results:
            return None
        return self.fetch_results.pop(0)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.closed = False
        self.isolation_level = None

    def set_isolation_level(self, isolation_level):
        self.isolation_level = isolation_level

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def query_text(query):
    return repr(query)


class InesdataBootstrapDatabaseTests(unittest.TestCase):
    def test_connector_participant_urls_use_public_ingress_in_dev(self):
        protocol_url, shared_url = bootstrap.connector_participant_urls(
            {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            "conn-citycouncil-pionera",
            "pionera",
            "DEV",
        )

        self.assertEqual(
            protocol_url,
            "http://conn-citycouncil-pionera.dev.ds.dataspaceunit.upm/protocol",
        )
        self.assertEqual(
            shared_url,
            "http://conn-citycouncil-pionera.dev.ds.dataspaceunit.upm/shared",
        )

    def test_connector_public_access_urls_use_vm_single_root_path_routes(self):
        urls = bootstrap.build_connector_public_access_urls(
            "conn-org2-pionera",
            "pionera",
            "DEV",
            {
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            },
        )

        self.assertEqual(urls["connector_ingress"], "https://org4.pionera.oeg.fi.upm.es/c/org2")
        self.assertEqual(
            urls["connector_interface_login"],
            "https://org4.pionera.oeg.fi.upm.es/c/org2/inesdata-connector-interface/",
        )
        self.assertEqual(urls["keycloak_realm"], "https://org4.pionera.oeg.fi.upm.es/auth/realms/pionera")
        self.assertEqual(urls["minio_console"], "https://org4.pionera.oeg.fi.upm.es/s3-console/")

    def test_connector_participant_urls_use_vm_single_public_root_path_routes(self):
        protocol_url, shared_url = bootstrap.connector_participant_urls(
            {
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            },
            "conn-org2-pionera",
            "pionera",
            "DEV",
        )

        self.assertEqual(
            protocol_url,
            "https://org4.pionera.oeg.fi.upm.es/c/org2/protocol",
        )
        self.assertEqual(
            shared_url,
            "https://org4.pionera.oeg.fi.upm.es/c/org2/shared",
        )

    def test_connector_participant_urls_use_vm_distributed_public_routes(self):
        protocol_url, shared_url = bootstrap.connector_participant_urls(
            {
                "TOPOLOGY": "vm-distributed",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "VM_PROVIDER_CONNECTORS": "org2",
            },
            "conn-org2-pionera",
            "pionera",
            "DEV",
        )

        self.assertEqual(protocol_url, "https://org2.pionera.oeg.fi.upm.es/protocol")
        self.assertEqual(shared_url, "https://org2.pionera.oeg.fi.upm.es/shared")

    def test_connector_participant_urls_keep_production_pattern(self):
        protocol_url, shared_url = bootstrap.connector_participant_urls(
            {},
            "conn-citycouncil",
            "pionera",
            "PRO",
        )

        self.assertEqual(
            protocol_url,
            "https://conn-citycouncil-pionera.ds.dataspaceunit-project.eu/protocol",
        )
        self.assertEqual(
            shared_url,
            "https://conn-citycouncil-pionera.ds.dataspaceunit-project.eu/shared",
        )

    def test_keycloak_frontend_url_from_config_uses_explicit_base_url(self):
        frontend_url = bootstrap.keycloak_frontend_url_from_config(
            {"KEYCLOAK_FRONTEND_URL": "https://auth.example.test/"},
            "pionera",
        )

        self.assertEqual(frontend_url, "https://auth.example.test")

    def test_keycloak_frontend_url_from_config_preserves_proxy_path(self):
        frontend_url = bootstrap.keycloak_frontend_url_from_config(
            {"KEYCLOAK_FRONTEND_URL": "https://org1.example.test/auth/"},
            "pionera",
        )

        self.assertEqual(frontend_url, "https://org1.example.test/auth")

    def test_keycloak_client_base_url_preserves_proxy_path_for_python_keycloak(self):
        client_base_url = bootstrap.keycloak_client_base_url(
            "https://org1.example.test/auth"
        )

        self.assertEqual(client_base_url, "https://org1.example.test/auth/")
        self.assertEqual(
            urljoin(client_base_url, "realms/master/protocol/openid-connect/token"),
            "https://org1.example.test/auth/realms/master/protocol/openid-connect/token",
        )

    def test_keycloak_frontend_url_from_config_normalizes_realm_url(self):
        frontend_url = bootstrap.keycloak_frontend_url_from_config(
            {"KEYCLOAK_FRONTEND_URL": "https://auth.example.test/realms/pionera"},
            "pionera",
        )

        self.assertEqual(frontend_url, "https://auth.example.test")

    def test_keycloak_frontend_url_from_config_derives_vm_distributed_public_url(self):
        frontend_url = bootstrap.keycloak_frontend_url_from_config(
            {
                "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "KEYCLOAK_HOSTNAME": "auth.pionera.oeg.fi.upm.es",
            },
            "pionera",
        )

        self.assertEqual(frontend_url, "https://org1.pionera.oeg.fi.upm.es/auth")

    def test_keycloak_frontend_url_from_config_ignores_vm_placeholder_public_url(self):
        frontend_url = bootstrap.keycloak_frontend_url_from_config(
            {
                "TOPOLOGY": "vm-distributed",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "KEYCLOAK_FRONTEND_URL": "https://org1.dev.ed.dataspaceunit.upm/auth",
            },
            "pionera",
        )

        self.assertEqual(frontend_url, "https://org1.pionera.oeg.fi.upm.es/auth")

    def test_keycloak_management_url_from_config_does_not_infer_vm_org_url_for_local(self):
        management_url = bootstrap.keycloak_management_url_from_config(
            {
                "TOPOLOGY": "local",
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "KC_URL": "http://admin.auth.dev.ed.dataspaceunit.upm",
                "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "KEYCLOAK_HOSTNAME": "auth.dev.ed.dataspaceunit.upm",
            },
            "http://localhost:8080",
        )

        self.assertEqual(management_url, "http://admin.auth.dev.ed.dataspaceunit.upm")

    def test_keycloak_management_url_from_config_prefers_public_frontend_url(self):
        management_url = bootstrap.keycloak_management_url_from_config(
            {
                "KC_URL": "http://admin.auth.pionera.oeg.fi.upm.es",
                "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
            },
            "http://localhost:8080",
        )

        self.assertEqual(management_url, "https://org1.pionera.oeg.fi.upm.es/auth")

    def test_common_access_urls_use_public_org1_routes_for_vm_distributed(self):
        urls = bootstrap.common_access_urls(
            "pionera",
            "DEV",
            {
                "TOPOLOGY": "vm-distributed",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            },
        )

        self.assertEqual(
            urls["keycloak_realm"],
            "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera",
        )
        self.assertEqual(
            urls["keycloak_admin_console"],
            "https://org1.pionera.oeg.fi.upm.es/auth/admin/pionera/console/",
        )
        self.assertEqual(urls["minio_api"], "https://org1.pionera.oeg.fi.upm.es")
        self.assertEqual(urls["minio_console"], "https://org1.pionera.oeg.fi.upm.es/s3-console/")

    def test_dataspace_access_urls_omit_unconfigured_legacy_routes_for_vm_distributed(self):
        urls = bootstrap.build_dataspace_access_urls(
            "pionera",
            "DEV",
            {
                "TOPOLOGY": "vm-distributed",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            },
        )

        self.assertNotIn("public_portal_login", urls)
        self.assertEqual(
            urls["public_portal_backend_admin"],
            "https://org1.pionera.oeg.fi.upm.es/public-portal-backend/admin",
        )
        self.assertNotIn("registration_service", urls)
        self.assertEqual(urls["keycloak_realm"], "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera")

    def test_keycloak_frontend_url_from_config_keeps_public_hostname_proxy_path(self):
        frontend_url = bootstrap.keycloak_frontend_url_from_config(
            {"PUBLIC_HOSTNAME": "gateway.example.test"},
            "pionera",
        )

        self.assertEqual(frontend_url, "https://gateway.example.test/auth")

    def test_connector_runtime_vault_url_falls_back_to_cluster_service(self):
        vault_url = bootstrap.connector_runtime_vault_url(
            {"COMMON_SERVICES_NAMESPACE": "shared-foundation"}
        )

        self.assertEqual(vault_url, "http://common-srvs-vault.shared-foundation.svc:8200")

    def test_connector_runtime_vault_url_preserves_explicit_value(self):
        vault_url = bootstrap.connector_runtime_vault_url(
            {"VAULT_URL": "http://vault.internal.example:8200/"}
        )

        self.assertEqual(vault_url, "http://vault.internal.example:8200")

    def test_connector_runtime_database_hostname_falls_back_to_cluster_service(self):
        hostname = bootstrap.connector_runtime_database_hostname(
            {"COMMON_SERVICES_NAMESPACE": "shared-foundation"}
        )

        self.assertEqual(hostname, "common-srvs-postgresql.shared-foundation.svc")

    def test_register_connector_database_inserts_public_ingress_urls_for_dev(self):
        cursor = FakeCursor(fetch_results=[])
        connection = FakeConnection(cursor)

        with (
            mock.patch("deployers.inesdata.bootstrap.psycopg2.connect", return_value=connection),
            mock.patch(
                "deployers.inesdata.bootstrap.load_effective_deployer_config",
                return_value={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            ),
        ):
            bootstrap.register_connector_database(
                "postgres",
                "secret",
                "localhost",
                "5432",
                "pionera_rs",
                "conn-citycouncil-pionera",
                "pionera",
                "DEV",
            )

        rendered_queries = "\n".join(query_text(query) for query, _params in cursor.executed)
        self.assertIn("DELETE FROM public.edc_participant", rendered_queries)
        self.assertIn("http://conn-citycouncil-pionera.dev.ds.dataspaceunit.upm/protocol", rendered_queries)
        self.assertIn("http://conn-citycouncil-pionera.dev.ds.dataspaceunit.upm/shared", rendered_queries)
        self.assertNotIn("http://conn-citycouncil-pionera:19194/protocol", rendered_queries)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_register_connector_database_reconciles_vm_single_public_participant_urls(self):
        cursor = FakeCursor(fetch_results=[])
        connection = FakeConnection(cursor)

        with (
            mock.patch("deployers.inesdata.bootstrap.psycopg2.connect", return_value=connection),
            mock.patch(
                "deployers.inesdata.bootstrap.load_effective_deployer_config",
                return_value={
                    "TOPOLOGY": "vm-single",
                    "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                    "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                    "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                },
            ),
        ):
            bootstrap.register_connector_database(
                "postgres",
                "secret",
                "localhost",
                "5432",
                "pionera_rs",
                "conn-org2-pionera",
                "pionera",
                "DEV",
            )

        rendered_queries = "\n".join(query_text(query) for query, _params in cursor.executed)
        self.assertIn("DELETE FROM public.edc_participant", rendered_queries)
        self.assertIn("https://org4.pionera.oeg.fi.upm.es/c/org2/protocol", rendered_queries)
        self.assertIn("https://org4.pionera.oeg.fi.upm.es/c/org2/shared", rendered_queries)
        self.assertNotIn("http://conn-org2-pionera.pionera.oeg.fi.upm.es/protocol", rendered_queries)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_create_database_reuses_existing_role_and_database(self):
        cursor = FakeCursor(fetch_results=[(1,), (1,)])
        connection = FakeConnection(cursor)

        with mock.patch("deployers.inesdata.bootstrap.psycopg2.connect", return_value=connection):
            bootstrap.create_database(
                "postgres",
                "secret",
                "localhost",
                "5432",
                "demoedc_rs",
                "demoedc_rsusr",
                "new-password",
            )

        rendered_queries = "\n".join(query_text(query) for query, _params in cursor.executed)
        self.assertIn("ALTER ROLE", rendered_queries)
        self.assertNotIn("CREATE ROLE", rendered_queries)
        self.assertNotIn("CREATE DATABASE", rendered_queries)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_create_database_creates_missing_role_and_database(self):
        cursor = FakeCursor(fetch_results=[None, None])
        connection = FakeConnection(cursor)

        with mock.patch("deployers.inesdata.bootstrap.psycopg2.connect", return_value=connection):
            bootstrap.create_database(
                "postgres",
                "secret",
                "localhost",
                "5432",
                "demoedc_rs",
                "demoedc_rsusr",
                "new-password",
            )

        rendered_queries = "\n".join(query_text(query) for query, _params in cursor.executed)
        self.assertIn("CREATE ROLE", rendered_queries)
        self.assertIn("CREATE DATABASE", rendered_queries)
        self.assertIn("ALTER DATABASE", rendered_queries)
        self.assertIn("GRANT ALL PRIVILEGES", rendered_queries)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
