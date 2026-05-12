import importlib.util
import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_module(name, relative_path):
    module_path = os.path.join(ROOT_DIR, relative_path)
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inesdata_bootstrap = load_module(
    "inesdata_access_urls",
    os.path.join("deployers", "inesdata", "access_urls.py"),
)
edc_bootstrap = load_module(
    "edc_bootstrap_access_urls",
    os.path.join("deployers", "edc", "bootstrap.py"),
)


class DeployerAccessUrlsTests(unittest.TestCase):
    def test_registration_service_internal_hostname_keeps_short_name_in_compact_mode(self):
        hostname = inesdata_bootstrap.registration_service_internal_hostname(
            {
                "DS_1_NAME": "demo",
                "DS_1_NAMESPACE": "demo",
            },
            "demo",
            "DEV",
            connector_namespace="demo",
        )

        self.assertEqual(hostname, "demo-registration-service:8080")

    def test_registration_service_internal_hostname_uses_fqdn_when_namespace_differs(self):
        hostname = inesdata_bootstrap.registration_service_internal_hostname(
            {
                "DS_1_NAME": "demo",
                "DS_1_NAMESPACE": "demo",
                "NAMESPACE_PROFILE": "role-aligned",
            },
            "demo",
            "DEV",
            connector_namespace="demo",
        )

        self.assertEqual(
            hostname,
            "demo-registration-service.demo-core.svc.cluster.local:8080",
        )

    def test_inesdata_dataspace_access_urls_include_login_entrypoints(self):
        urls = inesdata_bootstrap.build_dataspace_access_urls(
            "demo",
            "DEV",
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "KEYCLOAK_HOSTNAME": "keycloak.dev.ed.dataspaceunit.upm",
                "KC_URL": "http://keycloak-admin.dev.ed.dataspaceunit.upm",
            },
        )

        self.assertEqual(urls["public_portal_login"], "http://demo.dev.ds.dataspaceunit.upm")
        self.assertEqual(urls["public_portal_backend_admin"], "http://backend-demo.dev.ds.dataspaceunit.upm/admin")
        self.assertEqual(urls["registration_service"], "http://registration-service-demo.dev.ds.dataspaceunit.upm")
        self.assertEqual(urls["keycloak_realm"], "http://auth.dev.ed.dataspaceunit.upm/realms/demo")
        self.assertEqual(urls["keycloak_admin_console"], "http://admin.auth.dev.ed.dataspaceunit.upm/admin/demo/console/")
        self.assertEqual(urls["minio_api"], "http://minio.dev.ed.dataspaceunit.upm")

    def test_inesdata_connector_access_urls_include_connector_interface_login(self):
        urls = inesdata_bootstrap.build_connector_access_urls(
            "conn-company-demo",
            "demo",
            "DEV",
            {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

        self.assertEqual(urls["connector_ingress"], "http://conn-company-demo.dev.ds.dataspaceunit.upm")
        self.assertEqual(
            urls["connector_interface_login"],
            "http://conn-company-demo.dev.ds.dataspaceunit.upm/inesdata-connector-interface/",
        )
        self.assertEqual(urls["connector_management_api"], "http://conn-company-demo.dev.ds.dataspaceunit.upm/management")
        self.assertEqual(urls["connector_protocol_api"], "http://conn-company-demo.dev.ds.dataspaceunit.upm/protocol")
        self.assertEqual(urls["minio_bucket"], "demo-conn-company-demo")

    def test_access_urls_preserve_explicit_keycloak_port(self):
        urls = inesdata_bootstrap.common_access_urls(
            "demo",
            "DEV",
            {"KC_URL": "http://localhost:8080", "KC_INTERNAL_URL": "http://localhost:8081"},
        )

        self.assertEqual(urls["keycloak_realm"], "http://localhost:8081/realms/demo")
        self.assertEqual(urls["keycloak_admin_console"], "http://localhost:8080/admin/demo/console/")
        self.assertEqual(urls["minio_api"], "http://minio.dev.ed.dataspaceunit.upm")

    def test_edc_connector_access_urls_include_dashboard_oidc_login_when_enabled(self):
        urls = edc_bootstrap.build_connector_access_urls(
            {
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "EDC_DASHBOARD_ENABLED": "true",
                "EDC_DASHBOARD_PROXY_AUTH_MODE": "oidc-bff",
                "EDC_DASHBOARD_BASE_HREF": "edc-dashboard",
            },
            "conn-companyedc-demoedc",
            "demoedc",
            "DEV",
        )

        self.assertEqual(urls["connector_ingress"], "http://conn-companyedc-demoedc.dev.ds.dataspaceunit.upm")
        self.assertEqual(
            urls["edc_dashboard_login"],
            "http://conn-companyedc-demoedc.dev.ds.dataspaceunit.upm/edc-dashboard/",
        )
        self.assertEqual(
            urls["edc_dashboard_oidc_login"],
            "http://conn-companyedc-demoedc.dev.ds.dataspaceunit.upm/edc-dashboard-api/auth/login",
        )
        self.assertEqual(
            urls["connector_management_api_v3"],
            "http://conn-companyedc-demoedc.dev.ds.dataspaceunit.upm/management/v3",
        )
        self.assertEqual(urls["minio_bucket"], "demoedc-conn-companyedc-demoedc")


if __name__ == "__main__":
    unittest.main()
