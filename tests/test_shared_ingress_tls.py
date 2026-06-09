import json
import os
import tempfile
import unittest
from unittest import mock

from deployers.shared.lib.ingress_tls import (
    VMIngressTLSReconciler,
    configured_hostnames,
    ingress_redirect_annotation_patch,
    ingress_tls_patch,
    vm_ingress_tls_enabled,
)


class SharedIngressTLSTests(unittest.TestCase):
    def test_vm_ingress_tls_defaults_enabled_only_for_vm_topologies(self):
        self.assertTrue(vm_ingress_tls_enabled({}, "vm-single"))
        self.assertTrue(vm_ingress_tls_enabled({}, "vm-distributed"))
        self.assertFalse(vm_ingress_tls_enabled({}, "local"))
        self.assertFalse(vm_ingress_tls_enabled({"VM_INGRESS_TLS_ENABLED": "false"}, "vm-distributed"))

    def test_configured_hostnames_collects_public_urls_and_host_lists(self):
        hosts = configured_hostnames(
            {
                "KEYCLOAK_FRONTEND_URL": "https://org1.example.test/auth",
                "VM_PROVIDER_PUBLIC_URL": "https://org2.example.test",
                "VM_INGRESS_TLS_HOSTS": "org3.example.test, https://org4.example.test/path",
            }
        )

        self.assertEqual(
            hosts,
            [
                "org1.example.test",
                "org2.example.test",
                "org3.example.test",
                "org4.example.test",
            ],
        )

    def test_ingress_tls_patch_uses_shared_secret(self):
        self.assertEqual(
            ingress_tls_patch(["org2.example.test", "org3.example.test"], "shared-tls"),
            {
                "spec": {
                    "tls": [
                        {
                            "hosts": ["org2.example.test", "org3.example.test"],
                            "secretName": "shared-tls",
                        }
                    ]
                }
            },
        )
        self.assertEqual(
            ingress_redirect_annotation_patch()["metadata"]["annotations"],
            {
                "nginx.ingress.kubernetes.io/ssl-redirect": "false",
                "nginx.ingress.kubernetes.io/force-ssl-redirect": "false",
            },
        )

    def test_reconciler_patches_public_ingresses_and_creates_shared_secrets(self):
        ingress_payload = {
            "items": [
                {
                    "metadata": {"namespace": "edc-provider", "name": "connector-ingress"},
                    "spec": {"rules": [{"host": "org2.example.test"}]},
                },
                {
                    "metadata": {"namespace": "kube-system", "name": "internal"},
                    "spec": {"rules": [{"host": "service.namespace.svc.cluster.local"}]},
                },
            ]
        }
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            return "ok"

        def fake_run_silent(command, **_kwargs):
            if "get ingress -A -o json" in command:
                return json.dumps(ingress_payload)
            return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            cert = os.path.join(tmpdir, "tls.crt")
            key = os.path.join(tmpdir, "tls.key")
            with open(cert, "w", encoding="utf-8") as handle:
                handle.write("CERT")
            with open(key, "w", encoding="utf-8") as handle:
                handle.write("KEY")

            reconciler = VMIngressTLSReconciler(
                config={
                    "DOMAIN_BASE": "example.test",
                    "VM_INGRESS_TLS_CERT_FILE": cert,
                    "VM_INGRESS_TLS_KEY_FILE": key,
                    "VM_INGRESS_TLS_TRUSTSTORE_ENABLED": "false",
                },
                topology="vm-distributed",
                cluster_runtime={
                    "k3s_kubeconfig_common": "/tmp/common.yaml",
                    "k3s_kubeconfig_provider": "/tmp/provider.yaml",
                    "k3s_kubeconfig_consumer": "/tmp/provider.yaml",
                },
                run=fake_run,
                run_silent=fake_run_silent,
                artifact_dir=tmpdir,
            )

            result = reconciler.reconcile()

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["hosts"], ["org2.example.test"])
        self.assertEqual(result["namespaces"], ["edc-provider"])
        self.assertEqual(result["ingresses"], 2)
        self.assertTrue(any("apply -f" in command for command in commands))
        patch_commands = [command for command in commands if " patch ingress/" in command]
        self.assertEqual(len(patch_commands), 4)
        self.assertTrue(all("org2.example.test" in command for command in patch_commands[0::2]))

    @mock.patch("deployers.shared.lib.ingress_tls.subprocess.run")
    def test_reconciler_generates_dev_certificate_when_no_files_are_configured(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stderr="", stdout="")
        ingress_payload = {
            "items": [
                {
                    "metadata": {"namespace": "common-srvs", "name": "keycloak"},
                    "spec": {"rules": [{"host": "org1.example.test"}]},
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            reconciler = VMIngressTLSReconciler(
                config={
                    "DOMAIN_BASE": "example.test",
                    "DS_1_NAME": "demo",
                    "VM_INGRESS_TLS_TRUSTSTORE_ENABLED": "false",
                },
                topology="vm-single",
                cluster_runtime={"k3s_kubeconfig": "/tmp/k3s.yaml"},
                run=lambda *_args, **_kwargs: "ok",
                run_silent=lambda *_args, **_kwargs: json.dumps(ingress_payload),
                artifact_dir=tmpdir,
            )
            cert_dir = reconciler._cert_dir()
            cert_dir.mkdir(parents=True, exist_ok=True)
            # Simulate openssl output because subprocess.run is mocked.
            original_generate = reconciler._generate_self_signed_cert

            def fake_generate(hosts):
                result = original_generate(hosts)
                for path in result[:2]:
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write("material")
                return result

            reconciler._generate_self_signed_cert = fake_generate
            result = reconciler.reconcile()

        self.assertEqual(result["status"], "synced")
        self.assertIn("subjectAltName=DNS:org1.example.test", run_mock.call_args.args[0])

    @mock.patch("deployers.shared.lib.ingress_tls.subprocess.run")
    def test_truststore_starts_from_base_java_cacerts_before_importing_internal_ca(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stderr="", stdout="")

        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "base-cacerts")
            ca = os.path.join(tmpdir, "ca.crt")
            with open(base, "wb") as handle:
                handle.write(b"base-cacerts")
            with open(ca, "w", encoding="utf-8") as handle:
                handle.write("CA")

            reconciler = VMIngressTLSReconciler(
                config={
                    "DS_1_NAME": "demo",
                    "VM_INGRESS_TLS_BASE_TRUSTSTORE_FILE": base,
                    "VM_INGRESS_TLS_BASE_TRUSTSTORE_PASSWORD": "changeit",
                    "VM_INGRESS_TLS_TRUSTSTORE_PASSWORD": "dataspaceunit",
                },
                topology="vm-distributed",
                cluster_runtime={},
                run=lambda *_args, **_kwargs: "ok",
                run_silent=lambda *_args, **_kwargs: "",
                artifact_dir=tmpdir,
            )

            truststore = reconciler._truststore_path(ca)
            truststore_bytes = truststore.read_bytes()

        self.assertEqual(truststore_bytes, b"base-cacerts")
        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(commands[0][1], "-storepasswd")
        self.assertEqual(commands[1][1], "-importcert")
        self.assertIn("dataspaceunit", commands[0])


if __name__ == "__main__":
    unittest.main()
