import os
import sys
import unittest
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
        self.assertIn("http://conn-citycouncil-pionera.dev.ds.dataspaceunit.upm/protocol", rendered_queries)
        self.assertIn("http://conn-citycouncil-pionera.dev.ds.dataspaceunit.upm/shared", rendered_queries)
        self.assertNotIn("http://conn-citycouncil-pionera:19194/protocol", rendered_queries)
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
