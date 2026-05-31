import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.vm_distributed_public_access import (
    build_vm_distributed_public_access_plan,
    render_public_access_summary,
    render_role_http_entrypoint_nginx,
    resolve_vm_distributed_public_urls,
)


class VmDistributedPublicAccessTests(unittest.TestCase):
    def test_resolve_public_urls_infers_org_defaults_from_domains(self):
        urls = resolve_vm_distributed_public_urls(
            {
                "DOMAIN_BASE": "common.example.test",
                "DS_DOMAIN_BASE": "dataspace.example.test",
            }
        )

        self.assertEqual(urls["VM_COMMON_PUBLIC_URL"], "https://org1.common.example.test")
        self.assertEqual(urls["VM_PROVIDER_PUBLIC_URL"], "https://org2.dataspace.example.test")
        self.assertEqual(urls["VM_CONSUMER_PUBLIC_URL"], "https://org3.dataspace.example.test")
        self.assertEqual(urls["KEYCLOAK_FRONTEND_URL"], "https://org1.common.example.test/auth")
        self.assertEqual(urls["MINIO_API_PUBLIC_URL"], "https://org1.common.example.test")
        self.assertEqual(urls["MINIO_CONSOLE_PUBLIC_URL"], "https://org1.common.example.test/s3-console")
        self.assertEqual(urls["COMPONENTS_PUBLIC_BASE_URL"], "https://org1.common.example.test")
        self.assertEqual(
            urls["PUBLIC_PORTAL_BACKEND_PUBLIC_URL"],
            "https://org1.common.example.test/public-portal-backend",
        )

    def test_resolve_public_urls_preserves_explicit_urls(self):
        urls = resolve_vm_distributed_public_urls(
            {
                "DOMAIN_BASE": "common.example.test",
                "DS_DOMAIN_BASE": "dataspace.example.test",
                "VM_COMMON_PUBLIC_URL": "https://platform.example.org",
                "VM_PROVIDER_PUBLIC_URL": "https://provider.example.org",
                "VM_CONSUMER_PUBLIC_URL": "https://consumer.example.org",
                "KEYCLOAK_FRONTEND_URL": "https://login.example.org",
                "MINIO_API_PUBLIC_URL": "https://s3.example.org",
                "MINIO_CONSOLE_PUBLIC_URL": "https://storage.example.org/console",
                "COMPONENTS_PUBLIC_BASE_URL": "https://components.example.org",
                "PUBLIC_PORTAL_BACKEND_PUBLIC_URL": "https://backend.example.org/portal-backend",
            }
        )

        self.assertEqual(urls["VM_COMMON_PUBLIC_URL"], "https://platform.example.org")
        self.assertEqual(urls["VM_PROVIDER_PUBLIC_URL"], "https://provider.example.org")
        self.assertEqual(urls["VM_CONSUMER_PUBLIC_URL"], "https://consumer.example.org")
        self.assertEqual(urls["KEYCLOAK_FRONTEND_URL"], "https://login.example.org")
        self.assertEqual(urls["MINIO_API_PUBLIC_URL"], "https://s3.example.org")
        self.assertEqual(urls["MINIO_CONSOLE_PUBLIC_URL"], "https://storage.example.org/console")
        self.assertEqual(urls["COMPONENTS_PUBLIC_BASE_URL"], "https://components.example.org")
        self.assertEqual(urls["PUBLIC_PORTAL_BACKEND_PUBLIC_URL"], "https://backend.example.org/portal-backend")

    def test_build_plan_uses_org_connectors_and_public_urls_from_config(self):
        plan = build_vm_distributed_public_access_plan(
            {
                "DS_1_NAME": "pionera",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_1_CONNECTORS": "org2,org3",
                "DS_1_CONNECTOR_NAMESPACES": "org2:provider,org3:consumer",
                "VM_PROVIDER_CONNECTORS": "org2",
                "VM_CONSUMER_CONNECTORS": "org3",
                "VM_COMMON_IP": "192.168.122.64",
                "VM_PROVIDER_IP": "192.168.122.134",
                "VM_CONSUMER_IP": "192.168.122.9",
                "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "VM_PROVIDER_PUBLIC_URL": "https://org2.pionera.oeg.fi.upm.es",
                "VM_CONSUMER_PUBLIC_URL": "https://org3.pionera.oeg.fi.upm.es",
                "K3S_INGRESS_HTTP_NODEPORT": "31667",
                "VM_PROVIDER_INGRESS_HTTP_PORT": "80",
                "VM_CONSUMER_INGRESS_HTTP_PORT": "80",
                "VM_PROVIDER_INGRESS_NODEPORT": "30096",
                "VM_CONSUMER_INGRESS_NODEPORT": "",
            }
        )

        self.assertEqual(plan.provider.public_hostname, "org2.pionera.oeg.fi.upm.es")
        self.assertEqual(plan.consumer.public_hostname, "org3.pionera.oeg.fi.upm.es")
        self.assertEqual(plan.provider.connectors[0].full_name, "conn-org2-pionera")
        self.assertEqual(plan.consumer.connectors[0].full_name, "conn-org3-pionera")
        self.assertEqual(
            plan.consumer.connectors[0].canonical_hostname,
            "conn-org3-pionera.pionera.oeg.fi.upm.es",
        )
        self.assertEqual(plan.consumer.listen_port, 80)
        self.assertEqual(plan.consumer.target_port, 31667)

        summary = render_public_access_summary(plan)
        self.assertIn("| consumer | https://org3.pionera.oeg.fi.upm.es | 192.168.122.9 | 80 | conn-org3-pionera |", summary)
        self.assertNotIn("31667", summary)

    def test_render_role_http_entrypoint_preserves_public_host_header(self):
        plan = build_vm_distributed_public_access_plan(
            {
                "DS_1_NAME": "pionera",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_1_CONNECTORS": "org2,org3",
                "DS_1_CONNECTOR_NAMESPACES": "org2:provider,org3:consumer",
                "VM_CONSUMER_IP": "192.168.122.9",
                "VM_CONSUMER_PUBLIC_URL": "https://org3.pionera.oeg.fi.upm.es",
                "K3S_INGRESS_HTTP_NODEPORT": "31667",
                "VM_CONSUMER_INGRESS_HTTP_PORT": "80",
                "VM_CONSUMER_INGRESS_NODEPORT": "",
            }
        )

        rendered = render_role_http_entrypoint_nginx(plan.consumer)

        self.assertIn("listen 80;", rendered)
        self.assertIn("server_name org3.pionera.oeg.fi.upm.es conn-org3-pionera.pionera.oeg.fi.upm.es;", rendered)
        self.assertIn("proxy_pass http://127.0.0.1:31667;", rendered)
        self.assertIn("proxy_set_header Host $host;", rendered)
        self.assertIn("proxy_set_header X-Forwarded-Proto https;", rendered)

    def test_build_plan_infers_missing_public_role_urls(self):
        plan = build_vm_distributed_public_access_plan(
            {
                "DOMAIN_BASE": "common.example.test",
                "DS_DOMAIN_BASE": "dataspace.example.test",
                "DS_1_NAME": "pionera",
                "DS_1_CONNECTORS": "org2,org3",
                "DS_1_CONNECTOR_NAMESPACES": "org2:provider,org3:consumer",
            }
        )

        self.assertEqual(plan.common.public_url, "https://org1.common.example.test")
        self.assertEqual(plan.provider.public_url, "https://org2.dataspace.example.test")
        self.assertEqual(plan.consumer.public_url, "https://org3.dataspace.example.test")


if __name__ == "__main__":
    unittest.main()
