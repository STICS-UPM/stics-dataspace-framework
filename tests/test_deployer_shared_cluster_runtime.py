import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.cluster_runtime import (
    DEFAULT_K3S_INGRESS_CONTROLLER,
    DEFAULT_K3S_INGRESS_SERVICE_TYPE,
    DEFAULT_K3S_INSTALL_EXEC,
    DEFAULT_K3S_KUBECONFIG,
    DEFAULT_K3S_REPAIR_ON_LEVEL1,
    DEFAULT_K3S_SERVICE_NAME,
    DEFAULT_K3S_WRITE_KUBECONFIG_MODE,
    build_cluster_runtime,
    normalize_cluster_type,
)


class SharedClusterRuntimeTests(unittest.TestCase):
    def test_local_defaults_to_minikube(self):
        self.assertEqual(normalize_cluster_type(topology="local"), "minikube")
        self.assertEqual(build_cluster_runtime(topology="local")["cluster_type"], "minikube")

    def test_vm_single_defaults_to_k3s_runtime(self):
        runtime = build_cluster_runtime(topology="vm-single")

        self.assertEqual(runtime["cluster_type"], "k3s")
        self.assertEqual(runtime["k3s_kubeconfig"], DEFAULT_K3S_KUBECONFIG)
        self.assertEqual(runtime["k3s_install_exec"], DEFAULT_K3S_INSTALL_EXEC)
        self.assertEqual(runtime["k3s_service_name"], DEFAULT_K3S_SERVICE_NAME)
        self.assertEqual(runtime["k3s_ingress_controller"], DEFAULT_K3S_INGRESS_CONTROLLER)
        self.assertEqual(runtime["k3s_ingress_service_type"], DEFAULT_K3S_INGRESS_SERVICE_TYPE)
        self.assertEqual(runtime["k3s_repair_on_level1"], DEFAULT_K3S_REPAIR_ON_LEVEL1)
        self.assertEqual(runtime["k3s_write_kubeconfig_mode"], DEFAULT_K3S_WRITE_KUBECONFIG_MODE)

    def test_vm_single_can_opt_into_k3s(self):
        runtime = build_cluster_runtime(
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/custom/k3s.yaml",
                "K3S_INSTALL_EXEC": "--disable=traefik --write-kubeconfig-mode=0640",
                "K3S_SERVICE_NAME": "k3s-custom",
                "K3S_INGRESS_CONTROLLER": "ingress-nginx",
                "K3S_INGRESS_SERVICE_TYPE": "LoadBalancer",
                "K3S_REPAIR_ON_LEVEL1": "never",
                "K3S_WRITE_KUBECONFIG_MODE": "0640",
            },
            topology="vm-single",
        )

        self.assertEqual(runtime["cluster_type"], "k3s")
        self.assertEqual(runtime["k3s_kubeconfig"], "/custom/k3s.yaml")
        self.assertEqual(runtime["k3s_install_exec"], "--disable=traefik --write-kubeconfig-mode=0640")
        self.assertEqual(runtime["k3s_service_name"], "k3s-custom")
        self.assertEqual(runtime["k3s_ingress_service_type"], "LoadBalancer")
        self.assertEqual(runtime["k3s_repair_on_level1"], "never")
        self.assertEqual(runtime["k3s_write_kubeconfig_mode"], "0640")

    def test_vm_distributed_defaults_to_k3s_runtime(self):
        runtime = build_cluster_runtime(topology="vm-distributed")

        self.assertEqual(runtime["cluster_type"], "k3s")
        self.assertEqual(runtime["k3s_kubeconfig_common"], DEFAULT_K3S_KUBECONFIG)
        self.assertEqual(runtime["k3s_kubeconfig_provider"], DEFAULT_K3S_KUBECONFIG)
        self.assertEqual(runtime["k3s_kubeconfig_consumer"], DEFAULT_K3S_KUBECONFIG)
        self.assertEqual(runtime["k3s_kubeconfig_components"], DEFAULT_K3S_KUBECONFIG)

    def test_vm_distributed_resolves_role_kubeconfigs(self):
        runtime = build_cluster_runtime(
            {
                "K3S_KUBECONFIG": "/clusters/default.yaml",
                "K3S_KUBECONFIG_COMMON": "/clusters/common.yaml",
                "K3S_KUBECONFIG_PROVIDER": "/clusters/provider.yaml",
                "K3S_KUBECONFIG_CONSUMER": "/clusters/consumer.yaml",
                "K3S_KUBECONFIG_COMPONENTS": "/clusters/components.yaml",
            },
            topology="vm-distributed",
        )

        self.assertEqual(runtime["cluster_type"], "k3s")
        self.assertEqual(runtime["k3s_kubeconfig"], "/clusters/default.yaml")
        self.assertEqual(runtime["k3s_kubeconfig_common"], "/clusters/common.yaml")
        self.assertEqual(runtime["k3s_kubeconfig_provider"], "/clusters/provider.yaml")
        self.assertEqual(runtime["k3s_kubeconfig_consumer"], "/clusters/consumer.yaml")
        self.assertEqual(runtime["k3s_kubeconfig_components"], "/clusters/components.yaml")

    def test_unsupported_cluster_runtime_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "Unsupported cluster runtime"):
            normalize_cluster_type("kind", topology="vm-single")

    def test_vm_single_rejects_minikube_runtime(self):
        with self.assertRaisesRegex(ValueError, "Use k3s"):
            normalize_cluster_type("minikube", topology="vm-single")


if __name__ == "__main__":
    unittest.main()
