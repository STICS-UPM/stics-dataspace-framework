import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.config_loader import (
    TOPOLOGY_KEY_TARGETS,
    TOPOLOGY_OVERLAY_KEYS,
    detect_topology_key_migration_warnings,
    INFRASTRUCTURE_MANAGED_KEYS,
    iter_dataspace_slots,
    load_deployer_config,
    load_layered_deployer_config,
    resolve_deployer_config_layer_paths,
    topology_overlay_config_path,
)


class SharedConfigLoaderTests(unittest.TestCase):
    def test_infrastructure_base_config_files_do_not_include_topology_keys(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for relative_path in ("deployers/infrastructure/deployer.config.example",):
            path = os.path.join(repo_root, relative_path)
            config = load_deployer_config(path)
            drift_keys = sorted(key for key in config if key in TOPOLOGY_KEY_TARGETS)
            self.assertEqual(
                drift_keys,
                [],
                msg=f"{relative_path} should stay topology-agnostic; found {drift_keys}",
            )

    def test_infrastructure_topology_files_only_use_allowed_overlay_keys(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        files_by_topology = {
            "local": (
                "deployers/infrastructure/topologies/local.config",
                "deployers/infrastructure/topologies/local.config.example",
            ),
            "vm-single": (
                "deployers/infrastructure/topologies/vm-single.config",
                "deployers/infrastructure/topologies/vm-single.config.example",
            ),
            "vm-distributed": (
                "deployers/infrastructure/topologies/vm-distributed.config",
                "deployers/infrastructure/topologies/vm-distributed.config.example",
            ),
        }
        for topology_name, relative_paths in files_by_topology.items():
            allowed_keys = set(TOPOLOGY_OVERLAY_KEYS[topology_name])
            for relative_path in relative_paths:
                path = os.path.join(repo_root, relative_path)
                config = load_deployer_config(path)
                unexpected_keys = sorted(key for key in config if key not in allowed_keys)
                self.assertEqual(
                    unexpected_keys,
                    [],
                    msg=(
                        f"{relative_path} should only contain {topology_name} overlay keys; "
                        f"found unexpected keys {unexpected_keys}"
                    ),
                )

    def test_cluster_runtime_keys_are_topology_scoped(self):
        self.assertIn("CLUSTER_TYPE", TOPOLOGY_OVERLAY_KEYS["local"])
        self.assertIn("CLUSTER_TYPE", TOPOLOGY_OVERLAY_KEYS["vm-single"])
        self.assertIn("CLUSTER_TYPE", TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
        self.assertNotIn("K3S_KUBECONFIG", TOPOLOGY_OVERLAY_KEYS["local"])
        self.assertIn("K3S_KUBECONFIG", TOPOLOGY_OVERLAY_KEYS["vm-single"])
        self.assertIn("K3S_KUBECONFIG", TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
        self.assertIn("K3S_INSTALL_EXEC", TOPOLOGY_OVERLAY_KEYS["vm-single"])
        self.assertIn("K3S_INSTALL_EXEC", TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
        self.assertIn("K3S_SERVICE_NAME", TOPOLOGY_OVERLAY_KEYS["vm-single"])
        self.assertIn("K3S_INGRESS_SERVICE_TYPE", TOPOLOGY_OVERLAY_KEYS["vm-single"])
        self.assertIn("K3S_REPAIR_ON_LEVEL1", TOPOLOGY_OVERLAY_KEYS["vm-single"])

        self.assertEqual(
            TOPOLOGY_KEY_TARGETS["CLUSTER_TYPE"],
            ("local", "vm-distributed", "vm-single"),
        )
        self.assertEqual(
            TOPOLOGY_KEY_TARGETS["K3S_KUBECONFIG"],
            ("vm-distributed", "vm-single"),
        )
        self.assertEqual(
            TOPOLOGY_KEY_TARGETS["K3S_INSTALL_EXEC"],
            ("vm-distributed", "vm-single"),
        )

    def test_load_deployer_config_reads_key_value_pairs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "deployer.config")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "# comment\n"
                    "DS_1_NAME=demoedc\n"
                    "DS_1_NAMESPACE=demoedc\n"
                    "COMMON_SERVICES_NAMESPACE=common-srvs\n"
                )

            config = load_deployer_config(path)

        self.assertEqual(config["DS_1_NAME"], "demoedc")
        self.assertEqual(config["DS_1_NAMESPACE"], "demoedc")
        self.assertEqual(config["COMMON_SERVICES_NAMESPACE"], "common-srvs")

    def test_load_layered_deployer_config_applies_ordered_overlays(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common_path = os.path.join(tmpdir, "common.config")
            adapter_path = os.path.join(tmpdir, "adapter.config")
            with open(common_path, "w", encoding="utf-8") as handle:
                handle.write("KC_URL=http://shared-keycloak\nDS_1_NAME=shared\n")
            with open(adapter_path, "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=adapter\n")

            config = load_layered_deployer_config(
                [common_path, adapter_path],
                defaults={"KC_USER": "admin"},
                apply_environment=False,
            )

        self.assertEqual(config["KC_USER"], "admin")
        self.assertEqual(config["KC_URL"], "http://shared-keycloak")
        self.assertEqual(config["DS_1_NAME"], "adapter")

    def test_topology_overlay_config_path_uses_sibling_topologies_dir(self):
        path = "/tmp/deployers/infrastructure/deployer.config"

        overlay_path = topology_overlay_config_path(path, "vm-single")

        self.assertEqual(
            overlay_path,
            "/tmp/deployers/infrastructure/topologies/vm-single.config",
        )

    def test_resolve_deployer_config_layer_paths_keeps_base_path_without_topology(self):
        path = "/tmp/deployers/infrastructure/deployer.config"

        resolved_paths = resolve_deployer_config_layer_paths(path)

        self.assertEqual(
            resolved_paths,
            ["/tmp/deployers/infrastructure/deployer.config"],
        )

    def test_load_layered_deployer_config_loads_topology_overlays_after_each_base_layer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infrastructure_dir = os.path.join(tmpdir, "deployers", "infrastructure")
            adapter_dir = os.path.join(tmpdir, "deployers", "inesdata")
            os.makedirs(os.path.join(infrastructure_dir, "topologies"), exist_ok=True)
            os.makedirs(os.path.join(adapter_dir, "topologies"), exist_ok=True)

            infrastructure_path = os.path.join(infrastructure_dir, "deployer.config")
            adapter_path = os.path.join(adapter_dir, "deployer.config")
            with open(infrastructure_path, "w", encoding="utf-8") as handle:
                handle.write("KC_URL=http://shared-keycloak\nTOPOLOGY_MARKER=base\n")
            with open(
                os.path.join(infrastructure_dir, "topologies", "vm-single.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("VM_EXTERNAL_IP=192.0.2.10\nTOPOLOGY_MARKER=infrastructure-overlay\n")
            with open(adapter_path, "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=demo\n")
            with open(
                os.path.join(adapter_dir, "topologies", "vm-single.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("DS_1_NAMESPACE=demo-vm\nTOPOLOGY_MARKER=adapter-overlay\n")

            config = load_layered_deployer_config(
                [infrastructure_path, adapter_path],
                apply_environment=False,
                topology="vm-single",
            )

        self.assertEqual(config["KC_URL"], "http://shared-keycloak")
        self.assertEqual(config["VM_EXTERNAL_IP"], "192.0.2.10")
        self.assertEqual(config["DS_1_NAME"], "demo")
        self.assertEqual(config["DS_1_NAMESPACE"], "demo-vm")
        self.assertEqual(config["TOPOLOGY_MARKER"], "adapter-overlay")

    def test_detect_topology_key_migration_warnings_reports_base_config_drift(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infrastructure_dir = os.path.join(tmpdir, "deployers", "infrastructure")
            os.makedirs(infrastructure_dir, exist_ok=True)
            config_path = os.path.join(infrastructure_dir, "deployer.config")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "KC_URL=http://shared-keycloak\n"
                    "PG_HOST=localhost\n"
                    "VM_EXTERNAL_IP=192.0.2.10\n"
                    "INGRESS_EXTERNAL_IP=192.0.2.10\n"
                )

            warnings = detect_topology_key_migration_warnings(config_path)

        self.assertEqual([item["key"] for item in warnings], ["INGRESS_EXTERNAL_IP", "PG_HOST", "VM_EXTERNAL_IP"])
        self.assertEqual(
            warnings[0]["recommended_overlay_paths"],
            [
                os.path.join(infrastructure_dir, "topologies", "vm-distributed.config"),
                os.path.join(infrastructure_dir, "topologies", "vm-single.config"),
            ],
        )
        self.assertEqual(
            warnings[1]["recommended_overlay_paths"],
            [os.path.join(infrastructure_dir, "topologies", "local.config")],
        )

    def test_load_layered_deployer_config_can_protect_infrastructure_managed_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common_path = os.path.join(tmpdir, "common.config")
            adapter_path = os.path.join(tmpdir, "adapter.config")
            with open(common_path, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=real-token\nKC_PASSWORD=real-password\nDS_1_NAME=shared\n")
            with open(adapter_path, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=X\nKC_PASSWORD=CHANGE_ME\nDS_1_NAME=adapter\n")

            config = load_layered_deployer_config(
                [common_path, adapter_path],
                apply_environment=False,
                protected_keys=INFRASTRUCTURE_MANAGED_KEYS,
            )

        self.assertEqual(config["VT_TOKEN"], "real-token")
        self.assertEqual(config["KC_PASSWORD"], "real-password")
        self.assertEqual(config["DS_1_NAME"], "adapter")

    def test_protected_empty_infrastructure_value_is_not_replaced_by_adapter_placeholder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common_path = os.path.join(tmpdir, "common.config")
            adapter_path = os.path.join(tmpdir, "adapter.config")
            with open(common_path, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=\n")
            with open(adapter_path, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=X\n")

            config = load_layered_deployer_config(
                [common_path, adapter_path],
                apply_environment=False,
                protected_keys=INFRASTRUCTURE_MANAGED_KEYS,
            )

        self.assertEqual(config["VT_TOKEN"], "")

    def test_iter_dataspace_slots_groups_values_per_slot(self):
        slots = iter_dataspace_slots(
            {
                "DS_1_NAME": "demo",
                "DS_1_NAMESPACE": "demo",
                "DS_2_NAME": "demoedc",
                "DS_2_CONNECTORS": "citycounciledc,companyedc",
                "UNRELATED": "ignored",
            }
        )

        self.assertEqual(
            slots,
            [
                {"slot": "1", "NAME": "demo", "NAMESPACE": "demo"},
                {"slot": "2", "NAME": "demoedc", "CONNECTORS": "citycounciledc,companyedc"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
