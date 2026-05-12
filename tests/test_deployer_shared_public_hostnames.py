import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.public_hostnames import (
    canonical_common_service_config_values,
    resolved_common_service_hostnames,
    resolved_common_service_urls,
)


class SharedPublicHostnamesTests(unittest.TestCase):
    def test_resolved_common_service_hostnames_promote_legacy_keycloak_aliases(self):
        resolved = resolved_common_service_hostnames(
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KEYCLOAK_HOSTNAME": "keycloak.dev.ed.dataspaceunit.upm",
                "KEYCLOAK_ADMIN_HOSTNAME": "keycloak-admin.dev.ed.dataspaceunit.upm",
            }
        )

        self.assertEqual(resolved["keycloak_hostname"], "auth.dev.ed.dataspaceunit.upm")
        self.assertEqual(resolved["keycloak_admin_hostname"], "admin.auth.dev.ed.dataspaceunit.upm")
        self.assertEqual(resolved["minio_hostname"], "minio.dev.ed.dataspaceunit.upm")
        self.assertEqual(resolved["minio_console_hostname"], "console.minio-s3.dev.ed.dataspaceunit.upm")

    def test_resolved_common_service_hostnames_ignore_cluster_internal_keycloak_urls(self):
        resolved = resolved_common_service_hostnames(
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KC_INTERNAL_URL": "http://common-srvs-keycloak.common-srvs.svc.cluster.local",
                "KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm",
            }
        )

        self.assertEqual(resolved["keycloak_hostname"], "auth.dev.ed.dataspaceunit.upm")
        self.assertEqual(resolved["keycloak_admin_hostname"], "admin.auth.dev.ed.dataspaceunit.upm")

    def test_resolved_common_service_urls_preserve_explicit_localhost_ports(self):
        resolved = resolved_common_service_urls(
            {
                "KC_INTERNAL_URL": "http://localhost:8081",
                "KC_URL": "http://localhost:8080",
            }
        )

        self.assertEqual(resolved["KC_INTERNAL_URL"], "http://localhost:8081")
        self.assertEqual(resolved["KC_URL"], "http://localhost:8080")

    def test_resolved_common_service_urls_promote_legacy_public_kc_url(self):
        resolved = resolved_common_service_urls(
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KC_INTERNAL_URL": "http://common-srvs-keycloak.common-srvs.svc.cluster.local",
                "KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm",
            }
        )

        self.assertEqual(
            resolved["KC_URL"],
            "http://auth.dev.ed.dataspaceunit.upm",
        )

    def test_canonical_common_service_config_values_use_canonical_keycloak_names(self):
        values = canonical_common_service_config_values("dev.ed.dataspaceunit.upm")

        self.assertEqual(values["KC_INTERNAL_URL"], "http://auth.dev.ed.dataspaceunit.upm")
        self.assertEqual(values["KC_URL"], "http://admin.auth.dev.ed.dataspaceunit.upm")
        self.assertEqual(values["KEYCLOAK_HOSTNAME"], "auth.dev.ed.dataspaceunit.upm")
        self.assertEqual(values["KEYCLOAK_ADMIN_HOSTNAME"], "admin.auth.dev.ed.dataspaceunit.upm")


if __name__ == "__main__":
    unittest.main()
