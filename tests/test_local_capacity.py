import unittest

from framework.local_capacity import (
    LOCAL_COEXISTENCE_MEMORY_MB,
    evaluate_local_coexistence_capacity,
    node_capacity_memory_mb,
    parse_memory_quantity_mb,
    summarize_local_workloads,
)


class LocalCapacityTests(unittest.TestCase):
    def test_parse_memory_quantity_supports_config_docker_and_kubernetes_values(self):
        self.assertEqual(parse_memory_quantity_mb("14336"), 14336)
        self.assertEqual(parse_memory_quantity_mb("15996068Ki"), 15621)
        self.assertEqual(parse_memory_quantity_mb("18Gi"), 18432)
        self.assertEqual(parse_memory_quantity_mb("16379973632"), 15621)

    def test_node_capacity_memory_uses_smallest_reported_node_capacity(self):
        payload = {
            "items": [
                {"status": {"allocatable": {"memory": "18Gi"}}},
                {"status": {"allocatable": {"memory": "16Gi"}}},
            ]
        }

        self.assertEqual(node_capacity_memory_mb(payload), 16384)

    def test_summarize_local_workloads_detects_inesdata_edc_coexistence(self):
        pods = {
            "items": [
                {"metadata": {"namespace": "demo"}, "status": {"phase": "Running"}},
                {"metadata": {"namespace": "demoedc"}, "status": {"phase": "Running"}},
                {"metadata": {"namespace": "components"}, "status": {"phase": "Running"}},
                {"metadata": {"namespace": "ingress-nginx"}, "status": {"phase": "Succeeded"}},
            ]
        }

        summary = summarize_local_workloads(
            pods,
            adapter_namespaces={"inesdata": "demo", "edc": "demoedc"},
            component_namespaces=["components"],
        )

        self.assertTrue(summary["coexistence_detected"])
        self.assertEqual(summary["active_adapters"], ["edc", "inesdata"])
        self.assertEqual(summary["active_component_namespaces"], ["components"])

    def test_evaluate_local_coexistence_capacity_fails_when_memory_is_below_baseline(self):
        summary = {"coexistence_detected": True, "active_adapters": ["edc", "inesdata"]}

        result = evaluate_local_coexistence_capacity(
            summary,
            node_memory_mb=15621,
            docker_memory_mb=15621,
            configured_minikube_memory_mb=14336,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["required_memory_mb"], LOCAL_COEXISTENCE_MEMORY_MB)
        self.assertEqual(result["effective_memory_mb"], 14336)
        self.assertEqual(result["blocking_issues"][0]["name"], "local_coexistence_insufficient_memory")

    def test_evaluate_local_coexistence_capacity_passes_single_adapter(self):
        summary = {"coexistence_detected": False, "active_adapters": ["inesdata"]}

        result = evaluate_local_coexistence_capacity(
            summary,
            node_memory_mb=14336,
            docker_memory_mb=14336,
            configured_minikube_memory_mb=14336,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["reason"], "single-adapter-or-no-coexistence")


if __name__ == "__main__":
    unittest.main()
