import unittest
from unittest import mock

from validation.orchestration import hosts


class Level6HostsTests(unittest.TestCase):
    def test_connector_hosts_resolve_returns_unresolved_hosts(self):
        unresolved = hosts.connector_hosts_resolve(
            ["conn-a", "conn-b"],
            domain="example.local",
            resolver=mock.Mock(side_effect=[OSError("missing"), "127.0.0.1"]),
        )

        self.assertEqual(unresolved, ["conn-a.example.local"])

    def test_connector_hosts_resolve_skips_when_domain_is_missing(self):
        resolver = mock.Mock()

        unresolved = hosts.connector_hosts_resolve(
            ["conn-a"],
            domain="",
            resolver=resolver,
        )

        self.assertEqual(unresolved, [])
        resolver.assert_not_called()

    def test_ensure_connector_hosts_updates_hosts_before_resolution_failure(self):
        config_adapter = mock.Mock()
        config_adapter.generate_connector_hosts.return_value = [
            "127.0.0.1 conn-a.example.local",
            "127.0.0.1 conn-b.example.local",
        ]
        infrastructure_adapter = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "Connector hostnames do not resolve locally"):
            hosts.ensure_connector_hosts(
                ["conn-a", "conn-b"],
                config_adapter=config_adapter,
                infrastructure_adapter=infrastructure_adapter,
                domain="example.local",
                resolver=mock.Mock(side_effect=OSError("Name or service not known")),
            )

        infrastructure_adapter.manage_hosts_entries.assert_called_once_with(
            [
                "127.0.0.1 conn-a.example.local",
                "127.0.0.1 conn-b.example.local",
            ],
            header_comment="# Dataspace Connector Hosts",
        )

    def test_public_endpoint_check_accepts_any_http_response_as_reachable(self):
        class Response:
            status_code = 404

        result = hosts.ensure_public_endpoints_accessible(
            [{"label": "connector", "url": "http://conn-a.example.local"}],
            requester=mock.Mock(return_value=Response()),
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["checked"][0]["status_code"], 404)

    def test_public_endpoint_check_explains_minikube_tunnel_sudo_prompt(self):
        requester = mock.Mock(side_effect=OSError("connection refused"))

        with self.assertRaisesRegex(RuntimeError, "minikube tunnel") as exc:
            hosts.ensure_public_endpoints_accessible(
                [{"label": "Keycloak", "url": "http://keycloak.example.local"}],
                requester=requester,
                topology="local",
            )

        message = str(exc.exception)
        self.assertIn("[sudo] password", message)
        self.assertIn("does not collect", message)
        self.assertIn("Level 6 full validation still requires these public hostnames", message)
        self.assertIn("does not replace public ingress", message)

    def test_public_endpoint_check_skips_loopback_and_cluster_internal_urls(self):
        requester = mock.Mock()

        result = hosts.ensure_public_endpoints_accessible(
            [
                {"label": "local", "url": "http://localhost:8200"},
                {"label": "cluster", "url": "http://vault.common-srvs.svc:8200"},
            ],
            requester=requester,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["checked"], [])
        requester.assert_not_called()


if __name__ == "__main__":
    unittest.main()
