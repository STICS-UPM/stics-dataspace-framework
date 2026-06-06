import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import main
from adapters.inesdata.adapter import InesdataAdapter
from deployers.shared.lib.contracts import DeploymentContext


class FakeConfig:
    DS_NAME = "fake-ds"
    NS_COMMON = "common-srvs"

    @staticmethod
    def ds_domain_base():
        return "example.local"

    @staticmethod
    def namespace_demo():
        return "fake-ds"


class FakeConfigAdapter:
    def load_deployer_config(self):
        return {"KC_URL": "http://keycloak.local", "DS_1_NAME": "fake-ds"}

    def primary_dataspace_name(self):
        return self.load_deployer_config().get("DS_1_NAME", "fake-ds")


class FakeConnectors:
    @staticmethod
    def build_connector_url(connector):
        return f"http://{connector}.example.local/interface"

    @staticmethod
    def load_connector_credentials(connector):
        return {
            "connector_user": {
                "user": f"{connector}-user",
                "passwd": "secret",
            }
        }

    @staticmethod
    def cleanup_test_entities(connector):
        return None

    @staticmethod
    def validation_test_entities_absent(connector):
        return True, []

    @staticmethod
    def connector_target_namespace(connector):
        return f"{connector}-ns"


class FakeAdapter:
    def __init__(self):
        self.config = FakeConfig
        self.config_adapter = FakeConfigAdapter()
        self.connectors = FakeConnectors()
        self.components = types.SimpleNamespace(
            infer_component_urls=lambda components, **_: {
                component: f"http://{component}.example.local"
                for component in components
            }
        )
        self.calls = []

    def deploy_infrastructure(self):
        self.calls.append("deploy_infrastructure")

    def deploy_dataspace(self):
        self.calls.append("deploy_dataspace")

    def build_recreate_dataspace_plan(self):
        return {
            "status": "planned",
            "adapter": "fake",
            "dataspace": "fake-ds",
            "namespace": "fake-ds",
            "runtime_dir": "/tmp/fake-ds",
            "preserves_shared_services": True,
            "invalidates_level_4_connectors": True,
        }

    def recreate_dataspace(self, confirm_dataspace=None):
        self.calls.append(f"recreate_dataspace:{confirm_dataspace}")
        return {"status": "recreated", "dataspace": confirm_dataspace}

    def deploy_connectors(self):
        self.calls.append("deploy_connectors")
        return ["conn-a", "conn-b"]

    def get_cluster_connectors(self):
        self.calls.append("get_cluster_connectors")
        return ["conn-a", "conn-b"]


class FakeAdapterWithInfrastructure(FakeAdapter):
    def __init__(self):
        super().__init__()
        self.infrastructure = object()


class FakePublicAccessInfrastructure:
    def __init__(self):
        self.calls = []

    def sync_vm_distributed_public_access(self, topology="local"):
        self.calls.append(("sync_vm_distributed_public_access", topology))
        return {
            "status": "synced",
            "topology": topology,
            "common_public_paths": {"status": "synced"},
            "component_public_paths": {"status": "synced"},
        }


class FakePublicAccessAdapter(FakeAdapter):
    def __init__(self, dry_run=False, topology="local"):
        super().__init__()
        self.dry_run = dry_run
        self.topology = topology
        self.infrastructure = FakePublicAccessInfrastructure()


class RuntimeArtifactPathSummaryTests(unittest.TestCase):
    def test_vm_distributed_inesdata_summary_separates_shared_and_adapter_artifacts(self):
        context = DeploymentContext(
            deployer="inesdata",
            topology="vm-distributed",
            environment="DEV",
            dataspace_name="pionera",
            ds_domain_base="pionera.example.test",
            connectors=["conn-org2-pionera"],
        )

        summary = main.build_runtime_artifact_path_summary("inesdata", context)

        self.assertEqual(summary["status"], "available")
        self.assertEqual(summary["topology"], "vm-distributed")
        shared_paths = {item["path"] for item in summary["shared"]}
        adapter_paths = {item["path"] for item in summary["adapter_artifacts"]}
        connector_paths = {
            item["path"]
            for connector in summary["connectors"]
            for item in connector["artifacts"]
        }
        self.assertIn(
            "deployers/shared/deployments/DEV/vm-distributed/common/init-keys-vault.json",
            shared_paths,
        )
        self.assertIn(
            "deployers/inesdata/deployments/DEV/vm-distributed/pionera/credentials-dataspace-pionera.json",
            adapter_paths,
        )
        self.assertIn(
            "deployers/inesdata/deployments/DEV/vm-distributed/pionera/connectors/conn-org2-pionera/credentials.json",
            connector_paths,
        )
        self.assertIn(
            "deployers/inesdata/deployments/DEV/vm-distributed/pionera/connectors/conn-org2-pionera/policy.json",
            connector_paths,
        )

    def test_runtime_artifact_path_summary_prints_guidance(self):
        context = DeploymentContext(
            deployer="inesdata",
            topology="vm-distributed",
            environment="DEV",
            dataspace_name="pionera",
            ds_domain_base="pionera.example.test",
            connectors=["conn-org2-pionera"],
        )
        summary = main.build_runtime_artifact_path_summary("inesdata", context)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main._print_runtime_artifact_paths(summary)

        rendered = output.getvalue()
        self.assertIn("Shared foundation artifacts", rendered)
        self.assertIn("Adapter artifacts", rendered)
        self.assertIn("Connector artifacts", rendered)
        self.assertIn("deployers/shared", rendered)
        self.assertIn("deployers/<adapter>", rendered)


