import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.config_loader import (
    AI_MODEL_HUB_MODEL_SERVER_TOPOLOGY_KEYS,
    COMMON_SERVICE_TOPOLOGY_KEYS,
    COMPONENT_IMAGE_TOPOLOGY_KEYS,
    EDC_IMAGE_TOPOLOGY_KEYS,
    IMAGE_BUILD_POLICY_TOPOLOGY_KEYS,
    INESDATA_CONNECTOR_IMAGE_TOPOLOGY_KEYS,
    KAFKA_TOPOLOGY_KEYS,
    KUBERNETES_WORKLOAD_TOPOLOGY_KEYS,
    TOPOLOGY_KEY_TARGETS,
    TOPOLOGY_OVERLAY_KEYS,
    VM_SERVICE_TOPOLOGY_KEYS,
    apply_topology_runtime_defaults,
    detect_topology_key_migration_warnings,
    INFRASTRUCTURE_MANAGED_KEYS,
    iter_dataspace_slots,
    load_deployer_config,
    load_layered_deployer_config,
    resolve_deployer_config_layer_paths,
    topology_overlay_config_path,
)


class SharedConfigLoaderTests(unittest.TestCase):
    def test_vm_distributed_runtime_defaults_infer_database_hostname(self):
        config = apply_topology_runtime_defaults(
            {
                "DATABASE_HOSTNAME": "",
                "COMMON_SERVICES_NAMESPACE": "shared-foundation",
            },
            "vm-distributed",
        )

        self.assertEqual(
            config["DATABASE_HOSTNAME"],
            "common-srvs-postgresql.shared-foundation.svc",
        )

    def test_vm_runtime_defaults_keep_explicit_database_hostname(self):
        config = apply_topology_runtime_defaults(
            {
                "DATABASE_HOSTNAME": "postgresql.example.internal",
                "COMMON_SERVICES_NAMESPACE": "shared-foundation",
            },
            "vm-single",
        )

        self.assertEqual(config["DATABASE_HOSTNAME"], "postgresql.example.internal")

    def test_vm_runtime_defaults_infer_vault_service_url(self):
        config = apply_topology_runtime_defaults(
            {
                "VT_URL": "",
                "VAULT_URL": "http://127.0.0.1:8200",
                "COMMON_SERVICES_NAMESPACE": "shared-foundation",
            },
            "vm-distributed",
        )

        self.assertEqual(config["VT_URL"], "http://common-srvs-vault.shared-foundation.svc:8200")
        self.assertEqual(config["VAULT_URL"], "http://common-srvs-vault.shared-foundation.svc:8200")

    def test_vm_runtime_defaults_keep_explicit_vault_service_url(self):
        config = apply_topology_runtime_defaults(
            {
                "VT_URL": "http://vault.example.internal:8200",
                "VAULT_URL": "https://vault.example.org",
                "COMMON_SERVICES_NAMESPACE": "shared-foundation",
            },
            "vm-single",
        )

        self.assertEqual(config["VT_URL"], "http://vault.example.internal:8200")
        self.assertEqual(config["VAULT_URL"], "https://vault.example.org")

    def test_local_runtime_defaults_infer_database_hostname_for_cluster_workloads(self):
        config = apply_topology_runtime_defaults(
            {
                "DATABASE_HOSTNAME": "",
                "VT_URL": "http://127.0.0.1:8200",
                "VAULT_URL": "",
                "COMMON_SERVICES_NAMESPACE": "shared-foundation",
            },
            "local",
        )

        self.assertEqual(
            config["DATABASE_HOSTNAME"],
            "common-srvs-postgresql.shared-foundation.svc",
        )
        self.assertEqual(config["VT_URL"], "http://127.0.0.1:8200")
        self.assertEqual(config["VAULT_URL"], "http://common-srvs-vault.shared-foundation.svc:8200")

    def test_load_layered_deployer_config_replaces_vm_loopback_vault_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "deployer.config")
            topology_dir = os.path.join(tmpdir, "topologies")
            os.makedirs(topology_dir, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("VT_URL=http://127.0.0.1:8200\nCOMMON_SERVICES_NAMESPACE=shared-foundation\n")
            with open(os.path.join(topology_dir, "vm-distributed.config"), "w", encoding="utf-8") as handle:
                handle.write("CLUSTER_TYPE=k3s\n")

            config = load_layered_deployer_config([config_path], topology="vm-distributed")

        self.assertEqual(config["VT_URL"], "http://common-srvs-vault.shared-foundation.svc:8200")

    def test_load_layered_deployer_config_stamps_active_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "deployer.config")
            topology_dir = os.path.join(tmpdir, "topologies")
            os.makedirs(topology_dir, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("TOPOLOGY=local\nDOMAIN_BASE=dev.ed.dataspaceunit.upm\n")
            with open(os.path.join(topology_dir, "vm-single.config"), "w", encoding="utf-8") as handle:
                handle.write("VM_SINGLE_HTTP_URL=https://org4.pionera.oeg.fi.upm.es\n")

            config = load_layered_deployer_config([config_path], topology="vm-single")

        self.assertEqual(config["TOPOLOGY"], "vm-single")
        self.assertEqual(config["VM_SINGLE_HTTP_URL"], "https://org4.pionera.oeg.fi.upm.es")

    def test_load_layered_deployer_config_active_topology_overrides_environment_topology(self):
        previous = os.environ.get("PIONERA_TOPOLOGY")
        os.environ["PIONERA_TOPOLOGY"] = "local"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = os.path.join(tmpdir, "deployer.config")
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write("DOMAIN_BASE=dev.ed.dataspaceunit.upm\n")

                config = load_layered_deployer_config([config_path], topology="vm-single")
        finally:
            if previous is None:
                os.environ.pop("PIONERA_TOPOLOGY", None)
            else:
                os.environ["PIONERA_TOPOLOGY"] = previous

        self.assertEqual(config["TOPOLOGY"], "vm-single")

    def test_load_layered_deployer_config_keeps_environment_vault_override(self):
        previous = os.environ.get("PIONERA_VT_URL")
        os.environ["PIONERA_VT_URL"] = "http://127.0.0.1:59491"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = os.path.join(tmpdir, "deployer.config")
                topology_dir = os.path.join(tmpdir, "topologies")
                os.makedirs(topology_dir, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as handle:
                    handle.write("VT_URL=http://127.0.0.1:8200\nCOMMON_SERVICES_NAMESPACE=shared-foundation\n")
                with open(os.path.join(topology_dir, "vm-distributed.config"), "w", encoding="utf-8") as handle:
                    handle.write("CLUSTER_TYPE=k3s\n")

                config = load_layered_deployer_config([config_path], topology="vm-distributed")
        finally:
            if previous is None:
                os.environ.pop("PIONERA_VT_URL", None)
            else:
                os.environ["PIONERA_VT_URL"] = previous

        self.assertEqual(config["VT_URL"], "http://127.0.0.1:59491")

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

    def test_common_service_endpoint_keys_are_topology_scoped(self):
        for key in COMMON_SERVICE_TOPOLOGY_KEYS:
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("local", "vm-distributed", "vm-single"))

        for key in KUBERNETES_WORKLOAD_TOPOLOGY_KEYS:
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("local", "vm-distributed", "vm-single"))

        for key in VM_SERVICE_TOPOLOGY_KEYS:
            if key == "VT_URL":
                self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
                self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("local", "vm-distributed", "vm-single"))
                continue
            self.assertNotIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed", "vm-single"))

    def test_vm_ssh_access_keys_are_topology_scoped(self):
        shared_vm_keys = (
            "SSH_ACCESS_MODE",
            "SSH_BASTION_HOST",
            "SSH_BASTION_PORT",
            "SSH_BASTION_USER",
            "SSH_BASTION_IDENTITY_FILE",
            "SSH_IDENTITY_FILE",
            "SSH_CONNECT_TIMEOUT_SECONDS",
            "VM_SSH_USER",
            "VM_REMOTE_WORKDIR",
            "COMPONENTS_PUBLIC_BASE_URL",
            "COMPONENTS_PUBLIC_PATH_REWRITE",
            "VM_DISTRIBUTED_COMPONENT_PUBLIC_PATH_INGRESS_OWNER",
            "AI_MODEL_HUB_MODEL_SERVER_MODE",
            "LEVEL5_AI_MODEL_HUB_MODEL_SERVER_MODE",
            "MODEL_SERVER_MODE",
            "AI_MODEL_HUB_MODEL_SERVER_IMAGE",
            "MODEL_SERVER_IMAGE",
            "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR",
            "MODEL_SERVER_SOURCE_DIR",
            "AI_MODEL_HUB_REAL_MODEL_SERVER_SOURCE_DIR",
            "AI_MODEL_HUB_USE_CASE_MODEL_SERVER_SOURCE_DIR",
            "MODEL_SERVER_REAL_SOURCE_DIR",
            "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY",
            "AI_MODEL_HUB_USE_CASE_MODEL_SERVER_REPOSITORY",
            "AI_MODEL_HUB_REAL_MODEL_SERVER_REPOSITORY",
            "MODEL_SERVER_SOURCE_REPOSITORY",
            "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REF",
            "MODEL_SERVER_SOURCE_REF",
            "AI_MODEL_HUB_MODEL_SERVER_MANIFEST_PATH",
            "MODEL_SERVER_MANIFEST_PATH",
            "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH",
            "MODEL_SERVER_READINESS_PATH",
            "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT",
            "MODEL_SERVER_CONTAINER_PORT",
            "AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE",
            "MODEL_SERVER_DOCKER_BASE_IMAGE",
            "AI_MODEL_HUB_MODEL_SERVER_UVICORN_APP",
            "MODEL_SERVER_UVICORN_APP",
            "AI_MODEL_HUB_MODEL_SERVER_IMAGE_PULL_POLICY",
            "MODEL_SERVER_IMAGE_PULL_POLICY",
            "AI_MODEL_HUB_MODEL_SERVER_COPY_EXCLUDES",
            "MODEL_SERVER_COPY_EXCLUDES",
            "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL",
            "MODEL_SERVER_PUBLIC_URL",
            "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL",
            "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH",
            "MODEL_SERVER_PUBLIC_PATH",
            "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL",
            "MODEL_SERVER_CONNECTOR_BASE_URL",
            "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL",
            "MODEL_SERVER_CONNECTOR_URL",
            "AI_MODEL_HUB_REAL_MODELS_ARTIFACT_DIR",
            "AI_MODEL_HUB_REAL_MODELS_TRAIN_COMMAND",
            "AI_MODEL_HUB_SEED_NEGOTIATION_TIMEOUT_SECONDS",
            "AI_MODEL_HUB_SEED_NEGOTIATION_POLL_INTERVAL_SECONDS",
            "AI_MODEL_HUB_SEED_NEGOTIATION_STATE_REQUEST_TIMEOUT_SECONDS",
            "AI_MODEL_HUB_SEED_NEGOTIATION_PORT_FORWARD_DELAY_SECONDS",
            "AI_MODEL_OBSERVER_JOURNAL_BASE_URL",
            "AI_MODEL_HUB_OBSERVER_JOURNAL_BASE_URL",
            "MODEL_OBSERVER_JOURNAL_BASE_URL",
            "ONTOLOGY_HUB_PUBLIC_URL",
            "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_ENABLED",
            "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_SIZE",
            "ONTOLOGY_HUB_SELF_HOST_URL",
            "ONTOLOGY_HUB_INTERNAL_SELF_HOST_URL",
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME",
            "ONTOLOGY_HUB_SELF_HOST_NAMESPACE",
            "ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT",
            "ONTOLOGY_HUB_SELF_HOST_PORT",
            "ONTOLOGY_HUB_SERVICE_NAME",
            "ONTOLOGY_HUB_SERVICE_NAMESPACE",
            "ONTOLOGY_HUB_SERVICE_PORT",
            "AI_MODEL_HUB_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_PUBLIC_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NAMESPACE",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_NAME",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_PORT",
        )
        for key in shared_vm_keys:
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed", "vm-single"))

        for key in (
            "VM_SINGLE_SSH_HOST",
            "VM_SINGLE_SSH_PORT",
            "VM_SINGLE_SSH_USER",
            "VM_SINGLE_SSH_IDENTITY_FILE",
            "VM_SINGLE_SSH_BOOTSTRAP_MODE",
            "VM_SINGLE_SSH_KEY_COMMENT",
            "VM_SINGLE_SSH_MANAGED_MARKER",
            "VM_SINGLE_SSH_KNOWN_HOSTS_STRATEGY",
            "VM_SINGLE_LEVEL_EXECUTION_MODE",
            "VM_SINGLE_REMOTE_PYTHON",
            "VM_SINGLE_REMOTE_WORKDIR",
            "VM_SINGLE_LOCAL_KUBECONFIG",
            "VM_SINGLE_REMOTE_KUBECONFIG",
            "VM_SINGLE_K3S_TUNNEL_MODE",
            "VM_SINGLE_K3S_API_LOCAL_PORT",
            "VM_SINGLE_K3S_API_REMOTE_PORT",
            "VM_SINGLE_WORKSPACE_SYNC",
            "VM_SINGLE_WORKSPACE_SYNC_DELETE",
            "VM_SINGLE_WORKSPACE_SYNC_EXCLUDES",
            "VM_SINGLE_PUBLIC_URL",
            "VM_SINGLE_HTTP_URL",
            "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX",
        ):
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-single",))

        for role in ("COMMON", "COMPONENTS", "PROVIDER", "CONSUMER"):
            for suffix in (
                "SSH_ACCESS_MODE",
                "SSH_BASTION_HOST",
                "SSH_BASTION_PORT",
                "SSH_BASTION_USER",
                "SSH_BASTION_IDENTITY_FILE",
            ):
                key = f"VM_{role}_{suffix}"
                self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
                self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed",))

        for key in (
            "VM_DISTRIBUTED_EXECUTION_HOST",
            "VM_DISTRIBUTED_COMMON_VM_DIRECT_SSH",
            "VM_DISTRIBUTED_INFER_LOCAL_WORKDIR",
            "VM_DISTRIBUTED_KUBECONFIG_AUTO_LOCALIZE",
            "VM_DISTRIBUTED_KUBECONFIG_DIR",
            "VM_DISTRIBUTED_KUBECONFIG_SYNC",
            "VM_DISTRIBUTED_REMOTE_KUBECONFIG",
            "VM_COMMON_REMOTE_KUBECONFIG",
            "VM_PROVIDER_REMOTE_KUBECONFIG",
            "VM_CONSUMER_REMOTE_KUBECONFIG",
            "VM_COMPONENTS_REMOTE_KUBECONFIG",
            "VM_DISTRIBUTED_HTTP_PREFLIGHT_TLS_VERIFY",
            "VM_DISTRIBUTED_SSH_BOOTSTRAP_MODE",
            "VM_DISTRIBUTED_SSH_KEY_COMMENT",
            "VM_DISTRIBUTED_SSH_MANAGED_MARKER",
            "VM_DISTRIBUTED_SSH_KNOWN_HOSTS_STRATEGY",
            "VM_DISTRIBUTED_DEPLOYMENT_MODE",
            "VM_DISTRIBUTED_PREFLIGHT_DRY_RUN",
            "VM_COMMON_K3S_API_LOCAL_PORT",
            "VM_PROVIDER_K3S_API_LOCAL_PORT",
            "VM_CONSUMER_K3S_API_LOCAL_PORT",
            "VM_COMPONENTS_K3S_API_LOCAL_PORT",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_COMMAND",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_DIR",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_TTY",
            "VM_DISTRIBUTED_SSH_IDENTITY_FILE",
            "VM_COMMON_REMOTE_WORKDIR",
            "VM_PROVIDER_REMOTE_WORKDIR",
            "VM_CONSUMER_REMOTE_WORKDIR",
            "VM_COMMON_PUBLIC_URL",
            "VM_PROVIDER_PUBLIC_URL",
            "VM_CONSUMER_PUBLIC_URL",
            "VM_COMMON_HTTP_URL",
            "VM_PROVIDER_HTTP_URL",
            "VM_CONSUMER_HTTP_URL",
            "KEYCLOAK_BOOTSTRAP_PORT_FORWARD",
            "VM_PUBLIC_PROXY_IP",
            "VM_PROVIDER_K8S_NODE",
            "VM_CONSUMER_K8S_NODE",
            "VM_COMMON_SSH_HOST",
            "VM_COMMON_SSH_IDENTITY_FILE",
            "VM_COMPONENTS_SSH_HOST",
            "VM_COMPONENTS_SSH_IDENTITY_FILE",
            "VM_PROVIDER_SSH_HOST",
            "VM_PROVIDER_SSH_IDENTITY_FILE",
            "VM_CONSUMER_SSH_HOST",
            "VM_CONSUMER_SSH_IDENTITY_FILE",
        ):
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed",))

    def test_component_image_keys_are_vm_topology_scoped(self):
        for key in AI_MODEL_HUB_MODEL_SERVER_TOPOLOGY_KEYS:
            self.assertNotIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed", "vm-single"))

        for key in COMPONENT_IMAGE_TOPOLOGY_KEYS:
            self.assertNotIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed", "vm-single"))

        for key in IMAGE_BUILD_POLICY_TOPOLOGY_KEYS:
            self.assertNotIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed", "vm-single"))

        for key in INESDATA_CONNECTOR_IMAGE_TOPOLOGY_KEYS | EDC_IMAGE_TOPOLOGY_KEYS:
            self.assertNotIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed", "vm-single"))

        for key in KAFKA_TOPOLOGY_KEYS:
            self.assertNotIn(key, TOPOLOGY_OVERLAY_KEYS["local"])
            self.assertNotIn(key, TOPOLOGY_OVERLAY_KEYS["vm-single"])
            self.assertIn(key, TOPOLOGY_OVERLAY_KEYS["vm-distributed"])
            self.assertEqual(TOPOLOGY_KEY_TARGETS[key], ("vm-distributed",))

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

        self.assertEqual(
            [item["key"] for item in warnings],
            ["INGRESS_EXTERNAL_IP", "KC_URL", "PG_HOST", "VM_EXTERNAL_IP"],
        )
        warnings_by_key = {item["key"]: item for item in warnings}
        self.assertEqual(
            warnings_by_key["INGRESS_EXTERNAL_IP"]["recommended_overlay_paths"],
            [
                os.path.join(infrastructure_dir, "topologies", "vm-distributed.config"),
                os.path.join(infrastructure_dir, "topologies", "vm-single.config"),
            ],
        )
        self.assertEqual(
            warnings_by_key["KC_URL"]["recommended_overlay_paths"],
            [
                os.path.join(infrastructure_dir, "topologies", "local.config"),
                os.path.join(infrastructure_dir, "topologies", "vm-distributed.config"),
                os.path.join(infrastructure_dir, "topologies", "vm-single.config"),
            ],
        )
        self.assertEqual(
            warnings_by_key["PG_HOST"]["recommended_overlay_paths"],
            [os.path.join(infrastructure_dir, "topologies", "local.config")],
        )

    def test_load_layered_deployer_config_can_protect_infrastructure_managed_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            common_path = os.path.join(tmpdir, "common.config")
            adapter_path = os.path.join(tmpdir, "adapter.config")
            with open(common_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "VT_TOKEN=example-token\n"
                    "KC_PASSWORD=example-password\n"
                    "KEYCLOAK_FRONTEND_URL=https://auth.shared.example.test\n"
                    "DS_1_NAME=shared\n"
                )
            with open(adapter_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "VT_TOKEN=X\n"
                    "KC_PASSWORD=CHANGE_ME\n"
                    "KEYCLOAK_FRONTEND_URL=http://auth.adapter.example.test\n"
                    "DS_1_NAME=adapter\n"
                )

            config = load_layered_deployer_config(
                [common_path, adapter_path],
                apply_environment=False,
                protected_keys=INFRASTRUCTURE_MANAGED_KEYS,
            )

        self.assertEqual(config["VT_TOKEN"], "example-token")
        self.assertEqual(config["KC_PASSWORD"], "example-password")
        self.assertEqual(config["KEYCLOAK_FRONTEND_URL"], "https://auth.shared.example.test")
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