class KafkaTransferConsoleOutputTests(unittest.TestCase):
    def test_level6_kafka_disabled_message_explains_how_to_enable(self):
        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        stdout = io.StringIO()
        with (
            mock.patch.object(main, "_env_flag", side_effect=lambda name, default=False: default),
            mock.patch.object(main, "_save_kafka_edc_results") as save_results,
            contextlib.redirect_stdout(stdout),
        ):
            results = main.run_level6_kafka_edc_after_newman(
                KafkaReadyAdapter(),
                ["conn-a", "conn-b"],
                "/tmp/experiment",
                deployer_name="inesdata",
            )

        self.assertEqual(results[0]["status"], "skipped")
        save_results.assert_called_once()
        output = stdout.getvalue()
        self.assertIn("disabled by default in Level 6", output)
        self.assertIn("answer yes when prompted", output)
        self.assertIn("PIONERA_LEVEL6_RUN_KAFKA=true", output)
        self.assertIn("unset it or set PIONERA_LEVEL6_SKIP_KAFKA=false", output)

    def test_vm_distributed_kafka_preflight_blocks_invalid_connector_bootstrap(self):
        class VmDistributedKafkaAdapter(FakeAdapter):
            topology = "vm-distributed"

            def get_kafka_config(self):
                return {
                    "topology": "vm-distributed",
                    "cluster_bootstrap_servers": "framework-kafka.core-control.svc.cluster.local:9092",
                }

        experiment_storage = mock.Mock()
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as experiment_dir:
            with mock.patch.object(
                main,
                "run_kafka_edc_validation",
                side_effect=AssertionError("Kafka suite should not run after preflight failure"),
            ), contextlib.redirect_stdout(stdout):
                results = main.run_level6_kafka_edc_after_newman(
                    VmDistributedKafkaAdapter(),
                    ["conn-a", "conn-b"],
                    experiment_dir,
                    deployer_name="inesdata",
                    experiment_storage=experiment_storage,
                    kafka_enabled=True,
                )

        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(results[0]["reason"], "kafka_runtime_preflight_failed")
        self.assertIn("Kubernetes ClusterIP/DNS", results[0]["error"]["message"])
        experiment_storage.save_kafka_edc_results_json.assert_called_once()
        self.assertIn("Kafka runtime preflight failed", stdout.getvalue())

    def test_level6_kafka_prompt_enables_suite_when_user_confirms(self):
        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch.object(
            main,
            "_interactive_confirm",
            return_value=True,
        ) as confirm, contextlib.redirect_stdout(stdout):
            enabled = main._resolve_level6_kafka_enabled_for_run(
                KafkaReadyAdapter(),
                deployer_name="inesdata",
            )

        self.assertTrue(enabled)
        self.assertIn("Kafka transfer validation is available", stdout.getvalue())
        confirm.assert_called_once_with("Run Kafka validation suites too?", default=False)

    def test_level6_kafka_prompt_defaults_to_disabled_for_non_interactive_runs(self):
        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys.stdin, "isatty", return_value=False),
            mock.patch("builtins.input", side_effect=AssertionError("prompt should not run")),
            contextlib.redirect_stdout(stdout),
        ):
            enabled = main._resolve_level6_kafka_enabled_for_run(
                KafkaReadyAdapter(),
                deployer_name="inesdata",
            )

        self.assertFalse(enabled)
        self.assertIn("non-interactive", stdout.getvalue())
        self.assertIn("PIONERA_LEVEL6_RUN_KAFKA=true", stdout.getvalue())

    def test_level6_kafka_skip_flag_suppresses_prompt(self):
        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        def kafka_skip_env_flag(name, default=False):
            if name == "PIONERA_LEVEL6_SKIP_KAFKA":
                return True
            if name == "PIONERA_LEVEL6_RUN_KAFKA":
                return False
            return default

        stdout = io.StringIO()
        with mock.patch.object(main, "_env_flag", side_effect=kafka_skip_env_flag), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch("builtins.input", side_effect=AssertionError("prompt should not run")), contextlib.redirect_stdout(stdout):
            enabled = main._resolve_level6_kafka_enabled_for_run(
                KafkaReadyAdapter(),
                deployer_name="inesdata",
                flag_enabled=main._env_flag,
            )

        self.assertFalse(enabled)
        self.assertIn("PIONERA_LEVEL6_SKIP_KAFKA=true", stdout.getvalue())

    def test_level6_kafka_false_flags_do_not_suppress_interactive_prompt(self):
        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_LEVEL6_SKIP_KAFKA": "false",
                "PIONERA_LEVEL6_RUN_KAFKA": "false",
            },
            clear=True,
        ), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch.object(
            main,
            "_interactive_confirm",
            return_value=True,
        ) as confirm:
            enabled = main._resolve_level6_kafka_enabled_for_run(
                KafkaReadyAdapter(),
                deployer_name="inesdata",
            )

        self.assertTrue(enabled)
        confirm.assert_called_once_with("Run Kafka validation suites too?", default=False)

    def test_action_result_prints_compact_level_summary_instead_of_raw_json(self):
        payload = {
            "status": "completed",
            "adapter": "edc",
            "topology": "local",
            "levels": [
                {
                    "level": 4,
                    "name": "Deploy Connectors",
                    "status": "completed",
                    "result": ["conn-a", "conn-b"],
                }
            ],
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertTrue(output.startswith("\nResult: Succeeded\n"))
        self.assertIn("Result: Succeeded", output)
        self.assertIn("Adapter: edc", output)
        self.assertIn("Level 4 - Deploy Connectors: Succeeded (2 items)", output)
        self.assertNotIn("{", output)

    def test_action_result_prints_level6_completed_with_validation_failures(self):
        payload = {
            "status": "completed_with_validation_failures",
            "adapter": "inesdata",
            "topology": "local",
            "levels": [
                {
                    "level": 6,
                    "name": "Run Validation Tests",
                    "status": "completed_with_validation_failures",
                    "result": {
                        "validation_status": "failed",
                        "level6_validation_summary": {
                            "status": "failed",
                            "failures": [
                                {
                                    "suite": "AI Model Hub functional",
                                    "test": "PT5-MH-14",
                                    "reason": "UI asset list did not stabilize",
                                }
                            ],
                        },
                    },
                }
            ],
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Result: Completed with validation failures", output)
        self.assertIn("Level 6 - Run Validation Tests: Completed with validation failures", output)

    def test_action_result_prints_nested_level_hosts_summary(self):
        payload = {
            "status": "completed",
            "adapter": "inesdata",
            "topology": "local",
            "levels": [
                {
                    "level": 2,
                    "name": "Deploy Infrastructure",
                    "status": "completed",
                    "result": {},
                    "hosts_plan": {
                        "level_1_2": [
                            "auth.dev.ed.dataspaceunit.upm",
                            "admin.auth.dev.ed.dataspaceunit.upm",
                        ],
                    },
                    "hosts_sync": {
                        "status": "skipped",
                        "reason": "disabled",
                    },
                },
                {
                    "level": 3,
                    "name": "Deploy Dataspace",
                    "status": "completed",
                    "result": {},
                    "hosts_plan": {
                        "level_3": ["registration-service-demo.dev.ds.dataspaceunit.upm"],
                    },
                    "hosts_sync": {
                        "status": "updated",
                    },
                },
            ],
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Level 2 Hosts Level 1-2: 2", output)
        self.assertIn("- auth.dev.ed.dataspaceunit.upm", output)
        self.assertIn("- admin.auth.dev.ed.dataspaceunit.upm", output)
        self.assertIn("Level 3 Hosts Level 3: 1", output)
        self.assertIn("- registration-service-demo.dev.ds.dataspaceunit.upm", output)
        self.assertIn("Level 3 hosts sync: Succeeded", output)
        self.assertNotIn("Level 2 hosts sync: Skipped", output)

    def test_action_result_prints_compact_next_step_summary(self):
        payload = {
            "status": "completed",
            "deployer_name": "fake",
            "topology": "local",
            "dataspace": "fake-ds",
            "next_step": "Run Level 6 to validate the recreated dataspace and connectors.",
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Result: Succeeded", output)
        self.assertIn("Dataspace: fake-ds", output)
        self.assertIn("Next step: Run Level 6 to validate the recreated dataspace and connectors.", output)

    def test_action_result_prints_local_repair_summary(self):
        payload = {
            "status": "warning",
            "scope": "local repair",
            "adapter": "inesdata",
            "topology": "local",
            "doctor": {
                "status": "ready_with_warnings",
                "checks": [
                    {"name": "kubectl", "status": "ok"},
                    {"name": "minikube tunnel", "status": "warning"},
                ],
            },
            "hosts_plan": {
                "level_1_2": ["auth.dev.ed.dataspaceunit.upm"],
            },
            "missing_hostnames": ["registration-service-demo.dev.ds.dataspaceunit.upm"],
            "hosts_sync": {
                "status": "failed",
                "reason": "repair-error",
            },
            "connector_recovery": {
                "status": "skipped",
                "reason": "not-requested",
            },
            "public_endpoint_preflight": {
                "status": "failed",
                "failures": [{"label": "Registration service"}],
            },
            "next_step": "Start minikube tunnel and rerun local-repair.",
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Scope: local repair", output)
        self.assertIn("Doctor: Warning", output)
        self.assertIn("Doctor warnings: 1", output)
        self.assertIn("Hosts Level 1-2: 1", output)
        self.assertIn("Missing hostnames: 1", output)
        self.assertIn("Hosts sync: Failed (repair error)", output)
        self.assertIn("Connector recovery: Skipped (not requested)", output)
        self.assertIn("Public endpoints: Failed", output)
        self.assertIn("Public endpoints failures: 1", output)
        self.assertIn("Next step: Start minikube tunnel and rerun local-repair.", output)

    def test_action_result_prints_configuration_migration_warnings(self):
        payload = {
            "status": "completed",
            "adapter": "inesdata",
            "topology": "vm-single",
            "config_migration_warnings": [
                {
                    "key": "VM_EXTERNAL_IP",
                    "recommended_overlay_paths": [
                        "deployers/infrastructure/topologies/vm-single.config",
                        "deployers/infrastructure/topologies/vm-distributed.config",
                    ],
                }
            ],
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Configuration migration warnings: 1", output)
        self.assertIn(
            "- VM_EXTERNAL_IP -> deployers/infrastructure/topologies/vm-single.config, "
            "deployers/infrastructure/topologies/vm-distributed.config",
            output,
        )

    def test_action_result_prints_local_stability_summary(self):
        payload = {
            "status": "completed",
            "adapter": "inesdata",
            "topology": "local",
            "local_stability": {
                "postflight": {
                    "status": "warning",
                    "warnings": [{"name": "node_not_ready_delta"}],
                    "blocking_issues": [],
                }
            },
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Local stability: Warning", output)
        self.assertIn("Local stability warnings: 1", output)

    def test_action_result_prints_local_capacity_summary(self):
        payload = {
            "status": "completed",
            "adapter": "edc",
            "topology": "local",
            "local_capacity": {
                "preflight": {
                    "status": "failed",
                    "coexistence_detected": True,
                    "effective_memory_mb": 14336,
                    "required_memory_mb": 18432,
                }
            },
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Local coexistence capacity: Failed", output)
        self.assertIn("Local coexistence memory: 14336/18432 MiB", output)

    def test_action_result_prints_local_adapter_switch_summary(self):
        payload = {
            "status": "completed",
            "adapter": "edc",
            "topology": "local",
            "local_capacity": {
                "install_preflight": {
                    "status": "passed",
                    "coexistence_detected": False,
                    "switch": {
                        "status": "completed",
                        "adapters_to_remove": ["inesdata"],
                        "deleted_namespaces": ["demo", "components"],
                    },
                }
            },
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Local adapter switch: removed inesdata", output)
        self.assertIn("Local adapter switch namespaces: demo, components", output)

    def test_action_result_prints_shared_foundation_scope_without_adapter_label(self):
        payload = {
            "status": "completed",
            "scope": "shared foundation",
            "adapter": "inesdata",
            "topology": "local",
            "levels": [
                {
                    "level": 1,
                    "name": "Setup Cluster",
                    "status": "completed",
                    "result": None,
                }
            ],
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Result: Succeeded", output)
        self.assertIn("Scope: shared foundation", output)
        self.assertNotIn("Adapter: inesdata", output)
        self.assertIn("Level 1 - Setup Cluster: Succeeded", output)

    def test_action_result_prints_level5_component_urls(self):
        payload = {
            "status": "completed",
            "adapter": "inesdata",
            "topology": "local",
            "levels": [
                {
                    "level": 5,
                    "name": "Deploy Components",
                    "status": "completed",
                    "result": {
                        "deployed": ["ontology-hub"],
                        "urls": {
                            "ontology-hub": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                        },
                    },
                }
            ],
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Level 5 - Deploy Components: Succeeded", output)
        self.assertIn("Level 5 URLs:", output)
        self.assertIn("Ontology Hub: http://ontology-hub-demo.dev.ds.dataspaceunit.upm", output)

    def test_action_result_prints_level5_component_support_breakdown(self):
        payload = {
            "status": "completed",
            "adapter": "edc",
            "topology": "local",
            "levels": [
                {
                    "level": 5,
                    "name": "Deploy Components",
                    "status": "completed",
                    "result": {
                        "deployed": [],
                        "urls": {},
                        "configured": ["ontology-hub", "ai-model-hub"],
                        "deployable": [],
                        "pending_support": ["ontology-hub", "ai-model-hub"],
                        "unsupported": [],
                        "unknown": [],
                    },
                }
            ],
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Level 5 configured components: 2", output)
        self.assertIn("Level 5 pending adapter support: 2", output)
        self.assertIn("- ontology-hub", output)
        self.assertIn("- ai-model-hub", output)

    def test_action_result_prints_available_access_urls_in_multiline_format(self):
        payload = {
            "status": "available",
            "adapter": "inesdata",
            "topology": "local",
            "dataspace": "demo",
            "access_urls_view": True,
            "urls": {
                "public_portal_login": "http://demo.dev.ds.dataspaceunit.upm",
            },
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("URLs:", output)
        self.assertIn("- Public Portal Login:", output)
        self.assertIn("  http://demo.dev.ds.dataspaceunit.upm", output)

    def test_action_result_prints_vm_single_local_browser_access(self):
        payload = {
            "status": "available",
            "adapter": "edc",
            "topology": "vm-single",
            "dataspace": "demoedc",
            "access_urls_view": True,
            "urls": {
                "registration_service": "http://registration-service-demoedc.dev.ds.dataspaceunit.upm",
            },
            "local_browser_access": {
                "vm_ip": "192.168.122.134",
                "minikube_ip": "192.168.49.2",
                "ssh_user": "pionera",
                "tunnel_command_80": (
                    "sudo ssh -N -L 127.0.0.1:80:192.168.49.2:80 "
                    "pionera@192.168.122.134"
                ),
                "tunnel_command_8080": (
                    "ssh -N -L 127.0.0.1:8080:192.168.49.2:80 "
                    "pionera@192.168.122.134"
                ),
                "hosts_entries": [
                    "127.0.0.1 registration-service-demoedc.dev.ds.dataspaceunit.upm",
                ],
                "browser_urls": [
                    "http://registration-service-demoedc.dev.ds.dataspaceunit.upm",
                ],
            },
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Local Browser Access:", output)
        self.assertIn("VM IP: 192.168.122.134", output)
        self.assertIn("Minikube IP: 192.168.49.2", output)
        self.assertIn("sudo ssh -N -L 127.0.0.1:80:192.168.49.2:80 pionera@192.168.122.134", output)
        self.assertIn("127.0.0.1 registration-service-demoedc.dev.ds.dataspaceunit.upm", output)

    def test_kafka_transfer_results_are_printed_with_neutral_summary(self):
        results = [
            {
                "provider": "conn-provider",
                "consumer": "conn-consumer",
                "status": "passed",
                "source_topic": "source-topic",
                "destination_topic": "destination-topic",
                "artifact_path": "/tmp/experiment/kafka_transfer/conn-provider__conn-consumer.json",
                "steps": [
                    {
                        "name": "create_kafka_asset",
                        "status": "passed",
                        "http_status": 200,
                        "asset_id": "asset-1",
                    },
                    {
                        "name": "measure_kafka_transfer_latency",
                        "status": "passed",
                        "messages_consumed": 10,
                        "average_latency_ms": 7.2,
                    },
                ],
                "metrics": {
                    "messages_produced": 10,
                    "messages_consumed": 10,
                    "average_latency_ms": 7.2,
                    "p50_latency_ms": 6.8,
                    "p95_latency_ms": 9.1,
                    "p99_latency_ms": 9.8,
                    "throughput_messages_per_second": 18.5,
                    "message_samples": [
                        {
                            "message_id": "msg-1",
                            "status": "consumed",
                            "latency_ms": 6.5,
                        }
                    ],
                },
            }
        ]

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_kafka_edc_results(results)

        output = stdout.getvalue()
        self.assertIn("Kafka transfer validation results", output)
        self.assertIn("✓ Kafka transfer: conn-provider -> conn-consumer", output)
        self.assertIn("Steps:", output)
        self.assertIn("✓ create_kafka_asset", output)
        self.assertIn("✓ measure_kafka_transfer_latency", output)
        self.assertIn("Messages: produced=10 consumed=10", output)
        self.assertIn("Latency: avg=7.2ms p50=6.8ms p95=9.1ms p99=9.8ms", output)
        self.assertIn("Throughput: 18.5 msg/s", output)
        self.assertIn("Summary: ✓ 1  ✗ 0  - 0", output)
        self.assertNotIn("EDC+Kafka", output)
        self.assertNotIn("Message: id=msg-1", output)
        self.assertNotIn("PASS", output)
        self.assertNotIn("FAIL", output)
        self.assertNotIn("SKIP", output)

    def test_kafka_transfer_results_mark_failed_and_skipped_status_with_icons(self):
        results = [
            {
                "provider": "conn-provider",
                "consumer": "conn-consumer",
                "status": "failed",
                "error": {"message": "boom"},
                "steps": [{"name": "create_asset", "status": "failed"}],
            },
            {
                "provider": "conn-provider",
                "consumer": "conn-consumer",
                "status": "skipped",
                "reason": "not_supported",
                "steps": [{"name": "create_asset", "status": "skipped"}],
            },
        ]

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_kafka_edc_results(results)

        output = stdout.getvalue()
        self.assertIn("✗ Kafka transfer: conn-provider -> conn-consumer (boom)", output)
        self.assertIn("✗ create_asset", output)
        self.assertIn("- Kafka transfer: conn-provider -> conn-consumer (not_supported)", output)
        self.assertIn("- create_asset", output)
        self.assertIn("Summary: ✓ 0  ✗ 1  - 1", output)
        self.assertNotIn("FAIL", output)
        self.assertNotIn("SKIP", output)

    def test_kafka_transfer_results_can_print_message_samples_when_enabled(self):
        results = [
            {
                "provider": "conn-provider",
                "consumer": "conn-consumer",
                "status": "passed",
                "metrics": {
                    "messages_produced": 1,
                    "messages_consumed": 1,
                    "average_latency_ms": 3.4,
                    "p50_latency_ms": 3.4,
                    "p95_latency_ms": 3.4,
                    "p99_latency_ms": 3.4,
                    "throughput_messages_per_second": 2.0,
                    "message_samples": [
                        {
                            "message_id": "msg-1",
                            "status": "consumed",
                            "latency_ms": 3.4,
                        }
                    ],
                },
            }
        ]

        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"PIONERA_KAFKA_TRANSFER_LOG_MESSAGES": "true"}, clear=False):
            with contextlib.redirect_stdout(stdout):
                main._print_kafka_edc_results(results)

        self.assertIn("Message: id=msg-1 status=consumed latency=3.4ms", stdout.getvalue())

    def test_level6_kafka_log_completes_results_missing_from_progress_callback(self):
        class KafkaReadyAdapter:
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        class NoopFallback:
            def __init__(self, *args, **kwargs):
                pass

            def activate_if_needed(self):
                return False

            def close(self):
                return None

        results = [
            {"status": "passed", "provider": "conn-a", "consumer": "conn-b"},
            {"status": "passed", "provider": "conn-b", "consumer": "conn-a"},
        ]

        def run_kafka(connectors, experiment_dir, *, validator, experiment_storage, progress_callback=None):
            self.assertTrue(callable(progress_callback))
            progress_callback(results[0])
            return results

        stdout = io.StringIO()
        with mock.patch.object(main, "build_kafka_edc_validation_suite", return_value=mock.Mock()), mock.patch.object(
            main,
            "run_kafka_edc_validation",
            side_effect=run_kafka,
        ), mock.patch.object(
            main,
            "_Level6LocalHttpPortForwardFallback",
            NoopFallback,
        ), contextlib.redirect_stdout(stdout):
            returned = main.run_level6_kafka_edc_after_newman(
                KafkaReadyAdapter(),
                ["conn-a", "conn-b"],
                "/tmp/experiment",
                deployer_name="inesdata",
                kafka_enabled=True,
            )

        output = stdout.getvalue()
        self.assertEqual(returned, results)
        self.assertEqual(output.count("Kafka transfer: conn-a -> conn-b"), 1)
        self.assertEqual(output.count("Kafka transfer: conn-b -> conn-a"), 1)
        self.assertIn("Summary: ✓ 2  ✗ 0  - 0", output)


class NamespacePlanSummaryTests(unittest.TestCase):
    def test_namespace_plan_summary_marks_compact_layout_as_active(self):
        context = types.SimpleNamespace(
            namespace_profile="compact",
            namespace_roles={
                "registration_service_namespace": "demo",
                "provider_namespace": "demo",
                "consumer_namespace": "demo",
            },
            planned_namespace_roles={
                "registration_service_namespace": "demo",
                "provider_namespace": "demo",
                "consumer_namespace": "demo",
            },
        )

        summary = main._build_namespace_plan_summary(context)

        self.assertEqual(summary["status"], "active")
        self.assertEqual(summary["requested_profile"], "compact")
        self.assertEqual(summary["change_count"], 0)
        self.assertEqual(summary["changed_roles"], {})
        self.assertEqual(summary["notes"], [])

    def test_namespace_plan_summary_marks_role_aligned_layout_as_preview_only(self):
        context = types.SimpleNamespace(
            namespace_profile="role-aligned",
            namespace_roles={
                "registration_service_namespace": "demo",
                "provider_namespace": "demo",
                "consumer_namespace": "demo",
            },
            planned_namespace_roles={
                "registration_service_namespace": "demo-core",
                "provider_namespace": "demo-provider",
                "consumer_namespace": "demo-consumer",
            },
        )

        summary = main._build_namespace_plan_summary(context)

        self.assertEqual(summary["status"], "preview-only")
        self.assertEqual(summary["requested_profile"], "role-aligned")
        self.assertEqual(summary["change_count"], 3)
        self.assertEqual(
            summary["changed_roles"]["registration_service_namespace"],
            {"current": "demo", "planned": "demo-core"},
        )
        self.assertIn("preview-only", " ".join(summary["notes"]).lower())


class EdcDashboardReadinessTests(unittest.TestCase):
    def _context(self):
        return types.SimpleNamespace(
            dataspace_name="demoedc",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
            namespace_roles=types.SimpleNamespace(
                registration_service_namespace="demoedc",
                provider_namespace="demoedc",
                consumer_namespace="demoedc",
            ),
            config={
                "KC_INTERNAL_URL": "http://common-srvs-keycloak.common-srvs.svc.cluster.local",
                "KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm",
            },
        )

    def _role_aligned_context(self):
        return types.SimpleNamespace(
            dataspace_name="demoedc",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
            namespace_profile="role-aligned",
            namespace_roles=types.SimpleNamespace(
                registration_service_namespace="demoedc",
                provider_namespace="demoedc",
                consumer_namespace="demoedc",
            ),
            planned_namespace_roles=types.SimpleNamespace(
                registration_service_namespace="demoedc-core",
                provider_namespace="demoedc-provider",
                consumer_namespace="demoedc-consumer",
            ),
            config={
                "KC_INTERNAL_URL": "http://common-srvs-keycloak.common-srvs.svc.cluster.local",
                "KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm",
            },
        )

    def test_probe_edc_dashboard_readiness_requires_public_http_routes(self):
        context = self._context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/edc-dashboard"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/edc-dashboard-api/auth/me"):
                return types.SimpleNamespace(status_code=401, headers={})
            if url.endswith("/management/v3/assets/request"):
                return types.SimpleNamespace(status_code=405, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            return_value=(True, "1 endpoint address(es)"),
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get):
            readiness = main._probe_edc_dashboard_readiness(context)

        self.assertEqual(readiness["status"], "passed")
        http_gates = [gate for gate in readiness["gates"] if gate["gate"].startswith("dashboard-route:")]
        self.assertEqual(len(http_gates), 2)
        keycloak_gate = next(gate for gate in readiness["gates"] if gate["gate"] == "keycloak-metadata")
        self.assertEqual(
            keycloak_gate["url"],
            "http://auth.dev.ed.dataspaceunit.upm/realms/demoedc/.well-known/openid-configuration",
        )

    def test_probe_edc_dashboard_readiness_uses_planned_role_namespaces_in_role_aligned(self):
        context = self._role_aligned_context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/edc-dashboard"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/edc-dashboard-api/auth/me"):
                return types.SimpleNamespace(status_code=401, headers={})
            if url.endswith("/management/v3/assets/request"):
                return types.SimpleNamespace(status_code=405, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        endpoint_calls = []

        def fake_endpoint_ready(namespace, service_name):
            endpoint_calls.append((namespace, service_name))
            return True, "1 endpoint address(es)"

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            side_effect=fake_endpoint_ready,
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get):
            readiness = main._probe_edc_dashboard_readiness(context)

        self.assertEqual(readiness["status"], "passed")
        self.assertEqual(
            readiness["connector_namespaces"],
            {
                "conn-citycounciledc-demoedc": "demoedc-provider",
                "conn-companyedc-demoedc": "demoedc-consumer",
            },
        )
        self.assertEqual(
            endpoint_calls,
            [
                ("demoedc-provider", "conn-citycounciledc-demoedc-dashboard"),
                ("demoedc-provider", "conn-citycounciledc-demoedc-dashboard-proxy"),
                ("demoedc-consumer", "conn-companyedc-demoedc-dashboard"),
                ("demoedc-consumer", "conn-companyedc-demoedc-dashboard-proxy"),
            ],
        )

    def test_probe_edc_dashboard_readiness_rejects_http_503_even_with_ready_endpoints(self):
        context = self._context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/edc-dashboard"):
                return types.SimpleNamespace(status_code=503, headers={})
            if url.endswith("/edc-dashboard-api/auth/me"):
                return types.SimpleNamespace(status_code=401, headers={})
            if url.endswith("/management/v3/assets/request"):
                return types.SimpleNamespace(status_code=405, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            return_value=(True, "1 endpoint address(es)"),
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get):
            readiness = main._probe_edc_dashboard_readiness(context)

        self.assertEqual(readiness["status"], "failed")
        failing_gate = next(
            gate
            for gate in readiness["gates"]
            if gate["gate"] == "dashboard-route:conn-citycounciledc-demoedc"
        )
        self.assertFalse(failing_gate["ready"])
        self.assertEqual(failing_gate["detail"], "HTTP 503")


class InesdataPortalReadinessTests(unittest.TestCase):
    def _context(self):
        runtime_dir = os.path.join("/tmp", "inesdata-readiness-runtime")
        os.makedirs(runtime_dir, exist_ok=True)
        credentials_path = os.path.join(
            runtime_dir,
            "credentials-connector-conn-citycouncil-demo.json",
        )
        with open(credentials_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "connector_user": {
                        "user": "user-conn-citycouncil-demo",
                        "passwd": "change-me",
                    }
                },
                handle,
            )
        credentials_path = os.path.join(
            runtime_dir,
            "credentials-connector-conn-company-demo.json",
        )
        with open(credentials_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "connector_user": {
                        "user": "user-conn-company-demo",
                        "passwd": "change-me",
                    }
                },
                handle,
            )
        return types.SimpleNamespace(
            dataspace_name="demo",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=["conn-citycouncil-demo", "conn-company-demo"],
            runtime_dir=runtime_dir,
            namespace_roles=types.SimpleNamespace(
                registration_service_namespace="demo",
                provider_namespace="demo",
                consumer_namespace="demo",
            ),
            config={
                "KC_INTERNAL_URL": "http://common-srvs-keycloak.common-srvs.svc.cluster.local",
                "KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm",
            },
        )

    def _role_aligned_context(self):
        context = self._context()
        context.namespace_profile = "role-aligned"
        context.planned_namespace_roles = types.SimpleNamespace(
            registration_service_namespace="demo-core",
            provider_namespace="demo-provider",
            consumer_namespace="demo-consumer",
        )
        return context

    def test_probe_inesdata_portal_readiness_requires_public_http_routes(self):
        context = self._context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/inesdata-connector-interface/"):
                return types.SimpleNamespace(status_code=200, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        def fake_http_post(url, **kwargs):
            if url.endswith("/protocol/openid-connect/token"):
                return types.SimpleNamespace(status_code=200, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            return_value=(True, "1 endpoint address(es)"),
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get), mock.patch.object(
            main.requests,
            "post",
            side_effect=fake_http_post,
        ):
            readiness = main._probe_inesdata_portal_readiness(context)

        self.assertEqual(readiness["status"], "passed")
        portal_gates = [gate for gate in readiness["gates"] if gate["gate"].startswith("portal-route:")]
        self.assertEqual(len(portal_gates), 2)
        keycloak_gate = next(gate for gate in readiness["gates"] if gate["gate"] == "keycloak-metadata")
        self.assertEqual(
            keycloak_gate["url"],
            "http://auth.dev.ed.dataspaceunit.upm/realms/demo/.well-known/openid-configuration",
        )
        token_gate = next(
            gate for gate in readiness["gates"]
            if gate["gate"] == "keycloak-password-grant:conn-citycouncil-demo"
        )
        self.assertTrue(token_gate["ready"])
        self.assertEqual(
            token_gate["url"],
            "http://auth.dev.ed.dataspaceunit.upm/realms/demo/protocol/openid-connect/token",
        )

    def test_probe_inesdata_portal_readiness_vm_distributed_uses_configured_public_urls(self):
        context = self._context()
        context.topology = "vm-distributed"
        context.dataspace_name = "pionera"
        context.ds_domain_base = "pionera.oeg.fi.upm.es"
        context.connectors = ["conn-org2-pionera", "conn-org3-pionera"]
        context.config = {
            "KC_INTERNAL_URL": "http://auth.pionera.oeg.fi.upm.es",
            "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
            "VM_PROVIDER_CONNECTORS": "org2",
            "VM_CONSUMER_CONNECTORS": "org3",
            "VM_PROVIDER_PUBLIC_URL": "https://org2.pionera.oeg.fi.upm.es",
            "VM_CONSUMER_PUBLIC_URL": "https://org3.pionera.oeg.fi.upm.es",
        }
        for connector in context.connectors:
            with open(
                os.path.join(context.runtime_dir, f"credentials-connector-{connector}.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {"connector_user": {"user": f"user-{connector}", "passwd": "change-me"}},
                    handle,
                )

        probed_get_urls = []
        probed_post_urls = []

        def fake_http_get(url, **kwargs):
            probed_get_urls.append(url)
            return types.SimpleNamespace(status_code=200, headers={})

        def fake_http_post(url, **kwargs):
            probed_post_urls.append(url)
            return types.SimpleNamespace(status_code=200, headers={})

        with mock.patch.object(main, "_kubectl_endpoint_ready") as endpoint_ready, mock.patch.object(
            main.requests,
            "get",
            side_effect=fake_http_get,
        ), mock.patch.object(
            main.requests,
            "post",
            side_effect=fake_http_post,
        ):
            readiness = main._probe_inesdata_portal_readiness(context)

        self.assertEqual(readiness["status"], "passed")
        self.assertFalse(readiness["check_internal_endpoints"])
        endpoint_ready.assert_not_called()
        self.assertIn(
            "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera/.well-known/openid-configuration",
            probed_get_urls,
        )
        self.assertIn("https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/", probed_get_urls)
        self.assertIn("https://org3.pionera.oeg.fi.upm.es/inesdata-connector-interface/", probed_get_urls)
        self.assertEqual(
            probed_post_urls,
            [
                "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera/protocol/openid-connect/token",
                "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera/protocol/openid-connect/token",
            ],
        )

    def test_probe_inesdata_portal_readiness_uses_runtime_role_namespaces_in_role_aligned(self):
        context = self._role_aligned_context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/inesdata-connector-interface/"):
                return types.SimpleNamespace(status_code=200, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        def fake_http_post(url, **kwargs):
            if url.endswith("/protocol/openid-connect/token"):
                return types.SimpleNamespace(status_code=200, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        endpoint_calls = []

        def fake_endpoint_ready(namespace, service_name):
            endpoint_calls.append((namespace, service_name))
            return True, "1 endpoint address(es)"

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            side_effect=fake_endpoint_ready,
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get), mock.patch.object(
            main.requests,
            "post",
            side_effect=fake_http_post,
        ):
            readiness = main._probe_inesdata_portal_readiness(context)

        self.assertEqual(readiness["status"], "passed")
        self.assertEqual(
            readiness["connector_namespaces"],
            {
                "conn-citycouncil-demo": "demo",
                "conn-company-demo": "demo",
            },
        )
        self.assertEqual(
            endpoint_calls,
            [
                ("demo", "conn-citycouncil-demo-interface"),
                ("demo", "conn-company-demo-interface"),
            ],
        )

    def test_probe_inesdata_portal_readiness_rejects_http_503_even_with_ready_services(self):
        context = self._context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/inesdata-connector-interface/"):
                return types.SimpleNamespace(status_code=503, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        def fake_http_post(url, **kwargs):
            if url.endswith("/protocol/openid-connect/token"):
                return types.SimpleNamespace(status_code=200, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            return_value=(True, "1 endpoint address(es)"),
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get), mock.patch.object(
            main.requests,
            "post",
            side_effect=fake_http_post,
        ):
            readiness = main._probe_inesdata_portal_readiness(context)

        self.assertEqual(readiness["status"], "failed")
        failing_gate = next(
            gate
            for gate in readiness["gates"]
            if gate["gate"] == "portal-route:conn-citycouncil-demo"
        )
        self.assertFalse(failing_gate["ready"])
        self.assertEqual(failing_gate["detail"], "HTTP 503")

    def test_probe_inesdata_portal_readiness_rejects_redirect_only_portal_route(self):
        context = self._context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/inesdata-connector-interface/"):
                return types.SimpleNamespace(status_code=301, headers={"Location": "/inesdata-connector-interface/"})
            raise AssertionError(f"Unexpected URL probed: {url}")

        def fake_http_post(url, **kwargs):
            if url.endswith("/protocol/openid-connect/token"):
                return types.SimpleNamespace(status_code=200, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            return_value=(True, "1 endpoint address(es)"),
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get), mock.patch.object(
            main.requests,
            "post",
            side_effect=fake_http_post,
        ):
            readiness = main._probe_inesdata_portal_readiness(context)

        self.assertEqual(readiness["status"], "failed")
        failing_gate = next(
            gate
            for gate in readiness["gates"]
            if gate["gate"] == "portal-route:conn-citycouncil-demo"
        )
        self.assertFalse(failing_gate["ready"])
        self.assertEqual(failing_gate["detail"], "HTTP 301 -> /inesdata-connector-interface/")

    def test_probe_inesdata_portal_readiness_rejects_keycloak_password_grant_503(self):
        context = self._context()

        def fake_http_get(url, **kwargs):
            if url.endswith("/.well-known/openid-configuration"):
                return types.SimpleNamespace(status_code=200, headers={})
            if url.endswith("/inesdata-connector-interface/"):
                return types.SimpleNamespace(status_code=200, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        def fake_http_post(url, **kwargs):
            if url.endswith("/protocol/openid-connect/token"):
                return types.SimpleNamespace(status_code=503, headers={})
            raise AssertionError(f"Unexpected URL probed: {url}")

        with mock.patch.object(
            main,
            "_kubectl_endpoint_ready",
            return_value=(True, "1 endpoint address(es)"),
        ), mock.patch.object(main.requests, "get", side_effect=fake_http_get), mock.patch.object(
            main.requests,
            "post",
            side_effect=fake_http_post,
        ):
            readiness = main._probe_inesdata_portal_readiness(context)

        self.assertEqual(readiness["status"], "failed")
        failing_gate = next(
            gate
            for gate in readiness["gates"]
            if gate["gate"] == "keycloak-password-grant:conn-citycouncil-demo"
        )
        self.assertFalse(failing_gate["ready"])
        self.assertEqual(failing_gate["detail"], "HTTP 503")

    def test_wait_inesdata_portal_readiness_requires_consecutive_successful_polls(self):
        context = self._context()
        readiness_sequence = [
            {"status": "passed", "gates": []},
            {"status": "passed", "gates": []},
        ]

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_INESDATA_PORTAL_STABLE_POLLS": "2",
                "PIONERA_INESDATA_PORTAL_READINESS_TIMEOUT_SECONDS": "5",
                "PIONERA_INESDATA_PORTAL_READINESS_POLL_SECONDS": "0",
            },
            clear=False,
        ), mock.patch.object(
            main,
            "_probe_inesdata_portal_readiness",
            side_effect=readiness_sequence,
        ) as readiness_probe, mock.patch.object(
            main,
            "_write_inesdata_portal_readiness",
            return_value="/tmp/portal_readiness.json",
        ):
            readiness = main._wait_for_inesdata_portal_readiness(context, experiment_dir="/tmp/exp")

        self.assertEqual(readiness["status"], "passed")
        self.assertEqual(readiness["stable_polls_required"], 2)
        self.assertEqual(readiness["stable_polls_observed"], 2)
        self.assertEqual(readiness["artifact"], "/tmp/portal_readiness.json")
        self.assertEqual(readiness_probe.call_count, 2)

    def test_run_available_access_urls_includes_component_urls_for_inesdata(self):
        adapter = FakeAdapter()
        fake_context = types.SimpleNamespace(
            config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            dataspace_name="demo",
            environment="DEV",
            connectors=["conn-citycouncil-demo"],
            components=["ontology-hub"],
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("inesdata", fake_context),
        ), mock.patch(
            "deployers.inesdata.access_urls.build_dataspace_access_urls",
            return_value={
                "public_portal_login": "http://demo.dev.ds.dataspaceunit.upm",
                "registration_service": "http://registration-service-demo.dev.ds.dataspaceunit.upm",
                "keycloak_realm": "http://keycloak.dev.ds.dataspaceunit.upm/realms/demo",
                "keycloak_admin_console": "http://keycloak-admin.dev.ds.dataspaceunit.upm/admin/demo/console/",
                "minio_api": "http://minio.dev.ed.dataspaceunit.upm",
                "minio_console": "http://console.minio-s3.dev.ds.dataspaceunit.upm",
            },
        ), mock.patch(
            "deployers.inesdata.access_urls.build_connector_access_urls",
            return_value={
                "connector_interface_login": "http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/inesdata-connector-interface/",
                "connector_management_api": "http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/management",
                "connector_protocol_api": "http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/protocol",
                "minio_bucket": "demo-conn-citycouncil-demo",
            },
        ):
            result = main.run_available_access_urls(adapter, deployer_name="inesdata", topology="local")

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["adapter"], "inesdata")
        self.assertEqual(result["dataspace"], "demo")
        self.assertEqual(
            result["urls"]["components"]["ontology-hub"],
            "http://ontology-hub.example.local",
        )
        self.assertEqual(
            result["urls"]["connectors"]["conn-citycouncil-demo"]["connector_interface_login"],
            "http://conn-citycouncil-demo.dev.ds.dataspaceunit.upm/inesdata-connector-interface/",
        )
        self.assertEqual(result["urls"]["minio_api"], "http://minio.dev.ed.dataspaceunit.upm")
        self.assertEqual(
            result["urls"]["connectors"]["conn-citycouncil-demo"]["minio_bucket"],
            "demo-conn-citycouncil-demo",
        )

    def test_run_available_access_urls_for_inesdata_does_not_require_click(self):
        adapter = FakeAdapter()
        fake_context = types.SimpleNamespace(
            config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            dataspace_name="demo",
            environment="DEV",
            connectors=["conn-citycouncil-demo"],
            components=[],
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("inesdata", fake_context),
        ), mock.patch.dict(
            sys.modules,
            {"click": None},
            clear=False,
        ):
            result = main.run_available_access_urls(adapter, deployer_name="inesdata", topology="local")

        self.assertEqual(result["status"], "available")
        self.assertEqual(
            result["urls"]["registration_service"],
            "http://registration-service-demo.dev.ds.dataspaceunit.upm",
        )

    def test_run_available_access_urls_for_vm_distributed_uses_org1_common_routes(self):
        adapter = FakeAdapter()
        fake_context = types.SimpleNamespace(
            config={
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            },
            dataspace_name="pionera",
            environment="DEV",
            connectors=[],
            components=[],
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("inesdata", fake_context),
        ):
            result = main.run_available_access_urls(adapter, deployer_name="inesdata", topology="vm-distributed")

        self.assertEqual(
            result["urls"]["keycloak_realm"],
            "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera",
        )
        self.assertEqual(result["urls"]["minio_api"], "https://org1.pionera.oeg.fi.upm.es")
        self.assertEqual(result["urls"]["minio_console"], "https://org1.pionera.oeg.fi.upm.es/s3-console/")
        self.assertNotIn("public_portal_login", result["urls"])
        self.assertEqual(
            result["urls"]["public_portal_backend_admin"],
            "https://org1.pionera.oeg.fi.upm.es/public-portal-backend/admin",
        )
        self.assertNotIn("registration_service", result["urls"])
        self.assertNotIn("http://auth.pionera.oeg.fi.upm.es", result["urls"].values())

    def test_run_available_access_urls_for_vm_distributed_uses_public_connector_routes(self):
        adapter = FakeAdapter()
        fake_context = types.SimpleNamespace(
            config={
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "VM_PROVIDER_CONNECTORS": "org2",
                "VM_CONSUMER_CONNECTORS": "org3",
            },
            dataspace_name="pionera",
            environment="DEV",
            connectors=["conn-org2-pionera", "conn-org3-pionera"],
            components=[],
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("inesdata", fake_context),
        ):
            result = main.run_available_access_urls(adapter, deployer_name="inesdata", topology="vm-distributed")

        org2_urls = result["urls"]["connectors"]["conn-org2-pionera"]
        org3_urls = result["urls"]["connectors"]["conn-org3-pionera"]
        self.assertEqual(org2_urls["connector_ingress"], "https://org2.pionera.oeg.fi.upm.es")
        self.assertEqual(
            org2_urls["connector_interface_login"],
            "https://org2.pionera.oeg.fi.upm.es/inesdata-connector-interface/",
        )
        self.assertEqual(org3_urls["connector_ingress"], "https://org3.pionera.oeg.fi.upm.es")
        self.assertNotIn("http://conn-org2-pionera.pionera.oeg.fi.upm.es", org2_urls.values())
        self.assertNotIn("http://conn-org3-pionera.pionera.oeg.fi.upm.es", org3_urls.values())

    def test_run_available_access_urls_for_vm_single_uses_public_connector_path_routes(self):
        adapter = FakeAdapter()
        fake_context = types.SimpleNamespace(
            config={
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            },
            dataspace_name="pionera",
            environment="DEV",
            connectors=["conn-org2-pionera"],
            components=[],
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("inesdata", fake_context),
        ):
            result = main.run_available_access_urls(adapter, deployer_name="inesdata", topology="vm-single")

        org2_urls = result["urls"]["connectors"]["conn-org2-pionera"]
        self.assertEqual(org2_urls["connector_ingress"], "https://org4.pionera.oeg.fi.upm.es/c/org2")
        self.assertEqual(
            org2_urls["connector_interface_login"],
            "https://org4.pionera.oeg.fi.upm.es/c/org2/inesdata-connector-interface/",
        )
        self.assertEqual(
            result["urls"]["keycloak_realm"],
            "https://org4.pionera.oeg.fi.upm.es/auth/realms/pionera",
        )
        self.assertNotIn("http://conn-org2-pionera.pionera.oeg.fi.upm.es", org2_urls.values())

    def test_level2_access_urls_preserve_keycloak_proxy_path(self):
        urls = main._level2_access_urls(
            {
                "keycloak_realm": "https://org1.pionera.oeg.fi.upm.es/auth/realms/pionera",
                "keycloak_admin_console": "https://org1.pionera.oeg.fi.upm.es/auth/admin/pionera/console/",
                "minio_console": "https://org1.pionera.oeg.fi.upm.es/s3-console/",
                "minio_api": "https://org1.pionera.oeg.fi.upm.es",
            }
        )

        self.assertEqual(urls["keycloak"], "https://org1.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(urls["keycloak_admin_console"], "https://org1.pionera.oeg.fi.upm.es/auth/admin/")
        self.assertEqual(urls["minio_console"], "https://org1.pionera.oeg.fi.upm.es/s3-console/")
        self.assertEqual(urls["minio_api"], "https://org1.pionera.oeg.fi.upm.es")

    def test_run_available_access_urls_includes_vm_single_local_browser_access(self):
        adapter = FakeAdapter()
        fake_context = types.SimpleNamespace(
            config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            dataspace_name="demoedc",
            environment="DEV",
            connectors=["conn-citycounciledc-demoedc"],
            components=["ontology-hub"],
        )

        def fake_command_stdout(command):
            if command == ["minikube", "ip"]:
                return "192.168.49.2"
            if command == ["hostname", "-I"]:
                return "192.168.122.134 172.17.0.1 192.168.49.1"
            return ""

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("edc", fake_context),
        ), mock.patch(
            "deployers.edc.bootstrap.common_access_urls",
            return_value={
                "keycloak_admin_console": "http://admin.auth.dev.ed.dataspaceunit.upm/admin",
            },
        ), mock.patch(
            "deployers.edc.bootstrap.build_connector_access_urls",
            return_value={
                "connector_ingress": "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
                "edc_dashboard_login": "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm/edc-dashboard/",
            },
        ), mock.patch(
            "deployers.edc.bootstrap.dataspace_domain_base",
            return_value="dev.ds.dataspaceunit.upm",
        ), mock.patch(
            "deployers.edc.bootstrap.access_protocol",
            return_value="http",
        ), mock.patch.object(
            main,
            "_command_stdout",
            side_effect=fake_command_stdout,
        ), mock.patch.dict(os.environ, {"USER": "pionera"}, clear=False):
            result = main.run_available_access_urls(adapter, deployer_name="edc", topology="vm-single")

        access = result["local_browser_access"]
        self.assertEqual(access["vm_ip"], "192.168.122.134")
        self.assertEqual(access["minikube_ip"], "192.168.49.2")
        self.assertEqual(access["ssh_user"], "pionera")
        self.assertEqual(
            access["tunnel_command_80"],
            "sudo ssh -N -L 127.0.0.1:80:192.168.49.2:80 pionera@192.168.122.134",
        )
        self.assertIn(
            "127.0.0.1 conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
            access["hosts_entries"],
        )
        self.assertIn(
            "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
            access["browser_urls"],
        )


class NoConnectorDeployAdapter:
    def deploy_infrastructure(self):
        return None

    def deploy_dataspace(self):
        return None


class NoConnectorsAdapter:
    def get_cluster_connectors(self):
        return []

    def deploy_connectors(self):
        return []


class FakeRunner:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self):
        return {"status": "run-ok", "adapter": type(self.kwargs["adapter"]).__name__}


class FakeValidationEngine:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self, connectors):
        return {"validated": list(connectors)}


class FakeMetricsCollector:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def collect(self, connectors, experiment_dir=None):
        return {
            "connectors": list(connectors),
            "experiment_dir": experiment_dir,
            "kafka_enabled": self.kwargs.get("kafka_enabled", False),
        }

    def collect_kafka_benchmark(self, experiment_dir, run_index=1):
        if not self.kwargs.get("kafka_enabled"):
            return None
        return {
            "kafka_benchmark": {
                "status": "completed",
                "run_index": run_index,
            }
        }


class FakeStorage:
    @staticmethod
    def create_experiment_directory():
        return tempfile.mkdtemp(prefix="cli-test-")

    @staticmethod
    def save_experiment_metadata(experiment_dir, connectors):
        return None

    @staticmethod
    def newman_reports_dir(experiment_dir):
        path = tempfile.mkdtemp(prefix="cli-newman-", dir=experiment_dir)
        return path

    @staticmethod
    def save_raw_request_metrics_jsonl(results, experiment_dir):
        return None

    @staticmethod
    def save_aggregated_metrics(results, experiment_dir):
        return None

    @staticmethod
    def save_newman_results_json(results, experiment_dir):
        return None

    @staticmethod
    def save_test_results_json(results, experiment_dir):
        return None

    @staticmethod
    def save_negotiation_metrics_json(results, experiment_dir):
        return None

    @staticmethod
    def save_newman_request_metrics(results, experiment_dir):
        return None

    @staticmethod
    def save_kafka_metrics_json(results, experiment_dir):
        return None

    @staticmethod
    def save_kafka_edc_results_json(results, experiment_dir):
        return None

    @staticmethod
    def save(results, experiment_dir=None, file_name="experiment_results.json"):
        return file_name

    @staticmethod
    def create_comparison_directory(experiment_a, experiment_b):
        return tempfile.mkdtemp(prefix="cli-compare-")

    @staticmethod
    def save_comparison_json(results, comparison_dir, file_name="comparison_summary.json"):
        return os.path.join(comparison_dir, file_name)

    @staticmethod
    def save_comparison_markdown(content, comparison_dir, file_name="comparison_report.md"):
        return os.path.join(comparison_dir, file_name)


class FakeReportGenerator:
    def __init__(self, storage=None):
        self.storage = storage

    def generate(self, experiment_id):
        return {"experiment_id": experiment_id, "summary": True}

    def compare(self, experiment_a, experiment_b):
        return {
            "comparison_dir": "/tmp/comparison",
            "experiment_a": {"experiment_id": experiment_a},
            "experiment_b": {"experiment_id": experiment_b},
        }


class DryRunAwareAdapter(FakeAdapter):
    def __init__(self, dry_run=False):
        super().__init__()
        self.dry_run = dry_run


class TopologyAwareAdapter(FakeAdapter):
    def __init__(self, dry_run=False, topology="local"):
        super().__init__()
        self.dry_run = dry_run
        self.topology = topology


class PreviewAwareAdapter(FakeAdapter):
    def __init__(self, dry_run=False, topology="local"):
        super().__init__()
        self.dry_run = dry_run
        self.topology = topology

    def preview_deploy(self):
        return {
            "status": "ready",
            "topology": self.topology,
            "details": ["preflight-ok"],
        }


class EnvironmentPreviewAdapter(FakeAdapter):
    def __init__(self, dry_run=False, topology="local"):
        super().__init__()
        self.dry_run = dry_run
        self.topology = topology

    def preview_deploy(self):
        return {
            "status": "ready",
            "topology": self.topology,
            "kubeconfig": os.environ.get("KUBECONFIG"),
            "kubeconfig_role": os.environ.get("PIONERA_KUBECONFIG_ROLE"),
        }


class DeployShadowPreviewAdapter(FakeAdapter):
    def __init__(self, dry_run=False, topology="local"):
        super().__init__()
        self.dry_run = dry_run
        self.topology = topology

    def preview_deploy(self):
        return {
            "status": "dataspace-required",
            "shared_common_services": {
                "status": "ready",
                "action": "reuse",
            },
            "shared_dataspace": {
                "status": "missing",
                "action": "deploy_dataspace",
            },
            "connectors": {
                "status": "bootstrap-required",
                "action": "deploy_connectors",
            },
            "next_step": "Deploy dataspace first.",
        }


class FakeDeployer:
    def __init__(self, adapter=None, topology="local"):
        self.adapter = adapter
        self.topology = topology

    def name(self):
        return "fake"

    @staticmethod
    def supported_topologies():
        return ["local"]

    def resolve_context(self, topology="local"):
        return {
            "deployer": "fake",
            "topology": topology,
            "environment": "DEV",
            "dataspace_name": "fake-ds",
            "ds_domain_base": "example.local",
            "connectors": ["conn-a", "conn-b"],
            "components": [],
            "namespace_roles": {
                "registration_service_namespace": "fake-ds",
                "provider_namespace": "fake-ds",
                "consumer_namespace": "fake-ds",
            },
            "runtime_dir": "/tmp/fake-ds",
            "config": {
                "DS_1_NAME": "fake-ds",
                "KC_PASSWORD": "super-secret-password",
                "MINIO_ADMIN_PASS": "minio-admin-pass",
                "VT_TOKEN": "token-value",
            },
        }

    def get_cluster_connectors(self, context=None):
        return ["conn-deployer-a", "conn-deployer-b"]

    def get_validation_profile(self, context):
        return {
            "adapter": "fake",
            "newman_enabled": True,
            "test_data_cleanup_enabled": False,
            "playwright_enabled": False,
        }

    def deploy_infrastructure(self, context):
        return {"status": "infra-ok", "dataspace": context.dataspace_name}

    def deploy_dataspace(self, context):
        return {"status": "dataspace-ok", "namespace": context.namespace_roles.registration_service_namespace}

    def deploy_connectors(self, context):
        return ["conn-deployer-a", "conn-deployer-b"]

    def deploy_components(self, context):
        return {"deployed": list(context.components), "urls": {}}


class FakeVmDeployer(FakeDeployer):
    @staticmethod
    def supported_topologies():
        return ["local", "vm-single", "vm-distributed"]

    def resolve_context(self, topology="local"):
        context = super().resolve_context(topology=topology)
        if topology == "vm-single":
            context["topology_profile"] = {
                "name": "vm-single",
                "default_address": "192.0.2.10",
                "role_addresses": {
                    "common": "192.0.2.10",
                    "registration_service": "192.0.2.10",
                    "connectors": "192.0.2.10",
                    "components": "192.0.2.10",
                },
                "ingress_external_ip": "192.0.2.10",
                "routing_mode": "host",
            }
        return context


class MainCliTests(unittest.TestCase):
    def setUp(self):
        self.vm_single_execution_patch = mock.patch.dict(
            os.environ,
            {"PIONERA_VM_SINGLE_LEVEL_EXECUTION_MODE": "local"},
            clear=False,
        )
        self.vm_single_execution_patch.start()
        self.addCleanup(self.vm_single_execution_patch.stop)
        self.fake_module = types.ModuleType("fake_adapter_module")
        self.fake_module.FakeAdapter = FakeAdapter
        self.fake_module.DryRunAwareAdapter = DryRunAwareAdapter
        self.fake_module.TopologyAwareAdapter = TopologyAwareAdapter
        self.fake_module.PreviewAwareAdapter = PreviewAwareAdapter
        self.fake_module.EnvironmentPreviewAdapter = EnvironmentPreviewAdapter
        self.fake_module.DeployShadowPreviewAdapter = DeployShadowPreviewAdapter
        self.fake_module.FakePublicAccessAdapter = FakePublicAccessAdapter
        self.fake_deployer_module = types.ModuleType("fake_deployer_module")
        self.fake_deployer_module.FakeDeployer = FakeDeployer
        self.fake_deployer_module.FakeVmDeployer = FakeVmDeployer
        self.registry = {"fake": "fake_adapter_module:FakeAdapter"}
        self.deployer_registry = {
            "fake": "fake_deployer_module:FakeDeployer",
            "fakevm": "fake_deployer_module:FakeVmDeployer",
            "edc": "fake_deployer_module:FakeDeployer",
        }
        self.module_patcher = mock.patch.dict(
            sys.modules,
            {
                "fake_adapter_module": self.fake_module,
                "fake_deployer_module": self.fake_deployer_module,
            },
        )
        self.module_patcher.start()

    def tearDown(self):
        self.module_patcher.stop()

    def test_list_command_prints_available_adapters(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main.main(["list"], adapter_registry=self.registry)

        self.assertEqual(result, ["fake"])
        self.assertIn("fake", stdout.getvalue())

    def test_build_validation_engine_wires_validation_cleanup_dependency(self):
        adapter = FakeAdapter()

        validation_engine = main.build_validation_engine(adapter)

        self.assertIsNotNone(validation_engine.validation_test_entities_absent)
        self.assertIsNotNone(validation_engine.transfer_storage_verifier)

    def test_build_validation_engine_uses_dynamic_dataspace_name_when_available(self):
        class DynamicConfig(FakeConfig):
            @staticmethod
            def dataspace_name():
                return "demoedc"

        adapter = FakeAdapter()
        adapter.config = DynamicConfig

        validation_engine = main.build_validation_engine(adapter)

        self.assertEqual(validation_engine.ds_name, "demoedc")

    def test_build_validation_engine_uses_deployer_context_public_runtime(self):
        adapter = FakeAdapter()
        context = types.SimpleNamespace(
            topology="vm-single",
            ds_domain_base="pionera.oeg.fi.upm.es",
            config={
                "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "MINIO_API_PUBLIC_URL": "http://minio.dev.ed.dataspaceunit.upm",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
            },
        )

        validation_engine = main.build_validation_engine(
            adapter,
            deployer_context=context,
        )
        env_vars = validation_engine.build_newman_env("conn-a", "conn-b")

        self.assertEqual(env_vars["keycloakUrl"], "https://org4.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(env_vars["dsDomain"], "pionera.oeg.fi.upm.es")

    def test_list_command_rejects_extra_argument(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exc:
            main.main(["list", "run"], adapter_registry=self.registry)

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("does not accept an additional command", stderr.getvalue())

    def test_missing_arguments_prints_help_and_returns_one(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main.main([], adapter_registry=self.registry)

        self.assertEqual(result, 1)
        self.assertIn("usage:", stdout.getvalue().lower())

    def test_no_argument_interactive_entry_prompts_for_topology_before_menu(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["main.py"]), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch("builtins.input", side_effect=["2", "Q"]), mock.patch.object(
            main,
            "_interactive_offer_vm_single_address_configuration",
            return_value=True,
        ) as vm_single_prompt, mock.patch.object(
            main,
            "_try_vm_single_cluster_runtime_switch",
            return_value={"allowed": True, "status": "skipped"},
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                None,
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(result["topology"], "vm-single")
        rendered = stdout.getvalue()
        self.assertIn("Available topologies:", rendered)
        self.assertIn("Active topology set to vm-single.", rendered)
        self.assertNotIn("Available cluster runtimes for vm-single:", rendered)
        self.assertIn("Active cluster runtime set to k3s.", rendered)
        self.assertIn("Topology: vm-single", rendered)
        self.assertIn("Cluster runtime: k3s", rendered)
        vm_single_prompt.assert_not_called()

    def test_menu_selecting_vm_distributed_without_adapter_does_not_report_incomplete_configuration(self):
        registry = {
            "fake": "fake_adapter_module:FakeAdapter",
            "other": "fake_adapter_module:FakeAdapter",
        }
        stdout = io.StringIO()
        with mock.patch(
            "builtins.input",
            side_effect=["T", "3", "Q"],
        ), mock.patch.object(
            main,
            "_vm_distributed_configuration_needs_attention",
            side_effect=AssertionError("configuration should wait for adapter selection"),
        ), contextlib.redirect_stdout(stdout):
            result = main.run_interactive_menu(
                adapter_registry=registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertIsNone(result["adapter"])
        self.assertEqual(result["topology"], "vm-distributed")
        rendered = stdout.getvalue()
        self.assertIn("Active topology set to vm-distributed.", rendered)
        self.assertNotIn("vm-distributed configuration is incomplete", rendered)

    def test_menu_vm_single_cluster_runtime_override_is_session_scoped(self):
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"PIONERA_CLUSTER_TYPE": "minikube"}, clear=False), mock.patch(
            "builtins.input",
            side_effect=["2", "Q"],
        ), mock.patch.object(
            main,
            "_interactive_offer_vm_single_address_configuration",
            return_value=True,
        ), mock.patch.object(
            main,
            "_try_vm_single_cluster_runtime_switch",
            return_value={"allowed": True, "status": "skipped"},
        ), contextlib.redirect_stdout(stdout):
            result = main.run_interactive_menu(
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
                topology="local",
                prompt_initial_topology=True,
            )

            self.assertEqual(result["status"], "exited")
            self.assertIn("Cluster runtime: k3s", stdout.getvalue())
            self.assertEqual(os.environ.get("PIONERA_CLUSTER_TYPE"), "minikube")

    def test_vm_single_k3s_persist_updates_preserve_existing_k3s_values(self):
        updates = main._cluster_runtime_config_updates(
            "k3s",
            existing_config={
                "K3S_KUBECONFIG": "/custom/k3s.yaml",
                "K3S_INSTALL_EXEC": "--disable=traefik --write-kubeconfig-mode=0640",
                "K3S_INGRESS_SERVICE_TYPE": "LoadBalancer",
            },
        )

        self.assertEqual(updates["CLUSTER_TYPE"], "k3s")
        self.assertEqual(updates["K3S_KUBECONFIG"], "/custom/k3s.yaml")
        self.assertEqual(updates["K3S_INSTALL_EXEC"], "--disable=traefik --write-kubeconfig-mode=0640")
        self.assertEqual(updates["K3S_INGRESS_SERVICE_TYPE"], "LoadBalancer")
        self.assertEqual(updates["K3S_SERVICE_NAME"], "k3s")

    def test_vm_single_runtime_switch_plan_deletes_active_minikube_before_k3s(self):
        with mock.patch.object(main, "_vm_single_minikube_active", return_value=True):
            plan = main._build_vm_single_cluster_runtime_switch_plan("k3s", previous_runtime="minikube")

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["detected_runtime"], "minikube")
        self.assertEqual(plan["cleanup_command"], ["minikube", "delete", "-p", "minikube"])
        self.assertEqual(plan["confirmation_token"], "SWITCH VM-SINGLE TO K3S")

    def test_vm_single_runtime_switch_plan_rejects_minikube_target(self):
        with self.assertRaisesRegex(ValueError, "Use k3s"):
            main._build_vm_single_cluster_runtime_switch_plan("minikube", previous_runtime="k3s")

    def test_vm_single_runtime_switch_decline_blocks_menu_switch(self):
        plan = {
            "status": "planned",
            "target_runtime": "k3s",
            "detected_runtime": "minikube",
            "cleanup_command": ["minikube", "delete", "-p", "minikube"],
            "confirmation_token": "SWITCH VM-SINGLE TO K3S",
        }

        stdout = io.StringIO()
        with mock.patch.object(main, "_build_vm_single_cluster_runtime_switch_plan", return_value=plan), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=False,
        ), contextlib.redirect_stdout(stdout):
            result = main._try_vm_single_cluster_runtime_switch("k3s", previous_runtime="minikube")

        self.assertFalse(result["allowed"])
        self.assertEqual(result["status"], "declined")
        self.assertIn("Cluster runtime switch cancelled", stdout.getvalue())

    def test_vm_single_k3s_persist_replaces_generic_user_kubeconfig(self):
        updates = main._cluster_runtime_config_updates(
            "k3s",
            existing_config={"K3S_KUBECONFIG": "/home/pionera/.kube/config"},
        )

        self.assertEqual(updates["CLUSTER_TYPE"], "k3s")
        self.assertEqual(updates["K3S_KUBECONFIG"], "/etc/rancher/k3s/k3s.yaml")
        self.assertEqual(updates["K3S_INGRESS_SERVICE_TYPE"], "LoadBalancer")

    def test_vm_single_k3s_address_detection_prefers_vm_ip_over_minikube_ip(self):
        def fake_stdout(args):
            if args == ["hostname", "-I"]:
                return "198.51.100.20 172.17.0.1"
            if args == ["minikube", "ip"]:
                return "192.0.2.10"
            return ""

        with mock.patch.object(main, "_effective_vm_single_cluster_type", return_value="k3s"), mock.patch.object(
            main,
            "_command_stdout",
            side_effect=fake_stdout,
        ):
            candidates = main._detect_vm_single_address_candidates()

        self.assertEqual(candidates["recommended_source"], "vm")
        self.assertEqual(candidates["recommended_address"], "198.51.100.20")

    def test_vm_single_k3s_level1_sync_replaces_stale_minikube_addresses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "deployer.config")
            example_path = os.path.join(tmpdir, "deployer.config.example")
            overlay_path = os.path.join(tmpdir, "topologies", "vm-single.config")
            with open(example_path, "w", encoding="utf-8") as handle:
                handle.write("ENVIRONMENT=DEV\n")
            os.makedirs(os.path.dirname(overlay_path), exist_ok=True)
            with open(overlay_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "CLUSTER_TYPE=k3s\n"
                    "VM_EXTERNAL_IP=192.0.2.10\n"
                    "VM_COMMON_IP=192.0.2.10\n"
                    "INGRESS_EXTERNAL_IP=192.0.2.10\n"
                )

            with mock.patch.object(
                main,
                "_infrastructure_deployer_config_path",
                return_value=config_path,
            ), mock.patch.object(
                main,
                "_infrastructure_deployer_config_example_path",
                return_value=example_path,
            ), mock.patch.object(
                main,
                "_detect_vm_single_address_candidates",
                return_value={
                    "vm_ip": "198.51.100.20",
                    "minikube_ip": "192.0.2.10",
                    "recommended_address": "198.51.100.20",
                    "recommended_source": "vm",
                    "cluster_type": "k3s",
                },
            ):
                result = main._synchronize_vm_single_addresses_after_level1()

            with open(overlay_path, "r", encoding="utf-8") as handle:
                config_text = handle.read()

        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["source"], "vm")
        self.assertIn("VM_EXTERNAL_IP=198.51.100.20\n", config_text)
        self.assertIn("VM_COMMON_IP=198.51.100.20\n", config_text)
        self.assertIn("INGRESS_EXTERNAL_IP=198.51.100.20\n", config_text)

    def test_menu_command_exits_without_running_actions(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["Q"]), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(result["adapter"], "fake")
        self.assertEqual(result["topology"], "local")
        self.assertIn("DATASPACE VALIDATION ENVIRONMENT", stdout.getvalue())
        self.assertIn("Topology: local", stdout.getvalue())
        self.assertIn("[Full Deployment]", stdout.getvalue())
        self.assertIn("[Operations]", stdout.getvalue())
        self.assertIn("T - Select topology", stdout.getvalue())
        self.assertIn("K - Select cluster runtime", stdout.getvalue())
        self.assertIn("X - Recreate dataspace", stdout.getvalue())
        self.assertIn("[Developer]", stdout.getvalue())
        self.assertIn("L - Build and Deploy Local Images", stdout.getvalue())
        self.assertIn("[Validation]", stdout.getvalue())
        self.assertIn("F - Dataspace Interoperability Tests", stdout.getvalue())
        self.assertIn("I - INESData UI Tests", stdout.getvalue())
        self.assertIn("O - Ontology Hub UI Tests", stdout.getvalue())
        self.assertIn("A - AI Model Hub UI Tests", stdout.getvalue())
        self.assertIn("V - Semantic Virtualization UI Tests", stdout.getvalue())
        self.assertIn("? - Help", stdout.getvalue())

    def test_menu_help_explains_available_options(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["?", "Q"]), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertIn("MENU HELP", stdout.getvalue())
        self.assertIn("0 - Use for a fresh or full rebuild", stdout.getvalue())
        self.assertIn("4 - Use when connector deployments changed", stdout.getvalue())
        self.assertIn("S - Use when you want to preselect the adapter", stdout.getvalue())
        self.assertIn("T - Use when you want to change the active topology", stdout.getvalue())
        self.assertIn("K - Use when vm-single is active", stdout.getvalue())
        self.assertIn("H - Use to inspect or apply local hosts entries", stdout.getvalue())
        self.assertIn("U - Use to print access URLs derived from the selected adapter config", stdout.getvalue())
        self.assertIn("J - Use when an existing dataspace needs one more connector", stdout.getvalue())
        self.assertIn("X - Use only when you intentionally want to destroy and recreate", stdout.getvalue())
        self.assertIn("asks for one automatically", stdout.getvalue())
        self.assertIn("[Developer]", stdout.getvalue())
        self.assertIn("B - Use on a clean machine or after dependency issues", stdout.getvalue())
        self.assertIn("L - Use during development after changing local images", stdout.getvalue())
        self.assertIn("[Validation]", stdout.getvalue())
        self.assertIn("Newman connector tests from Kafka transfer tests", stdout.getvalue())
        self.assertIn("I - Use to validate the INESData portal experience", stdout.getvalue())
        self.assertIn("A - Use when AI Model Hub UI changed", stdout.getvalue())
        self.assertIn("V - Use when Semantic Virtualization UI/API browser reachability changed", stdout.getvalue())
        self.assertIn("shortcuts are available directly", stdout.getvalue())

    def test_menu_runs_newman_interoperability_submenu(self):
        stdout = io.StringIO()
        expected = {
            "status": "completed",
            "adapter": "fake",
            "topology": "local",
            "validation": {"validated": ["conn-a", "conn-b"]},
        }
        with mock.patch("builtins.input", side_effect=["F", "1", "y", "Q"]), mock.patch.object(
            main,
            "run_interoperability_newman_tests",
            return_value=expected,
        ) as run_newman, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertIn("INTEROPERABILITY TESTS", stdout.getvalue())
        self.assertIn("Newman connector interoperability tests", stdout.getvalue())
        self.assertIn("Validation: Succeeded", stdout.getvalue())
        run_newman.assert_called_once()

    def test_menu_runs_kafka_interoperability_submenu(self):
        stdout = io.StringIO()
        expected = {
            "status": "passed",
            "adapter": "fake",
            "topology": "local",
            "kafka_edc_results": [{"status": "passed"}],
        }
        with mock.patch("builtins.input", side_effect=["F", "2", "y", "Q"]), mock.patch.object(
            main,
            "run_interoperability_kafka_tests",
            return_value=expected,
        ) as run_kafka, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertIn("INTEROPERABILITY TESTS", stdout.getvalue())
        self.assertIn("Kafka transfer interoperability tests", stdout.getvalue())
        self.assertIn("Kafka: Passed", stdout.getvalue())
        run_kafka.assert_called_once()

    def test_add_connector_inventory_plan_sets_level4_additive_mode(self):
        plan = main._build_add_connector_inventory_plan(
            {
                "DS_1_NAME": "pionera",
                "DS_1_CONNECTORS": "org2,org3",
                "DS_1_CONNECTOR_NAMESPACES": "org2:provider,org3:consumer",
                "DS_1_VALIDATION_PAIRS": "org2>org3",
                "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "full",
            },
            "partnera",
            "provider",
            validation_pair="partnera>org3",
        )

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["connector"], "conn-partnera-pionera")
        self.assertEqual(
            plan["adapter_updates"],
            {
                "DS_1_CONNECTORS": "org2,org3,partnera",
                "DS_1_CONNECTOR_NAMESPACES": "org2:provider,org3:consumer,partnera:provider",
                "DS_1_VALIDATION_PAIRS": "org2>org3,partnera>org3",
                "LEVEL4_CONNECTOR_RECONCILIATION_MODE": "additive",
            },
        )

    def test_menu_add_connector_updates_config_and_runs_level4_additive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter_path = os.path.join(tmpdir, "deployer.config")
            adapter_example_path = os.path.join(tmpdir, "deployer.config.example")
            with open(adapter_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=pionera\n"
                    "DS_1_CONNECTORS=org2,org3\n"
                    "DS_1_CONNECTOR_NAMESPACES=org2:provider,org3:consumer\n"
                    "DS_1_VALIDATION_PAIRS=org2>org3\n"
                    "LEVEL4_CONNECTOR_RECONCILIATION_MODE=full\n"
                )
            with open(adapter_example_path, "w", encoding="utf-8") as handle:
                handle.write("")

            stdout = io.StringIO()
            with mock.patch("builtins.input", side_effect=[
                "J",
                "partnera",
                "provider",
                "partnera>org3",
                "Y",
                "Y",
                "Q",
            ]), mock.patch.object(
                main,
                "_adapter_deployer_config_path",
                return_value=adapter_path,
            ), mock.patch.object(
                main,
                "_adapter_deployer_config_example_path",
                return_value=adapter_example_path,
            ), mock.patch.object(
                main,
                "_interactive_ensure_hosts_ready_for_levels",
                return_value=True,
            ), mock.patch.object(
                main,
                "run_levels",
                return_value={"status": "completed", "levels": [{"level": 4}]},
            ) as run_levels, contextlib.redirect_stdout(stdout):
                result = main.main(
                    ["menu"],
                    adapter_registry=self.registry,
                    deployer_registry=self.deployer_registry,
                    validation_engine_cls=FakeValidationEngine,
                    metrics_collector_cls=FakeMetricsCollector,
                    experiment_storage=FakeStorage,
                )

            self.assertEqual(result["status"], "exited")
            with open(adapter_path, encoding="utf-8") as handle:
                content = handle.read()

        self.assertIn("J - Add connector to existing dataspace", stdout.getvalue())
        self.assertIn("ADD CONNECTOR PLAN", stdout.getvalue())
        self.assertIn("DS_1_CONNECTORS=org2,org3,partnera", content)
        self.assertIn(
            "DS_1_CONNECTOR_NAMESPACES=org2:provider,org3:consumer,partnera:provider",
            content,
        )
        self.assertIn("DS_1_VALIDATION_PAIRS=org2>org3,partnera>org3", content)
        self.assertIn("LEVEL4_CONNECTOR_RECONCILIATION_MODE=additive", content)
        run_levels.assert_called_once()
        self.assertEqual(run_levels.call_args.kwargs["levels"], [4])

    def test_menu_level3_adapter_prompt_does_not_print_generic_hosts_hint(self):
        registry = {
            "edc": "fake_adapter_module:FakeAdapter",
            "inesdata": "fake_adapter_module:FakeAdapter",
        }
        deployer_registry = {
            "edc": "fake_deployer_module:FakeDeployer",
            "inesdata": "fake_deployer_module:FakeDeployer",
        }

        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["3", "1", "Y", "Q"]), mock.patch.object(
            main,
            "_interactive_ensure_hosts_ready_for_levels",
            return_value=True,
        ), mock.patch.object(
            main,
            "run_levels",
            return_value={"status": "completed", "levels": []},
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["adapter"], "edc")
        self.assertIn("EDC adapter selected", stdout.getvalue())
        self.assertNotIn("use H to plan/apply host entries", stdout.getvalue())

    def test_menu_with_multiple_adapters_defers_selection_until_level3(self):
        registry = {
            "edc": "fake_adapter_module:FakeAdapter",
            "inesdata": "fake_adapter_module:FakeAdapter",
        }
        deployer_registry = {
            "edc": "fake_deployer_module:FakeDeployer",
            "inesdata": "fake_deployer_module:FakeDeployer",
        }

        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["Q"]), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertIsNone(result["adapter"])
        rendered = stdout.getvalue()
        self.assertNotIn("Shared foundation adapter", rendered)
        self.assertNotIn("Adapter for Levels 3-6", rendered)
        self.assertNotIn("Available adapters:", rendered)
        self.assertIn("S - Select adapter", rendered)

    def test_menu_can_preselect_adapter_with_shortcut_s(self):
        registry = {
            "edc": "fake_adapter_module:FakeAdapter",
            "inesdata": "fake_adapter_module:FakeAdapter",
        }
        deployer_registry = {
            "edc": "fake_deployer_module:FakeDeployer",
            "inesdata": "fake_deployer_module:FakeDeployer",
        }

        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["S", "1", "Q"]), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(result["adapter"], "edc")
        self.assertEqual(result["topology"], "local")
        self.assertIn("S - Select adapter", stdout.getvalue())
        self.assertIn("EDC adapter selected", stdout.getvalue())
        self.assertIn("Available adapters:", stdout.getvalue())

    def test_menu_can_preselect_topology_with_shortcut_t(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["T", "2", "Q"]), mock.patch.object(
            main,
            "_try_vm_single_cluster_runtime_switch",
            return_value={"allowed": True, "status": "skipped"},
        ), mock.patch.object(
            main,
            "_interactive_offer_vm_single_address_configuration",
            return_value=True,
        ) as vm_single_prompt, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(result["topology"], "vm-single")
        rendered = stdout.getvalue()
        self.assertIn("Available topologies:", rendered)
        self.assertIn("Active topology set to vm-single.", rendered)
        self.assertNotIn("Available cluster runtimes for vm-single:", rendered)
        self.assertIn("Topology: vm-single", rendered)
        vm_single_prompt.assert_not_called()

    def test_menu_level_execution_uses_selected_topology_from_shortcut_t(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["T", "2", "1", "Y", "Q"]), mock.patch.object(
            main,
            "run_level",
            return_value={"level": 1, "name": "Setup Cluster", "status": "completed", "result": {}},
        ) as run_level, mock.patch.object(
            main,
            "_interactive_offer_vm_single_address_configuration",
            return_value=True,
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(result["topology"], "vm-single")
        run_level.assert_called_once()
        self.assertEqual(run_level.call_args.kwargs["topology"], "vm-single")

    def test_menu_level_confirmation_includes_active_topology(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["1", "Q"]), mock.patch.object(
            main,
            "_interactive_confirm",
            return_value=False,
        ) as confirm, mock.patch.object(
            main,
            "_interactive_cluster_runtime_label",
            return_value="k3s",
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu", "--topology", "vm-single"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        confirm.assert_called_once_with(
            "Run Level 1: Setup Cluster (shared foundation) (topology: vm-single, cluster: k3s)?",
            default=False,
        )

    def test_interactive_vm_single_address_configuration_updates_infrastructure_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "deployer.config")
            example_path = os.path.join(tmpdir, "deployer.config.example")
            overlay_path = os.path.join(tmpdir, "topologies", "vm-single.config")
            with open(example_path, "w", encoding="utf-8") as handle:
                handle.write("ENVIRONMENT=DEV\n")

            stdout = io.StringIO()
            with mock.patch.object(
                main,
                "_infrastructure_deployer_config_path",
                return_value=config_path,
            ), mock.patch.object(
                main,
                "_infrastructure_deployer_config_example_path",
                return_value=example_path,
            ), mock.patch.object(
                main,
                "_detect_vm_single_address_candidates",
                return_value={
                    "vm_ip": "198.51.100.20",
                    "minikube_ip": "192.0.2.10",
                    "recommended_address": "192.0.2.10",
                    "recommended_source": "minikube",
                },
            ), mock.patch.object(
                main,
                "_interactive_confirm",
                return_value=True,
            ), contextlib.redirect_stdout(stdout):
                result = main._interactive_offer_vm_single_address_configuration(required=True)

            with open(overlay_path, "r", encoding="utf-8") as handle:
                config_text = handle.read()

        self.assertTrue(result)
        self.assertIn("VM_EXTERNAL_IP=192.0.2.10\n", config_text)
        self.assertIn("INGRESS_EXTERNAL_IP=192.0.2.10\n", config_text)
        self.assertIn("Updated deployers/infrastructure/topologies/vm-single.config", stdout.getvalue())

    def test_menu_level3_vm_single_requires_address_configuration_before_running(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["3", "Y", "Q"]), mock.patch.object(
            main,
            "_interactive_offer_vm_single_address_configuration",
            return_value=True,
        ) as vm_single_prompt, mock.patch.object(
            main,
            "_interactive_ensure_hosts_ready_for_levels",
            return_value=True,
        ), mock.patch.object(
            main,
            "run_levels",
            return_value={"status": "completed", "levels": []},
        ) as run_levels, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu", "--topology", "vm-single"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        vm_single_prompt.assert_called_once_with(required=True)
        run_levels.assert_called_once()

    def test_menu_level3_prompts_for_adapter_selection_when_missing(self):
        registry = {
            "edc": "fake_adapter_module:FakeAdapter",
            "inesdata": "fake_adapter_module:FakeAdapter",
        }
        deployer_registry = {
            "edc": "fake_deployer_module:FakeDeployer",
            "inesdata": "fake_deployer_module:FakeDeployer",
        }

        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["3", "Y", "Q"]), mock.patch.object(
            main,
            "_select_adapter_interactive",
            return_value="inesdata",
        ) as selector, mock.patch.object(
            main,
            "_interactive_ensure_hosts_ready_for_levels",
            return_value=True,
        ), mock.patch.object(
            main,
            "run_levels",
            return_value={"status": "completed", "levels": []},
        ) as run_levels, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        selector.assert_called_once()
        run_levels.assert_called_once()
        self.assertEqual(run_levels.call_args.args[0], "inesdata")
        self.assertIn("This action needs an adapter selection for Levels 3-6.", stdout.getvalue())

    def test_interactive_level2_reuses_healthy_shared_common_services(self):
        class SharedInfrastructure:
            def __init__(self):
                self.announced = []
                self.completed = []

            def verify_common_services_ready_for_level3(self):
                return True, None

            def announce_level(self, level, name):
                self.announced.append((level, name))

            def complete_level(self, level):
                self.completed.append(level)

        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = SharedInfrastructure()

        stdout = io.StringIO()
        with mock.patch.object(main, "build_adapter", return_value=adapter), mock.patch.object(
            main,
            "_interactive_confirm",
            return_value=True,
        ) as confirm, mock.patch.object(main, "run_level") as run_level, contextlib.redirect_stdout(stdout):
            result = main._run_interactive_level2_with_shared_foundation(
                adapter_registry={"fake": "fake_adapter_module:FakeAdapterWithInfrastructure"},
                deployer_registry=self.deployer_registry,
            )

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["result"]["action"], "reuse")
        self.assertEqual(result["result"]["shared_adapter"], "fake")
        self.assertEqual(adapter.infrastructure.announced, [(2, "DEPLOY COMMON SERVICES")])
        self.assertEqual(adapter.infrastructure.completed, [2])
        self.assertEqual(confirm.call_count, 1)
        run_level.assert_not_called()
        self.assertIn("Level 2 manages the shared foundation used by all adapters in this cluster.", stdout.getvalue())

    def test_interactive_level2_reuse_reconciles_vm_distributed_public_access(self):
        class SharedInfrastructure:
            def __init__(self):
                self.public_access_calls = []

            def verify_common_services_ready_for_level3(self):
                return True, None

            def sync_vm_distributed_public_access(self, topology="local"):
                self.public_access_calls.append(topology)
                return {
                    "status": "synced",
                    "common_public_paths": {"status": "synced"},
                }

        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = SharedInfrastructure()

        stdout = io.StringIO()
        with mock.patch.object(main, "build_adapter", return_value=adapter), mock.patch.object(
            main,
            "_interactive_confirm",
            return_value=True,
        ), mock.patch.object(main, "run_level") as run_level, contextlib.redirect_stdout(stdout):
            result = main._run_interactive_level2_with_shared_foundation(
                adapter_registry={"fake": "fake_adapter_module:FakeAdapterWithInfrastructure"},
                deployer_registry=self.deployer_registry,
                topology="vm-distributed",
            )

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["result"]["action"], "reuse")
        self.assertEqual(result["result"]["public_access"]["status"], "synced")
        self.assertEqual(adapter.infrastructure.public_access_calls, ["vm-distributed"])
        run_level.assert_not_called()
        self.assertIn("Reconciling vm-distributed public access", stdout.getvalue())

    def test_interactive_level2_reuse_reconciles_vm_single_public_access(self):
        class SharedInfrastructure:
            def __init__(self):
                self.public_access_calls = []

            def verify_common_services_ready_for_level3(self):
                return True, None

            def sync_vm_distributed_public_access(self, topology="local"):
                self.public_access_calls.append(topology)
                return {
                    "status": "synced",
                    "nginx_http": {"status": "synced"},
                }

        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = SharedInfrastructure()

        stdout = io.StringIO()
        with mock.patch.object(main, "build_adapter", return_value=adapter), mock.patch.object(
            main,
            "_interactive_confirm",
            return_value=True,
        ), mock.patch.object(main, "run_level") as run_level, contextlib.redirect_stdout(stdout):
            result = main._run_interactive_level2_with_shared_foundation(
                adapter_registry={"fake": "fake_adapter_module:FakeAdapterWithInfrastructure"},
                deployer_registry=self.deployer_registry,
                topology="vm-single",
            )

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["result"]["action"], "reuse")
        self.assertEqual(result["result"]["public_access"]["status"], "synced")
        self.assertEqual(adapter.infrastructure.public_access_calls, ["vm-single"])
        run_level.assert_not_called()
        self.assertIn("Reconciling vm-single public access", stdout.getvalue())

    def test_interactive_level2_can_recreate_healthy_shared_common_services(self):
        class SharedInfrastructure:
            def __init__(self):
                self.reset_reasons = []

            def verify_common_services_ready_for_level3(self):
                return True, None

            def reset_local_shared_common_services(self, reason=None):
                self.reset_reasons.append(reason)
                return True

        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = SharedInfrastructure()

        with mock.patch.object(main, "build_adapter", return_value=adapter), mock.patch.object(
            main,
            "_interactive_confirm",
            side_effect=[False, True],
        ), mock.patch.object(
            main,
            "run_level",
            return_value={"level": 2, "status": "completed", "result": True},
        ) as run_level:
            result = main._run_interactive_level2_with_shared_foundation(
                adapter_registry={"fake": "fake_adapter_module:FakeAdapterWithInfrastructure"},
                deployer_registry=self.deployer_registry,
            )

        self.assertEqual(result["level"], 2)
        self.assertEqual(adapter.infrastructure.reset_reasons, ["Interactive Level 2 recreate requested"])
        run_level.assert_called_once()

    def test_interactive_level2_recreates_when_vm_topology_vault_scoped_artifact_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scoped_path = os.path.join(
                tmpdir,
                "deployers",
                "shared",
                "deployments",
                "DEV",
                "vm-distributed",
                "common",
                "init-keys-vault.json",
            )
            legacy_path = os.path.join(
                tmpdir,
                "deployers",
                "shared",
                "common",
                "init-keys-vault.json",
            )
            os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
            with open(legacy_path, "w", encoding="utf-8") as handle:
                handle.write("{}\n")

            class SharedConfig:
                @staticmethod
                def script_dir():
                    return tmpdir

            class SharedInfrastructure:
                def __init__(self):
                    self.config = SharedConfig()
                    self.reset_reasons = []
                    self.reset_kubeconfigs = []

                def _vault_keys_artifact_path(self):
                    return scoped_path

                def verify_common_services_ready_for_level3(self):
                    return False, "Vault is not initialized/unsealed"

                def reset_local_shared_common_services(self, reason=None):
                    self.reset_reasons.append(reason)
                    self.reset_kubeconfigs.append(os.environ.get("KUBECONFIG"))
                    return True

            adapter = FakeAdapterWithInfrastructure()
            adapter.infrastructure = SharedInfrastructure()

            stdout = io.StringIO()
            with mock.patch.object(main, "build_adapter", return_value=adapter), mock.patch.object(
                main,
                "_interactive_confirm",
                return_value=True,
            ), mock.patch.object(
                main,
                "_ensure_vm_distributed_local_kubeconfigs",
                return_value={"status": "ready", "items": []},
            ) as kubeconfig_sync, mock.patch.object(
                main,
                "_topology_runtime_environment_overrides",
                return_value={"KUBECONFIG": "/tmp/common-k3s.yaml"},
            ), mock.patch.object(
                main,
                "run_level",
                return_value={"level": 2, "status": "completed", "result": True},
            ) as run_level, contextlib.redirect_stdout(stdout):
                result = main._run_interactive_level2_with_shared_foundation(
                    adapter_registry={"fake": "fake_adapter_module:FakeAdapterWithInfrastructure"},
                    deployer_registry=self.deployer_registry,
                    topology="vm-distributed",
                )

        self.assertEqual(result["level"], 2)
        self.assertEqual(
            adapter.infrastructure.reset_reasons,
            ["Interactive Level 2 recreate requested for topology-scoped Vault artifact"],
        )
        self.assertEqual(adapter.infrastructure.reset_kubeconfigs, ["/tmp/common-k3s.yaml"])
        kubeconfig_sync.assert_called_once_with(roles=("common",))
        run_level.assert_called_once()
        self.assertIn("Topology-scoped Vault keys are missing", stdout.getvalue())
        self.assertIn("Ignored legacy artifact", stdout.getvalue())

    def test_interactive_level2_cancels_when_vm_topology_vault_scoped_artifact_is_missing_and_recreate_is_declined(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scoped_path = os.path.join(
                tmpdir,
                "deployers",
                "shared",
                "deployments",
                "DEV",
                "vm-distributed",
                "common",
                "init-keys-vault.json",
            )
            legacy_path = os.path.join(
                tmpdir,
                "deployers",
                "shared",
                "common",
                "init-keys-vault.json",
            )
            os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
            with open(legacy_path, "w", encoding="utf-8") as handle:
                handle.write("{}\n")

            class SharedConfig:
                @staticmethod
                def script_dir():
                    return tmpdir

            class SharedInfrastructure:
                def __init__(self):
                    self.config = SharedConfig()
                    self.reset_called = False

                def _vault_keys_artifact_path(self):
                    return scoped_path

                def reset_local_shared_common_services(self, reason=None):
                    del reason
                    self.reset_called = True
                    return True

            adapter = FakeAdapterWithInfrastructure()
            adapter.infrastructure = SharedInfrastructure()

            with mock.patch.object(main, "build_adapter", return_value=adapter), mock.patch.object(
                main,
                "_interactive_confirm",
                return_value=False,
            ), mock.patch.object(main, "run_level") as run_level:
                result = main._run_interactive_level2_with_shared_foundation(
                    adapter_registry={"fake": "fake_adapter_module:FakeAdapterWithInfrastructure"},
                    deployer_registry=self.deployer_registry,
                    topology="vm-distributed",
                )

        self.assertIsNone(result)
        self.assertFalse(adapter.infrastructure.reset_called)
        run_level.assert_not_called()

    def test_interactive_hosts_preflight_applies_only_missing_entries_for_inesdata(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n127.0.0.1 conn-a.example.local\n")
            hosts_file.flush()

            stdout = io.StringIO()
            with mock.patch("builtins.input", side_effect=["Y"]), contextlib.redirect_stdout(stdout):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "inesdata",
                    levels=[4],
                    adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                    topology="local",
                )

            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertTrue(result)
        self.assertEqual(hosts_content.count("conn-a.example.local"), 1)
        self.assertIn("registration-service-fake-ds.example.local", hosts_content)
        self.assertIn("conn-b.example.local", hosts_content)
        self.assertIn("Host entries are missing for adapter 'inesdata'", stdout.getvalue())

    def test_interactive_hosts_preflight_enables_sudo_for_system_hosts(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n")
            hosts_file.flush()

            observed = {}

            def fake_run_hosts(*_args, **_kwargs):
                observed["use_sudo"] = os.getenv("PIONERA_HOSTS_USE_SUDO")
                return {"hosts_sync": {"status": "updated"}, "hosts_plan": {}}

            with mock.patch("builtins.input", side_effect=["Y"]), mock.patch.object(
                main,
                "run_hosts",
                side_effect=fake_run_hosts,
            ):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "inesdata",
                    levels=[3],
                    adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                    topology="local",
                )

        self.assertFalse(result)
        self.assertEqual(observed["use_sudo"], "true")

    def test_edc_interactive_hosts_preflight_applies_only_missing_entries(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n127.0.0.1 conn-a.example.local\n")
            hosts_file.flush()

            stdout = io.StringIO()
            with mock.patch("builtins.input", side_effect=["Y"]), contextlib.redirect_stdout(stdout):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "edc",
                    levels=[4],
                    adapter_registry={"edc": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"edc": "fake_deployer_module:FakeDeployer"},
                    topology="local",
                )

            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertTrue(result)
        self.assertEqual(hosts_content.count("conn-a.example.local"), 1)
        self.assertIn("registration-service-fake-ds.example.local", hosts_content)
        self.assertIn("conn-b.example.local", hosts_content)
        self.assertIn("Host entries are missing for adapter 'edc'", stdout.getvalue())

    def test_edc_interactive_hosts_preflight_applies_only_missing_entries_for_vm_single(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n192.0.2.10 conn-a.example.local\n")
            hosts_file.flush()

            stdout = io.StringIO()
            with mock.patch("builtins.input", side_effect=["Y"]), contextlib.redirect_stdout(stdout):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "edc",
                    levels=[4],
                    adapter_registry={"edc": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"edc": "fake_deployer_module:FakeVmDeployer"},
                    topology="vm-single",
                )

            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertTrue(result)
        self.assertEqual(hosts_content.count("conn-a.example.local"), 1)
        self.assertIn("192.0.2.10 registration-service-fake-ds.example.local", hosts_content)
        self.assertIn("192.0.2.10 conn-b.example.local", hosts_content)
        self.assertIn("Host entries are missing for adapter 'edc'", stdout.getvalue())

    def test_interactive_hosts_preflight_skips_vm_single_with_public_url(self):
        fake_context = types.SimpleNamespace(
            config={
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            }
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("inesdata", fake_context),
        ), mock.patch.object(
            main,
            "_build_hosts_readiness_plan",
            side_effect=AssertionError("vm-single public URL must not require local hosts"),
        ):
            result = main._interactive_ensure_hosts_ready_for_levels(
                "inesdata",
                levels=[3],
                adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                deployer_registry={"inesdata": "fake_deployer_module:FakeVmDeployer"},
                topology="vm-single",
            )

        self.assertTrue(result)

    def test_vm_distributed_common_services_hosts_preflight_reconciles_public_proxy_hostnames(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "inesdata",
                "topology": "vm-distributed",
                "environment": "DEV",
                "dataspace_name": "pionera",
                "ds_domain_base": "pionera.oeg.fi.upm.es",
                "connectors": ["conn-org2-pionera", "conn-org3-pionera"],
                "topology_profile": {
                    "name": "vm-distributed",
                    "default_address": "192.168.122.64",
                    "role_addresses": {
                        "common": "192.168.122.64",
                        "registration_service": "192.168.122.64",
                        "provider": "192.168.122.134",
                        "consumer": "192.168.122.9",
                        "components": "192.168.122.64",
                    },
                    "ingress_external_ip": "192.168.122.64",
                    "routing_mode": "host",
                },
                "config": {
                    "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                    "DS_1_NAME": "pionera",
                    "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "common-services",
                    "VM_PUBLIC_PROXY_IP": "138.100.15.165",
                },
            }
        )

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n192.168.122.64 org1.pionera.oeg.fi.upm.es\n")
            hosts_file.flush()

            stdout = io.StringIO()
            with mock.patch("builtins.input", side_effect=["Y"]), mock.patch.object(
                main,
                "build_adapter",
                return_value=object(),
            ), mock.patch.object(
                main,
                "_resolve_deployer_context",
                return_value=("inesdata", context),
            ), contextlib.redirect_stdout(stdout):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "inesdata",
                    levels=[3],
                    adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                    topology="vm-distributed",
                )

            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertTrue(result)
        self.assertNotIn("192.168.122.64 org1.pionera.oeg.fi.upm.es", hosts_content)
        self.assertIn("138.100.15.165 org1.pionera.oeg.fi.upm.es", hosts_content)
        self.assertIn("Hosts public names reconciled: 1", stdout.getvalue())

    def test_vm_distributed_auto_execution_host_reconciles_hosts_when_running_on_common_services(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "inesdata",
                "topology": "vm-distributed",
                "environment": "DEV",
                "dataspace_name": "pionera",
                "ds_domain_base": "pionera.oeg.fi.upm.es",
                "topology_profile": {
                    "name": "vm-distributed",
                    "default_address": "192.168.122.64",
                    "role_addresses": {
                        "common": "192.168.122.64",
                        "registration_service": "192.168.122.64",
                    },
                    "ingress_external_ip": "192.168.122.64",
                    "routing_mode": "host",
                },
                "config": {
                    "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                    "DS_1_NAME": "pionera",
                    "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "auto",
                    "VM_PUBLIC_PROXY_IP": "138.100.15.165",
                },
            }
        )

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n192.168.122.64 org1.pionera.oeg.fi.upm.es\n")
            hosts_file.flush()

            stdout = io.StringIO()
            with mock.patch("builtins.input", side_effect=["Y"]), mock.patch.object(
                main,
                "_vm_distributed_running_on_common_services",
                return_value=True,
            ), mock.patch.object(
                main,
                "build_adapter",
                return_value=object(),
            ), mock.patch.object(
                main,
                "_resolve_deployer_context",
                return_value=("inesdata", context),
            ), contextlib.redirect_stdout(stdout):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "inesdata",
                    levels=[3],
                    adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                    topology="vm-distributed",
                )

            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertTrue(result)
        self.assertNotIn("192.168.122.64 org1.pionera.oeg.fi.upm.es", hosts_content)
        self.assertIn("138.100.15.165 org1.pionera.oeg.fi.upm.es", hosts_content)
        self.assertIn("Hosts public names reconciled: 1", stdout.getvalue())

    def test_vm_distributed_external_hosts_preflight_does_not_touch_operator_hosts(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "inesdata",
                "topology": "vm-distributed",
                "environment": "DEV",
                "dataspace_name": "pionera",
                "ds_domain_base": "pionera.oeg.fi.upm.es",
                "config": {
                    "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                    "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                    "VM_DISTRIBUTED_EXECUTION_HOST": "external",
                    "VM_PUBLIC_PROXY_IP": "138.100.15.165",
                },
            }
        )

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n192.168.122.64 org1.pionera.oeg.fi.upm.es\n")
            hosts_file.flush()

            with mock.patch("builtins.input") as input_mock, mock.patch.object(
                main,
                "build_adapter",
                return_value=object(),
            ), mock.patch.object(
                main,
                "_resolve_deployer_context",
                return_value=("inesdata", context),
            ):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "inesdata",
                    levels=[3],
                    adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                    topology="vm-distributed",
                )

            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertTrue(result)
        input_mock.assert_not_called()
        self.assertIn("192.168.122.64 org1.pionera.oeg.fi.upm.es", hosts_content)

    def test_edc_interactive_hosts_preflight_can_cancel_level(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n")
            hosts_file.flush()

            stdout = io.StringIO()
            with mock.patch("builtins.input", side_effect=["N"]), contextlib.redirect_stdout(stdout):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "edc",
                    levels=[3],
                    adapter_registry={"edc": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"edc": "fake_deployer_module:FakeDeployer"},
                    topology="local",
                )

            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertFalse(result)
        self.assertNotIn("registration-service-fake-ds.example.local", hosts_content)
        self.assertIn("Level execution cancelled", stdout.getvalue())

    def test_interactive_hosts_preflight_hides_legacy_aliases_when_canonical_hosts_exist(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ):
            hosts_file.write(
                "127.0.0.1 localhost\n"
                "127.0.0.1 auth.dev.ed.dataspaceunit.upm\n"
                "127.0.0.1 admin.auth.dev.ed.dataspaceunit.upm\n"
                "127.0.0.1 minio.dev.ed.dataspaceunit.upm\n"
                "127.0.0.1 console.minio-s3.dev.ed.dataspaceunit.upm\n"
                "127.0.0.1 registration-service-fake-ds.example.local\n"
                "127.0.0.1 keycloak.dev.ed.dataspaceunit.upm\n"
                "127.0.0.1 keycloak-admin.dev.ed.dataspaceunit.upm\n"
            )
            hosts_file.flush()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main._interactive_ensure_hosts_ready_for_levels(
                    "inesdata",
                    levels=[3],
                    adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                    deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                    topology="local",
                )

        self.assertTrue(result)
        rendered = stdout.getvalue()
        self.assertNotIn("Old hostname aliases were found in your hosts file", rendered)
        self.assertNotIn("keycloak.dev.ed.dataspaceunit.upm -> auth.dev.ed.dataspaceunit.upm", rendered)

    def test_developer_shortcuts_delegate_setup_and_developer_actions(self):
        with mock.patch("builtins.input", side_effect=["B", "L", "Q"]), mock.patch.object(
            main,
            "_run_legacy_menu_action",
            return_value=None,
        ) as legacy_action:
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(
            [call.args[0] for call in legacy_action.call_args_list],
            ["bootstrap", "local_images"],
        )

    def test_recreate_dataspace_shortcut_requires_exact_name(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["X", "wrong-ds", "Q"]), mock.patch.object(
            main,
            "run_recreate_dataspace",
            return_value={"status": "completed"},
        ) as recreate, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        recreate.assert_not_called()
        self.assertIn("Dataspace recreation cancelled", stdout.getvalue())

    def test_recreate_dataspace_shortcut_dispatches_when_confirmed(self):
        with mock.patch("builtins.input", side_effect=["X", "fake-ds", "N", "Q"]), mock.patch.object(
            main,
            "run_recreate_dataspace",
            return_value={"status": "completed", "dataspace": "fake-ds"},
        ) as recreate:
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        recreate.assert_called_once()
        self.assertEqual(recreate.call_args.kwargs["confirm_dataspace"], "fake-ds")
        self.assertFalse(recreate.call_args.kwargs["with_connectors"])

    def test_recreate_dataspace_shortcut_can_recreate_connectors(self):
        with mock.patch("builtins.input", side_effect=["X", "fake-ds", "Y", "Q"]), mock.patch.object(
            main,
            "run_recreate_dataspace",
            return_value={"status": "completed", "dataspace": "fake-ds"},
        ) as recreate:
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        recreate.assert_called_once()
        self.assertTrue(recreate.call_args.kwargs["with_connectors"])

    def test_menu_keeps_legacy_setup_and_developer_shortcuts(self):
        with mock.patch("builtins.input", side_effect=["B", "L", "Q"]), mock.patch.object(
            main,
            "_run_legacy_menu_action",
            return_value=None,
        ) as legacy_action:
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(
            [call.args[0] for call in legacy_action.call_args_list],
            ["bootstrap", "local_images"],
        )

    def test_ui_validation_shortcuts_delegate_component_actions(self):
        with mock.patch("builtins.input", side_effect=["I", "O", "A", "V", "Y", "Z", "Q"]), mock.patch.object(
            main,
            "_run_legacy_menu_action",
            return_value=None,
        ) as legacy_action:
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(
            [call.args[0] for call in legacy_action.call_args_list],
            [
                "inesdata_ui",
                "ontology_hub_ui",
                "ai_model_hub_ui",
                "semantic_virtualization_ui",
                "validation_test_by_id",
                "validation_test_by_id",
            ],
        )

    def test_menu_keeps_legacy_component_ui_validation_shortcuts(self):
        with mock.patch("builtins.input", side_effect=["I", "O", "A", "V", "Q"]), mock.patch.object(
            main,
            "_run_legacy_menu_action",
            return_value=None,
        ) as legacy_action:
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(
            [call.args[0] for call in legacy_action.call_args_list],
            ["inesdata_ui", "ontology_hub_ui", "ai_model_hub_ui", "semantic_virtualization_ui"],
        )

    def test_migrated_bootstrap_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.local_menu_tools,
            "run_framework_bootstrap_interactive",
            return_value="bootstrap-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("bootstrap")

        self.assertEqual(result, "bootstrap-ok")
        migrated_action.assert_called_once_with()

    def test_migrated_cleanup_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.local_menu_tools,
            "run_workspace_cleanup_interactive",
            return_value="cleanup-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("cleanup")

        self.assertEqual(result, "cleanup-ok")
        migrated_action.assert_called_once_with()

    def test_migrated_local_images_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.local_menu_tools,
            "run_local_images_workflow_interactive",
            return_value="images-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("local_images")

        self.assertEqual(result, "images-ok")
        migrated_action.assert_called_once_with(active_adapter="inesdata")

    def test_migrated_recover_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.local_menu_tools,
            "run_connector_recovery_after_wsl_restart",
            return_value="recover-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("recover")

        self.assertEqual(result, "recover-ok")
        migrated_action.assert_called_once_with()

    def test_menu_repair_shortcut_dispatches_local_repair(self):
        with mock.patch("builtins.input", side_effect=["R", "Y", "N", "Q"]), mock.patch.object(
            main,
            "run_local_repair",
            return_value={
                "status": "completed",
                "scope": "local repair",
                "adapter": "fake",
                "topology": "local",
            },
        ) as local_repair:
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        local_repair.assert_called_once()
        self.assertTrue(local_repair.call_args.kwargs["apply_hosts"])
        self.assertFalse(local_repair.call_args.kwargs["recover_connectors"])

    def test_migrated_inesdata_ui_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.ui_interactive_menu,
            "run_inesdata_ui_tests_interactive",
            return_value="inesdata-ui-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("inesdata_ui")

        self.assertEqual(result, "inesdata-ui-ok")
        migrated_action.assert_called_once_with()

    def test_migrated_ontology_hub_ui_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.ui_interactive_menu,
            "run_ontology_hub_ui_tests_interactive",
            return_value="ontology-ui-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("ontology_hub_ui")

        self.assertEqual(result, "ontology-ui-ok")
        migrated_action.assert_called_once_with()

    def test_migrated_ai_model_hub_ui_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.ui_interactive_menu,
            "run_ai_model_hub_ui_tests_interactive",
            return_value="ai-model-ui-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("ai_model_hub_ui")

        self.assertEqual(result, "ai-model-ui-ok")
        migrated_action.assert_called_once_with()

    def test_migrated_ai_model_hub_ui_action_exports_active_topology(self):
        observed_env = {}

        def capture_env():
            observed_env["PIONERA_TOPOLOGY"] = os.environ.get("PIONERA_TOPOLOGY")
            observed_env["INESDATA_TOPOLOGY"] = os.environ.get("INESDATA_TOPOLOGY")
            observed_env["UI_TOPOLOGY"] = os.environ.get("UI_TOPOLOGY")
            observed_env["PIONERA_ADAPTER"] = os.environ.get("PIONERA_ADAPTER")
            return "ai-model-ui-ok"

        with mock.patch.object(
            main.ui_interactive_menu,
            "run_ai_model_hub_ui_tests_interactive",
            side_effect=capture_env,
        ):
            result = main._run_legacy_menu_action(
                "ai_model_hub_ui",
                current_adapter="inesdata",
                topology="vm-single",
            )

        self.assertEqual(result, "ai-model-ui-ok")
        self.assertEqual(observed_env["PIONERA_TOPOLOGY"], "vm-single")
        self.assertEqual(observed_env["INESDATA_TOPOLOGY"], "vm-single")
        self.assertEqual(observed_env["UI_TOPOLOGY"], "vm-single")
        self.assertEqual(observed_env["PIONERA_ADAPTER"], "inesdata")

    def test_migrated_semantic_virtualization_ui_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.ui_interactive_menu,
            "run_semantic_virtualization_ui_tests_interactive",
            return_value="semantic-virtualization-ui-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("semantic_virtualization_ui")

        self.assertEqual(result, "semantic-virtualization-ui-ok")
        migrated_action.assert_called_once_with()

    def test_migrated_validation_test_by_id_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.ui_interactive_menu,
            "run_validation_test_by_id_interactive",
            return_value="test-by-id-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action("validation_test_by_id")

        self.assertEqual(result, "test-by-id-ok")
        migrated_action.assert_called_once_with(adapter_name="inesdata", topology="local")

    def test_migrated_validation_api_test_by_id_action_does_not_import_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            main.ui_interactive_menu,
            "run_validation_api_test_by_id_interactive",
            return_value="api-test-by-id-ok",
        ) as migrated_action:
            result = main._run_legacy_menu_action(
                "validation_api_test_by_id",
                current_adapter="fake",
                topology="vm-single",
            )

        self.assertEqual(result, "api-test-by-id-ok")
        migrated_action.assert_called_once_with(adapter_name="fake", topology="vm-single")

    def test_menu_metrics_can_run_without_kafka_by_default(self):
        calls = []

        def fake_run_metrics(*args, **kwargs):
            calls.append(kwargs)
            return {"status": "metrics-ok", "kafka_enabled": kwargs.get("kafka_enabled")}

        with mock.patch("builtins.input", side_effect=["M", "Y", "N", "Q"]), mock.patch.object(
            main,
            "run_metrics",
            side_effect=fake_run_metrics,
        ):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["kafka_enabled"])

    def test_menu_metrics_can_enable_kafka_benchmark(self):
        calls = []

        def fake_run_metrics(*args, **kwargs):
            calls.append(kwargs)
            return {"status": "metrics-ok", "kafka_enabled": kwargs.get("kafka_enabled")}

        with mock.patch("builtins.input", side_effect=["M", "Y", "Y", "Q"]), mock.patch.object(
            main,
            "run_metrics",
            side_effect=fake_run_metrics,
        ):
            result = main.main(
                ["menu"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["kafka_enabled"])

    def test_menu_command_rejects_extra_arguments(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exc:
            main.main(["menu", "extra"], adapter_registry=self.registry)

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("does not accept additional arguments", stderr.getvalue())

    def test_run_level_invokes_level_two_adapter_method(self):
        adapter = FakeAdapter()

        with mock.patch.object(
            main,
            "_resolve_level_access_urls",
            return_value={"keycloak": "http://keycloak.example.local"},
        ):
            result = main.run_level(
                adapter,
                2,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
            )

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["urls"], {"keycloak": "http://keycloak.example.local"})
        self.assertEqual(result["hosts_plan"]["level_1_2"], [
            "auth.dev.ed.dataspaceunit.upm",
            "minio.dev.ed.dataspaceunit.upm",
            "admin.auth.dev.ed.dataspaceunit.upm",
            "console.minio-s3.dev.ed.dataspaceunit.upm",
        ])
        self.assertEqual(result["hosts_plan"]["level_3"], [])
        self.assertEqual(result["hosts_sync"]["status"], "skipped")
        self.assertEqual(adapter.calls, ["deploy_infrastructure"])

    def test_level_command_runs_selected_level(self):
        expected = {"status": "completed", "levels": [{"level": 1, "status": "completed"}]}

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "run_levels",
            return_value=expected,
        ) as run_levels, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "level", "1", "--topology", "vm-single"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
            )

        self.assertEqual(result, expected)
        run_levels.assert_called_once()
        self.assertEqual(run_levels.call_args.args[0], "fake")
        self.assertEqual(run_levels.call_args.kwargs["levels"], [1])
        self.assertEqual(run_levels.call_args.kwargs["topology"], "vm-single")
        self.assertIn("Result: Succeeded", stdout.getvalue())

    def test_run_local_repair_applies_hosts_reconciliation(self):
        adapter = FakeAdapter()
        doctor_report = {
            "status": "ready",
            "checks": [
                {"name": "kubectl", "status": "ok"},
                {"name": "minikube", "status": "ok"},
                {"name": "hosts file", "status": "ok"},
                {"name": "minikube tunnel", "status": "ok"},
            ],
        }

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ), mock.patch.object(
            main.local_menu_tools,
            "collect_framework_doctor_report",
            return_value=doctor_report,
        ), mock.patch.object(
            main,
            "_run_local_repair_public_endpoint_preflight",
            return_value={"status": "passed", "checked": []},
        ):
            hosts_file.write("127.0.0.1 localhost\n")
            hosts_file.flush()
            result = main.run_local_repair(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )
            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["doctor"]["status"], "ready")
        self.assertEqual(result["missing_hostnames"], [])
        self.assertIn(result["hosts_sync"]["status"], {"updated", "unchanged"})
        self.assertEqual(result["public_endpoint_preflight"]["status"], "passed")
        self.assertIn("auth.dev.ed.dataspaceunit.upm", hosts_content)
        self.assertIn("registration-service-fake-ds.example.local", hosts_content)

    def test_run_local_repair_can_trigger_connector_recovery(self):
        adapter = FakeAdapter()
        doctor_report = {
            "status": "ready",
            "checks": [
                {"name": "kubectl", "status": "ok"},
                {"name": "minikube", "status": "ok"},
                {"name": "hosts file", "status": "ok"},
                {"name": "minikube tunnel", "status": "ok"},
            ],
        }

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ), mock.patch.object(
            main.local_menu_tools,
            "collect_framework_doctor_report",
            return_value=doctor_report,
        ), mock.patch.object(
            main,
            "_run_local_repair_public_endpoint_preflight",
            return_value={"status": "passed", "checked": []},
        ), mock.patch.object(
            main.local_menu_tools,
            "run_connector_recovery_after_wsl_restart",
            return_value=True,
        ) as recover:
            result = main.run_local_repair(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
                recover_connectors=True,
            )

        self.assertEqual(result["connector_recovery"]["status"], "completed")
        recover.assert_called_once_with(adapter=adapter)

    def test_run_local_repair_records_public_endpoint_preflight_failure(self):
        adapter = FakeAdapter()
        doctor_report = {
            "status": "ready",
            "checks": [
                {"name": "kubectl", "status": "ok"},
                {"name": "minikube", "status": "ok"},
                {"name": "hosts file", "status": "ok"},
                {"name": "minikube tunnel", "status": "ok"},
            ],
        }

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ), mock.patch.object(
            main.local_menu_tools,
            "collect_framework_doctor_report",
            return_value=doctor_report,
        ), mock.patch.object(
            main,
            "_run_local_repair_public_endpoint_preflight",
            side_effect=RuntimeError("public ingress endpoints are not reachable"),
        ):
            hosts_file.write("127.0.0.1 localhost\n")
            hosts_file.flush()
            result = main.run_local_repair(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["public_endpoint_preflight"]["status"], "failed")
        self.assertIn("not reachable", result["public_endpoint_preflight"]["error"])

    def test_interactive_full_levels_defers_hosts_reconciliation_until_level_three(self):
        events = []

        def fake_run_level(adapter, level, **kwargs):
            events.append(("level", int(level)))
            return {
                "level": int(level),
                "name": main.LEVEL_DESCRIPTIONS[int(level)],
                "status": "completed",
                "result": {},
            }

        def fake_hosts_ready(adapter_name, levels=None, **kwargs):
            events.append(("hosts", int((levels or [0])[0])))
            return True

        with mock.patch.object(main, "run_level", side_effect=fake_run_level), mock.patch.object(
            main,
            "_interactive_ensure_hosts_ready_for_levels",
            side_effect=fake_hosts_ready,
        ):
            result = main._run_interactive_full_levels(
                "fake",
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                topology="local",
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            events,
            [
                ("level", 1),
                ("level", 2),
                ("hosts", 3),
                ("level", 3),
                ("hosts", 4),
                ("level", 4),
                ("hosts", 5),
                ("level", 5),
                ("hosts", 6),
                ("level", 6),
            ],
        )

    def test_run_level_five_uses_vm_single_component_deployment(self):
        adapter = FakeAdapter()
        fake_orchestrator = mock.Mock()
        fake_orchestrator.resolve_context = mock.Mock(
            return_value={"topology": "vm-single", "components": ["ontology-hub"]}
        )
        fake_orchestrator.deployer = mock.Mock()
        fake_orchestrator.deployer.deploy_components = mock.Mock(
            return_value={
                "deployed": ["ontology-hub"],
                "urls": {"ontology-hub": "http://ontology-hub.example.local"},
            }
        )

        with mock.patch.object(main, "build_deployer_orchestrator", return_value=fake_orchestrator), mock.patch.object(
            main,
            "_resolve_level_access_urls",
            return_value={},
        ):
            result = main.run_level(adapter, 5, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 5)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["deployed"], ["ontology-hub"])
        fake_orchestrator.resolve_context.assert_called_once_with(topology="vm-single")
        fake_orchestrator.deployer.deploy_components.assert_called_once_with(
            {"topology": "vm-single", "components": ["ontology-hub"]}
        )
        self.assertEqual(adapter.calls, [])

    def test_run_level_one_uses_vm_single_cluster_preflight(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.setup_cluster_preflight = mock.Mock(
            return_value={
                "status": "ready",
                "mode": "preflight",
                "topology": "vm-single",
                "cluster_creation": "skipped",
            }
        )

        with mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 1, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["mode"], "preflight")
        adapter.infrastructure.setup_cluster_preflight.assert_called_once_with(topology="vm-single")

    def test_run_level_one_vm_single_delegates_to_remote_when_configured_from_workstation(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.setup_cluster_preflight = mock.Mock(return_value={"status": "unexpected"})
        bundle = {
            "infrastructure": {"DOMAIN_BASE": "example.test"},
            "topology": {
                "VM_EXTERNAL_IP": "192.0.2.52",
                "SSH_ACCESS_MODE": "direct",
                "SSH_IDENTITY_FILE": "/home/operator/.ssh/validation-env-vm-single",
                "VM_SINGLE_SSH_HOST": "192.0.2.52",
                "VM_SINGLE_SSH_USER": "pionera",
                "VM_SINGLE_REMOTE_WORKDIR": "/srv/validation-framework",
                "VM_SINGLE_LEVEL_EXECUTION_MODE": "remote",
            },
            "adapter": {"DS_1_NAME": "pionera"},
            "paths": {},
        }

        with mock.patch.dict(
            os.environ,
            {"PIONERA_VM_SINGLE_LEVEL_EXECUTION_MODE": "remote"},
            clear=False,
        ), mock.patch.object(
            main,
            "_load_vm_single_configuration_bundle",
            return_value=bundle,
        ), mock.patch.object(
            main,
            "_vm_single_running_on_target",
            return_value=False,
        ), mock.patch.object(
            main.subprocess,
            "run",
            return_value=types.SimpleNamespace(returncode=0),
        ) as run_command:
            result = main.run_level(adapter, 1, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 1)
        self.assertEqual(result["result"]["status"], "remote_completed")
        self.assertEqual(result["result"]["workspace_sync"]["status"], "synced")
        adapter.infrastructure.setup_cluster_preflight.assert_not_called()
        command = run_command.call_args.args[0]
        self.assertEqual(command[0:2], ["ssh", "-tt"])
        rendered = " ".join(command)
        self.assertIn("PIONERA_VM_SINGLE_REMOTE_LEVEL_ACTIVE=true", rendered)
        self.assertIn("python3 main.py fake level 1 --topology vm-single", rendered)
        rsync_commands = [
            call.args[0] for call in run_command.call_args_list if call.args and call.args[0][0] == "rsync"
        ]
        self.assertEqual(len(rsync_commands), 1)
        self.assertIn("--exclude", rsync_commands[0])
        self.assertIn("experiments/", rsync_commands[0])
        self.assertIn("context/deliverables/logs/", rsync_commands[0])

    def test_run_level_one_vm_single_auto_runs_locally_when_already_inside_target(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.setup_cluster_preflight = mock.Mock(
            return_value={
                "status": "ready",
                "mode": "preflight",
                "topology": "vm-single",
            }
        )
        bundle = {
            "infrastructure": {"DOMAIN_BASE": "example.test"},
            "topology": {
                "VM_EXTERNAL_IP": "192.0.2.52",
                "SSH_ACCESS_MODE": "direct",
                "SSH_IDENTITY_FILE": "/home/operator/.ssh/validation-env-vm-single",
                "VM_SINGLE_SSH_HOST": "192.0.2.52",
                "VM_SINGLE_SSH_USER": "pionera",
                "VM_SINGLE_REMOTE_WORKDIR": "/srv/validation-framework",
                "VM_SINGLE_LEVEL_EXECUTION_MODE": "auto",
            },
            "adapter": {"DS_1_NAME": "pionera"},
            "paths": {},
        }

        with mock.patch.dict(
            os.environ,
            {"PIONERA_VM_SINGLE_LEVEL_EXECUTION_MODE": "auto"},
            clear=False,
        ), mock.patch.object(
            main,
            "_load_vm_single_configuration_bundle",
            return_value=bundle,
        ), mock.patch.object(
            main,
            "_vm_single_running_on_target",
            return_value=True,
        ), mock.patch.object(
            main,
            "_resolve_level_access_urls",
            return_value={},
        ), mock.patch.object(
            main,
            "_synchronize_vm_single_addresses_after_level1",
            return_value={"status": "unchanged"},
        ), mock.patch.object(main.subprocess, "run") as run_command:
            result = main.run_level(adapter, 1, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 1)
        self.assertEqual(result["result"]["mode"], "preflight")
        adapter.infrastructure.setup_cluster_preflight.assert_called_once_with(topology="vm-single")
        run_command.assert_not_called()

    def test_run_level_two_vm_single_auto_uses_tunneled_kubeconfig_from_workstation(self):
        class VmSingleInfrastructure:
            def __init__(self):
                self.seen_kubeconfig = None

            def deploy_infrastructure_for_topology(self, topology="local"):
                self.seen_kubeconfig = os.environ.get("KUBECONFIG")
                return {"status": "deployed", "topology": topology}

        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = VmSingleInfrastructure()
        bundle = {
            "infrastructure": {"DOMAIN_BASE": "example.test"},
            "topology": {
                "CLUSTER_TYPE": "k3s",
                "VM_EXTERNAL_IP": "192.0.2.52",
                "SSH_ACCESS_MODE": "direct",
                "SSH_IDENTITY_FILE": "/home/operator/.ssh/validation-env-vm-single",
                "VM_SINGLE_SSH_HOST": "192.0.2.52",
                "VM_SINGLE_SSH_USER": "pionera",
                "VM_SINGLE_LEVEL_EXECUTION_MODE": "auto",
                "VM_SINGLE_LOCAL_KUBECONFIG": "/tmp/vm-single-k3s.yaml",
            },
            "adapter": {"DS_1_NAME": "pionera"},
            "paths": {},
        }

        with mock.patch.dict(
            os.environ,
            {"PIONERA_VM_SINGLE_LEVEL_EXECUTION_MODE": "auto"},
            clear=False,
        ), mock.patch.object(
            main,
            "_load_vm_single_configuration_bundle",
            return_value=bundle,
        ), mock.patch.object(
            main,
            "_vm_single_running_on_target",
            return_value=False,
        ), mock.patch.object(
            main,
            "_ensure_vm_single_k3s_api_access",
            return_value={"status": "ready", "kubeconfig": "/tmp/vm-single-k3s.yaml"},
        ) as ensure_access:
            result = main.run_level(adapter, 2, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["result"]["status"], "deployed")
        self.assertEqual(adapter.infrastructure.seen_kubeconfig, "/tmp/vm-single-k3s.yaml")
        ensure_access.assert_called_once_with(adapter_name="fake")

    def test_framework_execution_mode_orchestrator_maps_vm_single_to_tunnel(self):
        topology_config = {
            "FRAMEWORK_EXECUTION_MODE": "orchestrator",
            "VM_SINGLE_LEVEL_EXECUTION_MODE": "auto",
        }

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main._normalized_vm_single_level_execution_mode(topology_config), "tunnel")

    def test_framework_execution_mode_target_vm_maps_vm_single_to_local(self):
        topology_config = {
            "FRAMEWORK_EXECUTION_MODE": "target-vm",
            "VM_SINGLE_LEVEL_EXECUTION_MODE": "auto",
        }

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main._normalized_vm_single_level_execution_mode(topology_config), "local")

    def test_specific_vm_single_execution_mode_overrides_framework_execution_mode(self):
        topology_config = {
            "FRAMEWORK_EXECUTION_MODE": "orchestrator",
            "VM_SINGLE_LEVEL_EXECUTION_MODE": "local",
        }

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main._normalized_vm_single_level_execution_mode(topology_config), "local")

    def test_run_level_one_vm_single_auto_syncs_vm_ip_after_preflight(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.setup_cluster_preflight = mock.Mock(
            return_value={
                "status": "ready",
                "mode": "preflight",
                "topology": "vm-single",
                "cluster_creation": "skipped",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "deployer.config")
            overlay_path = os.path.join(tmpdir, "topologies", "vm-single.config")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            "VM_EXTERNAL_IP=198.51.100.20",
                            "VM_COMMON_IP=198.51.100.20",
                            "VM_DATASPACE_IP=198.51.100.20",
                            "VM_CONNECTORS_IP=198.51.100.20",
                            "VM_COMPONENTS_IP=198.51.100.20",
                            "INGRESS_EXTERNAL_IP=198.51.100.20",
                            "",
                        ]
                    )
                )

            with mock.patch.object(main, "_infrastructure_deployer_config_path", return_value=config_path), \
                mock.patch.object(
                    main,
                    "_detect_vm_single_address_candidates",
                    return_value={
                        "vm_ip": "198.51.100.20",
                        "minikube_ip": "192.0.2.10",
                        "recommended_address": "198.51.100.20",
                        "recommended_source": "vm",
                        "cluster_type": "k3s",
                    },
                ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
                result = main.run_level(adapter, 1, deployer_name="fake", topology="vm-single")

            with open(overlay_path, "r", encoding="utf-8") as handle:
                config_text = handle.read()

        self.assertEqual(result["level"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertIn("VM_EXTERNAL_IP=198.51.100.20\n", config_text)
        self.assertIn("VM_COMMON_IP=198.51.100.20\n", config_text)
        self.assertIn("VM_DATASPACE_IP=198.51.100.20\n", config_text)
        self.assertIn("VM_CONNECTORS_IP=198.51.100.20\n", config_text)
        self.assertIn("VM_COMPONENTS_IP=198.51.100.20\n", config_text)
        self.assertIn("INGRESS_EXTERNAL_IP=198.51.100.20\n", config_text)

    def test_run_level_one_vm_single_preserves_explicit_custom_address_after_preflight(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.setup_cluster_preflight = mock.Mock(
            return_value={
                "status": "ready",
                "mode": "preflight",
                "topology": "vm-single",
                "cluster_creation": "skipped",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "deployer.config")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            "VM_EXTERNAL_IP=203.0.113.44",
                            "INGRESS_EXTERNAL_IP=203.0.113.44",
                            "",
                        ]
                    )
                )

            with mock.patch.object(main, "_infrastructure_deployer_config_path", return_value=config_path), \
                mock.patch.object(
                    main,
                    "_detect_vm_single_address_candidates",
                    return_value={
                        "vm_ip": "198.51.100.20",
                        "minikube_ip": "192.0.2.10",
                        "recommended_address": "192.0.2.10",
                        "recommended_source": "minikube",
                    },
                ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
                result = main.run_level(adapter, 1, deployer_name="fake", topology="vm-single")

            with open(config_path, "r", encoding="utf-8") as handle:
                config_text = handle.read()

        self.assertEqual(result["level"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertIn("VM_EXTERNAL_IP=203.0.113.44\n", config_text)
        self.assertIn("INGRESS_EXTERNAL_IP=203.0.113.44\n", config_text)

    def test_run_level_two_uses_vm_single_topology_deploy_infrastructure(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.deploy_infrastructure_for_topology = mock.Mock(
            return_value={"status": "deployed", "mode": "vm-single"}
        )

        with mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 2, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["mode"], "vm-single")
        adapter.infrastructure.deploy_infrastructure_for_topology.assert_called_once_with(topology="vm-single")
        self.assertEqual(adapter.calls, [])

    def test_run_level_three_uses_vm_single_topology_deploy_dataspace(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.deployment = mock.Mock()
        adapter.deployment.deploy_dataspace_for_topology = mock.Mock(
            return_value={"status": "deployed", "mode": "vm-single"}
        )

        with mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 3, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["mode"], "vm-single")
        adapter.deployment.deploy_dataspace_for_topology.assert_called_once_with(topology="vm-single")
        self.assertEqual(adapter.calls, [])

    def test_run_level_vm_single_with_public_url_skips_hosts_followup(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.deployment = mock.Mock()
        adapter.deployment.deploy_dataspace_for_topology = mock.Mock(
            return_value={"status": "deployed", "mode": "vm-single"}
        )
        context = types.SimpleNamespace(
            topology="vm-single",
            config={
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
            },
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("fake", context),
        ), mock.patch.object(
            main,
            "_resolve_level_access_urls",
            return_value={
                "public_portal_backend_admin": "https://org4.pionera.oeg.fi.upm.es/public-portal-backend/admin",
            },
        ):
            result = main.run_level(adapter, 3, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["urls"]["public_portal_backend_admin"],
            "https://org4.pionera.oeg.fi.upm.es/public-portal-backend/admin",
        )
        self.assertNotIn("hosts_plan", result)
        self.assertNotIn("hosts_sync", result)

    def test_run_level_vm_single_k3s_sets_kubeconfig_for_every_level(self):
        adapter = FakeAdapterWithInfrastructure()
        observed = {}

        def fake_deploy_dataspace_for_topology(**_kwargs):
            observed["kubeconfig"] = os.environ.get("KUBECONFIG")
            return {"status": "deployed", "mode": "vm-single"}

        adapter.deployment = mock.Mock()
        adapter.deployment.deploy_dataspace_for_topology = mock.Mock(side_effect=fake_deploy_dataspace_for_topology)

        with mock.patch.object(
            main,
            "_topology_runtime_environment_overrides",
            return_value={"KUBECONFIG": "/etc/rancher/k3s/k3s.yaml"},
        ), mock.patch.object(
            main,
            "_ensure_vm_single_k3s_api_access",
            return_value={"status": "ready", "kubeconfig": "/etc/rancher/k3s/k3s.yaml"},
        ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}), mock.patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            result = main.run_level(adapter, 3, deployer_name="fake", topology="vm-single")
            restored_kubeconfig = os.environ.get("KUBECONFIG")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(observed["kubeconfig"], "/etc/rancher/k3s/k3s.yaml")
        self.assertIsNone(restored_kubeconfig)

    def test_topology_runtime_environment_overrides_use_vm_single_local_kubeconfig(self):
        with mock.patch.object(
            main,
            "_load_effective_infrastructure_deployer_config",
            return_value={
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/etc/rancher/k3s/k3s.yaml",
                "VM_SINGLE_LOCAL_KUBECONFIG": "/home/operator/.kube/pionera4.yaml",
            },
        ):
            overrides = main._topology_runtime_environment_overrides("vm-single", level=4)

        self.assertEqual(overrides["KUBECONFIG"], "/home/operator/.kube/pionera4.yaml")

    def test_topology_runtime_environment_overrides_use_vm_single_remote_kubeconfig_on_target_vm(self):
        topology_config = {
            "CLUSTER_TYPE": "k3s",
            "K3S_KUBECONFIG": "/etc/rancher/k3s/k3s.yaml",
            "VM_SINGLE_LOCAL_KUBECONFIG": "/home/operator/.kube/pionera4.yaml",
            "VM_SINGLE_REMOTE_KUBECONFIG": "/etc/rancher/k3s/k3s.yaml",
        }
        with mock.patch.object(
            main,
            "_load_effective_infrastructure_deployer_config",
            return_value=topology_config,
        ), mock.patch.object(
            main,
            "_load_vm_single_configuration_bundle",
            return_value={"infrastructure": {}, "topology": topology_config, "adapter": {}},
        ), mock.patch.object(
            main,
            "_build_vm_single_topology_plan",
            return_value={"vms": [{"address": "127.0.0.1"}]},
        ), mock.patch.object(main, "_vm_single_running_on_target", return_value=True):
            overrides = main._topology_runtime_environment_overrides("vm-single", level=6)

        self.assertEqual(overrides["KUBECONFIG"], "/etc/rancher/k3s/k3s.yaml")

    def test_vm_single_k3s_tunnel_preparation_includes_level6(self):
        topology_config = {
            "CLUSTER_TYPE": "k3s",
            "VM_SINGLE_LEVEL_EXECUTION_MODE": "auto",
        }
        plan = {"vms": [{"address": "192.0.2.52"}]}

        with mock.patch.object(main, "_vm_single_running_on_target", return_value=False), mock.patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            self.assertTrue(main._vm_single_should_prepare_k3s_tunnel(6, plan, topology_config))

    def test_interactive_runtime_environment_applies_vm_single_kubeconfig(self):
        with mock.patch.object(
            main,
            "_load_effective_infrastructure_deployer_config",
            return_value={
                "CLUSTER_TYPE": "k3s",
                "VM_SINGLE_LOCAL_KUBECONFIG": "/home/operator/.kube/pionera4.yaml",
            },
        ), mock.patch.dict(os.environ, {}, clear=True):
            main._apply_interactive_topology_runtime_environment("vm-single")
            applied_kubeconfig = os.environ.get("KUBECONFIG")
            main._apply_interactive_topology_runtime_environment("local")
            cleared_kubeconfig = os.environ.get("KUBECONFIG")

        self.assertEqual(applied_kubeconfig, "/home/operator/.kube/pionera4.yaml")
        self.assertIsNone(cleared_kubeconfig)

    def test_topology_runtime_environment_overrides_use_vm_distributed_roles(self):
        with mock.patch.object(
            main,
            "_load_effective_infrastructure_deployer_config",
            return_value={
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG_COMMON": "/clusters/common.yaml",
                "K3S_KUBECONFIG_COMPONENTS": "/clusters/components.yaml",
            },
        ):
            level2_env = main._topology_runtime_environment_overrides("vm-distributed", level=2)
            level5_env = main._topology_runtime_environment_overrides("vm-distributed", level=5)

        self.assertEqual(level2_env["KUBECONFIG"], "/clusters/common.yaml")
        self.assertEqual(level2_env["PIONERA_KUBECONFIG_ROLE"], "common")
        self.assertEqual(level5_env["KUBECONFIG"], "/clusters/components.yaml")
        self.assertEqual(level5_env["PIONERA_KUBECONFIG_ROLE"], "components")

    def test_environment_profile_name_defaults_to_pionera(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main._environment_profile_name(), "pionera")
            self.assertEqual(main._environment_profile_path(), os.path.join(
                main._environment_profiles_dir(),
                "pionera.env",
            ))

    def test_vm_distributed_profile_template_uses_blank_variables_with_section_comments(self):
        content = main._vm_distributed_profile_template_content(
            topology="vm-distributed",
            adapter_name="inesdata",
        )

        self.assertIn("# Local validation-environment profile.", content)
        self.assertIn("# VM placement", content)
        self.assertIn("# Dataspace and connector inventory", content)
        self.assertIn("DOMAIN_BASE=\n", content)
        self.assertIn("VM_COMMON_IP=\n", content)
        self.assertIn("DS_1_CONNECTORS=\n", content)
        self.assertNotIn("example.org", content)
        for line in content.splitlines():
            if not line or line.startswith("#"):
                continue
            self.assertTrue(line.endswith("="), line)

    def test_vm_distributed_profile_template_keys_are_supported_by_profile_loader(self):
        keys = main._vm_distributed_profile_template_keys(
            topology="vm-distributed",
            adapter_name="inesdata",
        )
        values = {key: "x" for key in keys}

        _grouped, rejected = main._split_configuration_profile_updates(
            values,
            topology="vm-distributed",
            adapter_name="inesdata",
        )

        self.assertEqual(rejected, [])

    def test_vm_single_profile_template_uses_blank_variables_with_section_comments(self):
        content = main._vm_distributed_profile_template_content(
            topology="vm-single",
            adapter_name="inesdata",
        )

        self.assertIn("# Public domain and common routes", content)
        self.assertIn("# Kubernetes runtime", content)
        self.assertIn("# Execution mode", content)
        self.assertIn("VM_SINGLE_HTTP_URL=\n", content)
        self.assertIn("VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX=\n", content)
        self.assertIn("DS_1_CONNECTORS=\n", content)
        self.assertNotIn("org4.pionera", content)
        for line in content.splitlines():
            if not line or line.startswith("#"):
                continue
            self.assertTrue(line.endswith("="), line)

    def test_vm_single_profile_template_keys_are_supported_by_profile_loader(self):
        keys = main._vm_distributed_profile_template_keys(
            topology="vm-single",
            adapter_name="inesdata",
        )
        values = {key: "x" for key in keys}

        _grouped, rejected = main._split_configuration_profile_updates(
            values,
            topology="vm-single",
            adapter_name="inesdata",
        )

        self.assertEqual(rejected, [])

    def test_vm_distributed_profile_loader_ignores_blank_template_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = os.path.join(tmpdir, "profile.env")
            with open(profile_path, "w", encoding="utf-8") as handle:
                handle.write("DOMAIN_BASE=\nDS_1_NAME=pionera\nVM_COMMON_IP=\n")

            values, errors = main._load_vm_distributed_profile(profile_path)

        self.assertEqual(errors, [])
        self.assertEqual(values, {"DS_1_NAME": "pionera"})

    def test_vm_distributed_profile_creation_creates_pionera_env_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            main,
            "_framework_root_dir",
            return_value=tmpdir,
        ), mock.patch.dict(os.environ, {}, clear=True):
            state = main._ensure_vm_distributed_profile_file(adapter_name="inesdata")
            profile_path = os.path.join(tmpdir, ".profiles", "pionera.env")

            self.assertEqual(state["status"], "created")
            self.assertEqual(state["path"], profile_path)
            self.assertTrue(os.path.isfile(profile_path))
            with open(profile_path, encoding="utf-8") as handle:
                created_content = handle.read()
            self.assertIn("# Common and dataspace domains", created_content)
            self.assertIn("DOMAIN_BASE=\n", created_content)

            with open(profile_path, "w", encoding="utf-8") as handle:
                handle.write("DOMAIN_BASE=keep.example\n")
            state = main._ensure_vm_distributed_profile_file(adapter_name="inesdata")
            with open(profile_path, encoding="utf-8") as handle:
                preserved_content = handle.read()

        self.assertEqual(state["status"], "exists")
        self.assertEqual(preserved_content, "DOMAIN_BASE=keep.example\n")

    def test_run_level_two_uses_vm_distributed_topology_deploy_infrastructure(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.deploy_infrastructure_for_topology = mock.Mock(
            return_value={"status": "deployed", "mode": "vm-distributed"}
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            main,
            "_framework_root_dir",
            return_value=tmpdir,
        ), mock.patch.object(
            main,
            "_ensure_vm_distributed_local_kubeconfigs",
            return_value={"status": "skipped"},
        ), mock.patch.object(
            main,
            "_topology_runtime_environment_overrides",
            return_value={},
        ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 2, deployer_name="fake", topology="vm-distributed")
            profile_path = os.path.join(tmpdir, ".profiles", "pionera.env")
            profile_created = os.path.isfile(profile_path)

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["mode"], "vm-distributed")
        self.assertTrue(profile_created)
        adapter.infrastructure.deploy_infrastructure_for_topology.assert_called_once_with(topology="vm-distributed")
        self.assertEqual(adapter.calls, [])

    def test_run_level_two_creates_vm_single_profile_template(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.deploy_infrastructure_for_topology = mock.Mock(
            return_value={"status": "deployed", "mode": "vm-single"}
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            main,
            "_framework_root_dir",
            return_value=tmpdir,
        ), mock.patch.object(
            main,
            "_topology_runtime_environment_overrides",
            return_value={},
        ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 2, deployer_name="fake", topology="vm-single")
            profile_path = os.path.join(tmpdir, ".profiles", "pionera.env")
            with open(profile_path, encoding="utf-8") as handle:
                profile_content = handle.read()

        self.assertEqual(result["level"], 2)
        self.assertEqual(result["status"], "completed")
        self.assertIn("VM_SINGLE_HTTP_URL=\n", profile_content)
        self.assertIn("# Public domain and common routes", profile_content)
        adapter.infrastructure.deploy_infrastructure_for_topology.assert_called_once_with(topology="vm-single")

    def test_run_level_three_uses_vm_distributed_topology_deploy_dataspace(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.deployment = mock.Mock()
        adapter.deployment.deploy_dataspace_for_topology = mock.Mock(
            return_value={"status": "deployed", "mode": "vm-distributed"}
        )

        with mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 3, deployer_name="fake", topology="vm-distributed")

        self.assertEqual(result["level"], 3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["mode"], "vm-distributed")
        adapter.deployment.deploy_dataspace_for_topology.assert_called_once_with(topology="vm-distributed")
        self.assertEqual(adapter.calls, [])

    def test_run_level_four_vm_distributed_allows_multi_kubeconfig_connectors(self):
        adapter = FakeAdapter()

        with mock.patch.object(
            main,
            "_configured_vm_distributed_role_kubeconfigs",
            return_value={
                "common": "/clusters/common.yaml",
                "provider": "/clusters/provider.yaml",
                "consumer": "/clusters/consumer.yaml",
            },
        ), mock.patch.object(
            main,
            "_ensure_vm_distributed_level4_kubeconfig_supported",
            return_value=None,
        ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 4, deployer_name="fake", topology="vm-distributed")

        self.assertEqual(result["level"], 4)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(adapter.calls, ["deploy_connectors"])

    def test_run_level_four_vm_distributed_allows_single_logical_cluster(self):
        adapter = FakeAdapter()

        with mock.patch.object(
            main,
            "_configured_vm_distributed_role_kubeconfigs",
            return_value={
                "common": "/clusters/common.yaml",
                "provider": "/clusters/common.yaml",
                "consumer": "/clusters/common.yaml",
            },
        ), mock.patch.object(
            main,
            "_ensure_vm_distributed_level4_kubeconfig_supported",
            return_value=None,
        ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 4, deployer_name="fake", topology="vm-distributed")

        self.assertEqual(result["level"], 4)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], ["conn-a", "conn-b"])
        self.assertEqual(adapter.calls, ["deploy_connectors"])

    def test_run_level_four_vm_distributed_syncs_routing_after_connectors(self):
        adapter = FakeAdapter()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.sync_vm_distributed_routing = mock.Mock(return_value={"status": "synced"})

        with mock.patch.object(
            main,
            "_configured_vm_distributed_role_kubeconfigs",
            return_value={
                "common": "/clusters/common.yaml",
                "provider": "/clusters/common.yaml",
                "consumer": "/clusters/common.yaml",
            },
        ), mock.patch.object(
            main,
            "_ensure_vm_distributed_level4_kubeconfig_supported",
            return_value=None,
        ), mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 4, deployer_name="fake", topology="vm-distributed")

        self.assertEqual(result["level"], 4)
        self.assertEqual(result["status"], "completed")
        adapter.infrastructure.sync_vm_distributed_routing.assert_called_once()

    def test_run_level_four_uses_vm_single_connector_deployment(self):
        adapter = FakeAdapter()

        with mock.patch.object(main, "_resolve_level_access_urls", return_value={}):
            result = main.run_level(adapter, 4, deployer_name="fake", topology="vm-single")

        self.assertEqual(result["level"], 4)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], ["conn-a", "conn-b"])
        self.assertEqual(adapter.calls, ["deploy_connectors"])

    def test_run_level_four_prepares_local_edc_image_when_missing_override(self):
        adapter = FakeAdapter()
        adapter.config_adapter.load_deployer_config = lambda: {
            "KC_URL": "http://keycloak.local",
            "DS_1_NAME": "fake-ds",
            "EDC_DASHBOARD_ENABLED": "true",
        }

        with mock.patch.object(
            main,
            "_prepare_edc_local_connector_image_override",
            return_value={
                "image_name": "validation-environment/edc-connector",
                "image_tag": "local",
                "minikube_profile": "minikube",
            },
        ) as image_prepare, mock.patch.object(
            main,
            "_prepare_edc_local_dashboard_images",
            return_value={"status": "prepared"},
        ) as dashboard_prepare, mock.patch.object(
            main,
            "_resolve_level_access_urls",
            return_value={
                "connectors": {
                    "conn-a": {"connector_management_api_v3": "http://conn-a.example.local/management/v3"},
                    "conn-b": {"connector_management_api_v3": "http://conn-b.example.local/management/v3"},
                }
            },
        ), mock.patch.dict(os.environ, {}, clear=True):
            result = main.run_level(adapter, 4, deployer_name="edc", topology="local")

        self.assertEqual(result["level"], 4)
        self.assertEqual(result["result"], ["conn-a", "conn-b"])
        self.assertIn("connectors", result["urls"])
        image_prepare.assert_called_once_with(adapter)
        dashboard_prepare.assert_called_once()

    def test_run_available_access_urls_for_edc_includes_registration_service_and_connectors(self):
        adapter = FakeAdapter()
        fake_context = types.SimpleNamespace(
            config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm", "DOMAIN_BASE": "dev.ed.dataspaceunit.upm"},
            dataspace_name="demoedc",
            environment="DEV",
            connectors=["conn-citycounciledc-demoedc"],
            components=["ontology-hub"],
        )

        with mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("edc", fake_context),
        ), mock.patch(
            "deployers.edc.bootstrap.common_access_urls",
            return_value={
                "keycloak_realm": "http://keycloak.dev.ds.dataspaceunit.upm/realms/demoedc",
                "keycloak_admin_console": "http://keycloak-admin.dev.ds.dataspaceunit.upm/admin/demoedc/console/",
                "minio_api": "http://minio.dev.ed.dataspaceunit.upm",
                "minio_console": "http://console.minio-s3.dev.ds.dataspaceunit.upm",
            },
        ), mock.patch(
            "deployers.edc.bootstrap.build_connector_access_urls",
            return_value={
                "connector_management_api_v3": "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm/management/v3",
                "connector_protocol_api": "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm/protocol",
                "edc_dashboard_login": "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm/edc-dashboard/",
                "minio_bucket": "demoedc-conn-citycounciledc-demoedc",
            },
        ):
            result = main.run_available_access_urls(adapter, deployer_name="edc", topology="local")

        self.assertEqual(
            result["urls"]["registration_service"],
            "http://registration-service-demoedc.dev.ds.dataspaceunit.upm",
        )
        self.assertEqual(
            result["urls"]["connectors"]["conn-citycounciledc-demoedc"]["connector_management_api_v3"],
            "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm/management/v3",
        )
        self.assertEqual(
            result["urls"]["components"]["ontology-hub"],
            "http://ontology-hub.example.local",
        )
        self.assertEqual(result["urls"]["minio_api"], "http://minio.dev.ed.dataspaceunit.upm")
        self.assertEqual(
            result["urls"]["connectors"]["conn-citycounciledc-demoedc"]["minio_bucket"],
            "demoedc-conn-citycounciledc-demoedc",
        )

    def test_run_levels_reuses_one_adapter_for_selected_levels(self):
        result = main.run_levels(
            "fake",
            levels=[2, 3, 4],
            adapter_registry=self.registry,
            deployer_registry=self.deployer_registry,
            validation_engine_cls=FakeValidationEngine,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual([entry["level"] for entry in result["levels"]], [2, 3, 4])

    def test_default_command_runs_experiment_runner(self):
        result = main.main(
            ["fake"],
            runner_cls=FakeRunner,
            adapter_registry=self.registry,
            validation_engine_cls=FakeValidationEngine,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "run-ok")
        self.assertEqual(result["adapter"], "FakeAdapter")

    def test_run_command_can_return_deployer_shadow_plan_opt_in(self):
        adapter = FakeAdapter()

        with mock.patch.dict(os.environ, {"PIONERA_USE_DEPLOYER_RUN": "true"}, clear=False):
            result = main.run_run(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["mode"], "shadow")
        self.assertEqual(result["operation"], "run")
        self.assertEqual(result["sequence"], ["deploy", "validate", "metrics"])
        self.assertEqual(result["validate"]["connectors"], ["conn-deployer-a", "conn-deployer-b"])
        self.assertEqual(result["validate"]["validation_profile"]["adapter"], "fake")
        self.assertEqual(result["metrics"]["connectors"], ["conn-deployer-a", "conn-deployer-b"])

    def test_run_command_can_execute_real_deployer_chain_only_for_edc(self):
        adapter = FakeAdapter()

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_RUN": "true",
                "PIONERA_EXECUTE_DEPLOYER_RUN": "true",
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "clean1",
            },
            clear=False,
        ):
            result = main.run_run(
                adapter,
                deployer_name="edc",
                deployer_registry=self.deployer_registry,
                topology="local",
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["operation"], "run")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sequence"], ["deploy", "validate", "metrics"])
        self.assertEqual(result["experiment_dir"], result["validation"]["experiment_dir"])
        self.assertEqual(result["experiment_dir"], result["metrics"]["experiment_dir"])
        self.assertEqual(result["deployment"]["connectors"], ["conn-deployer-a", "conn-deployer-b"])
        self.assertEqual(result["validation"]["validation"], {"validated": ["conn-deployer-a", "conn-deployer-b"]})
        self.assertEqual(result["metrics"]["connectors"], ["conn-deployer-a", "conn-deployer-b"])

    def test_run_command_execute_runs_playwright_when_profile_enables_it(self):
        adapter = FakeAdapter()

        def resolve_context_with_dashboard(self, topology="local"):
            return {
                "deployer": "edc",
                "topology": topology,
                "environment": "DEV",
                "dataspace_name": "fake-ds",
                "ds_domain_base": "example.local",
                "connectors": ["conn-a", "conn-b"],
                "components": [],
                "namespace_roles": {
                    "registration_service_namespace": "fake-ds",
                    "provider_namespace": "fake-ds",
                    "consumer_namespace": "fake-ds",
                },
                "runtime_dir": "/tmp/fake-ds",
                "config": {
                    "DS_1_NAME": "fake-ds",
                    "EDC_DASHBOARD_ENABLED": os.environ.get("PIONERA_EDC_DASHBOARD_ENABLED", "false"),
                    "EDC_DASHBOARD_PROXY_AUTH_MODE": os.environ.get(
                        "PIONERA_EDC_DASHBOARD_PROXY_AUTH_MODE",
                        "service-account",
                    ),
                },
            }

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "test_data_cleanup_enabled": False,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.edc.config.ts",
            },
        ), mock.patch.object(
            FakeDeployer,
            "resolve_context",
            new=resolve_context_with_dashboard,
        ), mock.patch.object(
            main,
            "run_playwright_validation",
            return_value={"status": "passed", "summary": {"total_specs": 2}},
        ) as playwright_runner, mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_RUN": "true",
                "PIONERA_EXECUTE_DEPLOYER_RUN": "true",
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "clean1",
            },
            clear=False,
        ):
            result = main.run_run(
                adapter,
                deployer_name="edc",
                deployer_registry=self.deployer_registry,
                topology="local",
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["validation"]["playwright"]["status"], "passed")
        self.assertEqual(result["validation"]["playwright"]["summary"]["total_specs"], 2)
        playwright_runner.assert_called_once()

    def test_run_command_execute_can_disable_profile_playwright_explicitly(self):
        adapter = FakeAdapter()

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "test_data_cleanup_enabled": False,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.edc.config.ts",
            },
        ), mock.patch.object(
            main,
            "run_playwright_validation",
        ) as playwright_runner, mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_RUN": "true",
                "PIONERA_EXECUTE_DEPLOYER_RUN": "true",
                "PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT": "false",
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "clean1",
            },
            clear=False,
        ):
            result = main.run_run(
                adapter,
                deployer_name="edc",
                deployer_registry=self.deployer_registry,
                topology="local",
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["validation"]["playwright"]["status"], "skipped")
        self.assertEqual(result["validation"]["playwright"]["reason"], "disabled")
        playwright_runner.assert_not_called()

    def test_run_command_execute_runs_test_data_cleanup_when_profile_enables_it(self):
        adapter = FakeAdapter()

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "test_data_cleanup_enabled": True,
                "playwright_enabled": False,
            },
        ), mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={"status": "completed", "summary": {"deleted_total": 2}},
        ) as cleanup_runner, mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_RUN": "true",
                "PIONERA_EXECUTE_DEPLOYER_RUN": "true",
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "clean1",
            },
            clear=False,
        ):
            result = main.run_run(
                adapter,
                deployer_name="edc",
                deployer_registry=self.deployer_registry,
                topology="local",
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["validation"]["test_data_cleanup"]["status"], "completed")
        cleanup_runner.assert_called_once()
        cleanup_kwargs = cleanup_runner.call_args.kwargs
        self.assertEqual(cleanup_kwargs["connectors"], ["conn-deployer-a", "conn-deployer-b"])

    def test_build_adapter_passes_topology_when_supported(self):
        adapter = main.build_adapter(
            "topology",
            adapter_registry={"topology": "fake_adapter_module:TopologyAwareAdapter"},
            dry_run=True,
            topology="local",
        )

        self.assertTrue(adapter.dry_run)
        self.assertEqual(adapter.topology, "local")

    def test_build_deployer_wraps_existing_adapter_without_changing_cli_flow(self):
        adapter = FakeAdapter()

        deployer = main.build_deployer(
            "fake",
            deployer_registry=self.deployer_registry,
            adapter_registry=self.registry,
            adapter=adapter,
            topology="local",
        )

        self.assertEqual(deployer.name(), "fake")
        self.assertIs(deployer.adapter, adapter)
        self.assertEqual(deployer.topology, "local")

    def test_build_deployer_orchestrator_returns_safe_internal_orchestrator(self):
        adapter = FakeAdapter()

        orchestrator = main.build_deployer_orchestrator(
            "fake",
            deployer_registry=self.deployer_registry,
            adapter_registry=self.registry,
            adapter=adapter,
            topology="local",
        )

        result = orchestrator.validate(topology="local")

        self.assertEqual(result["context"].dataspace_name, "fake-ds")
        self.assertEqual(result["profile"].adapter, "fake")
        self.assertEqual(result["connectors"], ["conn-deployer-a", "conn-deployer-b"])

    def test_deploy_command_dispatches_to_adapter(self):
        adapter = FakeAdapter()
        result = main.run_deploy(adapter)

        self.assertEqual(result, ["conn-a", "conn-b"])
        self.assertEqual(
            adapter.calls,
            ["deploy_infrastructure", "deploy_dataspace", "deploy_connectors"],
        )

    def test_deploy_command_can_return_shadow_plan_via_deployer_opt_in(self):
        adapter = FakeAdapter()

        with mock.patch.dict(os.environ, {"PIONERA_USE_DEPLOYER_DEPLOY": "true"}, clear=False):
            result = main.run_deploy(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(result["mode"], "shadow")
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["deployer_name"], "fake")
        self.assertEqual(result["namespace_roles"]["provider_namespace"], "fake-ds")
        self.assertEqual(result["deployer_context"]["dataspace_name"], "fake-ds")
        self.assertEqual(result["deployer_context"]["config"]["KC_PASSWORD"], "***REDACTED***")
        self.assertEqual(result["deployer_context"]["config"]["VT_TOKEN"], "***REDACTED***")
        self.assertEqual(result["hosts_plan"]["level_3"], ["registration-service-fake-ds.example.local"])
        self.assertEqual(
            result["hosts_plan"]["level_4"],
            ["conn-a.example.local", "conn-b.example.local"],
        )
        self.assertEqual(result["validation_profile"]["adapter"], "fake")
        self.assertEqual(adapter.calls, [])

    def test_deploy_command_non_local_uses_deployer_shadow_plan_by_default(self):
        adapter = FakeAdapter()

        result = main.run_deploy(
            adapter,
            deployer_name="fakevm",
            deployer_registry=self.deployer_registry,
            topology="vm-single",
        )

        self.assertEqual(result["mode"], "shadow")
        self.assertEqual(result["topology"], "vm-single")
        self.assertEqual(result["hosts_plan"]["address"], "192.0.2.10")
        self.assertEqual(adapter.calls, [])

    def test_deploy_shadow_plan_includes_level_plan_from_adapter_preflight(self):
        adapter = DeployShadowPreviewAdapter(topology="local")

        with mock.patch.dict(os.environ, {"PIONERA_USE_DEPLOYER_DEPLOY": "true"}, clear=False):
            result = main.run_deploy(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(result["preflight"]["status"], "dataspace-required")
        self.assertEqual(result["level_plan"]["level_1_2"]["status"], "ready")
        self.assertEqual(result["level_plan"]["level_3"]["status"], "missing")
        self.assertEqual(result["level_plan"]["level_4"]["status"], "bootstrap-required")
        self.assertEqual(result["level_plan"]["level_5"]["status"], "not-applicable")

    def test_deploy_command_can_execute_real_deployer_only_for_edc(self):
        adapter = FakeAdapter()

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "clean1",
            },
            clear=False,
        ):
            result = main.run_deploy(
                adapter,
                deployer_name="edc",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["deployer_name"], "edc")
        self.assertEqual(result["deployment"]["infrastructure"]["status"], "infra-ok")
        self.assertEqual(result["deployment"]["dataspace"]["status"], "dataspace-ok")
        self.assertEqual(result["deployment"]["connectors"], ["conn-deployer-a", "conn-deployer-b"])
        self.assertEqual(result["validation_profile"]["adapter"], "fake")
        self.assertEqual(result["hosts_sync"]["status"], "skipped")

    def test_deploy_command_can_sync_hosts_when_explicitly_enabled(self):
        adapter = FakeAdapter()

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "clean1",
                "PIONERA_SYNC_HOSTS": "true",
                "PIONERA_HOSTS_FILE": hosts_file.name,
            },
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n")
            hosts_file.flush()
            result = main.run_deploy(
                adapter,
                deployer_name="edc",
                deployer_registry=self.deployer_registry,
                topology="local",
            )
            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertEqual(result["hosts_sync"]["status"], "updated")
        self.assertIn("# BEGIN Validation-Environment dataspace fake-ds", hosts_content)
        self.assertIn("127.0.0.1 registration-service-fake-ds.example.local", hosts_content)
        self.assertIn("127.0.0.1 conn-a.example.local", hosts_content)

    def test_hosts_command_plans_entries_without_modifying_hosts_by_default(self):
        adapter = FakeAdapter()

        result = main.run_hosts(
            adapter,
            deployer_name="fake",
            deployer_registry=self.deployer_registry,
            topology="local",
        )

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["hosts_sync"]["reason"], "disabled")
        self.assertEqual(result["hosts_plan"]["level_3"], ["registration-service-fake-ds.example.local"])
        self.assertEqual(result["hosts_plan"]["level_4"], ["conn-a.example.local", "conn-b.example.local"])

    def test_hosts_command_dry_run_reports_legacy_external_hostnames_when_hosts_file_is_known(self):
        adapter = FakeAdapter()
        context = DeploymentContext(
            deployer="fake",
            topology="local",
            environment="DEV",
            dataspace_name="fake-ds",
            ds_domain_base="example.local",
            connectors=["conn-a", "conn-b"],
            config={"DOMAIN_BASE": "dev.ed.dataspaceunit.upm"},
        )

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {"PIONERA_HOSTS_FILE": hosts_file.name},
            clear=False,
        ), mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("fake", context),
        ):
            hosts_file.write(
                "127.0.0.1 localhost\n"
                "127.0.0.1 keycloak.dev.ed.dataspaceunit.upm\n"
                "127.0.0.1 keycloak-admin.dev.ed.dataspaceunit.upm\n"
            )
            hosts_file.flush()
            result = main.run_hosts(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(
            result["hosts_plan"]["legacy_external_hostnames"],
            [
                {
                    "legacy": "keycloak.dev.ed.dataspaceunit.upm",
                    "canonical": "auth.dev.ed.dataspaceunit.upm",
                },
                {
                    "legacy": "keycloak-admin.dev.ed.dataspaceunit.upm",
                    "canonical": "admin.auth.dev.ed.dataspaceunit.upm",
                },
            ],
        )

    def test_public_access_command_reconciles_vm_distributed_entrypoints(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main.main(
                ["public", "public-access", "reconcile", "--topology", "vm-distributed"],
                adapter_registry={"public": "fake_adapter_module:FakePublicAccessAdapter"},
            )

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["topology"], "vm-distributed")
        self.assertEqual(result["adapter"], "public")
        self.assertIn("common_public_paths", result)
        self.assertIn("component_public_paths", result)
        self.assertIn('"status": "synced"', stdout.getvalue())

    def test_public_access_command_requires_vm_distributed_topology(self):
        with self.assertRaises(SystemExit):
            main.main(
                ["public", "public-access", "reconcile", "--topology", "local"],
                adapter_registry={"public": "fake_adapter_module:FakePublicAccessAdapter"},
            )

    def test_public_access_dry_run_lists_reconcile_actions(self):
        result = main.main(
            ["public", "public-access", "--dry-run", "--topology", "vm-distributed"],
            adapter_registry={"public": "fake_adapter_module:FakePublicAccessAdapter"},
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["command"], "public-access")
        self.assertEqual(
            result["actions"],
            [
                "reconcile_ingress_service_type",
                "reconcile_vm_distributed_routing",
                "reconcile_common_public_path_ingresses",
                "reconcile_component_public_path_ingresses",
            ],
        )
        self.assertTrue(result["public_access"]["supported"])

    def test_ssh_access_dry_run_lists_bootstrap_plan_actions(self):
        result = main.main(
            ["fake", "ssh-access", "--dry-run", "--topology", "vm-distributed"],
            adapter_registry=self.registry,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["command"], "ssh-access")
        self.assertIn("build_idempotent_ssh_bootstrap_plan", result["actions"])
        self.assertTrue(result["ssh_access"]["supported"])

    def test_ssh_access_dry_run_supports_vm_single(self):
        result = main.main(
            ["fake", "ssh-access", "--dry-run", "--topology", "vm-single"],
            adapter_registry=self.registry,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["command"], "ssh-access")
        self.assertTrue(result["ssh_access"]["supported"])

    def test_ssh_access_plan_returns_idempotent_bootstrap_plan(self):
        plan = {
            "execution_host": "common-services",
            "ssh": {
                "mode": "bastion",
                "bastion": {
                    "host": "bastion.example.test",
                    "port": "2222",
                    "user": "jump",
                },
            },
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "plan",
                "identity_file": "/home/operator/.ssh/validation-env-vm",
                "key_comment": "validation-env",
                "targets": [
                    {
                        "role": "common-services",
                        "role_key": "common",
                        "host": "common.example.test",
                        "user": "operator",
                        "port": "2256",
                        "identity_file": "/home/operator/.ssh/validation-env-vm",
                        "needs_public_key": True,
                    }
                ],
                "actions": [{"name": "ensure_dedicated_keypair"}],
            },
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "_current_vm_distributed_topology_plan",
            return_value=plan,
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "ssh-access", "plan", "--topology", "vm-distributed"],
                adapter_registry=self.registry,
            )

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["execution_host"], "common-services")
        self.assertEqual(result["execution_location"]["mode"], "common-services")
        self.assertEqual(result["ssh_bootstrap"]["mode"], "plan")
        self.assertEqual(
            result["manual_bootstrap_commands"][0]["command"],
            "getent hosts bastion.example.test",
        )
        self.assertTrue(
            any(item["name"] == "install_public_key_on_common" for item in result["manual_bootstrap_commands"])
        )
        self.assertTrue(
            any(
                item["name"] == "install_public_key_on_common"
                and "-p 2256" in item["command"]
                and "operator@common.example.test" in item["command"]
                for item in result["manual_bootstrap_commands"]
            )
        )
        self.assertIn("VM-DISTRIBUTED SSH ACCESS", stdout.getvalue())
        self.assertIn("Where to run this", stdout.getvalue())
        self.assertIn("common-services VM", stdout.getvalue())
        self.assertIn("Recommended interactive guide", stdout.getvalue())
        self.assertIn("Why it exists", stdout.getvalue())
        self.assertIn("python3 main.py fake ssh-access assistant --topology vm-distributed", stdout.getvalue())
        self.assertNotIn("Human setup guide", stdout.getvalue())

    def test_manual_ssh_bootstrap_commands_expand_home_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(os.environ, {"HOME": tmpdir}):
            plan = {
                "execution_host": "external",
                "ssh": {
                    "mode": "bastion",
                    "bastion": {
                        "host": "bastion.example.test",
                        "port": "2222",
                        "user": "jump",
                        "identity_file": "~/.ssh/validation-env-vm",
                    },
                },
                "ssh_bootstrap": {
                    "status": "ready",
                    "mode": "manual",
                    "identity_file": "~/.ssh/validation-env-vm",
                    "key_comment": "validation-env",
                    "targets": [
                        {
                            "role": "consumer-connectors",
                            "role_key": "consumer",
                            "host": "consumer.example.test",
                            "user": "operator",
                            "port": "22",
                            "identity_file": "~/.ssh/validation-env-vm",
                            "access_mode": "bastion",
                            "bastion": {
                                "host": "bastion.example.test",
                                "port": "2222",
                                "user": "jump",
                                "identity_file": "~/.ssh/validation-env-vm",
                            },
                            "needs_public_key": True,
                        }
                    ],
                },
            }

            commands = main._vm_distributed_manual_ssh_bootstrap_commands(plan)

        rendered_commands = [item["command"] for item in commands]
        expected_identity = os.path.join(tmpdir, ".ssh", "validation-env-vm")
        self.assertTrue(any(expected_identity in command for command in rendered_commands))
        self.assertFalse(any("~/.ssh/validation-env-vm" in command for command in rendered_commands))
        self.assertTrue(
            any(
                item["name"] == "create_dedicated_key_if_missing"
                and f"test -f {expected_identity}" in item["command"]
                for item in commands
            )
        )
        self.assertTrue(
            any(
                item["name"] == "verify_consumer_batchmode"
                and f"-i {expected_identity}" in item["command"]
                for item in commands
            )
        )

    def test_ssh_access_plan_supports_vm_single_target(self):
        plan = {
            "execution_host": "external",
            "topology": "vm-single",
            "ssh": {
                "mode": "bastion",
                "bastion": {
                    "host": "bastion.example.test",
                    "port": "2222",
                    "user": "jump",
                },
            },
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "plan",
                "identity_file": "/home/operator/.ssh/validation-env-vm-single",
                "key_comment": "validation-env-vm-single",
                "targets": [
                    {
                        "role": "vm-single",
                        "role_key": "single",
                        "host": "192.0.2.20",
                        "user": "operator",
                        "port": "22",
                        "identity_file": "/home/operator/.ssh/validation-env-vm-single",
                        "needs_public_key": True,
                    }
                ],
                "actions": [{"name": "ensure_dedicated_keypair"}],
            },
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "_current_vm_single_topology_plan",
            return_value=plan,
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "ssh-access", "plan", "--topology", "vm-single"],
                adapter_registry=self.registry,
            )

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["topology"], "vm-single")
        self.assertTrue(
            any(item["name"] == "install_public_key_on_single" for item in result["manual_bootstrap_commands"])
        )
        self.assertFalse(
            any(item["name"] == "optional_ssh_agent" for item in result["manual_bootstrap_commands"])
        )
        self.assertIn("VM-SINGLE SSH ACCESS", stdout.getvalue())
        self.assertIn("python3 main.py fake ssh-access assistant --topology vm-single", stdout.getvalue())

    def test_vm_single_ssh_bootstrap_plan_is_ready_without_remote_workdir(self):
        plan = main._build_vm_single_topology_plan(
            {"DOMAIN_BASE": "example.test"},
            {
                "VM_EXTERNAL_IP": "192.0.2.52",
                "SSH_ACCESS_MODE": "bastion",
                "SSH_BASTION_HOST": "bastion.example.test",
                "SSH_BASTION_PORT": "2222",
                "SSH_BASTION_USER": "jump",
                "SSH_IDENTITY_FILE": "/home/operator/.ssh/validation-env-vm-single",
                "VM_SINGLE_SSH_USER": "pionera",
            },
            {"DS_1_NAME": "pionera"},
        )

        self.assertEqual(plan["ssh_bootstrap"]["status"], "ready")
        self.assertEqual(plan["ssh_bootstrap"]["warnings"], [])
        self.assertEqual(plan["ssh_bootstrap"]["remote_workdir"], "")
        commands = main._vm_distributed_manual_ssh_bootstrap_commands(plan)
        self.assertTrue(any(item["name"] == "install_public_key_on_single" for item in commands))

    def test_vm_single_ssh_bootstrap_plan_reports_missing_required_ssh_metadata(self):
        plan = main._build_vm_single_topology_plan(
            {"DOMAIN_BASE": "example.test"},
            {"VM_EXTERNAL_IP": "192.0.2.52"},
            {"DS_1_NAME": "pionera"},
        )

        self.assertEqual(plan["ssh_bootstrap"]["status"], "needs-review")
        self.assertIn(
            "SSH_IDENTITY_FILE or VM_SINGLE_SSH_IDENTITY_FILE is required for SSH bootstrap.",
            plan["ssh_bootstrap"]["warnings"],
        )
        self.assertIn(
            "VM_SINGLE_SSH_USER or VM_SSH_USER is required for vm-single SSH bootstrap.",
            plan["ssh_bootstrap"]["warnings"],
        )

    def test_ssh_access_plan_can_print_raw_json(self):
        plan = {
            "execution_host": "external",
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "plan",
                "identity_file": "/home/operator/.ssh/validation-env-vm",
                "actions": [{"name": "ensure_dedicated_keypair"}],
            },
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "_current_vm_distributed_topology_plan",
            return_value=plan,
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "ssh-access", "plan", "--topology", "vm-distributed", "--json"],
                adapter_registry=self.registry,
            )

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["execution_location"]["mode"], "external")
        self.assertIn('"identity_file": "/home/operator/.ssh/validation-env-vm"', stdout.getvalue())
        self.assertIn('"execution_location"', stdout.getvalue())
        self.assertNotIn("Human setup guide", stdout.getvalue())
        self.assertNotIn("Recommended interactive guide", stdout.getvalue())

    def test_ssh_access_reconcile_runs_reconciliation_helper(self):
        plan = {
            "execution_host": "external",
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "auto",
                "identity_file": "/home/operator/.ssh/validation-env-vm",
            },
        }
        reconcile_result = {
            "status": "synced",
            "execution_host": "external",
            "ssh_bootstrap": plan["ssh_bootstrap"],
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "_current_vm_distributed_topology_plan",
            return_value=plan,
        ), mock.patch.object(
            main,
            "_reconcile_vm_distributed_ssh_access",
            return_value=reconcile_result,
        ) as reconcile, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "ssh-access", "reconcile", "--topology", "vm-distributed"],
                adapter_registry=self.registry,
            )

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["action"], "reconcile")
        reconcile.assert_called_once_with(plan)
        self.assertIn("VM-DISTRIBUTED SSH ACCESS", stdout.getvalue())
        self.assertIn("SSH access is ready", stdout.getvalue())

    def test_ssh_access_reconcile_supports_vm_single(self):
        plan = {
            "execution_host": "external",
            "topology": "vm-single",
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "auto",
                "identity_file": "/home/operator/.ssh/validation-env-vm-single",
            },
        }
        reconcile_result = {
            "status": "synced",
            "topology": "vm-single",
            "execution_host": "external",
            "ssh_bootstrap": plan["ssh_bootstrap"],
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "_current_vm_single_topology_plan",
            return_value=plan,
        ), mock.patch.object(
            main,
            "_reconcile_vm_distributed_ssh_access",
            return_value=reconcile_result,
        ) as reconcile, contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "ssh-access", "reconcile", "--topology", "vm-single"],
                adapter_registry=self.registry,
            )

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["topology"], "vm-single")
        reconcile.assert_called_once_with(plan)
        self.assertIn("VM-SINGLE SSH ACCESS", stdout.getvalue())

    def test_ssh_access_assistant_can_be_cancelled_before_commands(self):
        plan = {
            "execution_host": "external",
            "ssh": {
                "mode": "direct",
                "bastion": {},
            },
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "manual",
                "identity_file": "/home/operator/.ssh/validation-env-vm",
                "key_comment": "validation-env",
                "targets": [
                    {
                        "role": "common-services",
                        "role_key": "common",
                        "host": "common.example.test",
                        "user": "operator",
                        "port": "22",
                        "identity_file": "/home/operator/.ssh/validation-env-vm",
                        "needs_public_key": True,
                    }
                ],
            },
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "_current_vm_distributed_topology_plan",
            return_value=plan,
        ), mock.patch("builtins.input", side_effect=["n"]), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "ssh-access", "assistant", "--topology", "vm-distributed"],
                adapter_registry=self.registry,
            )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["executed"], [])
        self.assertEqual(result["execution_detection"]["ssh_route"], "direct")
        self.assertIn("SSH route from config: direct SSH", stdout.getvalue())
        self.assertIn("Questions:", stdout.getvalue())
        self.assertNotIn("What this prepares", stdout.getvalue())
        self.assertNotIn("Execution context check", stdout.getvalue())
        self.assertIn("Guided SSH setup cancelled", stdout.getvalue())

    def test_ssh_access_assistant_reports_completed_when_all_commands_pass(self):
        plan_result = {
            "status": "planned",
            "adapter": "fake",
            "topology": "vm-single",
            "execution_host": "external",
            "ssh": {
                "mode": "direct",
                "bastion": {},
            },
            "ssh_bootstrap": {
                "status": "ready",
                "identity_file": "/home/operator/.ssh/validation-env-vm-single",
                "targets": [],
            },
            "manual_bootstrap_commands": [
                {
                    "name": "verify_single_batchmode",
                    "command": "true",
                }
            ],
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "run_ssh_access",
            return_value=plan_result,
        ), mock.patch.object(
            main,
            "_interactive_read",
            side_effect=["y", "y"],
        ), contextlib.redirect_stdout(stdout):
            result = main._run_vm_distributed_ssh_access_assistant(
                FakeAdapter(),
                deployer_name="fake",
                topology="vm-single",
                command_runner=lambda command: types.SimpleNamespace(returncode=0),
            )

        self.assertEqual(result["status"], "completed")
        self.assertIn("Result: SSH setup commands completed", stdout.getvalue())
        self.assertIn("Next recommended check", stdout.getvalue())

    def test_interactive_confirm_with_progress_numbers_prompt(self):
        with mock.patch.object(main, "_interactive_read", return_value="n") as read_prompt:
            result = main._interactive_confirm_with_progress(
                "Start the guided SSH setup now?",
                1,
                8,
                default=False,
            )

        self.assertFalse(result)
        read_prompt.assert_called_once_with("Question 1/8: Start the guided SSH setup now? (y/N): ")

    def test_ssh_access_execution_detection_identifies_wsl_and_bastion(self):
        plan = {
            "execution_host": "external",
            "ssh": {
                "mode": "bastion",
                "bastion": {
                    "host": "bastion.example.test",
                    "port": "2222",
                    "user": "jump",
                },
            },
            "ssh_bootstrap": {
                "targets": [
                    {
                        "role": "common-services",
                        "role_key": "common",
                        "host": "common.example.test",
                    }
                ],
            },
            "manual_bootstrap_commands": [],
        }

        detection = main._vm_distributed_detect_execution_environment(
            plan,
            environ={"WSL_DISTRO_NAME": "Ubuntu"},
            proc_version="",
            hostname="operator-host",
            fqdn="operator-host",
        )

        self.assertEqual(detection["detected_label"], "WSL operator workstation")
        self.assertEqual(detection["alignment"], "matched")
        self.assertFalse(detection["needs_confirmation"])
        self.assertEqual(detection["ssh_route"], "bastion")
        self.assertEqual(detection["bastion"]["host"], "bastion.example.test")
        self.assertEqual(detection["bastion"]["port"], "2222")

    def test_framework_execution_mode_orchestrator_maps_vm_distributed_to_external(self):
        topology_config = {
            "FRAMEWORK_EXECUTION_MODE": "orchestrator",
            "VM_DISTRIBUTED_EXECUTION_HOST": "auto",
        }

        self.assertEqual(main._normalized_vm_distributed_execution_host(topology_config), "external")

    def test_framework_execution_mode_target_vm_maps_vm_distributed_to_common_services(self):
        topology_config = {
            "FRAMEWORK_EXECUTION_MODE": "target-vm",
            "VM_DISTRIBUTED_EXECUTION_HOST": "auto",
        }

        self.assertEqual(main._normalized_vm_distributed_execution_host(topology_config), "common-services")

    def test_specific_vm_distributed_execution_host_overrides_framework_execution_mode(self):
        topology_config = {
            "FRAMEWORK_EXECUTION_MODE": "target-vm",
            "VM_DISTRIBUTED_EXECUTION_HOST": "external",
        }

        self.assertEqual(main._normalized_vm_distributed_execution_host(topology_config), "external")

    def test_ssh_access_execution_detection_warns_when_running_inside_vm_with_bastion(self):
        plan = {
            "execution_host": "common-services",
            "ssh": {
                "mode": "bastion",
                "bastion": {
                    "host": "bastion.example.test",
                    "port": "2222",
                    "user": "jump",
                },
            },
            "ssh_bootstrap": {
                "targets": [
                    {
                        "role": "common-services",
                        "role_key": "common",
                        "host": "common-vm",
                    },
                    {
                        "role": "provider-connectors",
                        "role_key": "provider",
                        "host": "provider-vm",
                    },
                ],
            },
            "manual_bootstrap_commands": [],
        }

        detection = main._vm_distributed_detect_execution_environment(
            plan,
            environ={},
            proc_version="Linux",
            hostname="common-vm",
            fqdn="common-vm",
        )

        self.assertEqual(detection["detected_mode"], "common-services")
        self.assertEqual(detection["alignment"], "route-review")
        self.assertTrue(detection["needs_confirmation"])
        self.assertEqual(detection["ssh_route"], "bastion")
        self.assertIn("inside a configured VM", detection["route_warning"])

    def test_ssh_access_self_test_validates_temporary_key_creation(self):
        public_material = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey"

        def fake_runner(command, timeout):
            if command[:3] == ["ssh-keygen", "-t", "ed25519"]:
                private_key = command[command.index("-f") + 1]
                os.makedirs(os.path.dirname(private_key), exist_ok=True)
                with open(private_key, "w", encoding="utf-8") as handle:
                    handle.write("PRIVATE TEST KEY\n")
                with open(f"{private_key}.pub", "w", encoding="utf-8") as handle:
                    handle.write(f"{public_material} validation-env\n")
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            if command[:2] == ["ssh-keygen", "-y"]:
                return types.SimpleNamespace(returncode=0, stdout=f"{public_material}\n", stderr="")
            return types.SimpleNamespace(returncode=127, stdout="", stderr="unexpected command")

        plan = {
            "execution_host": "external",
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "plan",
                "identity_file": "/home/operator/.ssh/validation-env-vm",
                "key_comment": "validation-env",
            },
        }

        result = main._vm_distributed_ssh_key_self_test(plan, command_runner=fake_runner)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["scope"], "local-temporary-key-only")
        self.assertEqual(result["remote_validation"], "not-run")
        self.assertEqual(
            [item["name"] for item in result["checks"]],
            [
                "temporary_keypair_created",
                "temporary_keypair_files_exist",
                "private_key_permissions",
                "public_key_matches_private_key",
                "keypair_creation_is_idempotent",
                "temporary_files_removed",
            ],
        )
        self.assertTrue(all(item["status"] == "passed" for item in result["checks"]))

    def test_ssh_access_self_test_prints_human_summary(self):
        plan = {
            "execution_host": "external",
            "ssh_bootstrap": {
                "status": "ready",
                "mode": "plan",
                "identity_file": "/home/operator/.ssh/validation-env-vm",
            },
        }
        self_test_result = {
            "status": "passed",
            "message": "Temporary SSH key creation, validation and idempotency checks passed.",
            "scope": "local-temporary-key-only",
            "remote_validation": "not-run",
            "execution_host": "external",
            "checks": [{"name": "temporary_keypair_created", "status": "passed"}],
        }

        stdout = io.StringIO()
        with mock.patch.object(
            main,
            "_current_vm_distributed_topology_plan",
            return_value=plan,
        ), mock.patch.object(
            main,
            "_vm_distributed_ssh_key_self_test",
            return_value=self_test_result,
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["fake", "ssh-access", "self-test", "--topology", "vm-distributed"],
                adapter_registry=self.registry,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["action"], "self-test")
        self.assertIn("VM-DISTRIBUTED SSH KEY SELF-TEST", stdout.getvalue())
        self.assertIn("does not touch your existing SSH keys", stdout.getvalue())
        self.assertIn("temporary_keypair_created: Succeeded", stdout.getvalue())

    def test_action_result_prints_hosts_plan_when_sync_is_disabled(self):
        payload = {
            "status": "planned",
            "deployer_name": "inesdata",
            "topology": "local",
            "dataspace": "demo",
            "hosts_plan": {
                "level_3": ["registration-service-demo.example.local"],
                "level_4": ["conn-a.example.local", "conn-b.example.local"],
                "address": "127.0.0.1",
                "legacy_external_hostnames": [
                    {
                        "legacy": "keycloak.dev.ed.dataspaceunit.upm",
                        "canonical": "auth.dev.ed.dataspaceunit.upm",
                    }
                ],
            },
            "hosts_sync": {
                "status": "skipped",
                "reason": "disabled",
            },
        }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main._print_action_result(payload)

        output = stdout.getvalue()
        self.assertIn("Result: Succeeded", output)
        self.assertIn("Hosts Level 3: 1", output)
        self.assertIn("- registration-service-demo.example.local", output)
        self.assertIn("Hosts Level 4: 2", output)
        self.assertIn("- conn-a.example.local", output)
        self.assertIn("- conn-b.example.local", output)
        self.assertIn("Hosts address: 127.0.0.1", output)
        self.assertIn("Hosts legacy aliases detected: 1", output)
        self.assertIn("Hosts sync: Skipped (disabled by configuration)", output)

    def test_menu_hosts_can_offer_to_apply_plan_when_sync_is_disabled(self):
        registry = {
            "edc": "fake_adapter_module:FakeAdapter",
            "inesdata": "fake_adapter_module:FakeAdapter",
        }
        deployer_registry = {
            "edc": "fake_deployer_module:FakeDeployer",
            "inesdata": "fake_deployer_module:FakeDeployer",
        }
        planned_result = {
            "status": "planned",
            "deployer_name": "inesdata",
            "topology": "local",
            "dataspace": "demo",
            "hosts_plan": {
                "level_3": ["registration-service-demo.example.local"],
                "level_4": ["conn-a.example.local", "conn-b.example.local"],
                "address": "127.0.0.1",
            },
            "hosts_sync": {
                "status": "skipped",
                "reason": "disabled",
            },
        }
        applied_result = {
            "status": "updated",
            "deployer_name": "inesdata",
            "topology": "local",
            "dataspace": "demo",
            "hosts_plan": planned_result["hosts_plan"],
            "hosts_sync": {
                "status": "updated",
                "hosts_file": "/tmp/hosts",
                "changed": True,
            },
        }

        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["H", "2", "Y", "Q"]), mock.patch.object(
            main,
            "run_hosts",
            side_effect=[planned_result, applied_result],
        ) as run_hosts, mock.patch.object(
            main,
            "_interactive_hosts_file_path",
            return_value="/tmp/hosts",
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(run_hosts.call_count, 2)
        rendered = stdout.getvalue()
        self.assertIn("Hosts sync: Skipped (disabled by configuration)", rendered)
        self.assertIn("Detected hosts file: /tmp/hosts", rendered)
        self.assertIn("The framework can apply this hosts plan now.", rendered)

    def test_hosts_command_vm_single_uses_vm_address_from_context(self):
        adapter = FakeAdapter()

        result = main.run_hosts(
            adapter,
            deployer_name="fakevm",
            deployer_registry=self.deployer_registry,
            topology="vm-single",
        )

        self.assertEqual(result["hosts_plan"]["address"], "192.0.2.10")
        self.assertIn(
            "192.0.2.10 registration-service-fake-ds.example.local",
            result["hosts_plan"]["blocks"]["dataspace fake-ds"],
        )
        self.assertIn(
            "192.0.2.10 conn-a.example.local",
            result["hosts_plan"]["blocks"]["connectors fake fake-ds"],
        )

    def test_hosts_command_applies_only_missing_entries_when_enabled(self):
        adapter = FakeAdapter()

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {
                "PIONERA_SYNC_HOSTS": "true",
                "PIONERA_HOSTS_FILE": hosts_file.name,
            },
            clear=False,
        ):
            hosts_file.write("127.0.0.1 localhost\n127.0.0.1 conn-a.example.local\n")
            hosts_file.flush()
            result = main.run_hosts(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )
            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertEqual(result["status"], "updated")
        self.assertIn("127.0.0.1 conn-a.example.local", result["hosts_sync"]["skipped_existing"]["connectors fake fake-ds"])
        self.assertIn("127.0.0.1 conn-b.example.local", hosts_content)

    def test_hosts_command_uses_detected_hosts_file_when_sync_enabled(self):
        adapter = FakeAdapter()

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {
                "PIONERA_SYNC_HOSTS": "true",
            },
            clear=False,
        ), mock.patch.object(main.local_menu_tools, "get_hosts_path", return_value=hosts_file.name):
            hosts_file.write("127.0.0.1 localhost\n")
            hosts_file.flush()
            result = main.run_hosts(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )
            hosts_file.seek(0)
            hosts_content = hosts_file.read()

        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["hosts_sync"]["hosts_file"], hosts_file.name)
        self.assertIn("127.0.0.1 registration-service-fake-ds.example.local", hosts_content)
        self.assertEqual(hosts_content.count("conn-a.example.local"), 1)

    def test_hosts_command_rejects_windows_hosts_file_for_vm_distributed(self):
        adapter = FakeAdapter()

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_SYNC_HOSTS": "true",
                "PIONERA_HOSTS_FILE": "/mnt/c/Windows/System32/drivers/etc/hosts",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "Windows hosts sync is only supported"):
                main.run_hosts(
                    adapter,
                    deployer_name="fakevm",
                    deployer_registry=self.deployer_registry,
                    topology="vm-distributed",
                )

    def test_hosts_command_reports_legacy_external_hostnames(self):
        adapter = FakeAdapter()
        context = DeploymentContext(
            deployer="fake",
            topology="local",
            environment="DEV",
            dataspace_name="fake-ds",
            ds_domain_base="example.local",
            connectors=["conn-a", "conn-b"],
            config={"DOMAIN_BASE": "dev.ed.dataspaceunit.upm"},
        )

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as hosts_file, mock.patch.dict(
            os.environ,
            {
                "PIONERA_SYNC_HOSTS": "true",
                "PIONERA_HOSTS_FILE": hosts_file.name,
            },
            clear=False,
        ), mock.patch.object(
            main,
            "_resolve_deployer_context",
            return_value=("fake", context),
        ):
            hosts_file.write(
                "127.0.0.1 localhost\n"
                "127.0.0.1 keycloak.dev.ed.dataspaceunit.upm\n"
                "127.0.0.1 keycloak-admin.dev.ed.dataspaceunit.upm\n"
            )
            hosts_file.flush()
            result = main.run_hosts(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(
            result["hosts_sync"]["legacy_external_hostnames"],
            [
                {
                    "legacy": "keycloak.dev.ed.dataspaceunit.upm",
                    "canonical": "auth.dev.ed.dataspaceunit.upm",
                },
                {
                    "legacy": "keycloak-admin.dev.ed.dataspaceunit.upm",
                    "canonical": "admin.auth.dev.ed.dataspaceunit.upm",
                },
            ],
        )

    def test_deploy_command_prepares_local_edc_image_when_missing_override(self):
        adapter = FakeAdapter()
        adapter.config_adapter.load_deployer_config = lambda: {
            "KC_URL": "http://keycloak.local",
            "DS_1_NAME": "fake-ds",
            "EDC_DASHBOARD_ENABLED": "true",
        }

        with mock.patch.object(
            main,
            "_prepare_edc_local_connector_image_override",
            return_value={
                "image_name": "validation-environment/edc-connector",
                "image_tag": "local",
                "minikube_profile": "minikube",
            },
        ) as image_prepare, mock.patch.object(
            main,
            "_prepare_edc_local_dashboard_images",
            return_value={"status": "prepared"},
        ) as dashboard_prepare, mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
            },
            clear=True,
        ):
            result = main.run_deploy(
                adapter,
                deployer_name="edc",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["deployment"]["connectors"], ["conn-deployer-a", "conn-deployer-b"])
        image_prepare.assert_called_once_with(adapter)
        dashboard_prepare.assert_called_once()

    def test_safe_edc_execution_refuses_vm_single_missing_image_override_by_default(self):
        adapter = FakeAdapter()
        adapter.config_adapter.load_deployer_config = lambda: {
            "KC_URL": "http://keycloak.local",
            "DS_1_NAME": "fake-ds",
            "EDC_DASHBOARD_ENABLED": "true",
        }

        with mock.patch.object(
            main,
            "_prepare_edc_local_connector_image_override",
        ) as image_prepare, mock.patch.object(
            main,
            "_prepare_edc_local_dashboard_images",
        ) as dashboard_prepare, mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires explicit EDC connector image overrides"):
                main._ensure_safe_edc_deployer_execution(
                    adapter,
                    deployer_name="edc",
                    topology="vm-single",
                )

        image_prepare.assert_not_called()
        dashboard_prepare.assert_not_called()

    def test_safe_edc_execution_prepares_vm_single_image_when_local_images_opted_in(self):
        adapter = FakeAdapter()
        adapter.config_adapter.load_deployer_config = lambda: {
            "KC_URL": "http://keycloak.local",
            "DS_1_NAME": "fake-ds",
            "EDC_DASHBOARD_ENABLED": "true",
            "EDC_LOCAL_IMAGES_MODE": "auto",
        }

        with mock.patch.object(
            main,
            "_prepare_edc_local_connector_image_override",
            return_value={
                "image_name": "validation-environment/edc-connector",
                "image_tag": "local",
                "minikube_profile": "minikube",
            },
        ) as image_prepare, mock.patch.object(
            main,
            "_prepare_edc_local_dashboard_images",
            return_value={"status": "prepared"},
        ) as dashboard_prepare, mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
            },
            clear=True,
        ):
            main._ensure_safe_edc_deployer_execution(
                adapter,
                deployer_name="edc",
                topology="vm-single",
            )

        image_prepare.assert_called_once_with(adapter)
        dashboard_prepare.assert_called_once()

    def test_deploy_command_refuses_real_edc_execution_with_partial_image_override(self):
        adapter = FakeAdapter()

        with mock.patch.object(main, "_prepare_edc_local_connector_image_override") as image_prepare, \
                mock.patch.dict(
                    os.environ,
                    {
                        "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                        "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
                        "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                    },
                    clear=True,
                ):
            with self.assertRaises(RuntimeError) as exc:
                main.run_deploy(
                    adapter,
                    deployer_name="edc",
                    deployer_registry=self.deployer_registry,
                    topology="local",
                )

        self.assertIn("EDC connector image overrides", str(exc.exception))
        image_prepare.assert_not_called()

    def test_prepare_edc_local_dashboard_images_builds_dashboard_and_proxy(self):
        adapter = FakeAdapter()
        config = {
            "DS_1_NAME": "fake-ds",
            "EDC_DASHBOARD_ENABLED": "true",
            "EDC_DASHBOARD_IMAGE_NAME": "validation-environment/edc-dashboard",
            "EDC_DASHBOARD_IMAGE_TAG": "local-ui",
            "EDC_DASHBOARD_PROXY_IMAGE_NAME": "validation-environment/edc-dashboard-proxy",
            "EDC_DASHBOARD_PROXY_IMAGE_TAG": "local-proxy",
        }

        with mock.patch("main.subprocess.run", return_value=mock.Mock(returncode=0)) as run_command, \
                mock.patch.dict(os.environ, {}, clear=True):
            result = main._prepare_edc_local_dashboard_images(adapter, config)
            dashboard_tag = os.environ["PIONERA_EDC_DASHBOARD_IMAGE_TAG"]
            proxy_tag = os.environ["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG"]
            prepared_flag = os.environ["PIONERA_EDC_LOCAL_DASHBOARD_IMAGES_PREPARED"]

        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["dashboard_image"], "validation-environment/edc-dashboard:local-ui")
        self.assertEqual(result["dashboard_proxy_image"], "validation-environment/edc-dashboard-proxy:local-proxy")
        self.assertEqual(run_command.call_count, 2)
        self.assertIn("build_dashboard_image.sh", run_command.call_args_list[0].args[0][1])
        self.assertIn("build_dashboard_proxy_image.sh", run_command.call_args_list[1].args[0][1])
        self.assertEqual(dashboard_tag, "local-ui")
        self.assertEqual(proxy_tag, "local-proxy")
        self.assertEqual(prepared_flag, "true")

    def test_deploy_command_refuses_real_edc_execution_on_shared_demo_dataspace(self):
        adapter = FakeAdapter()
        adapter.config_adapter = types.SimpleNamespace(
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak.local",
                "DS_1_NAME": "demo",
            },
            primary_dataspace_name=lambda: "demo",
        )

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "validation-environment/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "clean1",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError) as exc:
                main.run_deploy(
                    adapter,
                    deployer_name="edc",
                    deployer_registry=self.deployer_registry,
                    topology="local",
                )

        self.assertIn("shared dataspace 'demo'", str(exc.exception))

    def test_deploy_command_keeps_shadow_mode_for_non_edc_even_if_execution_flag_is_enabled(self):
        adapter = FakeAdapter()

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_USE_DEPLOYER_DEPLOY": "true",
                "PIONERA_EXECUTE_DEPLOYER_DEPLOY": "true",
            },
            clear=False,
        ):
            result = main.run_deploy(
                adapter,
                deployer_name="fake",
                deployer_registry=self.deployer_registry,
                topology="local",
            )

        self.assertEqual(result["mode"], "shadow")

    def test_deploy_command_requires_connector_deployment(self):
        with self.assertRaises(RuntimeError):
            main.run_deploy(NoConnectorDeployAdapter())

    def test_validate_command_uses_validation_engine(self):
        result = main.main(
            ["fake", "validate"],
            adapter_registry=self.registry,
            validation_engine_cls=FakeValidationEngine,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["validation"], {"validated": ["conn-a", "conn-b"]})
        self.assertEqual(result["newman_request_metrics"], [])
        self.assertEqual(result["storage_checks"], [])
        self.assertTrue(result["experiment_dir"].startswith("/tmp/cli-test-"))
        self.assertEqual(result["test_data_cleanup"]["status"], "skipped")
        self.assertEqual(result["test_data_cleanup"]["reason"], "disabled")

    def test_validate_command_uses_deployer_resolution_by_default_when_available(self):
        result = main.main(
            ["fake", "validate"],
            adapter_registry=self.registry,
            deployer_registry=self.deployer_registry,
            validation_engine_cls=FakeValidationEngine,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["validation"], {"validated": ["conn-deployer-a", "conn-deployer-b"]})
        self.assertEqual(result["validation_profile"]["adapter"], "fake")
        self.assertTrue(result["validation_profile"]["newman_enabled"])
        self.assertFalse(result["validation_profile"]["playwright_enabled"])
        self.assertEqual(result["deployer_context"]["dataspace_name"], "fake-ds")
        self.assertEqual(result["deployer_context"]["config"]["KC_PASSWORD"], "***REDACTED***")
        self.assertEqual(result["deployer_context"]["config"]["VT_TOKEN"], "***REDACTED***")

    def test_validate_command_runs_kafka_edc_after_newman_for_supported_adapter(self):
        events = []

        class RecordingValidationEngine(FakeValidationEngine):
            def run(self, connectors):
                events.append("validation")
                return super().run(connectors)

        class RecordingMetricsCollector:
            def collect_experiment_newman_metrics(self, experiment_dir):
                events.append("newman_metrics")
                return [{"request": "login"}]

        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        class InesdataValidationDeployer(FakeDeployer):
            def get_validation_profile(self, context):
                return {
                    "adapter": "inesdata",
                    "newman_enabled": True,
                    "test_data_cleanup_enabled": False,
                    "playwright_enabled": False,
                }

        def run_kafka(connectors, experiment_dir, *, validator, experiment_storage, progress_callback=None):
            events.append("kafka_edc")
            self.assertTrue(callable(progress_callback))
            return [{"status": "passed", "provider": connectors[0], "consumer": connectors[1]}]

        self.fake_module.KafkaReadyAdapter = KafkaReadyAdapter
        self.fake_deployer_module.InesdataValidationDeployer = InesdataValidationDeployer
        registry = {
            **self.registry,
            "fake": "fake_adapter_module:KafkaReadyAdapter",
        }
        deployer_registry = {
            **self.deployer_registry,
            "fake": "fake_deployer_module:InesdataValidationDeployer",
        }

        def kafka_enabled_env_flag(name, default=False):
            if name == "PIONERA_LEVEL6_RUN_KAFKA":
                return True
            if name == "PIONERA_LEVEL6_SKIP_KAFKA":
                return False
            return default

        with mock.patch.object(
            main,
            "build_metrics_collector",
            return_value=RecordingMetricsCollector(),
        ), mock.patch.object(
            main,
            "build_kafka_edc_validation_suite",
            return_value=mock.Mock(),
        ), mock.patch.object(
            main,
            "run_kafka_edc_validation",
            side_effect=run_kafka,
        ), mock.patch.object(
            main,
            "_env_flag",
            side_effect=kafka_enabled_env_flag,
        ):
            result = main.main(
                ["fake", "validate"],
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=RecordingValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(events, ["validation", "newman_metrics", "kafka_edc"])
        self.assertEqual(result["kafka_edc_results"][0]["status"], "passed")

    def test_level6_kafka_edc_support_honors_adapter_capability_opt_out(self):
        class HttpOnlyEdcAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

            def supports_kafka_transfer_validation(self):
                return False

        validation_profile = types.SimpleNamespace(adapter="edc")

        self.assertFalse(
            main._supports_level6_kafka_edc(
                HttpOnlyEdcAdapter(),
                validation_profile=validation_profile,
            )
        )

    def test_level6_validation_mode_defaults_to_stable_only_for_local(self):
        local_mode = main._resolve_level6_validation_mode(topology="local")
        vm_mode = main._resolve_level6_validation_mode(topology="vm-single")
        explicit_fast = main._resolve_level6_validation_mode("fast", topology="local")

        self.assertEqual(local_mode["effective"], "stable")
        self.assertTrue(local_mode["local_stable"])
        self.assertEqual(vm_mode["effective"], "fast")
        self.assertFalse(vm_mode["local_stable"])
        self.assertEqual(explicit_fast["effective"], "fast")
        self.assertFalse(explicit_fast["local_stable"])

    def test_level6_local_stability_checks_are_limited_to_real_local_stable_deployers(self):
        local_mode = main._resolve_level6_validation_mode(topology="local")
        vm_mode = main._resolve_level6_validation_mode(topology="vm-single")

        self.assertTrue(main._should_run_level6_local_stability_checks(local_mode, deployer_name="inesdata"))
        self.assertTrue(main._should_run_level6_local_stability_checks(local_mode, deployer_name="edc"))
        self.assertFalse(main._should_run_level6_local_stability_checks(local_mode, deployer_name="fake"))
        self.assertFalse(main._should_run_level6_local_stability_checks(vm_mode, deployer_name="inesdata"))
        self.assertFalse(
            main._should_run_level6_local_stability_checks(
                local_mode,
                deployer_name="edc",
                validation_profile=types.SimpleNamespace(adapter="fake"),
            )
        )
        self.assertFalse(
            main._should_run_level6_local_stability_checks(
                local_mode,
                deployer_name="inesdata",
                env={"PIONERA_LOCAL_STABILITY_CHECKS": "false"},
            )
        )

    def test_level6_local_stability_postflight_waits_for_recovery(self):
        validation_mode = main._resolve_level6_validation_mode(topology="local")
        context = types.SimpleNamespace(namespace_roles={"registration_service_namespace": "demoedc"})
        preflight = {
            "status": "passed",
            "restart_index": {},
            "node_not_ready_event_count": 0,
        }
        recovered_snapshot = {
            "status": "warning",
            "restart_index": {},
            "node_not_ready_event_count": 1,
            "warnings": [{"name": "node_not_ready_events"}],
            "blocking_issues": [],
        }

        class RecoveringMonitor:
            def __init__(self, namespaces):
                self.namespaces = namespaces

            def wait_until_ready(self, *, timeout_seconds, poll_interval_seconds):
                self.timeout_seconds = timeout_seconds
                self.poll_interval_seconds = poll_interval_seconds
                return recovered_snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            result = main._run_level6_local_stability_postflight(
                validation_mode,
                "edc",
                context,
                temp_dir,
                preflight,
                monitor_cls=RecoveringMonitor,
            )

        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["snapshot"], recovered_snapshot)
        self.assertEqual(result["comparison"]["node_not_ready_delta"], 1)
        self.assertFalse(result["blocking_issues"])

    def test_level6_local_capacity_preflight_blocks_low_memory_coexistence(self):
        validation_mode = main._resolve_level6_validation_mode(topology="local")
        context = types.SimpleNamespace(
            namespace_roles={"registration_service_namespace": "demoedc"},
        )
        nodes_payload = {
            "items": [
                {"status": {"allocatable": {"memory": "15996068Ki"}}},
            ]
        }
        pods_payload = {
            "items": [
                {"metadata": {"namespace": "core-control"}, "status": {"phase": "Running"}},
                {"metadata": {"namespace": "demoedc"}, "status": {"phase": "Running"}},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            main,
            "_run_json_command",
            side_effect=[nodes_payload, pods_payload],
        ), mock.patch.object(
            main,
            "_docker_memory_total_mb",
            return_value=15621,
        ), mock.patch.object(
            main,
            "load_layered_deployer_config",
            return_value={"MINIKUBE_MEMORY": "14336"},
        ):
            with self.assertRaisesRegex(RuntimeError, "Local EDC/INESData coexistence"):
                main._run_level6_local_capacity_preflight(
                    validation_mode,
                    "edc",
                    context,
                    tmpdir,
                    validation_profile=types.SimpleNamespace(adapter="edc"),
                )

    def test_level6_local_capacity_preflight_can_warn_instead_of_blocking(self):
        validation_mode = main._resolve_level6_validation_mode(topology="local")
        context = types.SimpleNamespace(
            namespace_roles={"registration_service_namespace": "demoedc"},
        )
        nodes_payload = {
            "items": [
                {"status": {"allocatable": {"memory": "15996068Ki"}}},
            ]
        }
        pods_payload = {
            "items": [
                {"metadata": {"namespace": "core-control"}, "status": {"phase": "Running"}},
                {"metadata": {"namespace": "demoedc"}, "status": {"phase": "Running"}},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"PIONERA_LOCAL_COEXISTENCE_GUARD": "warn"},
            clear=False,
        ), mock.patch.object(
            main,
            "_run_json_command",
            side_effect=[nodes_payload, pods_payload],
        ), mock.patch.object(
            main,
            "_docker_memory_total_mb",
            return_value=15621,
        ), mock.patch.object(
            main,
            "load_layered_deployer_config",
            return_value={"MINIKUBE_MEMORY": "14336"},
        ):
            result = main._run_level6_local_capacity_preflight(
                validation_mode,
                "edc",
                context,
                tmpdir,
                validation_profile=types.SimpleNamespace(adapter="edc"),
            )
            self.assertTrue(os.path.isfile(result["artifact"]))

        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["coexistence_detected"])

    def test_local_adapter_install_capacity_preflight_blocks_second_adapter(self):
        pods_payload = {
            "items": [
                {"metadata": {"namespace": "core-control"}, "status": {"phase": "Running"}},
            ]
        }
        nodes_payload = {
            "items": [
                {"status": {"allocatable": {"memory": "15996068Ki"}}},
            ]
        }

        with mock.patch.object(
            main,
            "_run_json_command",
            side_effect=[nodes_payload, pods_payload],
        ), mock.patch.object(
            main,
            "_docker_memory_total_mb",
            return_value=15621,
        ), mock.patch.object(
            main,
            "load_layered_deployer_config",
            return_value={"MINIKUBE_MEMORY": "14336"},
        ):
            with self.assertRaisesRegex(RuntimeError, "only supports one adapter at a time"):
                main._run_local_adapter_install_capacity_preflight(
                    "edc",
                    "local",
                    3,
                )

    def test_local_adapter_switch_plan_removes_old_adapter_and_components_for_edc(self):
        payload = {
            "workloads": {
                "active_adapters": ["inesdata"],
                "active_component_namespaces": ["components"],
                "adapter_namespaces": {"inesdata": "core-control", "edc": "demoedc"},
            }
        }

        plan = main._build_local_adapter_switch_plan(payload, "edc")

        self.assertEqual(plan["target_adapter"], "edc")
        self.assertEqual(plan["adapters_to_remove"], ["inesdata"])
        self.assertEqual(plan["namespaces_to_delete"], ["core-control", "provider", "consumer", "components"])
        self.assertEqual(plan["confirmation_token"], "SWITCH TO EDC")
        self.assertEqual(plan["preserved_namespaces"], ["common-srvs"])
        provider_action = next(
            action for action in plan["namespace_actions"] if action["namespace"] == "provider"
        )
        self.assertIn("conn-org2-pionera-pionera", provider_action["expected_releases"])

    def test_local_adapter_switch_cleanup_readiness_requires_matching_helm_release(self):
        def fake_switch_command(command):
            if command[:3] == ["kubectl", "get", "namespace"]:
                return types.SimpleNamespace(returncode=0, stdout="namespace/provider", stderr="")
            if command[:3] == ["helm", "list", "-n"]:
                return types.SimpleNamespace(returncode=0, stdout="other-release\n", stderr="")
            raise AssertionError(f"Unexpected command: {command}")

        with mock.patch.object(main, "_run_switch_command", side_effect=fake_switch_command):
            result = main._local_switch_namespace_cleanup_readiness(
                {
                    "namespace": "provider",
                    "expected_releases": ["conn-org2-pionera-pionera"],
                }
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no-matching-helm-releases")

    def test_local_adapter_switch_cleanup_readiness_allows_matching_helm_release(self):
        def fake_switch_command(command):
            if command[:3] == ["kubectl", "get", "namespace"]:
                return types.SimpleNamespace(returncode=0, stdout="namespace/provider", stderr="")
            if command[:3] == ["helm", "list", "-n"]:
                return types.SimpleNamespace(
                    returncode=0,
                    stdout="conn-org2-pionera-pionera\n",
                    stderr="",
                )
            raise AssertionError(f"Unexpected command: {command}")

        with mock.patch.object(main, "_run_switch_command", side_effect=fake_switch_command):
            result = main._local_switch_namespace_cleanup_readiness(
                {
                    "namespace": "provider",
                    "expected_releases": ["conn-org2-pionera-pionera"],
                }
            )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["matching_releases"], ["conn-org2-pionera-pionera"])

    def test_level6_component_validation_environment_uses_edc_context(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "edc",
                "topology": "local",
                "environment": "DEV",
                "dataspace_name": "pionera-edc",
                "ds_domain_base": "dev.ds.dataspaceunit.upm",
                "connectors": [
                    "conn-citycounciledc-pionera-edc",
                    "conn-companyedc-pionera-edc",
                ],
                "config": {"KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm"},
            }
        )

        env = main._level6_component_validation_environment(context, "edc")

        self.assertEqual(env["PIONERA_ADAPTER"], "edc")
        self.assertEqual(env["UI_ADAPTER"], "edc")
        self.assertEqual(env["AI_MODEL_HUB_COMPONENT_ADAPTER"], "edc")
        self.assertNotIn("PIONERA_COMPONENT_VALIDATION_MODE", env)
        self.assertNotIn("LEVEL6_COMPONENT_VALIDATION_MODE", env)
        self.assertEqual(env["UI_DATASPACE"], "pionera-edc")
        self.assertEqual(env["AI_MODEL_HUB_CONNECTOR_GOVERNANCE_PROVIDER"], "conn-citycounciledc-pionera-edc")
        self.assertEqual(env["AI_MODEL_HUB_CONNECTOR_GOVERNANCE_CONSUMER"], "conn-companyedc-pionera-edc")
        self.assertEqual(env["AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER"], "conn-citycounciledc-pionera-edc")

    def test_level6_component_validation_environment_honors_explicit_api_only_mode(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "edc",
                "topology": "local",
                "environment": "DEV",
                "dataspace_name": "pionera-edc",
                "ds_domain_base": "dev.ds.dataspaceunit.upm",
                "connectors": [
                    "conn-citycounciledc-pionera-edc",
                    "conn-companyedc-pionera-edc",
                ],
                "config": {
                    "KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm",
                    "PIONERA_COMPONENT_VALIDATION_MODE": "api-only",
                },
            }
        )

        env = main._level6_component_validation_environment(context, "edc")

        self.assertEqual(env["PIONERA_COMPONENT_VALIDATION_MODE"], "api-only")
        self.assertEqual(env["LEVEL6_COMPONENT_VALIDATION_MODE"], "api-only")

    def test_level6_component_validation_environment_uses_vm_distributed_public_urls(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "inesdata",
                "topology": "vm-distributed",
                "environment": "DEV",
                "dataspace_name": "pionera",
                "ds_domain_base": "pionera.oeg.fi.upm.es",
                "runtime_dir": "/repo/deployers/inesdata/deployments/DEV/vm-distributed/pionera",
                "connectors": [
                    "conn-org2-pionera",
                    "conn-org3-pionera",
                ],
                "config": {
                    "DS_1_CONNECTORS": "org2,org3",
                    "VM_PROVIDER_CONNECTORS": "org2",
                    "VM_CONSUMER_CONNECTORS": "org3",
                    "VM_PROVIDER_PUBLIC_URL": "https://org2.pionera.oeg.fi.upm.es",
                    "VM_CONSUMER_PUBLIC_URL": "https://org3.pionera.oeg.fi.upm.es",
                    "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                    "CONNECTOR_PROTOCOL_ADDRESS_MODE": "internal",
                },
            }
        )

        env = main._level6_component_validation_environment(context, "inesdata")

        self.assertEqual(env["UI_TOPOLOGY"], "vm-distributed")
        self.assertEqual(env["UI_ENVIRONMENT"], "DEV")
        self.assertEqual(env["UI_RUNTIME_DIR"], "/repo/deployers/inesdata/deployments/DEV/vm-distributed/pionera")
        self.assertEqual(env["AI_MODEL_HUB_KEYCLOAK_URL"], "https://org1.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(
            env["AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL"],
            "https://org2.pionera.oeg.fi.upm.es/management",
        )
        self.assertEqual(
            env["AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL"],
            "https://org3.pionera.oeg.fi.upm.es/management",
        )
        self.assertEqual(
            env["AI_MODEL_HUB_PROVIDER_PROTOCOL_URL"],
            "http://conn-org2-pionera.pionera.oeg.fi.upm.es/protocol",
        )

    def test_level6_component_validation_environment_uses_vm_single_public_path_urls(self):
        context = DeploymentContext.from_mapping(
            {
                "deployer": "inesdata",
                "topology": "vm-single",
                "environment": "DEV",
                "dataspace_name": "pionera",
                "ds_domain_base": "dev.ds.dataspaceunit.upm",
                "runtime_dir": "/repo/deployers/inesdata/deployments/DEV/vm-single/pionera",
                "connectors": [
                    "conn-org2-pionera",
                    "conn-org3-pionera",
                ],
                "config": {
                    "TOPOLOGY": "vm-single",
                    "DS_1_CONNECTORS": "org2,org3",
                    "VM_PROVIDER_CONNECTORS": "org2",
                    "VM_CONSUMER_CONNECTORS": "org3",
                    "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
                    "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX": "/c",
                    "KEYCLOAK_FRONTEND_URL": "https://org4.pionera.oeg.fi.upm.es/auth",
                },
            }
        )

        env = main._level6_component_validation_environment(context, "inesdata")

        self.assertEqual(env["UI_TOPOLOGY"], "vm-single")
        self.assertEqual(env["UI_ENVIRONMENT"], "DEV")
        self.assertEqual(env["UI_RUNTIME_DIR"], "/repo/deployers/inesdata/deployments/DEV/vm-single/pionera")
        self.assertEqual(env["AI_MODEL_HUB_KEYCLOAK_URL"], "https://org4.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(
            env["AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL"],
            "https://org4.pionera.oeg.fi.upm.es/c/org2/management",
        )
        self.assertEqual(
            env["AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL"],
            "https://org4.pionera.oeg.fi.upm.es/c/org3/management",
        )
        self.assertEqual(
            env["AI_MODEL_HUB_PROVIDER_PROTOCOL_URL"],
            "https://org4.pionera.oeg.fi.upm.es/c/org2/protocol",
        )

    def test_vm_single_mapping_editor_k3s_prefers_kubectl_port_forward(self):
        with mock.patch.object(main, "_vm_single_mapping_editor_is_k3s", return_value=True), mock.patch.object(
            main,
            "_ensure_vm_single_mapping_editor_kubectl_port_forward",
            return_value={
                "status": "started",
                "mode": "kubectl-port-forward",
                "url": "http://127.0.0.1:5678",
            },
        ) as port_forward_mock, mock.patch.object(
            main,
            "_vm_single_mapping_editor_host_port",
            side_effect=AssertionError("hostPort fallback should not be used first for vm-single k3s"),
        ):
            result = main._ensure_vm_single_mapping_editor_tunnel(
                {"vms": [{"address": "192.168.122.52"}]},
                {
                    "CLUSTER_TYPE": "k3s",
                    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT": "5678",
                },
            )

        port_forward_mock.assert_called_once()
        self.assertEqual(result["status"], "started")
        self.assertEqual(result["mode"], "kubectl-port-forward")
        self.assertEqual(result["url"], "http://127.0.0.1:5678")

    def test_vm_single_mapping_editor_public_url_disables_auto_tunnel(self):
        should_tunnel = main._vm_single_mapping_editor_should_use_tunnel(
            {"vms": [{"address": "192.168.122.52"}]},
            {
                "CLUSTER_TYPE": "k3s",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL": "https://streamlit-org4.example.test",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE": "host-port",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT": "5678",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_TUNNEL_MODE": "auto",
            },
        )

        self.assertFalse(should_tunnel)

    def test_vm_single_mapping_editor_port_forward_command_is_parametrized(self):
        command = main._vm_single_mapping_editor_port_forward_command(
            {
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NAMESPACE": "custom-components",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_NAME": "custom-editor",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_PORT": "8502",
            },
            45678,
        )

        self.assertEqual(
            command,
            [
                "kubectl",
                "port-forward",
                "--address",
                "127.0.0.1",
                "-n",
                "custom-components",
                "svc/custom-editor",
                "45678:8502",
            ],
        )

    def test_local_adapter_install_capacity_preflight_switches_when_explicitly_confirmed(self):
        nodes_payload = {
            "items": [
                {"status": {"allocatable": {"memory": "15996068Ki"}}},
            ]
        }
        pods_before = {
            "items": [
                {"metadata": {"namespace": "core-control"}, "status": {"phase": "Running"}},
            ]
        }
        pods_after = {
            "items": [
                {"metadata": {"namespace": "demoedc"}, "status": {"phase": "Running"}},
            ]
        }
        switch_result = {
            "status": "completed",
            "target_adapter": "edc",
            "adapters_to_remove": ["inesdata"],
            "deleted_namespaces": ["core-control", "components"],
        }

        with mock.patch.dict(
            os.environ,
            {"PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM": "SWITCH TO EDC"},
            clear=False,
        ), mock.patch.object(
            main,
            "_run_json_command",
            side_effect=[nodes_payload, pods_before, nodes_payload, pods_after],
        ), mock.patch.object(
            main,
            "_docker_memory_total_mb",
            return_value=15621,
        ), mock.patch.object(
            main,
            "load_layered_deployer_config",
            return_value={"MINIKUBE_MEMORY": "14336"},
        ), mock.patch.object(
            main,
            "_execute_local_adapter_switch_plan",
            return_value=switch_result,
        ) as switch_mock:
            result = main._run_local_adapter_install_capacity_preflight(
                "edc",
                "local",
                3,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["switch"], switch_result)
        self.assertFalse(result["coexistence_detected"])
        switch_mock.assert_called_once()

    def test_local_adapter_install_capacity_preflight_allows_first_adapter(self):
        pods_payload = {
            "items": [
                {"metadata": {"namespace": "common-srvs"}, "status": {"phase": "Running"}},
            ]
        }
        nodes_payload = {
            "items": [
                {"status": {"allocatable": {"memory": "15996068Ki"}}},
            ]
        }

        with mock.patch.object(
            main,
            "_run_json_command",
            side_effect=[nodes_payload, pods_payload],
        ), mock.patch.object(
            main,
            "_docker_memory_total_mb",
            return_value=15621,
        ), mock.patch.object(
            main,
            "load_layered_deployer_config",
            return_value={"MINIKUBE_MEMORY": "14336"},
        ):
            result = main._run_local_adapter_install_capacity_preflight(
                "edc",
                "local",
                3,
            )

        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["coexistence_detected"])

    def test_local_adapter_install_capacity_preflight_allows_target_adapter_components(self):
        pods_payload = {
            "items": [
                {"metadata": {"namespace": "edc-control"}, "status": {"phase": "Running"}},
                {"metadata": {"namespace": "components"}, "status": {"phase": "Running"}},
            ]
        }
        nodes_payload = {
            "items": [
                {"status": {"allocatable": {"memory": "15996068Ki"}}},
            ]
        }

        with mock.patch.object(
            main,
            "_run_json_command",
            side_effect=[nodes_payload, pods_payload],
        ), mock.patch.object(
            main,
            "_docker_memory_total_mb",
            return_value=15621,
        ), mock.patch.object(
            main,
            "load_layered_deployer_config",
            return_value={"MINIKUBE_MEMORY": "14336"},
        ):
            result = main._run_local_adapter_install_capacity_preflight(
                "edc",
                "local",
                3,
            )

        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["coexistence_detected"])
        self.assertEqual(result["workloads"]["active_adapters"], ["edc"])
        self.assertEqual(result["workloads"]["active_component_namespaces"], ["components"])

    def test_local_adapter_install_capacity_preflight_blocks_edc_when_components_remain(self):
        pods_payload = {
            "items": [
                {"metadata": {"namespace": "components"}, "status": {"phase": "Running"}},
            ]
        }
        nodes_payload = {
            "items": [
                {"status": {"allocatable": {"memory": "15996068Ki"}}},
            ]
        }

        with mock.patch.object(
            main,
            "_run_json_command",
            side_effect=[nodes_payload, pods_payload],
        ), mock.patch.object(
            main,
            "_docker_memory_total_mb",
            return_value=15621,
        ), mock.patch.object(
            main,
            "load_layered_deployer_config",
            return_value={"MINIKUBE_MEMORY": "14336"},
        ):
            with self.assertRaisesRegex(RuntimeError, "only supports one adapter at a time"):
                main._run_local_adapter_install_capacity_preflight(
                    "edc",
                    "local",
                    3,
                )

    def test_run_validate_records_local_stability_for_local_stable_real_deployer(self):
        class InesdataValidationDeployer(FakeDeployer):
            def get_validation_profile(self, context):
                return {
                    "adapter": "inesdata",
                    "newman_enabled": True,
                    "test_data_cleanup_enabled": False,
                    "playwright_enabled": False,
                }

        adapter = FakeAdapter()
        self.fake_deployer_module.InesdataValidationDeployer = InesdataValidationDeployer
        preflight = {"status": "passed", "restart_index": {}, "node_not_ready_event_count": 0}
        postflight = {"status": "warning", "warnings": [{"name": "node_not_ready_delta"}]}

        with mock.patch.object(
            main,
            "build_metrics_collector",
            return_value=mock.Mock(collect_experiment_newman_metrics=lambda experiment_dir: []),
        ), mock.patch.object(
            main,
            "_run_level6_local_capacity_preflight",
            return_value={"status": "passed"},
        ) as capacity_mock, mock.patch.object(
            main,
            "_run_level6_local_stability_preflight",
            return_value=preflight,
        ) as preflight_mock, mock.patch.object(
            main,
            "_run_level6_local_stability_postflight",
            return_value=postflight,
        ) as postflight_mock:
            result = main.run_validate(
                adapter,
                deployer_name="inesdata",
                deployer_registry={
                    **self.deployer_registry,
                    "inesdata": "fake_deployer_module:InesdataValidationDeployer",
                },
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
                topology="local",
            )

        capacity_mock.assert_called_once()
        preflight_mock.assert_called_once()
        postflight_mock.assert_called_once()
        self.assertIs(result["local_capacity"]["preflight"], capacity_mock.return_value)
        self.assertIs(result["local_stability"]["preflight"], preflight)
        self.assertIs(result["local_stability"]["postflight"], postflight)

    def test_run_validate_cli_generates_framework_dashboard(self):
        class InesdataValidationDeployer(FakeDeployer):
            def get_validation_profile(self, context):
                return {
                    "adapter": "inesdata",
                    "newman_enabled": True,
                    "test_data_cleanup_enabled": False,
                    "playwright_enabled": False,
                }

        adapter = FakeAdapter()
        self.fake_deployer_module.InesdataValidationDeployer = InesdataValidationDeployer
        dashboard_result = {
            "status": "generated",
            "path": "/tmp/experiment/framework-report/index.html",
        }

        with mock.patch.object(
            main,
            "build_metrics_collector",
            return_value=mock.Mock(collect_experiment_newman_metrics=lambda experiment_dir: []),
        ), mock.patch.object(
            main,
            "_run_level6_local_capacity_preflight",
            return_value={"status": "passed"},
        ), mock.patch.object(
            main,
            "_run_level6_local_stability_preflight",
            return_value={"status": "passed"},
        ), mock.patch.object(
            main,
            "_run_level6_local_stability_postflight",
            return_value={"status": "passed"},
        ), mock.patch.object(
            main,
            "_generate_framework_dashboard",
            return_value=dashboard_result,
        ) as dashboard_mock:
            result = main.run_validate(
                adapter,
                deployer_name="inesdata",
                deployer_registry={
                    **self.deployer_registry,
                    "inesdata": "fake_deployer_module:InesdataValidationDeployer",
                },
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
                topology="local",
            )

        dashboard_mock.assert_called_once_with(result["experiment_dir"])
        self.assertEqual(result["framework_report"], dashboard_result)
        self.assertEqual(result["une_0087_alignment"]["status"], "generated")
        self.assertTrue(os.path.exists(os.path.join(result["experiment_dir"], "une_0087_alignment.json")))
        self.assertTrue(os.path.exists(os.path.join(result["experiment_dir"], "une_0087_alignment.md")))

    def test_level6_kafka_prompt_is_first_visible_level6_action(self):
        events = []

        class InesdataValidationDeployer(FakeDeployer):
            def get_validation_profile(self, context):
                return {
                    "adapter": "inesdata",
                    "newman_enabled": True,
                    "test_data_cleanup_enabled": False,
                    "playwright_enabled": False,
                }

        self.fake_deployer_module.InesdataValidationDeployer = InesdataValidationDeployer

        def resolve_kafka(*args, **kwargs):
            events.append("kafka_prompt")
            return False

        def sync_hosts(context):
            events.append("hosts_sync")
            return {"status": "skipped"}

        def save_metadata(*args, **kwargs):
            events.append("metadata")

        with mock.patch.object(
            main,
            "_resolve_level6_kafka_enabled_for_run",
            side_effect=resolve_kafka,
        ), mock.patch.object(
            main,
            "_sync_deployer_hosts_if_enabled",
            side_effect=sync_hosts,
        ), mock.patch.object(
            main,
            "_save_experiment_metadata",
            side_effect=save_metadata,
        ), mock.patch.object(
            main,
            "_run_level6_local_capacity_preflight",
            return_value={"status": "skipped"},
        ), mock.patch.object(
            main,
            "_run_level6_local_stability_preflight",
            return_value={"status": "skipped"},
        ), mock.patch.object(
            main,
            "_run_level6_local_stability_postflight",
            return_value={"status": "skipped"},
        ), mock.patch.object(
            main,
            "_ensure_level6_public_endpoint_access",
            return_value={"status": "skipped"},
        ), mock.patch.object(
            main,
            "build_metrics_collector",
            return_value=mock.Mock(collect_experiment_newman_metrics=lambda experiment_dir: []),
        ):
            main.run_validate(
                FakeAdapter(),
                deployer_name="fake",
                deployer_registry={
                    **self.deployer_registry,
                    "fake": "fake_deployer_module:InesdataValidationDeployer",
                },
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
                topology="local",
            )

        self.assertEqual(events[:3], ["kafka_prompt", "hosts_sync", "metadata"])

    def test_run_validate_local_stable_defers_background_kafka_preparation(self):
        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        class InesdataValidationDeployer(FakeDeployer):
            def get_validation_profile(self, context):
                return {
                    "adapter": "inesdata",
                    "newman_enabled": True,
                    "test_data_cleanup_enabled": False,
                    "playwright_enabled": False,
                }

        adapter = KafkaReadyAdapter()
        self.fake_deployer_module.InesdataValidationDeployer = InesdataValidationDeployer

        with mock.patch.object(
            main,
            "build_metrics_collector",
            return_value=mock.Mock(collect_experiment_newman_metrics=lambda experiment_dir: []),
        ), mock.patch.object(
            main,
            "_start_level6_kafka_preparation",
            return_value=None,
        ) as start_preparation, mock.patch.object(
            main,
            "run_level6_kafka_edc_after_newman",
            return_value=[],
        ):
            result = main.run_validate(
                adapter,
                deployer_name="fake",
                deployer_registry={
                    **self.deployer_registry,
                    "fake": "fake_deployer_module:InesdataValidationDeployer",
                },
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
                topology="local",
            )

        self.assertEqual(result["validation_mode"]["effective"], "stable")
        self.assertTrue(result["validation_mode"]["local_stable"])
        self.assertFalse(start_preparation.call_args.kwargs["background"])

    def test_run_validate_prepares_kafka_in_background_without_blocking_newman(self):
        events = []
        validation_started = threading.Event()
        allow_kafka_finish = threading.Event()

        class KafkaReadyAdapter(FakeAdapter):
            def get_kafka_config(self):
                return {"bootstrap_servers": "localhost:9092"}

        class InesdataValidationDeployer(FakeDeployer):
            def get_validation_profile(self, context):
                return {
                    "adapter": "inesdata",
                    "newman_enabled": True,
                    "test_data_cleanup_enabled": False,
                    "playwright_enabled": False,
                }

        class RecordingValidationEngine(FakeValidationEngine):
            def run(self, connectors):
                events.append("validation")
                validation_started.set()
                return super().run(connectors)

        class RecordingMetricsCollector:
            def collect_experiment_newman_metrics(self, experiment_dir):
                events.append("newman_metrics")
                allow_kafka_finish.set()
                return [{"request": "login"}]

        class BlockingKafkaManager:
            def __init__(self, *args, **kwargs):
                self.bootstrap_servers = None
                self.cluster_bootstrap_servers = None
                self.started_by_framework = False
                self.provisioning_mode = None
                self.last_error = None

            def ensure_kafka_running(self):
                events.append("kafka_prepare_start")
                validation_started.wait(timeout=2)
                events.append("kafka_prepare_running")
                allow_kafka_finish.wait(timeout=2)
                self.bootstrap_servers = "127.0.0.1:39092"
                self.cluster_bootstrap_servers = "framework-kafka.fake-ds.svc.cluster.local:9092"
                self.started_by_framework = True
                self.provisioning_mode = "kubernetes"
                events.append("kafka_prepare_finish")
                return self.bootstrap_servers

            def stop_kafka(self):
                events.append("kafka_stop")

        def run_kafka(connectors, experiment_dir, *, validator, experiment_storage, progress_callback=None):
            events.append("kafka_edc")
            self.assertTrue(callable(progress_callback))
            return [{"status": "passed", "provider": connectors[0], "consumer": connectors[1]}]

        adapter = KafkaReadyAdapter()
        self.fake_deployer_module.InesdataValidationDeployer = InesdataValidationDeployer

        def kafka_enabled_env_flag(name, default=False):
            if name == "PIONERA_LEVEL6_RUN_KAFKA":
                return True
            if name == "PIONERA_LEVEL6_SKIP_KAFKA":
                return False
            return default

        with mock.patch.object(
            main,
            "build_metrics_collector",
            return_value=RecordingMetricsCollector(),
        ), mock.patch.object(
            main,
            "build_kafka_edc_validation_suite",
            return_value=mock.Mock(),
        ) as build_suite, mock.patch.object(
            main,
            "run_kafka_edc_validation",
            side_effect=run_kafka,
        ), mock.patch.object(
            main,
            "_env_flag",
            side_effect=kafka_enabled_env_flag,
        ):
            result = main.run_validate(
                adapter,
                deployer_name="fake",
                deployer_registry={
                    **self.deployer_registry,
                    "fake": "fake_deployer_module:InesdataValidationDeployer",
                },
                validation_engine_cls=RecordingValidationEngine,
                experiment_storage=FakeStorage,
                kafka_manager_cls=BlockingKafkaManager,
                validation_mode="fast",
            )

        self.assertEqual(result["kafka_edc_results"][0]["status"], "passed")
        self.assertIn("kafka_prepare_start", events)
        self.assertIn("validation", events)
        self.assertIn("newman_metrics", events)
        self.assertIn("kafka_prepare_finish", events)
        self.assertIn("kafka_edc", events)
        self.assertLess(events.index("validation"), events.index("kafka_prepare_finish"))
        self.assertLess(events.index("newman_metrics"), events.index("kafka_prepare_finish"))
        self.assertLess(events.index("kafka_prepare_finish"), events.index("kafka_edc"))
        self.assertIsInstance(build_suite.call_args.kwargs["kafka_manager"], BlockingKafkaManager)

    def test_level6_local_http_fallback_is_not_used_when_disabled(self):
        adapter = FakeAdapter()
        adapter.topology = "local"
        validator = mock.Mock()
        validator.load_deployer_config.return_value = {"KC_URL": "http://keycloak.local"}
        validator._dataspace_name.return_value = "fake-ds"
        validator._management_url.side_effect = lambda connector, path: f"http://{connector}.example.local{path}"

        fallback = main._Level6LocalHttpPortForwardFallback(adapter, ["conn-a", "conn-b"], validator)

        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(
            main._Level6LocalHttpPortForwardFallback,
            "_probe_http_url",
            return_value=False,
        ) as probe, mock.patch.object(
            main._Level6LocalHttpPortForwardFallback,
            "_start_service_port_forward",
        ) as start_forward:
            activated = fallback.activate_if_needed()

        self.assertFalse(activated)
        start_forward.assert_not_called()
        probe.assert_not_called()

    def test_level6_local_http_fallback_starts_port_forwards_only_for_unreachable_endpoints(self):
        adapter = FakeAdapter()
        adapter.topology = "local"
        validator = mock.Mock()
        validator.load_deployer_config.return_value = {"KC_URL": "http://keycloak.local"}
        validator._dataspace_name.return_value = "fake-ds"
        validator._management_url.side_effect = lambda connector, path: f"http://{connector}.example.local{path}"
        validator.keycloak_url_resolver = None
        validator.management_url_resolver = None

        fallback = main._Level6LocalHttpPortForwardFallback(adapter, ["conn-a", "conn-b"], validator)

        def probe(url, timeout=3):
            if "keycloak.local" in url:
                return False
            if "conn-a.example.local" in url:
                return False
            return True

        with mock.patch.dict(
            os.environ,
            {"PIONERA_LEVEL6_LOCAL_HTTP_PORT_FORWARD_FALLBACK": "true"},
            clear=False,
        ), mock.patch.object(
            main._Level6LocalHttpPortForwardFallback,
            "_probe_http_url",
            side_effect=probe,
        ), mock.patch.object(
            main._Level6LocalHttpPortForwardFallback,
            "_start_service_port_forward",
            side_effect=[38080, 39193],
        ) as start_forward:
            activated = fallback.activate_if_needed()

        self.assertTrue(activated)
        self.assertEqual(start_forward.call_count, 2)
        self.assertEqual(validator.keycloak_url_resolver(), "http://127.0.0.1:38080")
        self.assertEqual(
            validator.management_url_resolver("conn-a", "/management/v3/assets/request"),
            "http://127.0.0.1:39193/management/v3/assets/request",
        )
        self.assertEqual(
            validator.management_url_resolver("conn-b", "/management/v3/assets/request"),
            "",
        )

    def test_validate_command_runs_test_data_cleanup_when_enabled(self):
        with mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={"status": "completed", "summary": {"deleted_total": 3}},
        ) as cleanup_runner, mock.patch.dict(
            os.environ,
            {
                "PIONERA_TEST_DATA_CLEANUP": "true",
                "PIONERA_TEST_DATA_CLEANUP_MODE": "dry-run",
            },
            clear=False,
        ):
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["test_data_cleanup"]["status"], "completed")
        cleanup_runner.assert_called_once()
        cleanup_kwargs = cleanup_runner.call_args.kwargs
        self.assertEqual(cleanup_kwargs["connectors"], ["conn-deployer-a", "conn-deployer-b"])
        self.assertEqual(cleanup_kwargs["mode"], "dry-run")
        self.assertTrue(cleanup_kwargs["report_enabled"])

    def test_resolve_validation_runtime_keeps_legacy_fallback_for_local_topology(self):
        adapter = FakeAdapter()
        failing_orchestrator = mock.Mock()
        failing_orchestrator.resolve_context.side_effect = ValueError("boom")

        with mock.patch.object(
            main,
            "build_deployer_orchestrator",
            return_value=failing_orchestrator,
        ):
            result = main._resolve_validation_runtime(
                adapter,
                deployer_name="fake",
                topology="local",
            )

        self.assertEqual(result["connectors"], ["conn-a", "conn-b"])
        self.assertIsNone(result["validation_profile"])
        self.assertIsNone(result["deployer_context"])
        self.assertIsNone(result["deployer_name"])

    def test_resolve_validation_runtime_fails_clearly_for_vm_single_without_topology_address(self):
        adapter = FakeAdapter()
        failing_orchestrator = mock.Mock()
        failing_orchestrator.resolve_context.side_effect = ValueError(
            "Topology 'vm-single' requires VM_EXTERNAL_IP, VM_SINGLE_IP, VM_SINGLE_ADDRESS, HOSTS_ADDRESS, or INGRESS_EXTERNAL_IP."
        )

        with mock.patch.object(
            main,
            "build_deployer_orchestrator",
            return_value=failing_orchestrator,
        ):
            with self.assertRaises(RuntimeError) as exc:
                main._resolve_validation_runtime(
                    adapter,
                    deployer_name="fake",
                    topology="vm-single",
                )

        self.assertIn("deployer-aware validation context", str(exc.exception))
        self.assertIn("PIONERA_VM_EXTERNAL_IP", str(exc.exception))
        self.assertIn("vm-single", str(exc.exception))

    def test_test_data_cleanup_requires_local_infra_access_for_local_topology(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = types.SimpleNamespace(
            ensure_local_infra_access=mock.Mock(return_value=True)
        )

        with mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={"status": "completed", "summary": {"deleted_total": 1}},
        ) as cleanup_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_TEST_DATA_CLEANUP": "true"},
            clear=False,
        ):
            result = main._run_test_data_cleanup_if_enabled(
                adapter,
                ["conn-a", "conn-b"],
                {"topology": "local", "dataspace_name": "fake-ds"},
                "/tmp/cleanup-local",
            )

        self.assertEqual(result["status"], "completed")
        adapter.infrastructure.ensure_local_infra_access.assert_called_once()
        cleanup_runner.assert_called_once()

    def test_test_data_cleanup_skips_local_infra_access_for_vm_single_topology(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = types.SimpleNamespace(
            ensure_local_infra_access=mock.Mock(return_value=False)
        )

        with mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={"status": "completed", "summary": {"deleted_total": 1}},
        ) as cleanup_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_TEST_DATA_CLEANUP": "true"},
            clear=False,
        ):
            result = main._run_test_data_cleanup_if_enabled(
                adapter,
                ["conn-a", "conn-b"],
                {"topology": "vm-single", "dataspace_name": "fake-ds"},
                "/tmp/cleanup-vm-single",
            )

        self.assertEqual(result["status"], "completed")
        adapter.infrastructure.ensure_local_infra_access.assert_not_called()
        cleanup_runner.assert_called_once()

    def test_test_data_cleanup_resolves_vm_single_public_runtime(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = types.SimpleNamespace(
            ensure_local_infra_access=mock.Mock(return_value=False)
        )

        with mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={"status": "completed", "summary": {"deleted_total": 1}},
        ) as cleanup_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_TEST_DATA_CLEANUP": "true"},
            clear=False,
        ):
            result = main._run_test_data_cleanup_if_enabled(
                adapter,
                ["conn-org2-pionera"],
                {
                    "topology": "vm-single",
                    "dataspace_name": "pionera",
                    "ds_domain_base": "dev.ed.dataspaceunit.upm",
                    "config": {
                        "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
                        "KEYCLOAK_FRONTEND_URL": "https://org1.dev.ed.dataspaceunit.upm/auth",
                        "MINIO_API_PUBLIC_URL": "http://minio.dev.ed.dataspaceunit.upm",
                        "MINIO_CONSOLE_PUBLIC_URL": "https://console.minio-s3.dev.ed.dataspaceunit.upm",
                        "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                    },
                },
                "/tmp/cleanup-vm-single",
            )

        self.assertEqual(result["status"], "completed")
        cleanup_context = cleanup_runner.call_args.kwargs["context"]
        self.assertEqual(
            cleanup_context.config["KEYCLOAK_FRONTEND_URL"],
            "https://org4.pionera.oeg.fi.upm.es/auth",
        )
        self.assertEqual(
            cleanup_context.config["KEYCLOAK_PUBLIC_URL"],
            "https://org4.pionera.oeg.fi.upm.es/auth",
        )
        self.assertEqual(
            cleanup_context.config["MINIO_API_PUBLIC_URL"],
            "https://org4.pionera.oeg.fi.upm.es",
        )
        self.assertEqual(
            cleanup_context.config["MINIO_CONSOLE_PUBLIC_URL"],
            "https://org4.pionera.oeg.fi.upm.es/s3-console",
        )
        self.assertNotEqual(
            cleanup_context.config["KEYCLOAK_FRONTEND_URL"],
            "https://org1.dev.ed.dataspaceunit.upm/auth",
        )

    def test_test_data_cleanup_requires_local_infra_access_for_vm_single_loopback_endpoints(self):
        adapter = FakeAdapterWithInfrastructure()
        adapter.infrastructure = types.SimpleNamespace(
            ensure_local_infra_access=mock.Mock(return_value=True)
        )

        with mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={"status": "completed", "summary": {"deleted_total": 1}},
        ) as cleanup_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_TEST_DATA_CLEANUP": "true"},
            clear=False,
        ):
            result = main._run_test_data_cleanup_if_enabled(
                adapter,
                ["conn-a", "conn-b"],
                {
                    "topology": "vm-single",
                    "dataspace_name": "fake-ds",
                    "config": {"MINIO_ENDPOINT": "http://127.0.0.1:9000"},
                },
                "/tmp/cleanup-vm-single",
            )

        self.assertEqual(result["status"], "completed")
        adapter.infrastructure.ensure_local_infra_access.assert_called_once()
        cleanup_runner.assert_called_once()

    def test_level6_public_endpoint_preflight_builds_dataspace_and_connector_urls(self):
        adapter = FakeAdapterWithInfrastructure()
        context = types.SimpleNamespace(
            topology="local",
            dataspace_name="fake-ds",
            ds_domain_base="example.local",
            config={
                "KC_URL": "http://keycloak-admin.example.local",
                "KC_INTERNAL_URL": "http://keycloak.example.local",
                "MINIO_HOSTNAME": "minio.example.local",
            },
        )

        with mock.patch.object(
            main,
            "ensure_public_endpoints_accessible",
            return_value={"status": "passed", "checked": []},
        ) as preflight:
            result = main._ensure_level6_public_endpoint_access(
                adapter,
                ["conn-a"],
                context,
            )

        self.assertEqual(result["status"], "passed")
        endpoints = preflight.call_args.args[0]
        urls = {endpoint["url"] for endpoint in endpoints}
        self.assertIn("http://keycloak-admin.example.local", urls)
        self.assertIn("http://keycloak.example.local", urls)
        self.assertIn("http://minio.example.local", urls)
        self.assertIn("http://registration-service-fake-ds.example.local", urls)
        self.assertIn("http://conn-a.example.local/interface", urls)

    def test_level6_public_endpoint_preflight_uses_vm_distributed_public_urls(self):
        class PublicConnectors(FakeConnectors):
            @staticmethod
            def connector_base_url(connector):
                return {
                    "conn-org2-pionera": "https://org2.pionera.oeg.fi.upm.es",
                    "conn-org3-pionera": "https://org3.pionera.oeg.fi.upm.es",
                }[connector]

        adapter = FakeAdapterWithInfrastructure()
        adapter.connectors = PublicConnectors()
        context = types.SimpleNamespace(
            topology="vm-distributed",
            dataspace_name="pionera",
            ds_domain_base="pionera.oeg.fi.upm.es",
            config={
                "KC_URL": "http://admin.auth.pionera.oeg.fi.upm.es",
                "KC_INTERNAL_URL": "http://auth.pionera.oeg.fi.upm.es",
                "MINIO_HOSTNAME": "minio-s3.pionera.oeg.fi.upm.es",
                "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                "MINIO_CONSOLE_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es/s3-console",
            },
        )

        with mock.patch.object(
            main,
            "ensure_public_endpoints_accessible",
            return_value={"status": "passed", "checked": []},
        ) as preflight:
            result = main._ensure_level6_public_endpoint_access(
                adapter,
                ["conn-org2-pionera", "conn-org3-pionera"],
                context,
            )

        self.assertEqual(result["status"], "passed")
        endpoints = preflight.call_args.args[0]
        urls = {endpoint["url"] for endpoint in endpoints}
        self.assertIn("https://org1.pionera.oeg.fi.upm.es/auth", urls)
        self.assertIn("https://org1.pionera.oeg.fi.upm.es/s3-console", urls)
        self.assertIn("https://org2.pionera.oeg.fi.upm.es", urls)
        self.assertIn("https://org3.pionera.oeg.fi.upm.es", urls)
        self.assertNotIn("http://auth.pionera.oeg.fi.upm.es", urls)
        self.assertNotIn("http://registration-service-pionera.pionera.oeg.fi.upm.es", urls)
        self.assertEqual(preflight.call_args.kwargs["tls_verify"], "auto")

    def test_level6_public_endpoint_preflight_uses_vm_single_public_paths(self):
        class PublicConnectors(FakeConnectors):
            @staticmethod
            def connector_base_url(connector):
                return {
                    "conn-org2-pionera": "https://org4.pionera.oeg.fi.upm.es/c/org2",
                    "conn-org3-pionera": "https://org4.pionera.oeg.fi.upm.es/c/org3",
                }[connector]

        adapter = FakeAdapterWithInfrastructure()
        adapter.connectors = PublicConnectors()
        context = types.SimpleNamespace(
            topology="vm-single",
            dataspace_name="pionera",
            ds_domain_base="dev.ed.dataspaceunit.upm",
            config={
                "KC_URL": "http://admin.auth.dev.ed.dataspaceunit.upm",
                "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "KEYCLOAK_FRONTEND_URL": "https://org1.dev.ed.dataspaceunit.upm/auth",
                "MINIO_HOSTNAME": "minio.dev.ed.dataspaceunit.upm",
                "MINIO_API_PUBLIC_URL": "http://minio.dev.ed.dataspaceunit.upm",
                "MINIO_CONSOLE_PUBLIC_URL": "https://console.minio-s3.dev.ed.dataspaceunit.upm",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
            },
        )

        with mock.patch.object(
            main,
            "ensure_public_endpoints_accessible",
            return_value={"status": "passed", "checked": []},
        ) as preflight:
            result = main._ensure_level6_public_endpoint_access(
                adapter,
                ["conn-org2-pionera", "conn-org3-pionera"],
                context,
            )

        self.assertEqual(result["status"], "passed")
        endpoints = preflight.call_args.args[0]
        urls = {endpoint["url"] for endpoint in endpoints}
        self.assertIn("https://org4.pionera.oeg.fi.upm.es/auth", urls)
        self.assertIn("https://org4.pionera.oeg.fi.upm.es/s3-console", urls)
        self.assertIn("https://org4.pionera.oeg.fi.upm.es", urls)
        self.assertIn("https://org4.pionera.oeg.fi.upm.es/c/org2", urls)
        self.assertIn("https://org4.pionera.oeg.fi.upm.es/c/org3", urls)
        self.assertNotIn("http://auth.dev.ed.dataspaceunit.upm", urls)
        self.assertNotIn("http://admin.auth.dev.ed.dataspaceunit.upm", urls)
        self.assertNotIn("https://org1.dev.ed.dataspaceunit.upm/auth", urls)
        self.assertNotIn("http://minio.dev.ed.dataspaceunit.upm", urls)
        self.assertNotIn("https://console.minio-s3.dev.ed.dataspaceunit.upm", urls)
        self.assertNotIn("http://registration-service-pionera.dev.ed.dataspaceunit.upm", urls)

    def test_cleanup_failure_hint_explains_local_artifact_credential_mismatch(self):
        cleanup_result = {
            "connectors": [
                {
                    "errors": [
                        {
                            "message": (
                                "Token request for conn-a failed with HTTP 401: "
                                '{"error":"invalid_grant","error_description":"Invalid user credentials"}'
                            )
                        }
                    ],
                    "storage": {
                        "errors": [
                            {
                                "message": (
                                    "S3 operation failed; code: InvalidAccessKeyId, "
                                    "message: The Access Key Id you provided does not exist"
                                )
                            }
                        ]
                    },
                }
            ]
        }

        hint = main._test_data_cleanup_failure_hint(cleanup_result)

        self.assertIn("Local deployment artifacts are out of sync", hint)
        self.assertIn("Run Level 4 again from this same checkout", hint)

    def test_validate_command_runs_test_data_cleanup_when_profile_enables_it_by_default(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "test_data_cleanup_enabled": True,
                "playwright_enabled": False,
            },
        ), mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={"status": "completed", "summary": {"deleted_total": 1}},
        ) as cleanup_runner:
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["test_data_cleanup"]["status"], "completed")
        cleanup_runner.assert_called_once()

    def test_validate_command_can_disable_profile_test_data_cleanup_explicitly(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "test_data_cleanup_enabled": True,
                "playwright_enabled": False,
            },
        ), mock.patch.object(
            main,
            "run_pre_validation_cleanup",
        ) as cleanup_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_DISABLE_TEST_DATA_CLEANUP": "true"},
            clear=False,
        ):
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["test_data_cleanup"]["status"], "skipped")
        self.assertEqual(result["test_data_cleanup"]["reason"], "disabled")
        cleanup_runner.assert_not_called()

    def test_validate_command_fails_clearly_when_test_data_cleanup_fails(self):
        with mock.patch.object(
            main,
            "run_pre_validation_cleanup",
            return_value={
                "status": "failed",
                "report_path": "/tmp/experiment/cleanup/test_data_cleanup.json",
            },
        ), mock.patch.dict(
            os.environ,
            {"PIONERA_TEST_DATA_CLEANUP": "true"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError) as exc:
                main.main(
                    ["fake", "validate"],
                    adapter_registry=self.registry,
                    deployer_registry=self.deployer_registry,
                    validation_engine_cls=FakeValidationEngine,
                    experiment_storage=FakeStorage,
                )

        self.assertIn("Pre-validation test data cleanup failed", str(exc.exception))
        self.assertIn("test_data_cleanup.json", str(exc.exception))

    def test_validate_command_can_disable_deployer_resolution_explicitly(self):
        with mock.patch.dict(os.environ, {"PIONERA_DISABLE_DEPLOYER_VALIDATE": "true"}, clear=False):
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["validation"], {"validated": ["conn-a", "conn-b"]})
        self.assertIsNone(result["validation_profile"])
        self.assertIsNone(result["deployer_context"])

    def test_validate_command_can_run_playwright_when_profile_enables_it(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.edc.config.ts",
            },
        ), mock.patch.object(
            main,
            "run_playwright_validation",
            return_value={"status": "passed", "summary": {"total_specs": 3}},
        ) as playwright_runner:
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["validation"], {"validated": ["conn-deployer-a", "conn-deployer-b"]})
        self.assertEqual(result["playwright"]["status"], "passed")
        self.assertEqual(result["playwright"]["summary"]["total_specs"], 3)
        playwright_runner.assert_called_once()

    def test_validate_command_can_disable_profile_playwright_explicitly(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.edc.config.ts",
            },
        ), mock.patch.object(main, "run_playwright_validation") as playwright_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_DISABLE_DEPLOYER_PLAYWRIGHT": "true"},
            clear=False,
        ):
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["playwright"]["status"], "skipped")
        self.assertEqual(result["playwright"]["reason"], "disabled")
        playwright_runner.assert_not_called()

    def test_validate_command_fails_clearly_when_edc_playwright_is_enabled_but_dashboard_is_disabled(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "edc",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.edc.config.ts",
            },
        ), mock.patch.dict(
            os.environ,
            {"PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT": "true"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError) as exc:
                main.main(
                    ["fake", "validate"],
                    adapter_registry=self.registry,
                    deployer_registry={"fake": "fake_deployer_module:FakeDeployer"},
                    validation_engine_cls=FakeValidationEngine,
                    experiment_storage=FakeStorage,
                )

        self.assertIn("EDC_DASHBOARD_ENABLED=true", str(exc.exception))

    def test_validate_command_fails_clearly_when_edc_playwright_auth_mode_is_not_oidc_bff(self):
        def resolve_context_without_oidc(self, topology="local"):
            return {
                "deployer": "edc",
                "topology": topology,
                "environment": "DEV",
                "dataspace_name": "fake-ds",
                "ds_domain_base": "example.local",
                "connectors": ["conn-a", "conn-b"],
                "components": [],
                "namespace_roles": {
                    "registration_service_namespace": "fake-ds",
                    "provider_namespace": "fake-ds",
                    "consumer_namespace": "fake-ds",
                },
                "runtime_dir": "/tmp/fake-ds",
                "config": {
                    "DS_1_NAME": "fake-ds",
                    "EDC_DASHBOARD_ENABLED": "true",
                    "EDC_DASHBOARD_PROXY_AUTH_MODE": "service-account",
                },
            }

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "edc",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.edc.config.ts",
            },
        ), mock.patch.object(
            FakeDeployer,
            "resolve_context",
            new=resolve_context_without_oidc,
        ), mock.patch.dict(
            os.environ,
            {"PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT": "true"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError) as exc:
                main.main(
                    ["fake", "validate"],
                    adapter_registry=self.registry,
                    deployer_registry={"fake": "fake_deployer_module:FakeDeployer"},
                    validation_engine_cls=FakeValidationEngine,
                    experiment_storage=FakeStorage,
                )

        self.assertIn("EDC_DASHBOARD_PROXY_AUTH_MODE=oidc-bff", str(exc.exception))

    def test_validate_command_allows_edc_playwright_when_dashboard_runtime_artifacts_exist(self):
        with tempfile.TemporaryDirectory() as runtime_root:
            runtime_dir = os.path.join(runtime_root, "fake-ds")
            dashboard_dir = os.path.join(runtime_dir, "dashboard", "conn-a")
            os.makedirs(dashboard_dir, exist_ok=True)
            with open(os.path.join(dashboard_dir, "app-config.json"), "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            with open(
                os.path.join(dashboard_dir, "edc-connector-config.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("[]\n")
            with open(os.path.join(runtime_dir, "values-conn-a.yaml"), "w", encoding="utf-8") as handle:
                handle.write("dashboard:\n  authMode: oidc-bff\n")

            def resolve_context_from_runtime(self, topology="local"):
                return {
                    "deployer": "edc",
                    "topology": topology,
                    "environment": "DEV",
                    "dataspace_name": "fake-ds",
                    "ds_domain_base": "example.local",
                    "connectors": ["conn-a", "conn-b"],
                    "components": [],
                    "namespace_roles": {
                        "registration_service_namespace": "fake-ds",
                        "provider_namespace": "fake-ds",
                        "consumer_namespace": "fake-ds",
                    },
                    "runtime_dir": runtime_dir,
                    "config": {
                        "DS_1_NAME": "fake-ds",
                        "EDC_DASHBOARD_ENABLED": "false",
                        "EDC_DASHBOARD_PROXY_AUTH_MODE": "service-account",
                    },
                }

            with mock.patch.object(
                FakeDeployer,
                "get_validation_profile",
                return_value={
                    "adapter": "edc",
                    "newman_enabled": True,
                    "playwright_enabled": True,
                    "playwright_config": "validation/ui/playwright.edc.config.ts",
                },
            ), mock.patch.object(
                FakeDeployer,
                "resolve_context",
                new=resolve_context_from_runtime,
            ), mock.patch.object(
                main,
                "run_playwright_validation",
                return_value={"status": "passed", "summary": {"total_specs": 5}},
            ) as playwright_runner, mock.patch.object(
                main,
                "_wait_for_edc_dashboard_readiness",
                return_value={"status": "passed", "gates": []},
            ) as readiness_probe, mock.patch.dict(
                os.environ,
                {"PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT": "true"},
                clear=False,
            ):
                result = main.main(
                    ["fake", "validate"],
                    adapter_registry=self.registry,
                    deployer_registry={"fake": "fake_deployer_module:FakeDeployer"},
                    validation_engine_cls=FakeValidationEngine,
                    experiment_storage=FakeStorage,
                )

        self.assertEqual(result["playwright"]["status"], "passed")
        self.assertEqual(result["playwright"]["summary"]["total_specs"], 5)
        playwright_runner.assert_called_once()
        readiness_probe.assert_called_once()

    def test_validate_command_fails_clearly_when_edc_dashboard_services_are_not_ready(self):
        with tempfile.TemporaryDirectory() as runtime_root:
            runtime_dir = os.path.join(runtime_root, "fake-ds")
            dashboard_dir = os.path.join(runtime_dir, "dashboard", "conn-a")
            os.makedirs(dashboard_dir, exist_ok=True)
            with open(os.path.join(dashboard_dir, "app-config.json"), "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            with open(
                os.path.join(dashboard_dir, "edc-connector-config.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("[]\n")
            with open(os.path.join(runtime_dir, "values-conn-a.yaml"), "w", encoding="utf-8") as handle:
                handle.write("dashboard:\n  authMode: oidc-bff\n")

            def resolve_context_from_runtime(self, topology="local"):
                return {
                    "deployer": "edc",
                    "topology": topology,
                    "environment": "DEV",
                    "dataspace_name": "fake-ds",
                    "ds_domain_base": "example.local",
                    "connectors": ["conn-a"],
                    "components": [],
                    "namespace_roles": {
                        "registration_service_namespace": "fake-ds",
                        "provider_namespace": "fake-ds",
                        "consumer_namespace": "fake-ds",
                    },
                    "runtime_dir": runtime_dir,
                    "config": {
                        "DS_1_NAME": "fake-ds",
                        "EDC_DASHBOARD_ENABLED": "false",
                        "EDC_DASHBOARD_PROXY_AUTH_MODE": "service-account",
                    },
                }

            with mock.patch.object(
                FakeDeployer,
                "get_validation_profile",
                return_value={
                    "adapter": "edc",
                    "newman_enabled": True,
                    "playwright_enabled": True,
                    "playwright_config": "validation/ui/playwright.edc.config.ts",
                },
            ), mock.patch.object(
                FakeDeployer,
                "resolve_context",
                new=resolve_context_from_runtime,
            ), mock.patch.object(
                main,
                "_wait_for_edc_dashboard_readiness",
                return_value={
                    "status": "failed",
                    "artifact": "/tmp/dashboard_readiness.json",
                    "gates": [
                        {
                            "service": "conn-a-dashboard",
                            "ready": False,
                            "detail": "service has no ready endpoints",
                        }
                    ],
                },
            ), mock.patch.object(main, "run_playwright_validation") as playwright_runner, mock.patch.dict(
                os.environ,
                {"PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT": "true"},
                clear=False,
            ):
                with self.assertRaises(RuntimeError) as exc:
                    main.main(
                        ["fake", "validate"],
                        adapter_registry=self.registry,
                        deployer_registry={"fake": "fake_deployer_module:FakeDeployer"},
                        validation_engine_cls=FakeValidationEngine,
                        experiment_storage=FakeStorage,
                    )

        self.assertIn("dashboard and dashboard-proxy services", str(exc.exception))
        self.assertIn("conn-a-dashboard: service has no ready endpoints", str(exc.exception))
        playwright_runner.assert_not_called()

    def test_validate_command_waits_for_inesdata_portal_readiness_before_playwright(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "inesdata",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.inesdata.config.ts",
            },
        ), mock.patch.object(
            main,
            "_wait_for_inesdata_portal_readiness",
            return_value={"status": "passed", "gates": []},
        ) as readiness_probe, mock.patch.object(
            main,
            "run_playwright_validation",
            return_value={"status": "passed", "summary": {"total_specs": 3}},
        ) as playwright_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT": "true"},
            clear=False,
        ), mock.patch.object(
            main,
            "print_interoperability_suite_header",
            wraps=main.print_interoperability_suite_header,
        ) as suite_header:
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["playwright"]["status"], "passed")
        readiness_probe.assert_called_once()
        playwright_runner.assert_called_once()
        suite_header.assert_any_call("INESData integration", "Playwright")

    def test_validate_command_runs_component_validation_after_playwright_when_enabled(self):
        events = []

        def fake_playwright(*args, **kwargs):
            events.append("playwright")
            return {"status": "passed", "summary": {"total_specs": 3}}

        def fake_component_validation(
            components,
            *,
            infer_component_urls,
            run_component_validations_fn,
            experiment_dir,
        ):
            events.append("components")
            self.assertEqual(components, ["ontology-hub"])
            self.assertEqual(
                infer_component_urls(components),
                {"ontology-hub": "http://ontology-hub.example.local"},
            )
            self.assertIs(run_component_validations_fn, main.run_registered_component_validations)
            self.assertTrue(experiment_dir)
            return [{"component": "ontology-hub", "status": "passed"}]

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.inesdata.config.ts",
                "component_validation_enabled": True,
                "component_groups": ["ontology-hub"],
            },
        ), mock.patch.object(
            main,
            "run_playwright_validation",
            side_effect=fake_playwright,
        ) as playwright_runner, mock.patch.object(
            main,
            "run_level6_component_validations",
            side_effect=fake_component_validation,
        ) as component_runner:
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(events, ["playwright", "components"])
        self.assertEqual(result["playwright"]["status"], "passed")
        self.assertEqual(result["component_results"][0]["component"], "ontology-hub")
        self.assertEqual(result["component_results"][0]["status"], "passed")
        self.assertEqual(result["component_validation_summary"]["passed"], 1)
        playwright_runner.assert_called_once()
        component_runner.assert_called_once()

    def test_validate_command_marks_validation_failed_when_component_validation_fails(self):
        def fake_playwright(*args, **kwargs):
            return {"status": "passed", "summary": {"total_specs": 3}}

        def fake_component_validation(
            components,
            *,
            infer_component_urls,
            run_component_validations_fn,
            experiment_dir,
        ):
            self.assertEqual(components, ["ontology-hub"])
            return [{"component": "ontology-hub", "status": "failed"}]

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.inesdata.config.ts",
                "component_validation_enabled": True,
                "component_groups": ["ontology-hub"],
            },
        ), mock.patch.object(
            main,
            "run_playwright_validation",
            side_effect=fake_playwright,
        ) as playwright_runner, mock.patch.object(
            main,
            "run_level6_component_validations",
            side_effect=fake_component_validation,
        ) as component_runner:
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["validation_status"], "failed")
        self.assertEqual(result["level6_validation_summary"]["status"], "failed")
        playwright_runner.assert_called_once()
        component_runner.assert_called_once()

    def test_validate_command_can_disable_component_validation_explicitly(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.inesdata.config.ts",
                "component_validation_enabled": True,
                "component_groups": ["ontology-hub"],
            },
        ), mock.patch.object(
            main,
            "run_playwright_validation",
            return_value={"status": "passed", "summary": {"total_specs": 3}},
        ) as playwright_runner, mock.patch.object(
            main,
            "run_level6_component_validations",
        ) as component_runner, mock.patch.dict(
            os.environ,
            {"LEVEL6_RUN_COMPONENT_VALIDATION": "false"},
            clear=False,
        ):
            result = main.main(
                ["fake", "validate"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["playwright"]["status"], "passed")
        self.assertEqual(result["component_results"][0]["component"], "ontology-hub")
        self.assertEqual(result["component_results"][0]["status"], "skipped")
        self.assertEqual(result["component_results"][0]["reason"], "disabled")
        self.assertEqual(result["component_validation_summary"]["skipped"], 1)
        playwright_runner.assert_called_once()
        component_runner.assert_not_called()

    def test_validate_command_still_runs_component_validation_when_playwright_fails(self):
        events = []

        def fake_playwright(*args, **kwargs):
            events.append("playwright")
            return {"status": "failed", "summary": {"total_specs": 3, "failed_specs": 1}}

        def fake_component_validation(
            components,
            *,
            infer_component_urls,
            run_component_validations_fn,
            experiment_dir,
        ):
            events.append("components")
            self.assertEqual(components, ["ontology-hub"])
            self.assertEqual(
                infer_component_urls(components),
                {"ontology-hub": "http://ontology-hub.example.local"},
            )
            self.assertIs(run_component_validations_fn, main.run_registered_component_validations)
            self.assertTrue(experiment_dir)
            return [{"component": "ontology-hub", "status": "passed"}]

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.inesdata.config.ts",
                "component_validation_enabled": True,
                "component_groups": ["ontology-hub"],
            },
        ), mock.patch.object(
            main,
            "run_playwright_validation",
            side_effect=fake_playwright,
        ) as playwright_runner, mock.patch.object(
            main,
            "run_level6_component_validations",
            side_effect=fake_component_validation,
        ) as component_runner:
            with self.assertRaises(RuntimeError) as exc:
                main.main(
                    ["fake", "validate"],
                    adapter_registry=self.registry,
                    deployer_registry=self.deployer_registry,
                    validation_engine_cls=FakeValidationEngine,
                    experiment_storage=FakeStorage,
                )

        self.assertEqual(events, ["playwright", "components"])
        self.assertIn("Playwright validation failed with status 'failed'", str(exc.exception))
        playwright_runner.assert_called_once()
        component_runner.assert_called_once()

    def test_validate_command_stops_before_components_when_playwright_fail_fast_enabled(self):
        events = []

        def fake_playwright(*args, **kwargs):
            events.append("playwright")
            return {"status": "failed", "summary": {"total_specs": 3, "failed_specs": 1}}

        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "fake",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.inesdata.config.ts",
                "component_validation_enabled": True,
                "component_groups": ["ontology-hub"],
            },
        ), mock.patch.object(
            main,
            "run_playwright_validation",
            side_effect=fake_playwright,
        ) as playwright_runner, mock.patch.object(
            main,
            "run_level6_component_validations",
        ) as component_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_LEVEL6_STOP_ON_PLAYWRIGHT_FAILURE": "1"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError) as exc:
                main.main(
                    ["fake", "validate"],
                    adapter_registry=self.registry,
                    deployer_registry=self.deployer_registry,
                    validation_engine_cls=FakeValidationEngine,
                    experiment_storage=FakeStorage,
                )

        self.assertEqual(events, ["playwright"])
        self.assertIn("Playwright validation failed with status 'failed'", str(exc.exception))
        playwright_runner.assert_called_once()
        component_runner.assert_not_called()

    def test_validate_command_fails_clearly_when_inesdata_portal_is_not_ready(self):
        with mock.patch.object(
            FakeDeployer,
            "get_validation_profile",
            return_value={
                "adapter": "inesdata",
                "newman_enabled": True,
                "playwright_enabled": True,
                "playwright_config": "validation/ui/playwright.inesdata.config.ts",
            },
        ), mock.patch.object(
            main,
            "_wait_for_inesdata_portal_readiness",
            return_value={
                "status": "failed",
                "artifact": "/tmp/portal_readiness.json",
                "gates": [
                    {
                        "service": "conn-a-interface",
                        "ready": False,
                        "detail": "demo: service has no ready endpoints",
                    }
                ],
            },
        ), mock.patch.object(main, "run_playwright_validation") as playwright_runner, mock.patch.dict(
            os.environ,
            {"PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT": "true"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError) as exc:
                main.main(
                    ["fake", "validate"],
                    adapter_registry=self.registry,
                    deployer_registry=self.deployer_registry,
                    validation_engine_cls=FakeValidationEngine,
                    experiment_storage=FakeStorage,
                )

        self.assertIn("connector interface services and public portal routes", str(exc.exception))
        self.assertIn("conn-a-interface: demo: service has no ready endpoints", str(exc.exception))
        playwright_runner.assert_not_called()

    def test_metrics_command_uses_metrics_collector(self):
        result = main.main(
            ["fake", "metrics"],
            adapter_registry=self.registry,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
            deployer_registry=self.deployer_registry,
        )

        self.assertEqual(result["connectors"], ["conn-deployer-a", "conn-deployer-b"])
        self.assertTrue(result["experiment_dir"].startswith("/tmp/cli-test-"))
        self.assertEqual(result["deployer_context"]["dataspace_name"], "fake-ds")
        self.assertEqual(result["deployer_context"]["config"]["KC_PASSWORD"], "***REDACTED***")
        self.assertEqual(result["deployer_context"]["config"]["VT_TOKEN"], "***REDACTED***")

    def test_metrics_command_can_disable_deployer_resolution_explicitly(self):
        with mock.patch.dict(os.environ, {"PIONERA_DISABLE_DEPLOYER_METRICS": "true"}, clear=False):
            result = main.main(
                ["fake", "metrics"],
                adapter_registry=self.registry,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
                deployer_registry=self.deployer_registry,
            )

        self.assertEqual(result["connectors"], ["conn-a", "conn-b"])
        self.assertIsNone(result["deployer_context"])

    def test_metrics_command_can_enable_kafka_benchmark(self):
        class FakeKafkaManager:
            def __init__(self, *args, **kwargs):
                self.last_error = None
            def ensure_kafka_running(self):
                return "localhost:9092"
            def stop_kafka(self):
                return None

        result = main.main(
            ["fake", "metrics", "--kafka"],
            adapter_registry=self.registry,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
            kafka_manager_cls=FakeKafkaManager,
            deployer_registry=self.deployer_registry,
        )

        self.assertIn("kafka_metrics", result)
        self.assertEqual(result["kafka_metrics"]["kafka_benchmark"]["status"], "completed")
        self.assertEqual(result["deployer_context"]["dataspace_name"], "fake-ds")

    def test_invalid_adapter_raises_system_exit(self):
        with self.assertRaises(SystemExit):
            main.main(["unknown"], adapter_registry=self.registry)

    def test_invalid_command_raises_system_exit(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exc:
            main.main(["fake", "unknown"], adapter_registry=self.registry)

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue().lower())

    def test_report_command_generates_summary_for_existing_experiment(self):
        dashboard_result = {
            "status": "generated",
            "path": "/tmp/experiment/framework-report/index.html",
        }

        with mock.patch.object(
            main,
            "_generate_framework_dashboard",
            return_value=dashboard_result,
        ) as dashboard_mock:
            result = main.main(
                ["report", "experiment_2026-03-10_12-00-00"],
                adapter_registry=self.registry,
                report_generator_cls=FakeReportGenerator,
            )

        self.assertEqual(result["summary"]["experiment_id"], "experiment_2026-03-10_12-00-00")
        dashboard_mock.assert_called_once()
        self.assertEqual(result["framework_report"], dashboard_result)

    def test_compare_command_dispatches_to_report_generator(self):
        result = main.main(
            ["compare", "experiment_A", "experiment_B"],
            adapter_registry=self.registry,
            report_generator_cls=FakeReportGenerator,
        )

        self.assertEqual(result["experiment_a"]["experiment_id"], "experiment_A")
        self.assertEqual(result["experiment_b"]["experiment_id"], "experiment_B")

    def test_resolve_adapter_class_fails_cleanly_for_missing_module(self):
        with self.assertRaises(ValueError) as exc:
            main.resolve_adapter_class(
                "broken",
                {"broken": "missing.module:MissingAdapter"},
            )

        self.assertIn("Failed to load adapter 'broken'", str(exc.exception))

    def test_resolve_adapter_class_fails_cleanly_for_missing_class(self):
        with self.assertRaises(ValueError) as exc:
            main.resolve_adapter_class(
                "broken",
                {"broken": "fake_adapter_module:MissingAdapter"},
            )

        self.assertIn("Failed to load adapter 'broken'", str(exc.exception))

    def test_main_raises_parser_error_for_broken_adapter_registration(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exc:
            main.main(["broken"], adapter_registry={"broken": "fake_adapter_module:MissingAdapter"})

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("Failed to load adapter 'broken'", stderr.getvalue())

    def test_resolve_connectors_raises_when_adapter_cannot_provide_any(self):
        with self.assertRaises(RuntimeError):
            main._resolve_connectors(NoConnectorsAdapter())

    def test_real_inesdata_adapter_builds_framework_collaborators(self):
        adapter = InesdataAdapter(
            run=lambda *args, **kwargs: None,
            run_silent=lambda *args, **kwargs: "",
            auto_mode_getter=lambda: True,
        )

        validation_engine = main.build_validation_engine(adapter)
        metrics_collector = main.build_metrics_collector(adapter)

        self.assertIs(validation_engine.load_connector_credentials.__self__, adapter.connectors)
        self.assertIs(validation_engine.load_connector_credentials.__func__, adapter.connectors.load_connector_credentials.__func__)
        self.assertIs(validation_engine.load_deployer_config.__self__, adapter.config_adapter)
        self.assertIs(validation_engine.load_deployer_config.__func__, adapter.config_adapter.load_deployer_config.__func__)
        self.assertIs(validation_engine.protocol_address_resolver.__self__, adapter.connectors)
        self.assertIs(
            validation_engine.protocol_address_resolver.__func__,
            adapter.connectors.build_protocol_address.__func__,
        )
        self.assertIs(validation_engine.cleanup_test_entities.__self__, adapter.connectors)
        self.assertIs(validation_engine.cleanup_test_entities.__func__, adapter.connectors.cleanup_test_entities.__func__)
        self.assertIs(metrics_collector.build_connector_url.__self__, adapter.connectors)
        self.assertIs(metrics_collector.build_connector_url.__func__, adapter.connectors.build_connector_url.__func__)
        self.assertIs(metrics_collector.is_kafka_available.__self__, adapter)
        self.assertIs(metrics_collector.is_kafka_available.__func__, adapter.is_kafka_available.__func__)
        self.assertIs(metrics_collector.ensure_kafka_topic.__self__, adapter)
        self.assertIs(metrics_collector.ensure_kafka_topic.__func__, adapter.ensure_kafka_topic.__func__)
        self.assertTrue(metrics_collector.auto_mode())

    def test_build_kafka_edc_validation_suite_wires_protocol_resolver(self):
        adapter = InesdataAdapter(
            run=lambda *args, **kwargs: None,
            run_silent=lambda *args, **kwargs: "",
            auto_mode_getter=lambda: True,
        )

        suite = main.build_kafka_edc_validation_suite(adapter)

        self.assertIs(suite.protocol_address_resolver.__self__, adapter.connectors)
        self.assertIs(
            suite.protocol_address_resolver.__func__,
            adapter.connectors.build_protocol_address.__func__,
        )

    def test_build_kafka_edc_validation_suite_uses_deployer_context_public_keycloak_url(self):
        adapter = FakeAdapter()
        context = DeploymentContext(
            deployer="inesdata",
            topology="vm-single",
            environment="DEV",
            dataspace_name="pionera",
            ds_domain_base="pionera.oeg.fi.upm.es",
            connectors=["conn-org2-pionera", "conn-org3-pionera"],
            config={
                "TOPOLOGY": "vm-single",
                "DS_1_NAME": "pionera",
                "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
            },
        )

        suite = main.build_kafka_edc_validation_suite(adapter, deployer_context=context)

        self.assertEqual(
            suite.keycloak_url_resolver(),
            "https://org4.pionera.oeg.fi.upm.es/auth",
        )
        self.assertEqual(
            suite.load_deployer_config()["KEYCLOAK_FRONTEND_URL"],
            "https://org4.pionera.oeg.fi.upm.es/auth",
        )

    def test_build_adapter_passes_dry_run_when_supported(self):
        registry = {"fake": "fake_adapter_module:DryRunAwareAdapter"}
        adapter = main.build_adapter("fake", adapter_registry=registry, dry_run=True)

        self.assertIsInstance(adapter, DryRunAwareAdapter)
        self.assertTrue(adapter.dry_run)

    def test_run_command_dry_run_returns_preview_without_executing_runner(self):
        result = main.main(
            ["fake", "run", "--dry-run"],
            runner_cls=FakeRunner,
            adapter_registry=self.registry,
            validation_engine_cls=FakeValidationEngine,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["command"], "run")
        self.assertIn("deploy_connectors", result["actions"])
        self.assertEqual(result["runner"], "ExperimentRunner")

    def test_run_command_dry_run_includes_iterations(self):
        result = main.main(
            ["fake", "run", "--dry-run", "--iterations", "5"],
            runner_cls=FakeRunner,
            adapter_registry=self.registry,
            validation_engine_cls=FakeValidationEngine,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["iterations"], 5)

    def test_metrics_command_dry_run_reports_kafka_capability(self):
        result = main.main(
            ["fake", "metrics", "--dry-run", "--kafka"],
            adapter_registry=self.registry,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertTrue(result["kafka_enabled"])

    def test_deploy_command_dry_run_includes_adapter_preflight_when_available(self):
        result = main.main(
            ["preview", "deploy", "--dry-run", "--topology", "local"],
            adapter_registry={"preview": "fake_adapter_module:PreviewAwareAdapter"},
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertIn("preflight", result)
        self.assertEqual(result["preflight"]["status"], "ready")
        self.assertEqual(result["preflight"]["topology"], "local")

    def test_deploy_command_dry_run_applies_topology_kubeconfig_to_adapter_preflight(self):
        with mock.patch.object(
            main,
            "_topology_runtime_environment_overrides",
            return_value={
                "KUBECONFIG": "/clusters/common.yaml",
                "PIONERA_KUBECONFIG_ROLE": "common",
            },
        ), mock.patch.dict(os.environ, {}, clear=True):
            result = main.build_dry_run_preview(
                adapter_name="preview",
                command="deploy",
                adapter_registry={"preview": "fake_adapter_module:EnvironmentPreviewAdapter"},
                experiment_storage=FakeStorage,
                topology="vm-distributed",
                include_deployer_dry_run=False,
            )
            restored_kubeconfig = os.environ.get("KUBECONFIG")

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["preflight"]["kubeconfig"], "/clusters/common.yaml")
        self.assertEqual(result["preflight"]["kubeconfig_role"], "common")
        self.assertIsNone(restored_kubeconfig)

    def test_deploy_command_dry_run_can_include_deployer_orchestrator_preview_opt_in(self):
        with mock.patch.dict(os.environ, {"PIONERA_ENABLE_DEPLOYER_DRY_RUN": "true"}, clear=False):
            result = main.main(
                ["fake", "deploy", "--dry-run", "--topology", "local"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "dry-run")
        self.assertIn("deployer_orchestrator", result)
        self.assertEqual(result["deployer_orchestrator"]["status"], "available")
        self.assertEqual(result["deployer_orchestrator"]["deployer"], "fake")
        self.assertEqual(result["deployer_orchestrator"]["namespace_profile"], "compact")
        self.assertEqual(result["deployer_orchestrator"]["namespace_plan_summary"]["status"], "active")
        self.assertEqual(result["deployer_orchestrator"]["context"]["dataspace_name"], "fake-ds")
        self.assertEqual(
            result["deployer_orchestrator"]["planned_namespace_roles"]["registration_service_namespace"],
            "fake-ds",
        )
        self.assertIn("deploy_components", result["deployer_orchestrator"]["actions"])
        self.assertEqual(
            result["deployer_orchestrator"]["context"]["config"]["KC_PASSWORD"],
            "***REDACTED***",
        )
        self.assertEqual(
            result["deployer_orchestrator"]["context"]["config"]["MINIO_ADMIN_PASS"],
            "***REDACTED***",
        )
        self.assertEqual(
            result["deployer_orchestrator"]["context"]["config"]["VT_TOKEN"],
            "***REDACTED***",
        )
        self.assertEqual(
            result["deployer_orchestrator"]["context"]["config"]["DS_1_NAME"],
            "fake-ds",
        )

    def test_hosts_command_dry_run_includes_hosts_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            infrastructure_dir = os.path.join(tmpdir, "deployers", "infrastructure")
            os.makedirs(infrastructure_dir, exist_ok=True)
            config_path = os.path.join(infrastructure_dir, "deployer.config")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("PG_HOST=localhost\n")

            with mock.patch.object(main, "_infrastructure_deployer_config_path", return_value=config_path):
                result = main.main(
                    ["fake", "hosts", "--dry-run", "--topology", "local"],
                    adapter_registry=self.registry,
                    deployer_registry=self.deployer_registry,
                    experiment_storage=FakeStorage,
                )

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["command"], "hosts")
        self.assertIn("plan_hosts_entries", result["actions"])
        self.assertEqual(result["config_migration_warnings"][0]["key"], "PG_HOST")
        self.assertTrue(
            result["config_migration_warnings"][0]["recommended_overlay_paths"][0].endswith(
                "deployers/infrastructure/topologies/local.config"
            )
        )
        self.assertEqual(result["namespace_profile"], "compact")
        self.assertEqual(result["hosts_plan"]["namespace_profile"], "compact")
        self.assertEqual(result["hosts_plan"]["namespace_plan_summary"]["status"], "active")
        self.assertEqual(result["hosts_plan"]["level_3"], ["registration-service-fake-ds.example.local"])
        self.assertEqual(
            result["hosts_plan"]["planned_namespace_roles"]["registration_service_namespace"],
            "fake-ds",
        )

    def test_local_repair_command_dry_run_includes_doctor_and_hosts_plan(self):
        doctor_report = {
            "status": "ready",
            "checks": [
                {"name": "kubectl", "status": "ok"},
                {"name": "minikube", "status": "ok"},
                {"name": "hosts file", "status": "ok"},
                {"name": "minikube tunnel", "status": "ok"},
            ],
        }

        with mock.patch.object(
            main.local_menu_tools,
            "collect_framework_doctor_report",
            return_value=doctor_report,
        ):
            result = main.main(
                ["fake", "local-repair", "--dry-run"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["command"], "local-repair")
        self.assertIn("doctor", result)
        self.assertIn("hosts_plan", result)
        self.assertIn("missing_hostnames", result)
        self.assertIn("verify_public_ingress_endpoints", result["actions"])
        self.assertEqual(result["public_endpoint_preflight"]["status"], "planned")

    def test_local_repair_command_dispatches_to_run_local_repair(self):
        with mock.patch.object(
            main,
            "run_local_repair",
            return_value={"status": "completed", "scope": "local repair"},
        ) as local_repair:
            result = main.main(
                ["fake", "local-repair"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "completed")
        local_repair.assert_called_once()
        self.assertTrue(local_repair.call_args.kwargs["apply_hosts"])
        self.assertFalse(local_repair.call_args.kwargs["recover_connectors"])

    def test_recreate_dataspace_dry_run_includes_protected_plan(self):
        result = main.main(
            ["fake", "recreate-dataspace", "--dry-run", "--topology", "local"],
            adapter_registry=self.registry,
            deployer_registry=self.deployer_registry,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["command"], "recreate-dataspace")
        self.assertIn("require_exact_dataspace_confirmation", result["actions"])
        self.assertIn("skip_level_4_connectors", result["actions"])
        self.assertFalse(result["with_connectors"])
        self.assertEqual(result["recreate_dataspace_plan"]["dataspace"], "fake-ds")
        self.assertTrue(result["recreate_dataspace_plan"]["preserves_shared_services"])

    def test_recreate_dataspace_dry_run_can_include_connectors(self):
        result = main.main(
            ["fake", "recreate-dataspace", "--dry-run", "--topology", "local", "--with-connectors"],
            adapter_registry=self.registry,
            deployer_registry=self.deployer_registry,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "dry-run")
        self.assertTrue(result["with_connectors"])
        self.assertIn("run_level_4_connectors", result["actions"])

    def test_recreate_dataspace_command_requires_exact_confirmation(self):
        with self.assertRaises(RuntimeError) as exc:
            main.main(
                ["fake", "recreate-dataspace", "--topology", "local"],
                adapter_registry=self.registry,
                deployer_registry=self.deployer_registry,
                experiment_storage=FakeStorage,
            )

        self.assertIn("--confirm-dataspace fake-ds", str(exc.exception))

    def test_recreate_dataspace_command_dispatches_to_adapter_when_confirmed(self):
        result = main.main(
            [
                "fake",
                "recreate-dataspace",
                "--topology",
                "local",
                "--confirm-dataspace",
                "fake-ds",
            ],
            adapter_registry=self.registry,
            deployer_registry=self.deployer_registry,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["dataspace"], "fake-ds")
        self.assertEqual(result["result"]["status"], "recreated")
        self.assertFalse(result["with_connectors"])
        self.assertIsNone(result["connectors"])
        self.assertIn("Run Level 4 again", result["next_step"])

    def test_recreate_dataspace_command_can_recreate_connectors_when_requested(self):
        result = main.main(
            [
                "fake",
                "recreate-dataspace",
                "--topology",
                "local",
                "--confirm-dataspace",
                "fake-ds",
                "--with-connectors",
            ],
            adapter_registry=self.registry,
            deployer_registry=self.deployer_registry,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["with_connectors"])
        self.assertEqual(result["connectors"]["level"], 4)
        self.assertEqual(result["connectors"]["name"], "Deploy Connectors")
        self.assertIn("Run Level 6", result["next_step"])

    def test_default_command_passes_iterations_to_runner(self):
        class IterationAwareRunner:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def run(self):
                return {"iterations": self.kwargs["iterations"]}

        result = main.main(
            ["fake", "--iterations", "3"],
            runner_cls=IterationAwareRunner,
            adapter_registry=self.registry,
            validation_engine_cls=FakeValidationEngine,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
        )

        self.assertEqual(result["iterations"], 3)

    def test_run_command_passes_baseline_flag_to_runner(self):
        class BaselineAwareRunner:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def run(self):
                return {"baseline": self.kwargs["baseline"]}

        result = main.main(
            ["fake", "run", "--baseline"],
            runner_cls=BaselineAwareRunner,
            adapter_registry=self.registry,
            validation_engine_cls=FakeValidationEngine,
            metrics_collector_cls=FakeMetricsCollector,
            experiment_storage=FakeStorage,
        )

        self.assertTrue(result["baseline"])

    def test_level6_validation_summary_deduplicates_failed_component_cases(self):
        failed_case = {
            "test_case_id": "OH-APP-11",
            "description": "add a new ontology version",
            "evaluation": {"status": "failed", "assertions": ["502 Bad Gateway"]},
            "response": {"message": "502 Bad Gateway"},
        }
        component_results = [
            {
                "component": "ontology-hub",
                "status": "failed",
                "phase_order": ["functional"],
                "phases": {
                    "functional": {
                        "display_name": "Ontology Hub functional",
                        "executed_cases": [failed_case],
                        "suites": {
                            "playwright": {
                                "executed_cases": [failed_case],
                            }
                        },
                    }
                },
            }
        ]

        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False), contextlib.redirect_stdout(buffer):
            main._print_level6_validation_summary(
                experiment_dir="/tmp/experiment_2026-05-25_14-24-03",
                component_results=component_results,
            )

        self.assertEqual(buffer.getvalue().count("OH-APP-11"), 1)

    def test_offer_open_level6_dashboard_opens_report_when_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_path = os.path.join(tmp, "framework-report", "index.html")
            os.makedirs(os.path.dirname(dashboard_path), exist_ok=True)
            with open(dashboard_path, "w", encoding="utf-8") as handle:
                handle.write("<html></html>")

            with mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch.object(
                main,
                "_interactive_confirm",
                return_value=True,
            ) as confirm_mock, mock.patch.object(
                main,
                "launch_static_report_server",
                return_value={"url": "http://127.0.0.1:34567", "ready": True},
            ) as server_mock, mock.patch.object(
                main,
                "open_local_url",
                return_value={"opened": True, "method": "test-browser"},
            ) as open_mock:
                main._offer_open_level6_dashboard({"path": dashboard_path})

        confirm_mock.assert_called_once_with("Open Level 6 dashboard report now?", default=False)
        server_mock.assert_called_once_with(tmp)
        open_mock.assert_called_once_with("http://127.0.0.1:34567/framework-report/index.html")

    def test_offer_open_level6_dashboard_uses_wsl_file_url_fallback_when_browser_open_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_path = os.path.join(tmp, "framework-report", "index.html")
            os.makedirs(os.path.dirname(dashboard_path), exist_ok=True)
            with open(dashboard_path, "w", encoding="utf-8") as handle:
                handle.write("<html></html>")

            with mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch.object(
                main,
                "_interactive_confirm",
                return_value=True,
            ), mock.patch.object(
                main,
                "launch_static_report_server",
                return_value={"url": "http://127.0.0.1:34567", "ready": True},
            ), mock.patch.object(
                main,
                "wsl_file_url_for_path",
                return_value="file://wsl.localhost/Ubuntu/tmp/framework-report/index.html",
            ), mock.patch.object(
                main,
                "open_local_url",
                side_effect=[
                    {"opened": False, "reason": "Desktop opener failed."},
                    {"opened": True, "method": "windows-cmd-start"},
                ],
            ) as open_mock:
                main._offer_open_level6_dashboard({"path": dashboard_path})

        self.assertEqual(
            [call.args[0] for call in open_mock.call_args_list],
            [
                "http://127.0.0.1:34567/framework-report/index.html",
                "file://wsl.localhost/Ubuntu/tmp/framework-report/index.html",
            ],
        )

    def test_offer_open_level6_dashboard_skips_non_interactive_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_path = os.path.join(tmp, "framework-report", "index.html")
            os.makedirs(os.path.dirname(dashboard_path), exist_ok=True)
            with open(dashboard_path, "w", encoding="utf-8") as handle:
                handle.write("<html></html>")

            with mock.patch.object(sys.stdin, "isatty", return_value=False), mock.patch.object(
                main,
                "_interactive_confirm",
            ) as confirm_mock, mock.patch.object(
                main,
                "launch_static_report_server",
            ) as server_mock:
                main._offer_open_level6_dashboard({"path": dashboard_path})

        confirm_mock.assert_not_called()
        server_mock.assert_not_called()
