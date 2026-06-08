import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import requests
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.edc.adapter import EdcAdapter
from adapters.edc.connectors import EDCConnectorsAdapter
from adapters.edc.deployment import EDCDeploymentAdapter, EdcSharedDataspaceConfig
from adapters.shared.config import resolve_shared_level3_bootstrap_runtime
from adapters.shared.components import SharedComponentsAdapter
from adapters.shared.infrastructure import SharedFoundationInfrastructureAdapter
from adapters.inesdata.adapter import InesdataAdapter


class SharedInfrastructureStub:
    def __init__(self, *, dataspace_ready=True, registration_pod="demo-registration-service-0", schema_ready=True):
        self.announced = []
        self.completed = []
        self.deploy_calls = 0
        self.dataspace_ready = dataspace_ready
        self.registration_pod = registration_pod
        self.schema_ready = schema_ready

    def verify_common_services_ready_for_level3(self):
        return True, []

    def verify_dataspace_ready_for_level4(self):
        return self.dataspace_ready, []

    def get_pod_by_name(self, namespace, partial_name):
        del namespace
        if partial_name == "registration-service":
            return self.registration_pod
        return None

    def wait_for_registration_service_schema(self, timeout=1, poll_interval=1, quiet=True):
        del timeout, poll_interval, quiet
        return self.schema_ready

    def announce_level(self, level, label):
        self.announced.append((level, label))

    def complete_level(self, level):
        self.completed.append(level)

    def deploy_infrastructure(self):
        self.deploy_calls += 1
        return "deploy-called"

    @staticmethod
    def _is_ignored_transient_hook_pod(namespace, pod_name):
        del namespace
        return "minio-post-job" in pod_name


class DeploymentDelegateStub:
    def __init__(self):
        self.deploy_calls = 0
        self.recreate_calls = []
        self.connectors_adapter = None

    def deploy_dataspace(self):
        self.deploy_calls += 1
        return "dataspace-deploy-called"

    def build_recreate_dataspace_plan(self):
        return {"dataspace": "demoedc", "adapter": "edc"}

    def recreate_dataspace(self, confirm_dataspace=None):
        self.recreate_calls.append(confirm_dataspace)
        return "dataspace-recreate-called"


class EdcConnectorConfig:
    MINIKUBE_IP = "192.168.49.2"
    EDC_MANAGED_LABEL = "edc"
    NS_COMMON = "common-srvs"

    @staticmethod
    def script_dir():
        return "/tmp/validation-environment"

    @staticmethod
    def repo_dir():
        return "/tmp/deployers/inesdata"

    @staticmethod
    def connector_credentials_path(connector_name):
        return os.path.join("/tmp", "default", f"credentials-connector-{connector_name}.json")

    @staticmethod
    def host_alias_domains():
        return [
            "keycloak.dev.ed.dataspaceunit.upm",
            "minio.dev.ed.dataspaceunit.upm",
        ]


class EdcConnectorConfigAdapter:
    def __init__(self, root):
        self.root = root

    @staticmethod
    def load_deployer_config():
        return {
            "ENVIRONMENT": "DEV",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            "KEYCLOAK_HOSTNAME": "keycloak.dev.ed.dataspaceunit.upm",
            "MINIO_HOSTNAME": "minio.dev.ed.dataspaceunit.upm",
            "DATABASE_HOSTNAME": "postgresql.demo.svc.cluster.local",
            "VAULT_URL": "http://vault.common:8200",
        }

    @staticmethod
    def ds_domain_base():
        return "dev.ds.dataspaceunit.upm"

    @staticmethod
    def edc_connector_image_name():
        return "ghcr.io/proyectopionera/edc-connector"

    @staticmethod
    def edc_connector_image_tag():
        return "latest"

    @staticmethod
    def edc_connector_image_pull_policy():
        return "IfNotPresent"

    @staticmethod
    def edc_dashboard_enabled():
        return False

    @staticmethod
    def edc_sql_schema_autocreate():
        return True

    @staticmethod
    def edc_inference_edr_attempts():
        return 40

    @staticmethod
    def edc_inference_edr_delay_ms():
        return 1000

    @staticmethod
    def edc_dashboard_base_href():
        return "/edc-dashboard/"

    @staticmethod
    def edc_dashboard_image_name():
        return "validation-environment/edc-dashboard"

    @staticmethod
    def edc_dashboard_image_tag():
        return "latest"

    @staticmethod
    def edc_dashboard_image_pull_policy():
        return "IfNotPresent"

    @staticmethod
    def edc_dashboard_proxy_image_name():
        return "validation-environment/edc-dashboard-proxy"

    @staticmethod
    def edc_dashboard_proxy_image_tag():
        return "latest"

    @staticmethod
    def edc_dashboard_proxy_image_pull_policy():
        return "IfNotPresent"

    @staticmethod
    def edc_dashboard_proxy_auth_mode():
        return "service-account"

    @staticmethod
    def edc_dashboard_proxy_client_id():
        return "dataspace-users"

    @staticmethod
    def edc_dashboard_proxy_scope():
        return "openid profile email"

    @staticmethod
    def edc_dashboard_proxy_cookie_name():
        return "edc_dashboard_session"

    @staticmethod
    def deployment_environment_name():
        return "DEV"

    def edc_dataspace_runtime_dir(self, ds_name=None):
        return os.path.join(self.root, ds_name or "default")

    def edc_connector_values_file(self, connector_name, ds_name=None):
        return os.path.join(self.edc_dataspace_runtime_dir(ds_name=ds_name), f"values-{connector_name}.yaml")

    def edc_connector_certs_dir(self, ds_name=None):
        return os.path.join(self.edc_dataspace_runtime_dir(ds_name=ds_name), "certs")

    def edc_connector_credentials_path(self, connector_name, ds_name=None, for_write=False):
        del for_write
        return os.path.join(
            self.edc_dataspace_runtime_dir(ds_name=ds_name),
            f"credentials-connector-{connector_name}.json",
        )

    def edc_dashboard_runtime_dir(self, connector_name, ds_name=None):
        return os.path.join(self.edc_dataspace_runtime_dir(ds_name=ds_name), "dashboard", connector_name)

    def edc_dashboard_app_config_file(self, connector_name, ds_name=None):
        return os.path.join(self.edc_dashboard_runtime_dir(connector_name, ds_name=ds_name), "app-config.json")

    def edc_dashboard_connector_config_file(self, connector_name, ds_name=None):
        return os.path.join(
            self.edc_dashboard_runtime_dir(connector_name, ds_name=ds_name),
            "edc-connector-config.json",
        )

    def edc_dashboard_base_href_file(self, connector_name, ds_name=None):
        return os.path.join(self.edc_dashboard_runtime_dir(connector_name, ds_name=ds_name), "APP_BASE_HREF.txt")

    def edc_connector_policy_file(self, connector_name, ds_name=None):
        dataspace = ds_name or "default"
        return os.path.join(self.edc_dataspace_runtime_dir(ds_name=dataspace), f"policy-{dataspace}-{connector_name}.json")

    def connector_minio_policy_path(self, connector_name, ds_name=None, for_write=False):
        del for_write
        return self.edc_connector_policy_file(connector_name, ds_name=ds_name)

    @staticmethod
    def edc_reference_repo_url():
        return "https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"

    @staticmethod
    def edc_reference_repo_subdir():
        return "asset-filter-template"

    def edc_connector_source_dir(self):
        return os.path.join(self.root, "source")

    def edc_connector_dir(self):
        return self.root

    @staticmethod
    def generate_connector_hosts(connectors):
        return [f"127.0.0.1 {connector}.dev.ds.dataspaceunit.upm" for connector in connectors]


class EdcAdapterTests(unittest.TestCase):
    def test_inesdata_adapter_uses_shared_foundation_infrastructure_adapter(self):
        adapter = InesdataAdapter(dry_run=True)
        self.assertIsInstance(adapter.infrastructure, SharedFoundationInfrastructureAdapter)

    def test_inesdata_adapter_propagates_topology_to_config_adapter(self):
        adapter = InesdataAdapter(dry_run=True, topology="vm-single")
        self.assertEqual(adapter.topology, "vm-single")
        self.assertEqual(adapter.config_adapter.topology, "vm-single")
        self.assertFalse(adapter.connectors._is_local_topology())

    def test_inesdata_adapter_uses_shared_components_adapter(self):
        adapter = InesdataAdapter(dry_run=True)
        self.assertIsInstance(adapter.components, SharedComponentsAdapter)

    def test_edc_adapter_uses_shared_foundation_infrastructure_adapter(self):
        adapter = EdcAdapter(dry_run=True)
        self.assertIsInstance(adapter.infrastructure, SharedFoundationInfrastructureAdapter)

    def test_edc_adapter_uses_shared_components_adapter(self):
        adapter = EdcAdapter(dry_run=True)
        self.assertIsInstance(adapter.components, SharedComponentsAdapter)

    def test_edc_adapter_advertises_kafka_transfer_capability(self):
        adapter = EdcAdapter(dry_run=True)
        self.assertTrue(adapter.supports_kafka_transfer_validation())

    def test_edc_connector_runtime_includes_s3_and_kafka_data_planes(self):
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        build_file = os.path.join(
            root_dir,
            "adapters",
            "edc",
            "sources",
            "connector",
            "final-connector",
            "build.gradle.kts",
        )

        with open(build_file, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn("implementation(libs.edc.data.plane.aws.s3)", content)
        self.assertIn("implementation(libs.edc.data.plane.kafka)", content)
        self.assertIn("implementation(libs.edc.vault.hashicorp)", content)


class EdcConnectorTopologyTests(unittest.TestCase):
    def test_edc_host_aliases_use_vm_single_topology_address(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter.config = type("Config", (), {"MINIKUBE_IP": "192.168.49.2"})
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-single",
                "ds_domain_base": staticmethod(lambda: "dev.ds.dataspaceunit.upm"),
                "load_deployer_config": staticmethod(lambda: {"VM_EXTERNAL_IP": "192.168.49.2"}),
            },
        )()
        adapter.run_silent = mock.Mock(return_value="192.168.49.2")
        adapter._host_alias_domains_for_dataspace = mock.Mock(return_value=["keycloak.dev.ds.dataspaceunit.upm"])

        aliases = adapter._host_aliases(["conn-a-demo"], ds_name="demo", connector_name="conn-a-demo")

        self.assertEqual(
            aliases,
            [
                {
                    "ip": "192.168.49.2",
                    "hostnames": [
                        "keycloak.dev.ds.dataspaceunit.upm",
                        "conn-a-demo.dev.ds.dataspaceunit.upm",
                    ],
                }
            ],
        )
        adapter.run_silent.assert_not_called()

    def test_edc_level4_local_images_prepare_build_in_vm_single_topology(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter.config_adapter = type("ConfigAdapter", (), {"topology": "vm-single"})()

        with (
            mock.patch.object(adapter, "_level4_edc_local_images_mode", return_value="auto"),
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_connector_image") as connector_mock,
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_dashboard_images") as dashboard_mock,
        ):
            self.assertTrue(adapter._maybe_prepare_level4_local_edc_images())

        connector_mock.assert_called_once_with("required", env_prefix="")
        dashboard_mock.assert_called_once_with("auto", env_prefix="")

    def test_edc_level4_local_images_can_be_disabled_explicitly_in_vm_single(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-single",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "EDC_CONNECTOR_IMAGE_NAME": "registry.example/edc",
                        "EDC_CONNECTOR_IMAGE_TAG": "stable",
                    }
                ),
            },
        )()

        with (
            mock.patch.object(adapter, "_level4_edc_local_images_mode", return_value="disabled"),
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_connector_image") as connector_mock,
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_dashboard_images") as dashboard_mock,
        ):
            self.assertTrue(adapter._maybe_prepare_level4_local_edc_images())

        connector_mock.assert_not_called()
        dashboard_mock.assert_not_called()

    def test_edc_local_connector_image_required_ignores_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, "adapters", "edc", "scripts", "build_image.sh")
            os.makedirs(os.path.dirname(script_path), exist_ok=True)
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\n")

            source_dir = os.path.join(tmpdir, "adapters", "edc", "sources", "connector")
            calls = []
            adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
            adapter.config = type("Config", (), {"script_dir": staticmethod(lambda: tmpdir)})()
            adapter.config_adapter = type(
                "ConfigAdapter",
                (),
                {
                    "load_deployer_config": staticmethod(
                        lambda: {
                            "EDC_CONNECTOR_IMAGE_NAME": "registry.example/edc",
                            "EDC_CONNECTOR_IMAGE_TAG": "stable",
                        }
                    ),
                    "edc_connector_source_dir": staticmethod(lambda: source_dir),
                },
            )()
            adapter._run_level4_edc_image_script = lambda script, args=None, **_kwargs: (
                calls.append((script, args)) or True
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertTrue(adapter._maybe_prepare_level4_local_edc_connector_image("required"))
                self.assertEqual(
                    os.environ.get("PIONERA_EDC_CONNECTOR_IMAGE_NAME"),
                    "validation-environment/edc-connector",
                )
                self.assertEqual(os.environ.get("PIONERA_EDC_CONNECTOR_IMAGE_TAG"), "local")

        self.assertEqual(calls[0][0], script_path)
        self.assertIn("--source-dir", calls[0][1])
        self.assertIn(source_dir, calls[0][1])

    def test_edc_vm_distributed_imports_local_connector_image_for_each_remote_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, "adapters", "edc", "scripts", "build_image.sh")
            os.makedirs(os.path.dirname(script_path), exist_ok=True)
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\n")

            source_dir = os.path.join(tmpdir, "adapters", "edc", "sources", "connector")
            calls = []
            adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
            adapter.config = type("Config", (), {"script_dir": staticmethod(lambda: tmpdir)})()
            adapter.config_adapter = type(
                "ConfigAdapter",
                (),
                {
                    "load_deployer_config": staticmethod(lambda: {}),
                    "edc_connector_source_dir": staticmethod(lambda: source_dir),
                    "edc_reference_repo_url": staticmethod(lambda: "https://example.test/edc.git"),
                    "edc_reference_repo_subdir": staticmethod(lambda: "asset-filter-template"),
                },
            )()
            adapter._cluster_runtime = lambda: {"cluster_type": "k3s"}
            adapter._export_ontology_validator_patch_env_for_edc_build = lambda: None
            adapter._run_level4_edc_image_script = lambda script, args=None, env_prefix="": (
                calls.append((script, args, env_prefix)) or True
            )

            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertTrue(
                    adapter._maybe_prepare_level4_local_edc_connector_image(
                        "auto",
                        env_prefix="K3S_REMOTE_IMPORT_HOST=pionera20",
                    )
                )
                self.assertTrue(
                    adapter._maybe_prepare_level4_local_edc_connector_image(
                        "auto",
                        env_prefix="K3S_REMOTE_IMPORT_HOST=pionera3",
                    )
                )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2], "K3S_REMOTE_IMPORT_HOST=pionera20")
        self.assertEqual(calls[1][2], "K3S_REMOTE_IMPORT_HOST=pionera3")

    def test_edc_vm_distributed_keeps_external_connector_image_override_without_import(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.config_adapter = type("ConfigAdapter", (), {"load_deployer_config": staticmethod(lambda: {})})()
        adapter._run_level4_edc_image_script = mock.Mock(side_effect=AssertionError("should not build"))

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_EDC_CONNECTOR_IMAGE_NAME": "registry.example/edc-connector",
                "PIONERA_EDC_CONNECTOR_IMAGE_TAG": "stable",
            },
            clear=True,
        ):
            self.assertTrue(
                adapter._maybe_prepare_level4_local_edc_connector_image(
                    "auto",
                    env_prefix="K3S_REMOTE_IMPORT_HOST=pionera20",
                )
            )

        adapter._run_level4_edc_image_script.assert_not_called()

    def test_edc_level4_vm_single_passes_remote_import_env_to_image_scripts(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-single",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "CLUSTER_TYPE": "k3s",
                        "VM_EXTERNAL_IP": "192.168.122.52",
                        "VM_SINGLE_SSH_HOST": "192.168.122.52",
                        "VM_SINGLE_SSH_USER": "pionera",
                        "VM_SINGLE_SSH_PORT": "22",
                        "SSH_ACCESS_MODE": "bastion",
                        "SSH_BASTION_HOST": "orion.example.test",
                        "SSH_BASTION_USER": "pionera",
                        "SSH_BASTION_PORT": "2222",
                        "SSH_IDENTITY_FILE": "/home/operator/.ssh/vm-single",
                        "VM_SINGLE_REMOTE_IMAGE_IMPORT": "auto",
                        "VM_SINGLE_REMOTE_IMAGE_IMPORT_INTERACTIVE": "auto",
                        "LEVEL4_EDC_LOCAL_IMAGES_MODE": "auto",
                    }
                ),
            },
        )()
        adapter.infrastructure = mock.Mock()

        with (
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_connector_image", return_value=True) as connector_mock,
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_dashboard_images", return_value=True) as dashboard_mock,
        ):
            self.assertTrue(adapter._maybe_prepare_level4_local_edc_images())

        connector_call = connector_mock.call_args
        dashboard_call = dashboard_mock.call_args
        self.assertEqual(connector_call.args, ("required",))
        self.assertEqual(dashboard_call.args, ("auto",))
        self.assertIn("K3S_REMOTE_IMPORT_HOST=192.168.122.52", connector_call.kwargs["env_prefix"])
        self.assertIn("K3S_REMOTE_IMPORT_USER=pionera", connector_call.kwargs["env_prefix"])
        self.assertIn("K3S_REMOTE_IMPORT_BASTION_HOST=orion.example.test", connector_call.kwargs["env_prefix"])
        self.assertIn("K3S_REMOTE_IMPORT_INTERACTIVE=auto", connector_call.kwargs["env_prefix"])
        self.assertEqual(dashboard_call.kwargs["env_prefix"], connector_call.kwargs["env_prefix"])

    def test_edc_level4_vm_distributed_passes_remote_import_env_for_each_connector_role(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-distributed"
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-distributed",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
                        "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE": "auto",
                        "SSH_ACCESS_MODE": "bastion",
                        "SSH_BASTION_HOST": "orion.example.test",
                        "SSH_BASTION_USER": "jump",
                        "SSH_BASTION_PORT": "2222",
                        "VM_PROVIDER_SSH_HOST": "pionera20",
                        "VM_PROVIDER_SSH_USER": "pionera",
                        "VM_PROVIDER_SSH_PORT": "22",
                        "VM_CONSUMER_SSH_HOST": "pionera3",
                        "VM_CONSUMER_SSH_USER": "pionera",
                        "VM_CONSUMER_SSH_PORT": "22",
                        "LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES": "true",
                        "LEVEL4_EDC_LOCAL_IMAGES_MODE": "auto",
                    }
                ),
            },
        )()
        adapter.infrastructure = mock.Mock()
        adapter.load_dataspace_connectors = lambda: [
            {
                "name": "pionera-edc",
                "namespace": "edc-control",
                "connectors": ["conn-citycounciledc-pionera-edc", "conn-companyedc-pionera-edc"],
                "namespace_profile": "role-aligned",
                "namespace_roles": {
                    "provider_namespace": "edc-provider",
                    "consumer_namespace": "edc-consumer",
                },
                "planned_namespace_roles": {
                    "provider_namespace": "edc-provider",
                    "consumer_namespace": "edc-consumer",
                },
                "connector_details": [
                    {
                        "name": "conn-citycounciledc-pionera-edc",
                        "planned_namespace": "edc-provider",
                        "namespace_role": "provider",
                    },
                    {
                        "name": "conn-companyedc-pionera-edc",
                        "planned_namespace": "edc-consumer",
                        "namespace_role": "consumer",
                    },
                ],
            }
        ]

        with (
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_connector_image", return_value=True) as connector_mock,
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_dashboard_images", return_value=True) as dashboard_mock,
        ):
            self.assertTrue(adapter._maybe_prepare_level4_local_edc_images())

        env_prefixes = [call.kwargs["env_prefix"] for call in connector_mock.call_args_list]
        self.assertEqual(len(env_prefixes), 2)
        self.assertTrue(any("K3S_REMOTE_IMPORT_HOST=pionera20" in prefix for prefix in env_prefixes))
        self.assertTrue(any("K3S_REMOTE_IMPORT_HOST=pionera3" in prefix for prefix in env_prefixes))
        self.assertEqual(
            [call.kwargs["env_prefix"] for call in dashboard_mock.call_args_list],
            env_prefixes,
        )

    def test_edc_rollout_failure_diagnostics_reports_image_pull_root_cause(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)

        def fake_run_silent(command):
            if "kubectl get deployment conn-demo -n demo -o json" in command:
                return json.dumps(
                    {
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {
                                            "name": "conn-demo",
                                            "image": "validation-environment/edc-connector:local",
                                            "imagePullPolicy": "IfNotPresent",
                                        }
                                    ]
                                }
                            }
                        }
                    }
                )
            if "kubectl get pods -n demo -l service=conn-demo -o json" in command:
                return json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {"name": "conn-demo-5fd48"},
                                "status": {
                                    "phase": "Pending",
                                    "containerStatuses": [
                                        {
                                            "name": "conn-demo",
                                            "ready": False,
                                            "state": {
                                                "waiting": {
                                                    "reason": "ImagePullBackOff",
                                                    "message": "Back-off pulling image",
                                                }
                                            },
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                )
            if "kubectl get events -n demo -o json" in command:
                return json.dumps(
                    {
                        "items": [
                            {
                                "lastTimestamp": "2026-06-07T10:00:00Z",
                                "reason": "Failed",
                                "message": (
                                    "Failed to pull image "
                                    '"validation-environment/edc-connector:local"'
                                ),
                                "involvedObject": {
                                    "kind": "Pod",
                                    "name": "conn-demo-5fd48",
                                },
                            }
                        ]
                    }
                )
            return ""

        adapter.run_silent = fake_run_silent

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            adapter._print_edc_rollout_failure_diagnostics("conn-demo", "demo")

        output = stdout.getvalue()
        self.assertIn("EDC rollout failure diagnostics", output)
        self.assertIn("validation-environment/edc-connector:local", output)
        self.assertIn("pullPolicy=IfNotPresent", output)
        self.assertIn("ImagePullBackOff", output)
        self.assertIn("Failed to pull image", output)

    def test_edc_level4_local_images_fail_when_required_outside_supported_topology(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-distributed"
        adapter.config_adapter = type("ConfigAdapter", (), {"topology": "vm-distributed"})()

        with (
            mock.patch.object(adapter, "_level4_edc_local_images_mode", return_value="required"),
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_connector_image") as connector_mock,
            mock.patch.object(adapter, "_maybe_prepare_level4_local_edc_dashboard_images") as dashboard_mock,
        ):
            self.assertFalse(adapter._maybe_prepare_level4_local_edc_images())

        connector_mock.assert_not_called()
        dashboard_mock.assert_not_called()

    def test_edc_preview_components_marks_deployable_components_with_urls(self):
        adapter = EdcAdapter(dry_run=True)
        adapter.config_adapter.load_deployer_config = lambda: {
            "ENVIRONMENT": "DEV",
            "DS_1_NAME": "demoedc",
            "DS_1_NAMESPACE": "demoedc",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            "COMPONENTS": "ontology-hub,ai-model-hub",
        }

        preview = adapter._preview_components()

        self.assertEqual(preview["status"], "planned")
        self.assertEqual(preview["action"], "deploy_components")
        self.assertEqual(preview["configured"], ["ontology-hub", "ai-model-hub"])
        self.assertEqual(preview["deployable"], ["ontology-hub", "ai-model-hub"])
        self.assertEqual(preview["pending_support"], [])
        self.assertEqual(
            [component["status"] for component in preview["components"]],
            ["planned", "planned"],
        )
        self.assertEqual(
            [component["url"] for component in preview["components"]],
            [
                "http://ontology-hub-demoedc.dev.ds.dataspaceunit.upm",
                "http://ai-model-hub-demoedc.dev.ds.dataspaceunit.upm",
            ],
        )

    def test_edc_adapter_reuses_common_services_when_ready(self):
        adapter = EdcAdapter.__new__(EdcAdapter)
        adapter.infrastructure = SharedInfrastructureStub()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = adapter.deploy_infrastructure()

        self.assertTrue(result)
        self.assertEqual(adapter.infrastructure.deploy_calls, 0)
        self.assertEqual(adapter.infrastructure.announced, [(2, "DEPLOY COMMON SERVICES")])
        self.assertEqual(adapter.infrastructure.completed, [2])
        self.assertIn("Reusing them for the shared local foundation", output.getvalue())

    def test_preview_common_services_ignores_transient_minio_post_job(self):
        class PreviewConfig:
            NS_COMMON = "common-srvs"

        def run_silent(cmd, **_kwargs):
            if cmd == "kubectl get pods -n common-srvs --no-headers":
                return (
                    "common-srvs-keycloak-0 1/1 Running 0 1d\n"
                    "common-srvs-minio-56c96fbbdf-77qkg 1/1 Running 0 1d\n"
                    "common-srvs-minio-post-job-8fjdv 0/1 Completed 0 1d\n"
                    "common-srvs-postgresql-0 1/1 Running 0 1d\n"
                    "common-srvs-vault-0 1/1 Running 0 1d"
                )
            if cmd == "kubectl exec common-srvs-vault-0 -n common-srvs -- vault status -format=json":
                return '{"initialized": true, "sealed": false}'
            return ""

        adapter = EdcAdapter.__new__(EdcAdapter)
        adapter.config = PreviewConfig
        adapter.infrastructure = SharedInfrastructureStub()
        adapter.run_silent = run_silent

        preview = adapter._preview_common_services()

        self.assertEqual(preview["status"], "ready")
        self.assertEqual(preview["action"], "reuse")
        self.assertEqual(preview["services"]["minio"]["pod"], "common-srvs-minio-56c96fbbdf-77qkg")
        self.assertTrue(preview["services"]["minio"]["ready"])
        self.assertEqual(preview["issues"], [])

    def test_preview_common_services_marks_failed_helm_release_not_ready(self):
        class PreviewConfig:
            NS_COMMON = "common-srvs"

            @staticmethod
            def helm_release_common():
                return "common-srvs"

        class PreviewInfrastructure(SharedInfrastructureStub):
            @staticmethod
            def common_services_release_status():
                return "failed"

        def run_silent(cmd, **_kwargs):
            if cmd == "kubectl get pods -n common-srvs --no-headers":
                return (
                    "common-srvs-keycloak-0 1/1 Running 0 1d\n"
                    "common-srvs-minio-56c96fbbdf-77qkg 1/1 Running 0 1d\n"
                    "common-srvs-postgresql-0 1/1 Running 0 1d\n"
                    "common-srvs-vault-0 1/1 Running 0 1d"
                )
            if cmd == "kubectl exec common-srvs-vault-0 -n common-srvs -- vault status -format=json":
                return '{"initialized": true, "sealed": false}'
            return ""

        adapter = EdcAdapter.__new__(EdcAdapter)
        adapter.config = PreviewConfig
        adapter.infrastructure = PreviewInfrastructure()
        adapter.run_silent = run_silent

        preview = adapter._preview_common_services()

        self.assertEqual(preview["status"], "missing")
        self.assertEqual(preview["action"], "deploy_infrastructure")
        self.assertEqual(preview["helm_release"], {"name": "common-srvs", "status": "failed"})
        self.assertIn("common services Helm release is failed", preview["issues"])

    def test_deploy_connectors_repairs_common_services_when_vault_token_mismatch_is_confirmed_by_env(self):
        class Connectors:
            def __init__(self):
                self.calls = 0
                self._last_runtime_prerequisite_code = None

            def deploy_connectors(self):
                self.calls += 1
                if self.calls == 1:
                    self._last_runtime_prerequisite_code = "vault_token_mismatch"
                    raise RuntimeError("EDC Level 4 cannot continue because the local Vault token does not match")
                return ["conn-citycounciledc-demoedc"]

        adapter = EdcAdapter.__new__(EdcAdapter)
        adapter.topology = "local"
        adapter.connectors = Connectors()
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.reset_local_shared_common_services.return_value = True
        adapter.deploy_infrastructure = mock.Mock(return_value=None)
        adapter.deploy_dataspace = mock.Mock(return_value=None)

        with mock.patch.dict(os.environ, {"PIONERA_LEVEL4_REPAIR_COMMON_SERVICES": "true"}):
            result = adapter.deploy_connectors()

        self.assertEqual(result, ["conn-citycounciledc-demoedc"])
        self.assertEqual(adapter.connectors.calls, 2)
        adapter.infrastructure.reset_local_shared_common_services.assert_called_once()
        adapter.deploy_infrastructure.assert_called_once()
        adapter.deploy_dataspace.assert_called_once()

    def test_deploy_connectors_does_not_repair_common_services_without_confirmation(self):
        class Connectors:
            _last_runtime_prerequisite_code = "vault_token_mismatch"

            def __init__(self):
                self.calls = 0

            def deploy_connectors(self):
                self.calls += 1
                raise RuntimeError("EDC Level 4 cannot continue because the local Vault token does not match")

        adapter = EdcAdapter.__new__(EdcAdapter)
        adapter.topology = "local"
        adapter.connectors = Connectors()
        adapter.infrastructure = mock.Mock()

        with mock.patch.dict(os.environ, {"PIONERA_LEVEL4_REPAIR_COMMON_SERVICES": "false"}):
            with self.assertRaisesRegex(RuntimeError, "local Vault token does not match"):
                adapter.deploy_connectors()

        self.assertEqual(adapter.connectors.calls, 1)
        adapter.infrastructure.reset_local_shared_common_services.assert_not_called()
        adapter.infrastructure.reset_common_services_for_level4_repair.assert_not_called()

    def test_deploy_connectors_does_not_run_level3_when_edc_dataspace_realm_is_missing(self):
        class Connectors:
            _last_runtime_prerequisite_code = "keycloak_realm_missing"

            def __init__(self):
                self.calls = 0

            def deploy_connectors(self):
                self.calls += 1
                raise RuntimeError(
                    "EDC Level 4 cannot continue because Keycloak realm 'demoedc' does not exist."
                )

        adapter = EdcAdapter.__new__(EdcAdapter)
        adapter.topology = "local"
        adapter.connectors = Connectors()
        adapter.deploy_dataspace = mock.Mock(return_value=None)

        with self.assertRaisesRegex(RuntimeError, "Keycloak realm"):
            adapter.deploy_connectors()

        self.assertEqual(adapter.connectors.calls, 1)
        adapter.deploy_dataspace.assert_not_called()


class EdcDeploymentTests(unittest.TestCase):
    def test_edc_deployment_runs_level3_even_when_dataspace_is_ready(self):
        deployment = EDCDeploymentAdapter.__new__(EDCDeploymentAdapter)
        deployment.infrastructure = SharedInfrastructureStub()
        deployment._delegate = DeploymentDelegateStub()
        deployment.config = type("Config", (), {"namespace_demo": staticmethod(lambda: "demoedc")})
        deployment.config_adapter = None
        deployment.connectors_adapter = object()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = deployment.deploy_dataspace()

        self.assertEqual(result, "dataspace-deploy-called")
        self.assertEqual(deployment._delegate.deploy_calls, 1)
        self.assertEqual(deployment._delegate.connectors_adapter, deployment.connectors_adapter)
        self.assertEqual(deployment.infrastructure.announced, [])
        self.assertEqual(deployment.infrastructure.completed, [])
        self.assertNotIn("Skipping Level 3 redeploy", output.getvalue())

    def test_edc_deployment_delegates_level3_even_if_registration_service_is_ready(self):
        deployment = EDCDeploymentAdapter.__new__(EDCDeploymentAdapter)
        deployment.infrastructure = SharedInfrastructureStub(dataspace_ready=False, registration_pod="demoedc-registration-service-0", schema_ready=True)
        deployment._delegate = DeploymentDelegateStub()
        deployment.config = type("Config", (), {"namespace_demo": staticmethod(lambda: "demoedc")})
        deployment.config_adapter = None
        deployment.connectors_adapter = object()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = deployment.deploy_dataspace()

        self.assertEqual(result, "dataspace-deploy-called")
        self.assertEqual(deployment._delegate.deploy_calls, 1)
        self.assertEqual(deployment.infrastructure.announced, [])
        self.assertEqual(deployment.infrastructure.completed, [])
        self.assertNotIn("Skipping Level 3 redeploy", output.getvalue())

    def test_edc_deployment_uses_shared_dataspace_runtime_for_level3_only(self):
        deployment = EDCDeploymentAdapter(
            run=lambda *_args, **_kwargs: None,
            run_silent=lambda *_args, **_kwargs: "",
            auto_mode_getter=lambda: True,
            infrastructure_adapter=SharedInfrastructureStub(),
        )

        self.assertTrue(deployment.config.repo_dir().endswith("Validation-Environment/deployers/edc"))
        self.assertTrue(deployment._delegate.config.repo_dir().endswith("Validation-Environment/deployers/inesdata"))
        self.assertTrue(
            deployment._delegate.config.python_exec().endswith(
                "Validation-Environment/deployers/inesdata/.venv/bin/python"
            )
        )
        self.assertTrue(
            deployment._delegate.config.bootstrap_script().endswith(
                "Validation-Environment/deployers/inesdata/bootstrap.py"
            )
        )
        self.assertIn(
            "Validation-Environment/deployers/inesdata/bootstrap.py",
            deployment._delegate.config.bootstrap_dataspace_command("create", dataspace="pionera-edc"),
        )
        bootstrap_runtime = resolve_shared_level3_bootstrap_runtime(deployment._delegate.config)
        self.assertTrue(
            bootstrap_runtime["repo_dir"].endswith("Validation-Environment/deployers/inesdata")
        )
        self.assertTrue(
            bootstrap_runtime["bootstrap_script"].endswith("Validation-Environment/deployers/inesdata/bootstrap.py")
        )
        self.assertTrue(
            bootstrap_runtime["runtime_dir"].endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc"
            )
        )
        self.assertEqual(
            deployment._delegate.config.shared_level3_repo_dir(),
            EdcSharedDataspaceConfig.shared_level3_repo_dir(),
        )
        self.assertTrue(
            deployment._delegate.config.shared_level3_dataspace_runtime_dir().endswith(
                "Validation-Environment/deployers/inesdata/deployments/DEV/pionera-edc"
            )
        )
        self.assertTrue(
            deployment._delegate.config.shared_level3_dataspace_credentials_file().endswith(
                "Validation-Environment/deployers/inesdata/deployments/DEV/pionera-edc/"
                "credentials-dataspace-pionera-edc.json"
            )
        )

    def test_edc_shared_level3_bootstrap_command_receives_postgres_forward_overrides(self):
        deployment = EDCDeploymentAdapter(
            run=lambda *_args, **_kwargs: None,
            run_silent=lambda *_args, **_kwargs: "",
            auto_mode_getter=lambda: True,
            infrastructure_adapter=SharedInfrastructureStub(),
        )

        command = deployment._delegate._bootstrap_dataspace_command(
            "create",
            dataspace="pionera-edc",
            pg_host="127.0.0.1",
            pg_port="15432",
        )

        self.assertIn("PIONERA_TOPOLOGY=local", command)
        self.assertIn("PIONERA_PG_HOST=127.0.0.1", command)
        self.assertIn("PIONERA_PG_PORT=15432", command)
        self.assertIn("deployers/inesdata/bootstrap.py", command)
        self.assertTrue(
            deployment._delegate.config.registration_service_dir().endswith(
                "Validation-Environment/deployers/shared/dataspace/registration-service"
            )
        )
        self.assertTrue(
            deployment._delegate.config.registration_values_file().endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc/"
                "dataspace/registration-service/values-pionera-edc.yaml"
            )
        )
        self.assertTrue(
            deployment._delegate.config.legacy_registration_values_file().endswith(
                "Validation-Environment/deployers/inesdata/dataspace/registration-service/values-pionera-edc.yaml"
            )
        )
        self.assertEqual(deployment._delegate.config.RUNTIME_LABEL, "shared dataspace")
        self.assertTrue(deployment._delegate.config.QUIET_SENSITIVE_DEPLOYER_OUTPUT)

    def test_edc_deployment_builds_shared_level3_runtime_context_from_neutral_helper(self):
        deployment = EDCDeploymentAdapter(
            run=lambda *_args, **_kwargs: None,
            run_silent=lambda *_args, **_kwargs: "",
            auto_mode_getter=lambda: True,
            infrastructure_adapter=SharedInfrastructureStub(),
        )

        context = deployment._shared_level3_runtime_context()

        self.assertEqual(context["dataspace"], "pionera-edc")
        self.assertEqual(context["environment"], "DEV")
        self.assertTrue(
            context["source_runtime_dir"].endswith(
                "Validation-Environment/deployers/inesdata/deployments/DEV/pionera-edc"
            )
        )
        self.assertTrue(
            context["target_runtime_dir"].endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc"
            )
        )

    def test_edc_deployment_stages_shared_dataspace_credentials_into_edc_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_repo = os.path.join(tmpdir, "deployers", "inesdata")
            target_repo = os.path.join(tmpdir, "deployers", "edc")
            source_dir = os.path.join(source_repo, "deployments", "DEV", "demoedc")
            os.makedirs(source_dir, exist_ok=True)
            source_file = os.path.join(source_dir, "credentials-dataspace-demoedc.json")
            with open(source_file, "w", encoding="utf-8") as handle:
                json.dump({"registration_service_database": {"name": "demoedc_rs"}}, handle)

            class SourceConfig:
                @staticmethod
                def repo_dir():
                    return source_repo

                @staticmethod
                def shared_level3_dataspace_runtime_dir(ds_name=None, environment=None):
                    return os.path.join(
                        source_repo,
                        "deployments",
                        environment or "DEV",
                        ds_name or "demoedc",
                    )

                @staticmethod
                def shared_level3_dataspace_credentials_file(ds_name=None, environment=None):
                    return os.path.join(
                        source_repo,
                        "deployments",
                        environment or "DEV",
                        ds_name or "demoedc",
                        f"credentials-dataspace-{ds_name or 'demoedc'}.json",
                    )

            class ConfigAdapter:
                @staticmethod
                def primary_dataspace_name():
                    return "demoedc"

                @staticmethod
                def deployment_environment_name():
                    return "DEV"

                @staticmethod
                def edc_dataspace_runtime_dir(ds_name=None):
                    return os.path.join(target_repo, "deployments", "DEV", ds_name or "demoedc")

                @staticmethod
                def edc_dataspace_credentials_file(ds_name=None):
                    return os.path.join(
                        target_repo,
                        "deployments",
                        "DEV",
                        ds_name or "demoedc",
                        f"credentials-dataspace-{ds_name or 'demoedc'}.json",
                    )

            deployment = EDCDeploymentAdapter.__new__(EDCDeploymentAdapter)
            deployment._delegate = type("Delegate", (), {"config": SourceConfig})()
            deployment.config_adapter = ConfigAdapter()

            staged = deployment._stage_shared_dataspace_credentials()

            target_file = os.path.join(target_repo, "deployments", "DEV", "demoedc", "credentials-dataspace-demoedc.json")
            self.assertEqual(staged, target_file)
            self.assertTrue(os.path.isfile(target_file))
            self.assertFalse(os.path.exists(source_file))
            self.assertFalse(os.path.exists(source_dir))

    def test_edc_deployment_stages_topology_scoped_shared_credentials_into_edc_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_repo = os.path.join(tmpdir, "deployers", "inesdata")
            target_repo = os.path.join(tmpdir, "deployers", "edc")
            source_dir = os.path.join(source_repo, "deployments", "DEV", "vm-distributed", "demoedc")
            target_dir = os.path.join(target_repo, "deployments", "DEV", "vm-distributed", "demoedc")
            os.makedirs(source_dir, exist_ok=True)
            os.makedirs(target_dir, exist_ok=True)
            source_file = os.path.join(source_dir, "credentials-dataspace-demoedc.json")
            target_file = os.path.join(target_dir, "credentials-dataspace-demoedc.json")
            with open(source_file, "w", encoding="utf-8") as handle:
                json.dump({"source": "inesdata-vm-distributed"}, handle)
            with open(target_file, "w", encoding="utf-8") as handle:
                json.dump({"source": "stale-edc"}, handle)

            class SourceConfig:
                @staticmethod
                def repo_dir():
                    return source_repo

                @staticmethod
                def shared_level3_dataspace_runtime_dir(ds_name=None, environment=None):
                    return os.path.join(
                        source_repo,
                        "deployments",
                        environment or "DEV",
                        ds_name or "demoedc",
                    )

                @staticmethod
                def shared_level3_dataspace_credentials_file(ds_name=None, environment=None):
                    return os.path.join(
                        source_repo,
                        "deployments",
                        environment or "DEV",
                        ds_name or "demoedc",
                        f"credentials-dataspace-{ds_name or 'demoedc'}.json",
                    )

            class ConfigAdapter:
                topology = "vm-distributed"

                @staticmethod
                def primary_dataspace_name():
                    return "demoedc"

                @staticmethod
                def deployment_environment_name():
                    return "DEV"

                @staticmethod
                def edc_dataspace_runtime_dir(ds_name=None):
                    return os.path.join(target_repo, "deployments", "DEV", "vm-distributed", ds_name or "demoedc")

                @staticmethod
                def edc_dataspace_credentials_file(ds_name=None):
                    return os.path.join(
                        target_repo,
                        "deployments",
                        "DEV",
                        "vm-distributed",
                        ds_name or "demoedc",
                        f"credentials-dataspace-{ds_name or 'demoedc'}.json",
                    )

            deployment = EDCDeploymentAdapter.__new__(EDCDeploymentAdapter)
            deployment._delegate = type("Delegate", (), {"config": SourceConfig})()
            deployment.config_adapter = ConfigAdapter()

            staged = deployment._stage_shared_dataspace_credentials()

            self.assertEqual(staged, target_file)
            with open(target_file, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"source": "inesdata-vm-distributed"})
            self.assertFalse(os.path.exists(source_file))
            self.assertFalse(os.path.exists(source_dir))

    def test_edc_deployment_stages_registration_values_into_edc_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = tmpdir
            source_repo = os.path.join(root, "deployers", "inesdata")
            target_repo = os.path.join(root, "deployers", "edc")
            source_dir = os.path.join(source_repo, "dataspace", "registration-service")
            os.makedirs(source_dir, exist_ok=True)
            source_file = os.path.join(source_dir, "values-demoedc.yaml")
            with open(source_file, "w", encoding="utf-8") as handle:
                handle.write("dataspace:\n  name: demoedc\n")

            target_dir = os.path.join(
                target_repo,
                "deployments",
                "DEV",
                "demoedc",
                "dataspace",
                "registration-service",
            )
            target_file = os.path.join(target_dir, "values-demoedc.yaml")

            class SourceConfig:
                @staticmethod
                def repo_dir():
                    return source_repo

                @staticmethod
                def legacy_registration_values_file():
                    return source_file

                @staticmethod
                def registration_values_file():
                    return target_file

                @staticmethod
                def ensure_registration_values_file(refresh=False):
                    del refresh
                    os.makedirs(target_dir, exist_ok=True)
                    if os.path.exists(source_file):
                        with open(source_file, "r", encoding="utf-8") as source_handle, open(
                            target_file, "w", encoding="utf-8"
                        ) as target_handle:
                            target_handle.write(source_handle.read())
                    return target_file

            class ConfigAdapter:
                @staticmethod
                def primary_dataspace_name():
                    return "demoedc"

                @staticmethod
                def deployment_environment_name():
                    return "DEV"

                @staticmethod
                def edc_dataspace_runtime_dir(ds_name=None):
                    return os.path.join(target_repo, "deployments", "DEV", ds_name or "demoedc")

            deployment = EDCDeploymentAdapter.__new__(EDCDeploymentAdapter)
            deployment._delegate = type("Delegate", (), {"config": SourceConfig})()
            deployment.config_adapter = ConfigAdapter()

            staged = deployment._stage_shared_registration_service_values()

            self.assertEqual(staged, target_file)
            self.assertTrue(os.path.isfile(target_file))
            self.assertFalse(os.path.exists(source_file))
            with open(target_file, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "dataspace:\n  name: demoedc\n")

    def test_edc_deployment_stages_public_portal_values_into_edc_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = tmpdir
            source_repo = os.path.join(root, "deployers", "inesdata")
            target_repo = os.path.join(root, "deployers", "edc")
            source_dir = os.path.join(source_repo, "dataspace", "public-portal")
            os.makedirs(source_dir, exist_ok=True)
            source_file = os.path.join(source_dir, "values-demoedc.yaml")
            with open(source_file, "w", encoding="utf-8") as handle:
                handle.write("dataspace:\n  name: demoedc\n")

            target_file = os.path.join(
                target_repo,
                "deployments",
                "DEV",
                "vm-distributed",
                "demoedc",
                "dataspace",
                "public-portal",
                "values-demoedc.yaml",
            )

            class SourceConfig:
                @staticmethod
                def repo_dir():
                    return source_repo

                @staticmethod
                def legacy_public_portal_values_file():
                    return source_file

                @staticmethod
                def public_portal_values_file():
                    return os.path.join(
                        target_repo,
                        "deployments",
                        "DEV",
                        "demoedc",
                        "dataspace",
                        "public-portal",
                        "values-demoedc.yaml",
                    )

            class ConfigAdapter:
                topology = "vm-distributed"

                @staticmethod
                def primary_dataspace_name():
                    return "demoedc"

                @staticmethod
                def deployment_environment_name():
                    return "DEV"

                @staticmethod
                def edc_dataspace_runtime_dir(ds_name=None):
                    return os.path.join(
                        target_repo,
                        "deployments",
                        "DEV",
                        "vm-distributed",
                        ds_name or "demoedc",
                    )

            deployment = EDCDeploymentAdapter.__new__(EDCDeploymentAdapter)
            deployment._delegate = type("Delegate", (), {"config": SourceConfig})()
            deployment.config_adapter = ConfigAdapter()

            staged = deployment._stage_shared_dataspace_runtime_artifacts()

            self.assertEqual(staged["public_portal_values"], target_file)
            self.assertTrue(os.path.isfile(target_file))
            self.assertFalse(os.path.exists(source_file))

    def test_edc_deployment_recreate_dataspace_delegates_to_shared_level3_flow(self):
        deployment = EDCDeploymentAdapter.__new__(EDCDeploymentAdapter)
        deployment.infrastructure = SharedInfrastructureStub()
        deployment._delegate = DeploymentDelegateStub()
        deployment.connectors_adapter = object()

        plan = deployment.build_recreate_dataspace_plan()
        result = deployment.recreate_dataspace(confirm_dataspace="demoedc")

        self.assertEqual(plan["dataspace"], "demoedc")
        self.assertEqual(result, "dataspace-recreate-called")
        self.assertEqual(deployment._delegate.recreate_calls, ["demoedc"])
        self.assertIs(deployment._delegate.connectors_adapter, deployment.connectors_adapter)


class EdcConnectorAdapterTests(unittest.TestCase):
    class OidcEdcConnectorConfigAdapter(EdcConnectorConfigAdapter):
        @staticmethod
        def edc_dashboard_proxy_auth_mode():
            return "oidc-bff"

    class RoleAlignedEdcConnectorConfigAdapter(EdcConnectorConfigAdapter):
        @staticmethod
        def registration_service_internal_hostname(**_kwargs):
            return "demoedc-registration-service.demoedc-core.svc.cluster.local:8080"

        @staticmethod
        def host_alias_domains(ds_name=None, ds_namespace=None):
            del ds_namespace
            return [
                "keycloak.dev.ed.dataspaceunit.upm",
                f"registration-service-{ds_name}.dev.ds.dataspaceunit.upm",
            ]

    def _make_adapter(self, root):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "local"
        adapter.run = lambda *_args, **_kwargs: None
        adapter.run_silent = lambda cmd, **_kwargs: "192.168.49.2" if cmd == "minikube ip" else ""
        adapter.config = type(
            "RuntimeEdcConnectorConfig",
            (EdcConnectorConfig,),
            {
                "script_dir": staticmethod(lambda: root),
                "repo_dir": staticmethod(lambda: "/tmp/deployers/edc"),
                "connector_credentials_path": staticmethod(
                    lambda connector_name: os.path.join(
                        root,
                        "demoedc",
                        f"credentials-connector-{connector_name}.json",
                    )
                ),
            },
        )
        adapter.config_adapter = EdcConnectorConfigAdapter(root)
        adapter.load_connector_credentials = lambda _connector: {
            "database": {
                "name": "db_conn_citycounciledc_demoedc",
                "user": "conn-citycounciledc-demoedc",
                "passwd": "secret-db",
            },
            "minio": {
                "access_key": "minio-access-key",
                "secret_key": "minio-secret-key",
            },
            "vault": {
                "token": "vault-token",
            },
            "connector_user": {
                "user": "connector-user",
                "passwd": "connector-password",
            },
        }
        return adapter

    def test_wait_for_management_api_ready_prefers_internal_port_forward(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter._start_connector_management_api_fallback = lambda connector: (
            "http://127.0.0.1:45555/management/v3/assets/request",
            {"namespace": "demoedc", "pod_name": "conn-citycounciledc-demoedc-0"},
        )
        adapter._close_temporary_port_forward = mock.Mock()
        adapter.get_management_api_headers = lambda connector: {"Authorization": "Bearer token"}
        adapter.invalidate_management_api_token = mock.Mock()
        adapter.connector_base_url = mock.Mock(side_effect=AssertionError("public URL should not be used"))
        response = mock.Mock(status_code=200)

        with mock.patch("adapters.edc.connectors.requests.post", return_value=response) as post_mock:
            ready = adapter.wait_for_management_api_ready("conn-citycounciledc-demoedc", timeout=1)

        self.assertTrue(ready)
        post_mock.assert_called_once()
        self.assertEqual(
            post_mock.call_args.args[0],
            "http://127.0.0.1:45555/management/v3/assets/request",
        )
        adapter._close_temporary_port_forward.assert_called_once()

    def _make_oidc_adapter(self, root):
        adapter = self._make_adapter(root)
        adapter.config_adapter = self.OidcEdcConnectorConfigAdapter(root)
        return adapter

    def _make_role_aligned_adapter(self, root):
        adapter = self._make_adapter(root)
        adapter.config_adapter = self.RoleAlignedEdcConnectorConfigAdapter(root)
        return adapter

    def test_dashboard_runtime_config_infers_edc_ontology_hub_url_from_dataspace(self):
        with tempfile.TemporaryDirectory() as root:
            adapter = self._make_adapter(root)
            adapter.config_adapter.load_deployer_config = lambda: {
                "DS_1_NAME": "demoedc",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            }
            adapter.config_adapter.primary_dataspace_name = lambda: "demoedc"

            runtime = adapter._dashboard_runtime_config_block()

        self.assertEqual(
            runtime["ontologyUrl"],
            "/edc-dashboard-api/components/ontology-hub",
        )
        self.assertEqual(
            runtime["ontologyPublicUrl"],
            "http://ontology-hub-demoedc.dev.ds.dataspaceunit.upm",
        )

    def test_dashboard_runtime_config_prefers_explicit_ontology_hub_public_url(self):
        with tempfile.TemporaryDirectory() as root:
            adapter = self._make_adapter(root)
            adapter.config_adapter.load_deployer_config = lambda: {
                "DS_1_NAME": "demoedc",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "ONTOLOGY_HUB_PUBLIC_URL": "https://components.example.org/ontology-hub/",
            }
            adapter.config_adapter.primary_dataspace_name = lambda: "demoedc"

            runtime = adapter._dashboard_runtime_config_block()

        self.assertEqual(
            runtime["ontologyUrl"],
            "/edc-dashboard-api/components/ontology-hub",
        )
        self.assertEqual(
            runtime["ontologyPublicUrl"],
            "https://components.example.org/ontology-hub",
        )

    def test_dashboard_runtime_config_exposes_model_observer_proxy_path_per_connector(self):
        with tempfile.TemporaryDirectory() as root:
            adapter = self._make_adapter(root)
            adapter.config_adapter.load_deployer_config = lambda: {
                "DS_1_NAME": "demoedc",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            }
            adapter.config_adapter.primary_dataspace_name = lambda: "demoedc"

            runtime = adapter._dashboard_runtime_config_block(
                connector_name="conn-citycounciledc-demoedc"
            )

        self.assertEqual(
            runtime["modelObserverUrl"],
            "/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/api/check",
        )

    def test_dashboard_component_proxy_config_targets_internal_ontology_hub_service(self):
        with tempfile.TemporaryDirectory() as root:
            adapter = self._make_adapter(root)
            config = {
                "DS_1_NAME": "demoedc",
                "COMPONENTS_NAMESPACE": "semantic-components",
            }

            components = adapter._dashboard_component_proxy_config_entries(
                config=config,
                ds_name="demoedc",
            )

        self.assertEqual(
            components,
            [
                {
                    "name": "ontology-hub",
                    "target": "http://demoedc-ontology-hub.semantic-components:3333",
                }
            ],
        )

    def test_dashboard_component_proxy_uses_shared_component_release_for_edc_dataspace(self):
        with tempfile.TemporaryDirectory() as root:
            adapter = self._make_adapter(root)
            config = {
                "DS_1_NAME": "demo-edc",
                "COMPONENTS_NAMESPACE": "components",
                "COMPONENTS_RELEASE_SCOPE": "auto",
                "COMPONENTS_SHARED_RELEASE_COMPONENTS": "ontology-hub,ai-model-hub,semantic-virtualization",
            }

            components = adapter._dashboard_component_proxy_config_entries(
                config=config,
                ds_name="demo-edc",
            )

        self.assertEqual(
            components,
            [
                {
                    "name": "ontology-hub",
                    "target": "http://demo-ontology-hub.components:3333",
                }
            ],
        )

    def test_dashboard_component_proxy_prefers_explicit_component_release_dataspace(self):
        with tempfile.TemporaryDirectory() as root:
            adapter = self._make_adapter(root)
            config = {
                "DS_1_NAME": "demo-edc",
                "COMPONENTS_NAMESPACE": "components",
                "COMPONENTS_RELEASE_DATASPACE_NAME": "shared-demo",
            }

            target = adapter._resolve_ontology_hub_internal_url(config, "demo-edc")
            clusterlocal_target = adapter._resolve_ontology_hub_internal_clusterlocal_url(
                config,
                "demo-edc",
            )

        self.assertEqual(target, "http://shared-demo-ontology-hub.components:3333")
        self.assertEqual(
            clusterlocal_target,
            "http://shared-demo-ontology-hub.components.svc.cluster.local:3333",
        )

    def _make_runtime_prerequisites_adapter(
        self,
        root,
        repo_dir,
        venv_dir,
        chart_dir,
        requirements_path,
        native_bootstrap=False,
        topology="local",
    ):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = topology
        adapter.config = type(
            "RuntimePrerequisitesConfig",
            (),
            {
                "EDC_NATIVE_BOOTSTRAP": native_bootstrap,
                "repo_dir": staticmethod(lambda: repo_dir),
                "python_exec": staticmethod(lambda: "/usr/bin/python3"),
                "venv_path": staticmethod(lambda: venv_dir),
                "repo_requirements_path": staticmethod(lambda: requirements_path),
                "deployer_config_path": staticmethod(
                    lambda: os.path.join(root, "deployers", "edc", "deployer.config")
                ),
                "infrastructure_deployer_config_path": staticmethod(
                    lambda: os.path.join(root, "deployers", "infrastructure", "deployer.config")
                ),
            },
        )
        adapter.config_adapter = type(
            "RuntimePrerequisitesConfigAdapter",
            (),
            {
                "topology": topology,
                "edc_connector_dir": lambda _self: chart_dir,
                "edc_bootstrap_script": lambda _self: os.path.join(repo_dir, "bootstrap.py"),
            },
        )()
        return adapter

    def test_prepare_runtime_prerequisites_skips_vault_token_sync_without_local_edc_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "repo")
            venv_dir = os.path.join(tmpdir, "venv")
            chart_dir = os.path.join(tmpdir, "chart")
            requirements_path = os.path.join(tmpdir, "requirements.txt")
            os.makedirs(repo_dir)
            os.makedirs(venv_dir)
            os.makedirs(chart_dir)
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("")
            with open(requirements_path, "w", encoding="utf-8") as handle:
                handle.write("")

            adapter = self._make_runtime_prerequisites_adapter(
                tmpdir,
                repo_dir,
                venv_dir,
                chart_dir,
                requirements_path,
            )
            infrastructure = mock.Mock()
            infrastructure.ensure_local_infra_access.return_value = True
            infrastructure.ensure_vault_unsealed.return_value = True
            infrastructure.reconcile_vault_state_for_local_runtime.return_value = True
            infrastructure.sync_vault_token_to_deployer_config.return_value = True
            adapter.infrastructure = infrastructure

            with mock.patch("adapters.edc.connectors.ensure_python_requirements") as requirements_mock:
                result = adapter._prepare_runtime_prerequisites()

        self.assertEqual(result, (repo_dir, "/usr/bin/python3"))
        requirements_mock.assert_called_once_with(
            "/usr/bin/python3",
            requirements_path,
            label="EDC runtime",
            quiet=True,
        )
        infrastructure.reconcile_vault_state_for_local_runtime.assert_not_called()
        infrastructure.sync_vault_token_to_deployer_config.assert_not_called()

    def test_prepare_runtime_prerequisites_syncs_vault_token_when_local_edc_config_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "repo")
            venv_dir = os.path.join(tmpdir, "venv")
            chart_dir = os.path.join(tmpdir, "chart")
            requirements_path = os.path.join(tmpdir, "requirements.txt")
            config_path = os.path.join(tmpdir, "deployers", "edc", "deployer.config")
            os.makedirs(repo_dir)
            os.makedirs(venv_dir)
            os.makedirs(chart_dir)
            os.makedirs(os.path.dirname(config_path))
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("")
            with open(requirements_path, "w", encoding="utf-8") as handle:
                handle.write("")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=old-token\n")

            adapter = self._make_runtime_prerequisites_adapter(
                tmpdir,
                repo_dir,
                venv_dir,
                chart_dir,
                requirements_path,
            )
            infrastructure = mock.Mock()
            infrastructure.ensure_local_infra_access.return_value = True
            infrastructure.ensure_vault_unsealed.return_value = True
            infrastructure.reconcile_vault_state_for_local_runtime.return_value = True
            infrastructure.sync_vault_token_to_deployer_config.return_value = True
            adapter.infrastructure = infrastructure

            with mock.patch("adapters.edc.connectors.ensure_python_requirements") as requirements_mock:
                result = adapter._prepare_runtime_prerequisites()

        self.assertEqual(result, (repo_dir, "/usr/bin/python3"))
        requirements_mock.assert_called_once_with(
            "/usr/bin/python3",
            requirements_path,
            label="EDC runtime",
            quiet=True,
        )
        infrastructure.reconcile_vault_state_for_local_runtime.assert_called_once()
        infrastructure.sync_vault_token_to_deployer_config.assert_not_called()

    def test_prepare_runtime_prerequisites_syncs_vault_token_when_shared_infrastructure_config_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "repo")
            venv_dir = os.path.join(tmpdir, "venv")
            chart_dir = os.path.join(tmpdir, "chart")
            requirements_path = os.path.join(tmpdir, "requirements.txt")
            config_path = os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config")
            os.makedirs(repo_dir)
            os.makedirs(venv_dir)
            os.makedirs(chart_dir)
            os.makedirs(os.path.dirname(config_path))
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("")
            with open(requirements_path, "w", encoding="utf-8") as handle:
                handle.write("")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=old-token\n")

            adapter = self._make_runtime_prerequisites_adapter(
                tmpdir,
                repo_dir,
                venv_dir,
                chart_dir,
                requirements_path,
            )
            infrastructure = mock.Mock()
            infrastructure.ensure_local_infra_access.return_value = True
            infrastructure.ensure_vault_unsealed.return_value = True
            infrastructure.reconcile_vault_state_for_local_runtime.return_value = True
            infrastructure.sync_vault_token_to_deployer_config.return_value = True
            adapter.infrastructure = infrastructure

            with mock.patch("adapters.edc.connectors.ensure_python_requirements"):
                result = adapter._prepare_runtime_prerequisites()

        self.assertEqual(result, (repo_dir, "/usr/bin/python3"))
        infrastructure.reconcile_vault_state_for_local_runtime.assert_called_once()
        infrastructure.sync_vault_token_to_deployer_config.assert_not_called()

    def test_prepare_runtime_prerequisites_fails_when_vault_token_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "repo")
            venv_dir = os.path.join(tmpdir, "venv")
            chart_dir = os.path.join(tmpdir, "chart")
            requirements_path = os.path.join(tmpdir, "requirements.txt")
            config_path = os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config")
            os.makedirs(repo_dir)
            os.makedirs(venv_dir)
            os.makedirs(chart_dir)
            os.makedirs(os.path.dirname(config_path))
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("")
            with open(requirements_path, "w", encoding="utf-8") as handle:
                handle.write("")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("VT_TOKEN=old-token\n")

            adapter = self._make_runtime_prerequisites_adapter(
                tmpdir,
                repo_dir,
                venv_dir,
                chart_dir,
                requirements_path,
            )
            adapter.config_adapter.load_deployer_config = lambda: {
                "VT_URL": "http://vault.local:8200",
                "VT_TOKEN": "stale-token",
            }
            infrastructure = mock.Mock()
            infrastructure.ensure_local_infra_access.return_value = True
            infrastructure.ensure_vault_unsealed.return_value = True
            infrastructure.reconcile_vault_state_for_local_runtime.return_value = True
            infrastructure.sync_vault_token_to_deployer_config.return_value = True
            adapter.infrastructure = infrastructure

            stale_response = mock.Mock(status_code=403)
            output = io.StringIO()
            with mock.patch("adapters.edc.connectors.ensure_python_requirements"):
                with mock.patch("adapters.edc.connectors.requests.get", return_value=stale_response):
                    with contextlib.redirect_stdout(output):
                        result = adapter._prepare_runtime_prerequisites()

        self.assertEqual(result, (None, None))
        self.assertIn("Vault token validation failed", output.getvalue())
        self.assertIn("stale", output.getvalue())

    def test_vault_management_preflight_uses_port_forward_for_cluster_dns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.config_adapter.load_deployer_config = lambda: {
                "VT_URL": "http://common-srvs-vault.common-srvs.svc:8200",
                "VT_TOKEN": "management-token",
            }
            adapter.infrastructure = mock.Mock()
            adapter.infrastructure.port_forward_service.return_value = True
            adapter.infrastructure.stop_port_forward_service.return_value = True
            adapter._reserve_local_port = lambda: 49222

            def response(status_code=200, payload=None):
                item = mock.Mock(status_code=status_code)
                item.json.return_value = payload or {}
                return item

            def fake_get(url, **_kwargs):
                if "common-srvs-vault.common-srvs.svc" in url:
                    raise requests.ConnectionError("Failed to resolve common-srvs-vault.common-srvs.svc")
                return response()

            def fake_post(url, **_kwargs):
                self.assertIn("127.0.0.1:49222", url)
                return response(payload={"capabilities": ["root"]})

            output = io.StringIO()
            with mock.patch("adapters.edc.connectors.requests.get", side_effect=fake_get), mock.patch(
                "adapters.edc.connectors.requests.post",
                side_effect=fake_post,
            ), contextlib.redirect_stdout(output):
                result = adapter._verify_vault_management_token()

        self.assertTrue(result)
        adapter.infrastructure.port_forward_service.assert_called_once_with(
            "common-srvs",
            "common-srvs-vault",
            49222,
            8200,
            quiet=True,
        )
        adapter.infrastructure.stop_port_forward_service.assert_called_once_with(
            "common-srvs",
            "common-srvs-vault",
            quiet=True,
        )
        self.assertIn("temporary local port-forward", output.getvalue())

    def test_prepare_runtime_prerequisites_uses_native_edc_bootstrap_without_legacy_venv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "deployers", "edc")
            chart_dir = os.path.join(tmpdir, "connector")
            venv_dir = os.path.join(tmpdir, "missing-venv")
            requirements_path = os.path.join(tmpdir, "missing-requirements.txt")
            os.makedirs(repo_dir)
            os.makedirs(chart_dir)
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("")

            adapter = self._make_runtime_prerequisites_adapter(
                tmpdir,
                repo_dir,
                venv_dir,
                chart_dir,
                requirements_path,
                native_bootstrap=True,
            )
            infrastructure = mock.Mock()
            infrastructure.ensure_local_infra_access.return_value = True
            infrastructure.ensure_vault_unsealed.return_value = True
            infrastructure.reconcile_vault_state_for_local_runtime.return_value = True
            infrastructure.sync_vault_token_to_deployer_config.return_value = True
            adapter.infrastructure = infrastructure

            with mock.patch("adapters.edc.connectors.ensure_python_requirements") as requirements_mock:
                result = adapter._prepare_runtime_prerequisites()

        self.assertEqual(result, (repo_dir, "/usr/bin/python3"))
        requirements_mock.assert_not_called()
        infrastructure.reconcile_vault_state_for_local_runtime.assert_not_called()
        infrastructure.sync_vault_token_to_deployer_config.assert_not_called()

    def test_prepare_runtime_prerequisites_skips_local_infra_check_for_vm_single(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "repo")
            venv_dir = os.path.join(tmpdir, "venv")
            chart_dir = os.path.join(tmpdir, "chart")
            requirements_path = os.path.join(tmpdir, "requirements.txt")
            os.makedirs(repo_dir)
            os.makedirs(venv_dir)
            os.makedirs(chart_dir)
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("")
            with open(requirements_path, "w", encoding="utf-8") as handle:
                handle.write("")

            adapter = self._make_runtime_prerequisites_adapter(
                tmpdir,
                repo_dir,
                venv_dir,
                chart_dir,
                requirements_path,
                topology="vm-single",
            )
            infrastructure = mock.Mock()
            infrastructure.ensure_local_infra_access.return_value = False
            infrastructure.ensure_vault_unsealed.return_value = True
            adapter.infrastructure = infrastructure
            adapter._verify_vault_management_token = lambda: True

            with mock.patch("adapters.edc.connectors.ensure_python_requirements") as requirements_mock:
                result = adapter._prepare_runtime_prerequisites()

        self.assertEqual(result, (repo_dir, "/usr/bin/python3"))
        requirements_mock.assert_called_once()
        infrastructure.ensure_local_infra_access.assert_not_called()
        infrastructure.ensure_vault_unsealed.assert_called_once()

    def test_keycloak_realm_preflight_reports_missing_dataspace_realm(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter._last_runtime_prerequisite_error = None
        adapter._last_runtime_prerequisite_code = None
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "load_deployer_config": staticmethod(lambda: {"KC_INTERNAL_URL": "http://keycloak.local"}),
            },
        )()

        response = mock.Mock(status_code=404, text='{"error":"Realm not found."}')
        output = io.StringIO()
        with mock.patch("adapters.edc.connectors.requests.get", return_value=response):
            with contextlib.redirect_stdout(output):
                result = adapter._ensure_keycloak_realm_available("demoedc")

        self.assertFalse(result)
        self.assertEqual(adapter._last_runtime_prerequisite_code, "keycloak_realm_missing")
        self.assertIn("Run Level 3 for the EDC adapter", output.getvalue())

    def test_vm_single_keycloak_base_url_is_inferred_from_public_vm_url(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-single",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_SINGLE_HTTP_URL": "https://org4.example.test",
                        "DOMAIN_BASE": "example.test",
                        "DS_DOMAIN_BASE": "example.test",
                    }
                ),
            },
        )()

        self.assertEqual(adapter._keycloak_base_url(), "https://org4.example.test/auth")
        self.assertEqual(
            adapter._keycloak_token_url_for_dataspace("demoedc"),
            "https://org4.example.test/auth/realms/demoedc/protocol/openid-connect/token",
        )

    def test_vm_single_connector_credentials_expose_public_path_urls(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter.config = type(
            "Config",
            (),
            {
                "dataspace_name": staticmethod(lambda: "pionera-edc"),
            },
        )
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-single",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_SINGLE_HTTP_URL": "https://org4.example.test",
                        "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX": "/c",
                        "DOMAIN_BASE": "example.test",
                        "DS_DOMAIN_BASE": "example.test",
                    }
                ),
                "edc_dashboard_base_href": staticmethod(lambda: "/edc-dashboard/"),
                "edc_dashboard_proxy_auth_mode": staticmethod(lambda: "service-account"),
            },
        )()
        credentials = {
            "access_urls": {
                "connector_management_api_v3": (
                    "http://conn-citycounciledc-pionera-edc.example.test/management/v3"
                )
            }
        }

        enriched = adapter._with_connector_public_access_urls(
            "conn-citycounciledc-pionera-edc",
            credentials,
        )
        adapter.load_connector_credentials = lambda connector: enriched

        self.assertEqual(
            enriched["public_access_urls"]["connector_management_api_v3"],
            "https://org4.example.test/edc/c/citycounciledc/management/v3",
        )
        self.assertEqual(
            enriched["public_access_urls"]["edc_dashboard_login"],
            "https://org4.example.test/edc/c/citycounciledc/edc-dashboard/",
        )
        self.assertEqual(
            adapter.build_connector_url("conn-citycounciledc-pionera-edc"),
            "https://org4.example.test/edc/c/citycounciledc/management/v3",
        )

    def test_vm_single_edc_public_path_ingresses_route_management_and_dashboard(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter.config = type(
            "Config",
            (),
            {
                "dataspace_name": staticmethod(lambda: "pionera-edc"),
            },
        )
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-single",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_SINGLE_HTTP_URL": "https://org4.example.test",
                        "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX": "/c",
                        "DOMAIN_BASE": "example.test",
                        "DS_DOMAIN_BASE": "example.test",
                    }
                ),
            },
        )()
        values = {
            "connector": {
                "name": "conn-citycounciledc-pionera-edc",
                "dataspace": "pionera-edc",
                "ingress": {"proxyBodySize": "900m"},
            },
            "dashboard": {
                "enabled": True,
                "proxy": {"enabled": True, "port": 8080},
            },
        }

        manifests = adapter._vm_single_connector_public_path_ingress_manifests(values, "provider")

        self.assertEqual(len(manifests), 2)
        routed = manifests[0]
        self.assertEqual(routed["spec"]["rules"][0]["host"], "org4.example.test")
        paths = routed["spec"]["rules"][0]["http"]["paths"]
        management_path = next(path for path in paths if "(management.*)" in path["path"])
        self.assertEqual(
            management_path["backend"]["service"],
            {
                "name": "conn-citycounciledc-pionera-edc",
                "port": {"number": 19193},
            },
        )
        dashboard_proxy_path = next(path for path in paths if "(edc-dashboard-api.*)" in path["path"])
        self.assertEqual(
            dashboard_proxy_path["backend"]["service"],
            {
                "name": "conn-citycounciledc-pionera-edc-dashboard-proxy",
                "port": {"number": 8080},
            },
        )
        root = manifests[1]
        self.assertEqual(
            root["metadata"]["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"],
            "/edc-dashboard/",
        )
        self.assertEqual(
            root["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"],
            "conn-citycounciledc-pionera-edc-dashboard",
        )

    def test_vm_distributed_connector_credentials_keep_dashboard_root_and_prefix_apis(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-distributed"
        adapter.config = type(
            "Config",
            (),
            {
                "dataspace_name": staticmethod(lambda: "pionera-edc"),
            },
        )
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-distributed",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_PROVIDER_PUBLIC_URL": "https://org2.example.test",
                        "DOMAIN_BASE": "example.test",
                        "DS_DOMAIN_BASE": "example.test",
                        "EDC_VM_DISTRIBUTED_CONNECTOR_PUBLIC_PATH_PREFIX": "/edc",
                    }
                ),
                "edc_dashboard_base_href": staticmethod(lambda: "/edc-dashboard/"),
                "edc_dashboard_proxy_auth_mode": staticmethod(lambda: "oidc-bff"),
            },
        )()
        adapter._connector_layout_metadata = lambda connector_name: {"role": "provider"}

        enriched = adapter._with_connector_public_access_urls(
            "conn-citycounciledc-pionera-edc",
            {
                "public_access_urls": {
                    "connector_management_api_v3": "https://org2.example.test/management/v3",
                    "edc_dashboard_oidc_login": "https://org2.example.test/edc-dashboard-api/auth/login",
                }
            },
        )

        self.assertEqual(
            enriched["public_access_urls"]["connector_ingress"],
            "https://org2.example.test",
        )
        self.assertEqual(
            enriched["public_access_urls"]["connector_management_api_v3"],
            "https://org2.example.test/edc/management/v3",
        )
        self.assertEqual(
            enriched["public_access_urls"]["connector_protocol_api"],
            "https://org2.example.test/edc/protocol",
        )
        self.assertEqual(
            enriched["public_access_urls"]["edc_dashboard_oidc_login"],
            "https://org2.example.test/edc-dashboard-api/auth/login",
        )

    def test_vm_distributed_public_ingresses_keep_dashboard_root_and_prefix_management(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-distributed"
        adapter.config = type(
            "Config",
            (),
            {
                "dataspace_name": staticmethod(lambda: "pionera-edc"),
            },
        )
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-distributed",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_PROVIDER_PUBLIC_URL": "https://org2.example.test",
                        "DOMAIN_BASE": "example.test",
                        "DS_DOMAIN_BASE": "example.test",
                        "EDC_VM_DISTRIBUTED_CONNECTOR_PUBLIC_PATH_PREFIX": "/edc",
                    }
                ),
                "edc_dashboard_base_href": staticmethod(lambda: "/edc-dashboard/"),
                "edc_dashboard_proxy_auth_mode": staticmethod(lambda: "oidc-bff"),
            },
        )()
        adapter._connector_layout_metadata = lambda connector_name: {"role": "provider"}
        values = {
            "connector": {
                "name": "conn-citycounciledc-pionera-edc",
                "dataspace": "pionera-edc",
                "ingress": {"proxyBodySize": "900m"},
            },
            "dashboard": {
                "enabled": True,
                "proxy": {"enabled": True, "port": 8080},
            },
        }

        manifests = adapter._vm_distributed_connector_public_host_ingress_manifests(
            values,
            "edc-provider",
        )

        self.assertEqual(len(manifests), 3)
        dashboard_api = manifests[0]
        self.assertEqual(
            dashboard_api["metadata"]["name"],
            "conn-citycounciledc-pionera-edc-public-dashboard-api-ingress",
        )
        self.assertEqual(dashboard_api["spec"]["rules"][0]["host"], "org2.example.test")
        dashboard_api_paths = dashboard_api["spec"]["rules"][0]["http"]["paths"]
        self.assertEqual(
            [path["path"] for path in dashboard_api_paths],
            ["/edc-dashboard-api"],
        )

        dashboard = manifests[1]
        self.assertEqual(dashboard["metadata"]["name"], "conn-citycounciledc-pionera-edc-public-dashboard-ingress")
        self.assertEqual(dashboard["spec"]["rules"][0]["host"], "org2.example.test")
        self.assertEqual(
            dashboard["metadata"]["annotations"]["nginx.ingress.kubernetes.io/auth-url"],
            "http://conn-citycounciledc-pionera-edc-dashboard-proxy.edc-provider.svc.cluster.local:"
            "8080/edc-dashboard-api/auth/require",
        )
        self.assertEqual(
            dashboard["metadata"]["annotations"]["nginx.ingress.kubernetes.io/auth-signin"],
            "https://org2.example.test/edc-dashboard-api/auth/login?returnTo=%2Fedc-dashboard%2F",
        )
        self.assertEqual(
            dashboard["metadata"]["annotations"]["nginx.ingress.kubernetes.io/configuration-snippet"],
            "error_page 401 =302 https://org2.example.test/edc-dashboard-api/auth/login?returnTo=%2Fedc-dashboard%2F;",
        )
        dashboard_paths = dashboard["spec"]["rules"][0]["http"]["paths"]
        self.assertEqual(
            [path["path"] for path in dashboard_paths],
            ["/edc-dashboard"],
        )

        api = manifests[2]
        self.assertEqual(api["metadata"]["name"], "conn-citycounciledc-pionera-edc-public-api-ingress")
        self.assertEqual(
            api["metadata"]["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"],
            "/$2",
        )
        api_paths = api["spec"]["rules"][0]["http"]["paths"]
        management_path = next(path for path in api_paths if "(management.*)" in path["path"])
        self.assertEqual(management_path["path"], "/edc(/|$)(management.*)")
        self.assertEqual(
            management_path["backend"]["service"],
            {
                "name": "conn-citycounciledc-pionera-edc",
                "port": {"number": 19193},
            },
        )

    def test_vm_distributed_public_ingress_sync_removes_stale_edc_host_path_conflicts(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-distributed"
        adapter.config = type(
            "Config",
            (),
            {
                "dataspace_name": staticmethod(lambda: "pionera-edc"),
            },
        )
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-distributed",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_PROVIDER_PUBLIC_URL": "https://org2.example.test",
                        "DOMAIN_BASE": "example.test",
                        "DS_DOMAIN_BASE": "example.test",
                        "EDC_VM_DISTRIBUTED_CONNECTOR_PUBLIC_PATH_PREFIX": "/edc",
                    }
                ),
                "edc_dashboard_base_href": staticmethod(lambda: "/edc-dashboard/"),
                "edc_dashboard_proxy_auth_mode": staticmethod(lambda: "oidc-bff"),
            },
        )()
        adapter._connector_layout_metadata = lambda connector_name: {"role": "provider"}
        values = {
            "connector": {
                "name": "conn-org2-pionera-edc",
                "dataspace": "pionera-edc",
            },
            "dashboard": {
                "enabled": True,
                "proxy": {"enabled": True, "port": 8080},
            },
        }
        manifests = adapter._vm_distributed_connector_public_host_ingress_manifests(
            values,
            "edc-provider",
        )
        existing_ingresses = {
            "items": [
                {
                    "metadata": {
                        "name": "conn-citycounciledc-pionera-edc-public-dashboard-ingress",
                        "labels": {"validation-environment-adapter": "edc"},
                    },
                    "spec": {
                        "rules": [
                            {
                                "host": "org2.example.test",
                                "http": {"paths": [{"path": "/edc-dashboard-api"}]},
                            }
                        ]
                    },
                },
                {
                    "metadata": {
                        "name": "conn-citycounciledc-pionera-edc-public-api-ingress",
                        "labels": {"validation-environment-adapter": "edc"},
                    },
                    "spec": {
                        "rules": [
                            {
                                "host": "org2.example.test",
                                "http": {"paths": [{"path": "/edc(/|$)(api.*)"}]},
                            }
                        ]
                    },
                },
                {
                    "metadata": {
                        "name": "manual-ingress",
                        "labels": {},
                    },
                    "spec": {
                        "rules": [
                            {
                                "host": "org2.example.test",
                                "http": {"paths": [{"path": "/edc-dashboard-api"}]},
                            }
                        ]
                    },
                },
            ]
        }
        commands = []
        adapter.run_silent = lambda command: json.dumps(existing_ingresses)

        def run(command, **kwargs):
            del kwargs
            commands.append(command)
            return mock.Mock(returncode=0)

        adapter.run = run

        self.assertTrue(
            adapter._delete_conflicting_vm_distributed_public_ingresses(
                manifests,
                "edc-provider",
            )
        )

        self.assertEqual(len(commands), 2)
        self.assertTrue(
            any("conn-citycounciledc-pionera-edc-public-dashboard-ingress" in command for command in commands)
        )
        self.assertTrue(
            any("conn-citycounciledc-pionera-edc-public-api-ingress" in command for command in commands)
        )
        self.assertFalse(any("manual-ingress" in command for command in commands))

    def test_vm_distributed_public_ingress_sync_recreates_same_named_ingress_when_paths_change(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-distributed"
        adapter.config = type(
            "Config",
            (),
            {
                "dataspace_name": staticmethod(lambda: "pionera-edc"),
            },
        )
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-distributed",
                "load_deployer_config": staticmethod(
                    lambda: {
                        "VM_PROVIDER_PUBLIC_URL": "https://org2.example.test",
                        "DOMAIN_BASE": "example.test",
                        "DS_DOMAIN_BASE": "example.test",
                        "EDC_VM_DISTRIBUTED_CONNECTOR_PUBLIC_PATH_PREFIX": "/edc",
                    }
                ),
                "edc_dashboard_base_href": staticmethod(lambda: "/edc-dashboard/"),
                "edc_dashboard_proxy_auth_mode": staticmethod(lambda: "oidc-bff"),
            },
        )()
        adapter._connector_layout_metadata = lambda connector_name: {"role": "provider"}
        values = {
            "connector": {
                "name": "conn-org2-pionera-edc",
                "dataspace": "pionera-edc",
            },
            "dashboard": {
                "enabled": True,
                "proxy": {"enabled": True, "port": 8080},
            },
        }
        manifests = adapter._vm_distributed_connector_public_host_ingress_manifests(
            values,
            "edc-provider",
        )
        existing_ingresses = {
            "items": [
                {
                    "metadata": {
                        "name": "conn-org2-pionera-edc-public-dashboard-ingress",
                        "labels": {"validation-environment-adapter": "edc"},
                    },
                    "spec": {
                        "rules": [
                            {
                                "host": "org2.example.test",
                                "http": {"paths": [{"path": "/edc-dashboard-api"}]},
                            }
                        ]
                    },
                },
                {
                    "metadata": {
                        "name": "conn-org2-pionera-edc-public-api-ingress",
                        "labels": {"validation-environment-adapter": "edc"},
                    },
                    "spec": manifests[2]["spec"],
                },
            ]
        }
        commands = []
        adapter.run_silent = lambda command: json.dumps(existing_ingresses)

        def run(command, **kwargs):
            del kwargs
            commands.append(command)
            return mock.Mock(returncode=0)

        adapter.run = run

        self.assertTrue(
            adapter._delete_conflicting_vm_distributed_public_ingresses(
                manifests,
                "edc-provider",
            )
        )

        self.assertEqual(len(commands), 1)
        self.assertIn("conn-org2-pionera-edc-public-dashboard-ingress", commands[0])

    def test_keycloak_realm_preflight_can_use_bootstrap_url_override(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-single"
        adapter._last_runtime_prerequisite_error = None
        adapter._last_runtime_prerequisite_code = None
        adapter.config_adapter = type(
            "ConfigAdapter",
            (),
            {
                "topology": "vm-single",
                "load_deployer_config": staticmethod(lambda: {}),
            },
        )()

        response = mock.Mock(status_code=200, text="{}")
        with mock.patch("adapters.edc.connectors.requests.get", return_value=response) as get_mock:
            result = adapter._ensure_keycloak_realm_available(
                "demoedc",
                keycloak_url="http://127.0.0.1:18080",
            )

        self.assertTrue(result)
        get_mock.assert_called_once()
        self.assertEqual(
            get_mock.call_args.args[0],
            "http://127.0.0.1:18080/realms/demoedc",
        )

    def test_level4_keycloak_realm_preflight_uses_vm_distributed_bootstrap_access(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "vm-distributed"
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.port_forward_service = mock.Mock()
        adapter._vm_distributed_keycloak_admin_needs_port_forward = lambda: True
        adapter._start_keycloak_bootstrap_access = mock.Mock(
            return_value={"keycloak_url": "http://127.0.0.1:18080", "port_forward": object()}
        )
        adapter._stop_keycloak_bootstrap_access = mock.Mock()
        adapter._ensure_keycloak_realm_available = mock.Mock(return_value=True)

        result = adapter._ensure_keycloak_realm_available_for_level4("demoedc")

        self.assertTrue(result)
        adapter._ensure_keycloak_realm_available.assert_called_once_with(
            "demoedc",
            keycloak_url="http://127.0.0.1:18080",
        )
        adapter._stop_keycloak_bootstrap_access.assert_called_once()

    def test_connector_values_payload_maps_edc_runtime_and_shared_services(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)

            payload = adapter._connector_values_payload(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
            )

        self.assertEqual(payload["connector"]["image"]["name"], "ghcr.io/proyectopionera/edc-connector")
        self.assertEqual(payload["connector"]["configuration"]["configFilePath"], "/opt/connector/config/connector-configuration.properties")
        self.assertTrue(payload["connector"]["sql"]["schemaAutocreate"])
        self.assertEqual(payload["connector"]["inference"]["edrAttempts"], 40)
        self.assertEqual(payload["connector"]["inference"]["edrDelayMs"], 1000)
        self.assertEqual(payload["connector"]["ingress"]["hostname"], "conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm")
        self.assertEqual(
            payload["connector"]["minio"]["accesskey"],
            "demoedc/conn-citycounciledc-demoedc/aws-access-key",
        )
        self.assertEqual(
            payload["connector"]["minio"]["secretkey"],
            "demoedc/conn-citycounciledc-demoedc/aws-secret-key",
        )
        self.assertEqual(
            payload["connector"]["transfer"]["privatekey"],
            "demoedc/conn-citycounciledc-demoedc/private-key",
        )
        self.assertEqual(
            payload["connector"]["transfer"]["publickey"],
            "demoedc/conn-citycounciledc-demoedc/public-key",
        )
        self.assertEqual(payload["services"]["keycloak"]["hostname"], "keycloak.dev.ed.dataspaceunit.upm")
        self.assertEqual(payload["services"]["keycloak"]["url"], "http://keycloak.dev.ed.dataspaceunit.upm")
        self.assertEqual(payload["services"]["minio"]["bucket"], "demoedc-conn-citycounciledc-demoedc")
        self.assertEqual(payload["services"]["minio"]["url"], "http://minio.dev.ed.dataspaceunit.upm")
        self.assertEqual(payload["services"]["vault"]["path"], "demoedc/conn-citycounciledc-demoedc/")
        self.assertEqual(
            payload["connector"]["ontologyHub"],
            {
                "externalBase": "http://ontology-hub-demoedc.dev.ds.dataspaceunit.upm",
                "internalBase": "http://demoedc-ontology-hub.components:3333",
                "internalFallback": "http://ontology-hub:3333",
                "internalClusterLocalFallback": "http://demoedc-ontology-hub.components.svc.cluster.local:3333",
            },
        )
        self.assertFalse(payload["dashboard"]["enabled"])
        self.assertEqual(payload["dashboard"]["baseHref"], "/edc-dashboard/")
        self.assertEqual(payload["dashboard"]["runtime"]["appConfig"]["appTitle"], "EDC Dashboard - conn-citycounciledc-demoedc")
        self.assertEqual(
            payload["dashboard"]["runtime"]["connectorConfig"][0]["managementUrl"],
            "/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/management",
        )
        self.assertEqual(
            payload["dashboard"]["runtime"]["connectorConfig"][0]["controlUrl"],
            "/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/control",
        )
        self.assertEqual(payload["dashboard"]["proxy"]["image"]["name"], "validation-environment/edc-dashboard-proxy")
        self.assertEqual(payload["dashboard"]["proxy"]["config"]["authMode"], "service-account")
        self.assertEqual(
            payload["dashboard"]["proxy"]["config"]["connectors"][0]["managementTarget"],
            "http://conn-citycounciledc-demoedc:19193/management",
        )
        self.assertEqual(
            payload["dashboard"]["runtime"]["appConfig"]["runtime"]["ontologyUrl"],
            "/edc-dashboard-api/components/ontology-hub",
        )
        self.assertEqual(
            payload["dashboard"]["runtime"]["appConfig"]["runtime"]["modelObserverUrl"],
            "/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/api/check",
        )
        self.assertEqual(
            payload["dashboard"]["proxy"]["config"]["components"],
            [
                {
                    "name": "ontology-hub",
                    "target": "http://demoedc-ontology-hub.components:3333",
                }
            ],
        )
        self.assertEqual(
            payload["dashboard"]["proxy"]["auth"]["connectors"][0]["password"],
            "connector-password",
        )
        self.assertEqual(
            payload["hostAliases"][0]["hostnames"],
            [
                "keycloak.dev.ed.dataspaceunit.upm",
                "minio.dev.ed.dataspaceunit.upm",
                "conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
                "conn-companyedc-demoedc.dev.ds.dataspaceunit.upm",
            ],
        )

    def test_connector_values_payload_uses_shared_component_release_for_pionera_edc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            base_config = adapter.config_adapter.load_deployer_config()
            adapter.config_adapter.load_deployer_config = lambda: {
                **base_config,
                "DS_1_NAME": "pionera-edc",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "COMPONENTS_NAMESPACE": "components",
                "COMPONENTS_RELEASE_SCOPE": "auto",
                "COMPONENTS_SHARED_RELEASE_COMPONENTS": "ontology-hub,ai-model-hub,semantic-virtualization",
            }

            payload = adapter._connector_values_payload(
                "conn-companyedc-pionera-edc",
                "pionera-edc",
                [
                    "conn-citycounciledc-pionera-edc",
                    "conn-companyedc-pionera-edc",
                ],
            )

        self.assertEqual(
            payload["connector"]["ontologyHub"]["internalBase"],
            "http://pionera-ontology-hub.components:3333",
        )
        self.assertEqual(
            payload["connector"]["ontologyHub"]["internalClusterLocalFallback"],
            "http://pionera-ontology-hub.components.svc.cluster.local:3333",
        )
        self.assertEqual(
            payload["dashboard"]["proxy"]["config"]["components"],
            [
                {
                    "name": "ontology-hub",
                    "target": "http://pionera-ontology-hub.components:3333",
                }
            ],
        )
        self.assertEqual(
            payload["dashboard"]["runtime"]["appConfig"]["runtime"]["ontologyPublicUrl"],
            "http://ontology-hub-pionera.pionera.oeg.fi.upm.es",
        )

    def test_connector_values_payload_infers_vm_single_internal_common_service_endpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-single"
            adapter.config_adapter.topology = "vm-single"
            adapter.config_adapter.load_deployer_config = lambda: {
                "ENVIRONMENT": "DEV",
                "TOPOLOGY": "vm-single",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "COMMON_SERVICES_NAMESPACE": "common-srvs",
                "DATABASE_HOSTNAME": "common-srvs-postgresql.common-srvs.svc",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "KEYCLOAK_FRONTEND_URL": "https://org4.pionera.oeg.fi.upm.es/auth",
                "MINIO_ENDPOINT": "http://127.0.0.1:9000",
            }

            payload = adapter._connector_values_payload(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
            )

        self.assertEqual(payload["services"]["db"]["hostname"], "common-srvs-postgresql.common-srvs.svc")
        self.assertEqual(payload["services"]["keycloak"]["hostname"], "common-srvs-keycloak.common-srvs.svc:80")
        self.assertEqual(payload["services"]["keycloak"]["protocol"], "http")
        self.assertEqual(payload["services"]["keycloak"]["url"], "http://common-srvs-keycloak.common-srvs.svc:80")
        self.assertEqual(payload["services"]["minio"]["hostname"], "common-srvs-minio.common-srvs.svc:9000")
        self.assertEqual(payload["services"]["minio"]["protocol"], "http")
        self.assertEqual(payload["services"]["minio"]["url"], "http://common-srvs-minio.common-srvs.svc:9000")
        self.assertEqual(payload["services"]["db"]["port"], "5432")

    def test_update_connector_multicluster_common_service_endpoints_uses_direct_postgres_port_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-citycounciledc-demoedc.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "services:\n"
                    "  db:\n"
                    "    hostname: common-srvs-postgresql.common-srvs.svc\n"
                    "    port: '5432'\n"
                    "  keycloak:\n"
                    "    hostname: common-srvs-keycloak.common-srvs.svc:80\n"
                    "    protocol: http\n"
                    "    url: http://common-srvs-keycloak.common-srvs.svc:80\n"
                    "  minio:\n"
                    "    hostname: common-srvs-minio.common-srvs.svc:9000\n"
                    "    protocol: http\n"
                    "    url: http://common-srvs-minio.common-srvs.svc:9000\n"
                    "  registrationService:\n"
                    "    hostname: demoedc-registration-service\n"
                    "    protocol: http\n"
                    "connector:\n"
                    "  ontologyHub:\n"
                    "    internalBase: http://ontology-hub.components:3333\n"
                    "dashboard:\n"
                    "  proxy:\n"
                    "    config:\n"
                    "      components:\n"
                    "      - name: ontology-hub\n"
                    "        target: http://ontology-hub.components:3333\n"
                )

            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-distributed"
            adapter.config_adapter.topology = "vm-distributed"
            adapter._vm_distributed_uses_separate_connector_kubeconfigs = lambda: True
            adapter.config_adapter.load_deployer_config = lambda: {
                "TOPOLOGY": "vm-distributed",
                "VM_COMMON_IP": "192.168.122.64",
                "VM_DISTRIBUTED_POSTGRES_NODEPORT": "30432",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                "MINIO_API_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
            }

            adapter.update_connector_multicluster_common_service_endpoints(
                values_file,
                "conn-citycounciledc-demoedc",
                ds_name="demoedc",
            )

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

        self.assertEqual(values["services"]["db"]["hostname"], "192.168.122.64")
        self.assertEqual(values["services"]["db"]["port"], "5432")

    def test_update_connector_multicluster_common_service_endpoints_uses_postgres_nodeport_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-conn-citycounciledc-demoedc.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "services:\n"
                    "  db:\n"
                    "    hostname: common-srvs-postgresql.common-srvs.svc\n"
                    "    port: '5432'\n"
                    "  keycloak:\n"
                    "    hostname: common-srvs-keycloak.common-srvs.svc:80\n"
                    "    protocol: http\n"
                    "    url: http://common-srvs-keycloak.common-srvs.svc:80\n"
                    "  minio:\n"
                    "    hostname: common-srvs-minio.common-srvs.svc:9000\n"
                    "    protocol: http\n"
                    "    url: http://common-srvs-minio.common-srvs.svc:9000\n"
                    "  registrationService:\n"
                    "    hostname: demoedc-registration-service\n"
                    "    protocol: http\n"
                    "connector:\n"
                    "  ontologyHub:\n"
                    "    internalBase: http://ontology-hub.components:3333\n"
                    "dashboard:\n"
                    "  proxy:\n"
                    "    config:\n"
                    "      components:\n"
                    "      - name: ontology-hub\n"
                    "        target: http://ontology-hub.components:3333\n"
                )

            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-distributed"
            adapter.config_adapter.topology = "vm-distributed"
            adapter._vm_distributed_uses_separate_connector_kubeconfigs = lambda: True
            adapter.config_adapter.load_deployer_config = lambda: {
                "TOPOLOGY": "vm-distributed",
                "VM_COMMON_IP": "192.168.122.64",
                "VM_DISTRIBUTED_POSTGRES_ACCESS_MODE": "nodeport",
                "VM_DISTRIBUTED_POSTGRES_NODEPORT": "30432",
                "DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                "MINIO_API_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
            }

            adapter.update_connector_multicluster_common_service_endpoints(
                values_file,
                "conn-citycounciledc-demoedc",
                ds_name="demoedc",
            )

            with open(values_file, encoding="utf-8") as handle:
                values = yaml.safe_load(handle)

        self.assertEqual(values["services"]["db"]["hostname"], "192.168.122.64")
        self.assertEqual(values["services"]["db"]["port"], "30432")

    def test_edc_vm_distributed_level4_syncs_common_postgres_access_before_connectors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-distributed"
            adapter.config_adapter.topology = "vm-distributed"
            adapter.config_adapter.load_deployer_config = lambda: {
                "TOPOLOGY": "vm-distributed",
                "VM_DISTRIBUTED_POSTGRES_ACCESS_MODE": "nodeport",
            }
            adapter._vm_distributed_uses_separate_connector_kubeconfigs = lambda: True
            entered_roles = []

            @contextlib.contextmanager
            def temporary_kubeconfig_role(role):
                entered_roles.append(role)
                yield

            adapter._temporary_kubeconfig_role = temporary_kubeconfig_role
            adapter.infrastructure = mock.Mock()
            adapter.infrastructure.sync_vm_distributed_common_postgresql_access.return_value = {
                "status": "synced"
            }

            synchronized = adapter._sync_vm_distributed_common_postgresql_access_if_required()

        self.assertTrue(synchronized)
        self.assertEqual(entered_roles, ["common"])
        adapter.infrastructure.sync_vm_distributed_common_postgresql_access.assert_called_once()

    def test_edc_vm_distributed_level4_skips_common_postgres_nodeport_sync_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-distributed"
            adapter.config_adapter.topology = "vm-distributed"
            adapter.config_adapter.load_deployer_config = lambda: {"TOPOLOGY": "vm-distributed"}
            adapter._vm_distributed_uses_separate_connector_kubeconfigs = lambda: True
            adapter.infrastructure = mock.Mock()

            synchronized = adapter._sync_vm_distributed_common_postgresql_access_if_required()

        self.assertTrue(synchronized)
        adapter.infrastructure.sync_vm_distributed_common_postgresql_access.assert_not_called()

    def test_edc_local_level4_does_not_sync_vm_distributed_postgres_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.topology = "local"
            adapter.config_adapter.topology = "local"
            adapter.infrastructure = mock.Mock()

            synchronized = adapter._sync_vm_distributed_common_postgresql_access_if_required()

        self.assertTrue(synchronized)
        adapter.infrastructure.sync_vm_distributed_common_postgresql_access.assert_not_called()

    def test_common_services_namespace_keeps_inherited_no_argument_call_compatible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.config_adapter.load_deployer_config = lambda: {
                "COMMON_SERVICES_NAMESPACE": "shared-services",
            }

            self.assertEqual(adapter._common_services_namespace(), "shared-services")
            self.assertEqual(
                adapter._common_services_namespace({"COMMON_SERVICES_NAMESPACE": "explicit-services"}),
                "explicit-services",
            )

    def test_reconcile_connector_vault_secrets_refreshes_token_and_s3_aliases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            connector = "conn-citycounciledc-demoedc"
            credentials_path = os.path.join(tmpdir, "credentials.json")
            certs_dir = os.path.join(tmpdir, "certs")
            os.makedirs(certs_dir, exist_ok=True)
            for suffix, content in {
                "public.crt": "public-cert",
                "private.key": "private-key",
            }.items():
                with open(os.path.join(certs_dir, f"{connector}-{suffix}"), "w", encoding="utf-8") as handle:
                    handle.write(content)

            credentials = {
                "minio": {
                    "access_key": "access-value",
                    "secret_key": "secret-value",
                },
                "vault": {
                    "token": "stale-token",
                },
                "certificates": {
                    "path": certs_dir,
                },
            }
            with open(credentials_path, "w", encoding="utf-8") as handle:
                json.dump(credentials, handle)

            adapter.config_adapter.load_deployer_config = lambda: {
                "VT_URL": "http://vault.local",
                "VT_TOKEN": "management-token",
            }
            adapter.config_adapter.edc_connector_credentials_path = lambda connector_name, ds_name=None: credentials_path
            adapter.load_connector_credentials = lambda connector_name: credentials

            def response(status_code=200, payload=None):
                item = mock.Mock(status_code=status_code)
                item.raise_for_status = mock.Mock()
                item.json.return_value = payload or {}
                if status_code >= 400:
                    item.raise_for_status.side_effect = RuntimeError("failed")
                return item

            posted_secret_urls = []

            def fake_get(url, **kwargs):
                if url.endswith("/v1/auth/token/lookup-self"):
                    token = (kwargs.get("headers") or {}).get("X-Vault-Token")
                    return response(status_code=200 if token == "management-token" else 403)
                return response(status_code=404)

            def fake_post(url, **kwargs):
                if url.endswith("/v1/sys/capabilities-self"):
                    return response(
                        payload={
                            "sys/policies/acl/*": ["create", "read", "update", "delete", "list"],
                            "auth/token/create": ["create", "read", "update", "delete", "list"],
                            "secret/data/*": ["create", "read", "update", "delete", "list"],
                        }
                    )
                if url.endswith("/v1/auth/token/create"):
                    return response(payload={"auth": {"client_token": "fresh-token"}})
                posted_secret_urls.append((url, kwargs["json"]))
                return response()

            with mock.patch("adapters.edc.connectors.requests.get", side_effect=fake_get), mock.patch(
                "adapters.edc.connectors.requests.put",
                return_value=response(),
            ), mock.patch("adapters.edc.connectors.requests.post", side_effect=fake_post):
                reconciled = adapter._reconcile_connector_vault_secrets(
                    connector,
                    "demoedc",
                    credentials=credentials,
                )

            self.assertTrue(reconciled)
            with open(credentials_path, "r", encoding="utf-8") as handle:
                updated_credentials = json.load(handle)
            self.assertEqual(updated_credentials["vault"]["token"], "fresh-token")
            posted_paths = {url.rsplit("/v1/secret/data/", 1)[1] for url, _payload in posted_secret_urls}
            self.assertEqual(
                posted_paths,
                {
                    f"demoedc/{connector}/aws-access-key",
                    f"demoedc/{connector}/aws-secret-key",
                    f"demoedc/{connector}/public-key",
                    f"demoedc/{connector}/private-key",
                },
            )

    def test_reconcile_connector_vault_secrets_uses_explicit_management_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            connector = "conn-citycounciledc-demoedc"
            credentials_path = os.path.join(tmpdir, "credentials.json")
            credentials = {
                "minio": {
                    "access_key": "access-value",
                    "secret_key": "secret-value",
                },
                "vault": {
                    "token": "stale-token",
                },
            }
            with open(credentials_path, "w", encoding="utf-8") as handle:
                json.dump(credentials, handle)

            adapter.config_adapter.load_deployer_config = lambda: {
                "VT_URL": "http://vault.cluster",
                "VT_TOKEN": "stale-config-token",
            }
            adapter.config_adapter.edc_connector_credentials_path = lambda connector_name, ds_name=None: credentials_path
            adapter.load_connector_credentials = lambda connector_name: credentials
            seen_tokens = []

            def response(status_code=200, payload=None):
                item = mock.Mock(status_code=status_code)
                item.raise_for_status = mock.Mock()
                item.json.return_value = payload or {}
                if status_code >= 400:
                    item.raise_for_status.side_effect = RuntimeError("failed")
                return item

            def fake_get(url, **kwargs):
                if url.endswith("/v1/auth/token/lookup-self"):
                    token = (kwargs.get("headers") or {}).get("X-Vault-Token")
                    return response(status_code=200 if token == "fresh-management-token" else 403)
                return response(status_code=404)

            def fake_put(url, **kwargs):
                seen_tokens.append((kwargs.get("headers") or {}).get("X-Vault-Token"))
                return response()

            def fake_post(url, **kwargs):
                token = (kwargs.get("headers") or {}).get("X-Vault-Token")
                if url.endswith("/v1/sys/capabilities-self"):
                    seen_tokens.append(token)
                    return response(
                        payload={
                            "sys/policies/acl/*": ["create", "read", "update", "delete", "list"],
                            "auth/token/create": ["create", "read", "update", "delete", "list"],
                            "secret/data/*": ["create", "read", "update", "delete", "list"],
                        }
                    )
                if url.endswith("/v1/auth/token/create"):
                    seen_tokens.append(token)
                    return response(payload={"auth": {"client_token": "fresh-token"}})
                seen_tokens.append(token)
                return response()

            with mock.patch("adapters.edc.connectors.requests.get", side_effect=fake_get), mock.patch(
                "adapters.edc.connectors.requests.put",
                side_effect=fake_put,
            ), mock.patch("adapters.edc.connectors.requests.post", side_effect=fake_post):
                reconciled = adapter._reconcile_connector_vault_secrets(
                    connector,
                    "demoedc",
                    credentials=credentials,
                    vault_url="http://127.0.0.1:18200",
                    vault_token="fresh-management-token",
                )

            self.assertTrue(reconciled)
            self.assertIn("fresh-management-token", seen_tokens)
            self.assertNotIn("stale-config-token", seen_tokens)

    def test_edc_minio_dataspace_transfer_policy_allows_peer_buckets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            connector = "conn-citycounciledc-demoedc"
            policy_name = f"policy-demoedc-{connector}-dataspace-transfer"
            setattr(adapter.config, "service_minio", staticmethod(lambda: "minio"))
            adapter.infrastructure = mock.Mock()
            adapter.infrastructure.get_pod_by_name.return_value = "minio-pod"
            adapter.config_adapter.load_deployer_config = lambda: {
                "MINIO_ENDPOINT": "http://minio.local:9000",
                "MINIO_ADMIN_USER": "admin",
                "MINIO_ADMIN_PASS": "admin-password",
            }

            run_commands = []

            def fake_run(command, **_kwargs):
                run_commands.append(command)
                return "ok"

            adapter.run = fake_run
            adapter.run_silent = mock.Mock(side_effect=["", f"PolicyName: {policy_name}"])

            result = adapter.ensure_minio_dataspace_transfer_policy_attached(
                connector,
                ds_name="demoedc",
            )

        self.assertTrue(result)
        self.assertTrue(any(f"mc admin policy attach minio {policy_name} --user {connector}" in command for command in run_commands))
        write_command = next(command for command in run_commands if "base64 -d" in command)
        encoded_policy = write_command.split("echo '", 1)[1].split("'", 1)[0]
        policy = json.loads(base64.b64decode(encoded_policy).decode("utf-8"))
        self.assertEqual(
            policy["Statement"][0]["Resource"],
            [
                "arn:aws:s3:::demoedc-*",
                "arn:aws:s3:::demoedc-*/*",
            ],
        )

    def test_connector_values_payload_maps_oidc_bff_proxy_without_connector_passwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_oidc_adapter(tmpdir)

            payload = adapter._connector_values_payload(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
            )

        proxy_config = payload["dashboard"]["proxy"]["config"]
        self.assertEqual(proxy_config["authMode"], "oidc-bff")
        self.assertEqual(proxy_config["clientId"], "dataspace-users")
        self.assertEqual(proxy_config["scope"], "openid profile email")
        self.assertEqual(
            proxy_config["authorizationUrl"],
            "http://keycloak.dev.ed.dataspaceunit.upm/realms/demoedc/protocol/openid-connect/auth",
        )
        self.assertEqual(
            proxy_config["logoutUrl"],
            "http://keycloak.dev.ed.dataspaceunit.upm/realms/demoedc/protocol/openid-connect/logout",
        )
        self.assertEqual(proxy_config["callbackPath"], "/edc-dashboard-api/auth/callback")
        self.assertEqual(proxy_config["loginPath"], "/edc-dashboard-api/auth/login")
        self.assertEqual(proxy_config["logoutPath"], "/edc-dashboard-api/auth/logout")
        self.assertEqual(proxy_config["authCheckPath"], "/edc-dashboard-api/auth/require")
        self.assertEqual(proxy_config["externalBaseUrl"], "")
        self.assertEqual(proxy_config["cookieName"], "edc_dashboard_session")
        self.assertFalse(proxy_config["cookieSecure"])
        self.assertEqual(payload["dashboard"]["proxy"]["auth"]["connectors"], [])

    def test_vm_single_oidc_bff_proxy_uses_selected_connector_public_external_base_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_oidc_adapter(tmpdir)
            adapter.topology = "vm-single"
            adapter.config_adapter.topology = "vm-single"
            base_config = adapter.config_adapter.load_deployer_config()
            adapter.config_adapter.load_deployer_config = lambda: {
                **base_config,
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.example.test",
                "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX": "/c",
            }

            payload = adapter._connector_values_payload(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-companyedc-demoedc",
                    "conn-citycounciledc-demoedc",
                ],
            )

        proxy_config = payload["dashboard"]["proxy"]["config"]
        runtime = payload["dashboard"]["runtime"]
        self.assertEqual(
            proxy_config["externalBaseUrl"],
            "https://org4.example.test/edc/c/citycounciledc",
        )
        self.assertEqual(proxy_config["callbackPath"], "/edc-dashboard-api/auth/callback")
        self.assertEqual(proxy_config["loginPath"], "/edc-dashboard-api/auth/login")
        self.assertEqual(proxy_config["logoutPath"], "/edc-dashboard-api/auth/logout")
        self.assertEqual(proxy_config["authCheckPath"], "/edc-dashboard-api/auth/require")
        self.assertTrue(proxy_config["cookieSecure"])
        self.assertEqual(runtime["baseHref"], "/edc/c/citycounciledc/edc-dashboard/")
        self.assertEqual(
            runtime["appConfig"]["runtime"]["ontologyUrl"],
            "/edc/c/citycounciledc/edc-dashboard-api/components/ontology-hub",
        )
        self.assertEqual(
            runtime["appConfig"]["runtime"]["modelObserverUrl"],
            "/edc/c/citycounciledc/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/api/check",
        )
        self.assertEqual(
            runtime["connectorConfig"][0]["managementUrl"],
            "/edc/c/citycounciledc/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/management",
        )
        self.assertEqual(
            runtime["connectorConfig"][1]["managementUrl"],
            "/edc/c/citycounciledc/edc-dashboard-api/connectors/conn-companyedc-demoedc/management",
        )

    def test_connector_values_payload_uses_registration_service_fqdn_when_namespace_differs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_role_aligned_adapter(tmpdir)
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demoedc",
                    "namespace": "demoedc",
                    "namespace_profile": "role-aligned",
                    "connectors": [
                        "conn-citycounciledc-demoedc",
                        "conn-companyedc-demoedc",
                    ],
                    "connector_details": [
                        {
                            "name": "conn-citycounciledc-demoedc",
                            "role": "provider",
                            "runtime_namespace": "demoedc",
                            "active_namespace": "demoedc",
                            "planned_namespace": "demoedc-provider",
                            "registration_service_namespace": "demoedc-core",
                            "planned_registration_service_namespace": "demoedc-core",
                        }
                    ],
                }
            ]

            payload = adapter._connector_values_payload(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
                connector_namespace="demoedc",
            )

        self.assertEqual(
            payload["services"]["registrationService"]["hostname"],
            "demoedc-registration-service.demoedc-core.svc.cluster.local:8080",
        )
        self.assertEqual(
            payload["connector"]["layout"],
            {
                "role": "provider",
                "namespaceProfile": "role-aligned",
                "runtimeNamespace": "demoedc",
                "activeNamespace": "demoedc",
                "plannedNamespace": "demoedc-provider",
                "registrationServiceNamespace": "demoedc-core",
                "plannedRegistrationServiceNamespace": "demoedc-core",
            },
        )
        self.assertEqual(
            payload["hostAliases"][0]["hostnames"],
            [
                "keycloak.dev.ed.dataspaceunit.upm",
                "registration-service-demoedc.dev.ds.dataspaceunit.upm",
                "conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
                "conn-companyedc-demoedc.dev.ds.dataspaceunit.upm",
            ],
        )

    def test_connector_values_payload_uses_fqdn_dashboard_proxy_targets_for_role_aligned_namespaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_role_aligned_adapter(tmpdir)
            base_config = adapter.config_adapter.load_deployer_config()
            adapter.config_adapter.load_deployer_config = lambda: {
                **base_config,
                "LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES": "true",
            }
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demoedc",
                    "namespace": "demoedc",
                    "namespace_profile": "role-aligned",
                    "connectors": [
                        "conn-citycounciledc-demoedc",
                        "conn-companyedc-demoedc",
                    ],
                    "connector_details": [
                        {
                            "name": "conn-citycounciledc-demoedc",
                            "role": "provider",
                            "runtime_namespace": "demoedc",
                            "active_namespace": "demoedc",
                            "planned_namespace": "demoedc-provider",
                            "registration_service_namespace": "demoedc-core",
                            "planned_registration_service_namespace": "demoedc-core",
                        },
                        {
                            "name": "conn-companyedc-demoedc",
                            "role": "consumer",
                            "runtime_namespace": "demoedc",
                            "active_namespace": "demoedc",
                            "planned_namespace": "demoedc-consumer",
                            "registration_service_namespace": "demoedc-core",
                            "planned_registration_service_namespace": "demoedc-core",
                        },
                    ],
                }
            ]

            payload = adapter._connector_values_payload(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
                connector_namespace="demoedc-provider",
            )

        proxy_connectors = {
            entry["connectorName"]: entry
            for entry in payload["dashboard"]["proxy"]["config"]["connectors"]
        }
        self.assertEqual(
            proxy_connectors["conn-citycounciledc-demoedc"]["protocolTarget"],
            "http://conn-citycounciledc-demoedc.demoedc-provider.svc.cluster.local:19194/protocol",
        )
        self.assertEqual(
            proxy_connectors["conn-companyedc-demoedc"]["defaultTarget"],
            "http://conn-companyedc-demoedc.demoedc-consumer.svc.cluster.local:19191/api",
        )

    def test_render_values_file_writes_chart_values_into_edc_deployment_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)

            values_path = adapter._render_values_file(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
            )

            self.assertTrue(os.path.exists(values_path))
            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertIn(os.path.join("demoedc", "values-conn-citycounciledc-demoedc.yaml"), values_path)
        self.assertEqual(rendered["connector"]["name"], "conn-citycounciledc-demoedc")
        self.assertEqual(rendered["connector"]["dataspace"], "demoedc")
        self.assertEqual(rendered["services"]["db"]["name"], "db_conn_citycounciledc_demoedc")
        self.assertIn("dashboard", rendered)
        self.assertEqual(rendered["dashboard"]["runtime"]["baseHref"], "/edc-dashboard/")

    def test_render_values_file_rewrites_common_services_for_vm_distributed_cross_cluster(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-distributed"
            adapter.config_adapter.topology = "vm-distributed"
            adapter.config_adapter.ds_domain_base = lambda: "pionera.oeg.fi.upm.es"
            adapter.config_adapter.load_deployer_config = lambda: {
                "ENVIRONMENT": "DEV",
                "TOPOLOGY": "vm-distributed",
                "DS_1_NAME": "pionera-edc",
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "COMMON_SERVICES_NAMESPACE": "common-srvs",
                "DATABASE_HOSTNAME": "common-srvs-postgresql.common-srvs.svc",
                "VAULT_URL": "http://common-srvs-vault.common-srvs.svc:8200",
                "VM_COMMON_IP": "192.168.122.64",
                "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                "MINIO_API_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_PATH_REWRITE": "true",
            }
            adapter._vm_distributed_uses_separate_connector_kubeconfigs = lambda: True
            adapter._dataspace_name = lambda: "pionera-edc"
            adapter._edc_connector_public_api_base_url = lambda connector_name, credentials=None: (
                "https://org2.pionera.oeg.fi.upm.es/edc"
                if connector_name == "conn-citycounciledc-pionera-edc"
                else "https://org3.pionera.oeg.fi.upm.es/edc"
            )

            values_path = adapter._render_values_file(
                "conn-citycounciledc-pionera-edc",
                "pionera-edc",
                [
                    "conn-citycounciledc-pionera-edc",
                    "conn-companyedc-pionera-edc",
                ],
            )

            with open(values_path, "r", encoding="utf-8") as handle:
                rendered = yaml.safe_load(handle)

        self.assertEqual(rendered["services"]["db"]["hostname"], "192.168.122.64")
        self.assertEqual(rendered["services"]["db"]["port"], "5432")
        self.assertEqual(rendered["services"]["vault"]["url"], "http://192.168.122.64:8200")
        self.assertEqual(
            rendered["services"]["keycloak"]["url"],
            "https://org1.pionera.oeg.fi.upm.es/auth",
        )
        self.assertEqual(
            rendered["services"]["minio"]["url"],
            "https://org1.pionera.oeg.fi.upm.es",
        )
        self.assertEqual(
            rendered["services"]["registrationService"]["hostname"],
            "registration-service-pionera-edc.pionera.oeg.fi.upm.es",
        )
        self.assertEqual(
            rendered["connector"]["public"]["protocolUrl"],
            "https://org2.pionera.oeg.fi.upm.es/edc/protocol",
        )
        self.assertEqual(
            rendered["connector"]["public"]["publicUrl"],
            "https://org2.pionera.oeg.fi.upm.es/edc/public",
        )
        self.assertEqual(
            rendered["connector"]["ontologyHub"]["internalBase"],
            "https://org1.pionera.oeg.fi.upm.es/ontology-hub",
        )
        self.assertEqual(
            rendered["connector"]["ontologyHub"]["internalClusterLocalFallback"],
            "https://org1.pionera.oeg.fi.upm.es/ontology-hub",
        )
        self.assertEqual(
            rendered["dashboard"]["proxy"]["config"]["components"][0]["target"],
            "https://org1.pionera.oeg.fi.upm.es/ontology-hub",
        )
        proxy_connectors = {
            entry["connectorName"]: entry
            for entry in rendered["dashboard"]["proxy"]["config"]["connectors"]
        }
        self.assertEqual(
            proxy_connectors["conn-citycounciledc-pionera-edc"]["defaultTarget"],
            "http://conn-citycounciledc-pionera-edc.pionera-edc.svc.cluster.local:19191/api",
        )
        self.assertEqual(
            proxy_connectors["conn-companyedc-pionera-edc"]["defaultTarget"],
            "https://org3.pionera.oeg.fi.upm.es/edc/api",
        )
        self.assertEqual(
            proxy_connectors["conn-companyedc-pionera-edc"]["protocolTarget"],
            "https://org3.pionera.oeg.fi.upm.es/edc/protocol",
        )

    def test_render_values_file_generates_dashboard_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)

            adapter._render_values_file(
                "conn-citycounciledc-demoedc",
                "demoedc",
                [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
            )

            app_config_path = adapter.config_adapter.edc_dashboard_app_config_file(
                "conn-citycounciledc-demoedc",
                ds_name="demoedc",
            )
            connector_config_path = adapter.config_adapter.edc_dashboard_connector_config_file(
                "conn-citycounciledc-demoedc",
                ds_name="demoedc",
            )
            base_href_path = adapter.config_adapter.edc_dashboard_base_href_file(
                "conn-citycounciledc-demoedc",
                ds_name="demoedc",
            )

            self.assertTrue(os.path.exists(app_config_path))
            self.assertTrue(os.path.exists(connector_config_path))
            self.assertTrue(os.path.exists(base_href_path))

            with open(app_config_path, "r", encoding="utf-8") as handle:
                app_config = json.load(handle)
            with open(connector_config_path, "r", encoding="utf-8") as handle:
                connector_config = json.load(handle)
            with open(base_href_path, "r", encoding="utf-8") as handle:
                base_href = handle.read()

        self.assertEqual(app_config["appTitle"], "EDC Dashboard - conn-citycounciledc-demoedc")
        self.assertFalse(app_config["enableUserConfig"])
        self.assertEqual(connector_config[0]["connectorName"], "conn-citycounciledc-demoedc")
        self.assertEqual(
            connector_config[0]["protocolUrl"],
            "/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/protocol",
        )
        self.assertIn(
            "model-observer",
            {item["routerPath"] for item in app_config["menuItems"]},
        )
        self.assertEqual(
            app_config["runtime"]["ontologyUrl"],
            "/edc-dashboard-api/components/ontology-hub",
        )
        self.assertEqual(
            app_config["runtime"]["modelObserverUrl"],
            "/edc-dashboard-api/connectors/conn-citycounciledc-demoedc/api/check",
        )
        self.assertEqual(base_href, "/edc-dashboard/")

    def test_dashboard_runtime_validation_rejects_incompatible_component_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.config_adapter.edc_dashboard_enabled = lambda: True
            runtime_payload = {
                "appConfig": {
                    "menuItems": [
                        {"text": "Home", "routerPath": "home"},
                        {"text": "Ontologies", "routerPath": "ontologies"},
                    ],
                    "runtime": {
                        "ontologyUrl": "http://ontology-hub-pionera-edc.dev.ds.dataspaceunit.upm",
                        "modelObserverUrl": "",
                    },
                },
                "connectorConfig": [],
                "baseHref": "/edc-dashboard/",
            }

            with self.assertRaisesRegex(RuntimeError, "Generated EDC dashboard runtime is incomplete"):
                adapter._write_dashboard_runtime_config(
                    "conn-citycounciledc-demoedc",
                    "demoedc",
                    runtime_payload,
                )

    def test_stage_bootstrap_artifacts_copies_certs_and_rewrites_credentials_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            repo_dir = os.path.join(tmpdir, "bootstrap")
            source_dir = os.path.join(repo_dir, "deployments", "DEV", "demoedc")
            source_certs_dir = os.path.join(source_dir, "certs")
            os.makedirs(source_certs_dir, exist_ok=True)

            credentials_path = os.path.join(source_dir, "credentials-connector-conn-citycounciledc-demoedc.json")
            with open(credentials_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "certificates": {
                            "path": "deployments/DEV/demoedc/certs",
                            "passwd": "certificate-password",
                        }
                    },
                    handle,
                )

            with open(os.path.join(source_dir, "credentials-dataspace-demoedc.json"), "w", encoding="utf-8") as handle:
                json.dump({"realm_manager": {"user": "manager"}}, handle)

            with open(
                os.path.join(source_dir, "policy-demoedc-conn-citycounciledc-demoedc.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"Version": "2012-10-17"}, handle)

            for suffix in ("public.crt", "private.key", "store.p12"):
                with open(
                    os.path.join(source_certs_dir, f"conn-citycounciledc-demoedc-{suffix}"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(f"dummy-{suffix}")

            staged = adapter._stage_bootstrap_artifacts(
                "conn-citycounciledc-demoedc",
                "demoedc",
                repo_dir,
            )

            staged_credentials_path = staged["credentials"]
            staged_certs_dir = staged["certs"]
            with open(staged_credentials_path, "r", encoding="utf-8") as handle:
                staged_credentials = json.load(handle)
            self.assertTrue(os.path.exists(staged_certs_dir))
            self.assertEqual(
                staged_credentials["certificates"]["path"],
                adapter._runtime_relative_path(staged_certs_dir),
            )
            self.assertTrue(
                os.path.exists(
                    os.path.join(
                        staged_certs_dir,
                        "conn-citycounciledc-demoedc-public.crt",
                    )
                )
            )

    def test_stage_bootstrap_artifacts_keeps_native_runtime_in_place_when_source_matches_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            repo_dir = os.path.join(tmpdir, "deployers", "edc")
            runtime_dir = os.path.join(repo_dir, "deployments", "DEV", "demoedc")
            certs_dir = os.path.join(runtime_dir, "certs")
            os.makedirs(certs_dir, exist_ok=True)
            adapter.config_adapter.edc_dataspace_runtime_dir = lambda ds_name=None: runtime_dir
            adapter.config_adapter.edc_connector_certs_dir = lambda ds_name=None: certs_dir

            credentials_path = os.path.join(runtime_dir, "credentials-connector-conn-citycounciledc-demoedc.json")
            with open(credentials_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "certificates": {
                            "path": "deployers/edc/deployments/DEV/demoedc/certs",
                            "passwd": "certificate-password",
                        }
                    },
                    handle,
                )
            with open(
                os.path.join(runtime_dir, "policy-demoedc-conn-citycounciledc-demoedc.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"Version": "2012-10-17"}, handle)
            with open(
                os.path.join(certs_dir, "conn-citycounciledc-demoedc-public.crt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("dummy-public.crt")

            staged = adapter._stage_bootstrap_artifacts(
                "conn-citycounciledc-demoedc",
                "demoedc",
                repo_dir,
            )

        self.assertEqual(staged["credentials"], credentials_path)
        self.assertEqual(staged["certs"], certs_dir)
        self.assertEqual(
            staged["policy"],
            os.path.join(runtime_dir, "policy-demoedc-conn-citycounciledc-demoedc.json"),
        )

    def test_stage_bootstrap_artifacts_uses_topology_scoped_connector_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-single"
            repo_dir = os.path.join(tmpdir, "bootstrap")
            source_dir = os.path.join(repo_dir, "deployments", "DEV", "demoedc")
            source_certs_dir = os.path.join(source_dir, "certs")
            os.makedirs(source_certs_dir, exist_ok=True)

            connector_name = "conn-citycounciledc-demoedc"
            runtime_dir = os.path.join(
                tmpdir,
                "deployers",
                "edc",
                "deployments",
                "DEV",
                "vm-single",
                "demoedc",
            )
            credentials_target = os.path.join(
                runtime_dir,
                "connectors",
                connector_name,
                "credentials.json",
            )
            policy_target = os.path.join(
                runtime_dir,
                "connectors",
                connector_name,
                "policy.json",
            )
            certs_dir = os.path.join(runtime_dir, "certs")
            adapter.config_adapter.edc_dataspace_runtime_dir = lambda ds_name=None: runtime_dir
            adapter.config_adapter.edc_connector_certs_dir = lambda ds_name=None: certs_dir
            adapter.config_adapter.edc_connector_credentials_path = (
                lambda name, ds_name=None, for_write=False: credentials_target
            )
            adapter.config_adapter.connector_minio_policy_path = (
                lambda name, ds_name=None, for_write=False: policy_target
            )

            with open(
                os.path.join(source_dir, f"credentials-connector-{connector_name}.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "connector_user": {"user": "demo-user", "passwd": "demo-password"},
                        "minio": {"access_key": "demo-access", "secret_key": "demo-secret"},
                        "certificates": {
                            "path": "deployments/DEV/demoedc/certs",
                            "passwd": "certificate-password",
                        },
                    },
                    handle,
                )
            with open(
                os.path.join(source_dir, f"policy-demoedc-{connector_name}.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"Version": "2012-10-17"}, handle)
            for suffix in ("public.crt", "private.key"):
                with open(
                    os.path.join(source_certs_dir, f"{connector_name}-{suffix}"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(f"dummy-{suffix}")

            staged = adapter._stage_bootstrap_artifacts(connector_name, "demoedc", repo_dir)

            self.assertEqual(staged["credentials"], credentials_target)
            self.assertEqual(staged["policy"], policy_target)
            self.assertTrue(os.path.exists(credentials_target))
            self.assertTrue(os.path.exists(policy_target))
            with open(credentials_target, "r", encoding="utf-8") as handle:
                credentials = json.load(handle)
            self.assertEqual(
                credentials["certificates"]["path"],
                adapter._runtime_relative_path(certs_dir),
            )

    def test_stage_bootstrap_artifacts_does_not_overwrite_existing_topology_scoped_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.topology = "vm-single"
            repo_dir = os.path.join(tmpdir, "bootstrap")
            source_dir = os.path.join(repo_dir, "deployments", "DEV", "demoedc")
            os.makedirs(source_dir, exist_ok=True)

            connector_name = "conn-citycounciledc-demoedc"
            runtime_dir = os.path.join(tmpdir, "deployers", "edc", "deployments", "DEV", "vm-single", "demoedc")
            credentials_target = os.path.join(runtime_dir, "connectors", connector_name, "credentials.json")
            policy_target = os.path.join(runtime_dir, "connectors", connector_name, "policy.json")
            certs_dir = os.path.join(runtime_dir, "certs")
            os.makedirs(os.path.dirname(credentials_target), exist_ok=True)
            os.makedirs(certs_dir, exist_ok=True)
            adapter.config_adapter.edc_dataspace_runtime_dir = lambda ds_name=None: runtime_dir
            adapter.config_adapter.edc_connector_certs_dir = lambda ds_name=None: certs_dir
            adapter.config_adapter.edc_connector_credentials_path = (
                lambda name, ds_name=None, for_write=False: credentials_target
            )
            adapter.config_adapter.connector_minio_policy_path = (
                lambda name, ds_name=None, for_write=False: policy_target
            )

            with open(os.path.join(source_dir, f"credentials-connector-{connector_name}.json"), "w", encoding="utf-8") as handle:
                json.dump({"database": {"passwd": "legacy-password"}}, handle)
            with open(credentials_target, "w", encoding="utf-8") as handle:
                json.dump({"database": {"passwd": "fresh-password"}}, handle)

            adapter._stage_bootstrap_artifacts(connector_name, "demoedc", repo_dir)

            with open(credentials_target, "r", encoding="utf-8") as handle:
                credentials = json.load(handle)
            self.assertEqual(credentials["database"]["passwd"], "fresh-password")

    def test_load_connector_credentials_migrates_legacy_edc_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            del adapter.load_connector_credentials
            adapter.topology = "vm-single"
            repo_dir = os.path.join(tmpdir, "deployers", "edc")
            source_dir = os.path.join(repo_dir, "deployments", "DEV", "demoedc")
            source_certs_dir = os.path.join(source_dir, "certs")
            os.makedirs(source_certs_dir, exist_ok=True)

            connector_name = "conn-companyedc-demoedc"
            runtime_dir = os.path.join(
                tmpdir,
                "deployers",
                "edc",
                "deployments",
                "DEV",
                "vm-single",
                "demoedc",
            )
            credentials_target = os.path.join(
                runtime_dir,
                "connectors",
                connector_name,
                "credentials.json",
            )
            policy_target = os.path.join(
                runtime_dir,
                "connectors",
                connector_name,
                "policy.json",
            )
            certs_dir = os.path.join(runtime_dir, "certs")
            adapter.config_adapter.edc_deployment_dir = lambda: repo_dir
            adapter.config_adapter.edc_dataspace_runtime_dir = lambda ds_name=None: runtime_dir
            adapter.config_adapter.edc_connector_certs_dir = lambda ds_name=None: certs_dir
            adapter.config_adapter.edc_connector_credentials_path = (
                lambda name, ds_name=None, for_write=False: credentials_target
            )
            adapter.config_adapter.connector_minio_policy_path = (
                lambda name, ds_name=None, for_write=False: policy_target
            )
            adapter._dataspace_name = lambda: "demoedc"

            with open(
                os.path.join(source_dir, f"credentials-connector-{connector_name}.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "connector_user": {"user": "demo-user", "passwd": "demo-password"},
                        "minio": {"access_key": "demo-access", "secret_key": "demo-secret"},
                        "certificates": {
                            "path": "deployments/DEV/demoedc/certs",
                            "passwd": "certificate-password",
                        },
                    },
                    handle,
                )
            with open(
                os.path.join(source_dir, f"policy-demoedc-{connector_name}.json"),
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump({"Version": "2012-10-17"}, handle)
            with open(
                os.path.join(source_certs_dir, f"{connector_name}-public.crt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("dummy-public.crt")

            credentials = adapter.load_connector_credentials(connector_name)

            self.assertEqual(credentials["connector_user"]["user"], "demo-user")
            self.assertEqual(credentials["minio"]["access_key"], "demo-access")
            self.assertTrue(os.path.exists(credentials_target))
            self.assertTrue(os.path.exists(policy_target))

    def test_deploy_connectors_refuses_to_replace_non_edc_resources(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter._prepare_runtime_prerequisites = lambda: ("/tmp/repo", "/tmp/python")
        adapter.load_dataspace_connectors = lambda: [
            {
                "name": "demo",
                "namespace": "demo",
                "connectors": ["conn-citycouncil-demo"],
            }
        ]
        adapter._ensure_keycloak_realm_available = lambda ds_name, keycloak_url=None: True
        adapter._discover_existing_connectors = lambda ds_name, namespace, include_runtime_artifacts=True: set()
        adapter._conflicting_runtime_resources = lambda connector, namespace: [
            "deployment/conn-citycouncil-demo"
        ]

        with self.assertRaises(RuntimeError) as ctx:
            adapter.deploy_connectors()

        self.assertIn("Refusing to deploy generic EDC connector", str(ctx.exception))
        self.assertIn("deployment/conn-citycouncil-demo", str(ctx.exception))

    def test_deploy_connectors_raises_prerequisite_error_with_root_cause(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter._last_runtime_prerequisite_error = "Vault token is stale for the running common services"
        adapter._prepare_runtime_prerequisites = lambda: (None, None)

        with self.assertRaises(RuntimeError) as ctx:
            adapter.deploy_connectors()

        self.assertIn("Vault token is stale", str(ctx.exception))

    def test_deploy_connectors_stops_before_cleanup_or_image_build_when_dataspace_realm_is_missing(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter._prepare_runtime_prerequisites = lambda: ("/tmp/repo", "/tmp/python")
        adapter.load_dataspace_connectors = lambda: [
            {
                "name": "demoedc",
                "namespace": "demoedc",
                "connectors": ["conn-citycounciledc-demoedc"],
            }
        ]

        def missing_realm(ds_name, keycloak_url=None):
            adapter._last_runtime_prerequisite_error = (
                f"EDC Level 4 cannot continue because Keycloak realm '{ds_name}' does not exist. "
                "Run Level 3 for the EDC adapter before deploying connectors."
            )
            adapter._last_runtime_prerequisite_code = "keycloak_realm_missing"
            return False

        adapter._ensure_keycloak_realm_available = missing_realm
        adapter._discover_existing_connectors = mock.Mock(side_effect=AssertionError("cleanup discovery should not run"))
        adapter._maybe_prepare_level4_local_edc_images = mock.Mock(
            side_effect=AssertionError("image build should not run")
        )

        with self.assertRaisesRegex(RuntimeError, "Run Level 3 for the EDC adapter"):
            adapter.deploy_connectors()

        adapter._discover_existing_connectors.assert_not_called()
        adapter._maybe_prepare_level4_local_edc_images.assert_not_called()

    def test_deploy_connectors_prepares_local_edc_images_before_runtime_deploy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = os.path.join(tmpdir, "adapters", "edc", "scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            for script_name in (
                "build_image.sh",
                "build_dashboard_image.sh",
                "build_dashboard_proxy_image.sh",
            ):
                with open(os.path.join(scripts_dir, script_name), "w", encoding="utf-8") as handle:
                    handle.write("#!/usr/bin/env bash\n")

            events = []
            adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
            adapter.topology = "local"
            adapter.config = type(
                "Config",
                (),
                {
                    "script_dir": staticmethod(lambda: tmpdir),
                    "TIMEOUT_POD_WAIT": 120,
                    "NS_COMMON": "common-srvs",
                },
            )
            adapter.config_adapter = type(
                "ConfigAdapter",
                (),
                {
                    "load_deployer_config": staticmethod(
                        lambda: {
                            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                            "EDC_DASHBOARD_ENABLED": "true",
                        }
                    ),
                    "edc_dashboard_enabled": staticmethod(lambda: True),
                    "edc_dashboard_image_name": staticmethod(lambda: "validation-environment/edc-dashboard"),
                    "edc_dashboard_image_tag": staticmethod(lambda: "latest"),
                    "edc_dashboard_proxy_image_name": staticmethod(
                        lambda: "validation-environment/edc-dashboard-proxy"
                    ),
                    "edc_dashboard_proxy_image_tag": staticmethod(lambda: "latest"),
                    "edc_connector_dir": staticmethod(lambda: tmpdir),
                    "generate_connector_hosts": staticmethod(lambda connectors: list(connectors)),
                },
            )()

            def fake_run(command, **_kwargs):
                if "build_image.sh" in command:
                    events.append("build-connector-image")
                elif "build_dashboard_image.sh" in command:
                    events.append("build-dashboard-image")
                elif "build_dashboard_proxy_image.sh" in command:
                    events.append("build-dashboard-proxy-image")
                elif command.startswith("kubectl rollout restart deployment/"):
                    events.append(command)
                return object()

            adapter.run = fake_run
            adapter.run_silent = lambda *_args, **_kwargs: ""
            adapter._prepare_runtime_prerequisites = lambda: ("/tmp/repo", "/tmp/python")
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demoedc",
                    "namespace": "demoedc",
                    "connectors": ["conn-citycounciledc-demoedc"],
                }
            ]
            adapter._ensure_keycloak_realm_available = lambda ds_name, keycloak_url=None: True
            adapter._discover_existing_connectors = lambda ds_name, namespace, include_runtime_artifacts=True: set()
            adapter._conflicting_runtime_resources = lambda connector, namespace: []
            adapter._prepare_connector_prerequisites = lambda connector, ds_name, namespace, repo_dir, python_exec: (
                events.append("prepare-prerequisites") or True
            )
            adapter._render_values_file = (
                lambda connector, ds_name, connectors, connector_namespace=None: "/tmp/values.yaml"
            )
            adapter._wait_for_edc_deployment_rollout = (
                lambda deployment, namespace, timeout=300, label=None: (
                    events.append(f"wait-rollout:{deployment}") or True
                )
            )
            adapter._temporary_connector_kubeconfig = lambda connector: contextlib.nullcontext()
            adapter.wait_for_all_connectors = lambda connectors: True
            adapter.infrastructure = mock.Mock()
            adapter.infrastructure.deploy_helm_release.return_value = True

            with mock.patch.dict(os.environ, {}, clear=True):
                deployed = adapter.deploy_connectors()

        self.assertEqual(deployed, ["conn-citycounciledc-demoedc"])
        self.assertEqual(
            events,
            [
                "build-connector-image",
                "build-dashboard-image",
                "build-dashboard-proxy-image",
                "prepare-prerequisites",
                "kubectl rollout restart deployment/conn-citycounciledc-demoedc -n demoedc",
                "wait-rollout:conn-citycounciledc-demoedc",
                "kubectl rollout restart deployment/conn-citycounciledc-demoedc-dashboard -n demoedc",
                "wait-rollout:conn-citycounciledc-demoedc-dashboard",
                "kubectl rollout restart deployment/conn-citycounciledc-demoedc-dashboard-proxy -n demoedc",
                "wait-rollout:conn-citycounciledc-demoedc-dashboard-proxy",
            ],
        )
        adapter.infrastructure.deploy_helm_release.assert_called_once()

    def test_deploy_connectors_uses_planned_namespace_when_level4_role_aligned_opt_in_is_enabled(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "local"
        adapter.config = type(
            "Config",
            (),
            {
                "TIMEOUT_POD_WAIT": 120,
            },
        )
        adapter._prepare_runtime_prerequisites = lambda: ("/tmp/repo", "/tmp/python")
        adapter.load_dataspace_connectors = lambda: [
            {
                "name": "demoedc",
                "namespace": "demoedc",
                "namespace_profile": "role-aligned",
                "connectors": ["conn-citycounciledc-demoedc"],
                "connector_details": [
                    {
                        "name": "conn-citycounciledc-demoedc",
                        "role": "provider",
                        "runtime_namespace": "demoedc",
                        "active_namespace": "demoedc",
                        "planned_namespace": "demoedc-provider",
                        "registration_service_namespace": "demoedc-core",
                        "planned_registration_service_namespace": "demoedc-core",
                    }
                ],
            }
        ]
        adapter._ensure_keycloak_realm_available = lambda ds_name, keycloak_url=None: True
        adapter._discover_existing_connectors = lambda ds_name, namespace, include_runtime_artifacts=True: set()
        adapter._conflicting_runtime_resources = lambda connector, namespace: []
        adapter._maybe_prepare_level4_local_edc_images = lambda: True
        calls = []
        adapter._prepare_connector_prerequisites = lambda connector, ds_name, namespace, repo_dir, python_exec: (
            calls.append(("prepare", connector, namespace)) or True
        )
        adapter._render_values_file = lambda connector, ds_name, connectors, connector_namespace=None: (
            calls.append(("values", connector, connector_namespace)) or "/tmp/values.yaml"
        )
        adapter._edc_connector_dir = lambda: "/tmp/edc-connector-chart"
        adapter.config_adapter = mock.Mock()
        adapter.config_adapter.generate_connector_hosts.return_value = []
        adapter._wait_for_edc_deployment_rollout = lambda deployment, namespace, timeout=300, label=None: (
            calls.append(("rollout", deployment, namespace)) or True
        )
        adapter._restart_local_edc_deployments_if_needed = lambda connector, namespace, rollout_timeout=300: (
            calls.append(("restart", connector, namespace)) or True
        )

        @contextlib.contextmanager
        def connector_kubeconfig(connector):
            calls.append(("kubeconfig-enter", connector))
            try:
                yield
            finally:
                calls.append(("kubeconfig-exit", connector))

        adapter._temporary_connector_kubeconfig = connector_kubeconfig
        adapter.wait_for_all_connectors = lambda connectors: True
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.deploy_helm_release.return_value = True
        adapter._level4_role_aligned_connector_namespaces_requested = lambda: True

        deployed = adapter.deploy_connectors()

        self.assertEqual(deployed, ["conn-citycounciledc-demoedc"])
        self.assertEqual(
            calls,
            [
                ("prepare", "conn-citycounciledc-demoedc", "demoedc-provider"),
                ("values", "conn-citycounciledc-demoedc", "demoedc-provider"),
                ("kubeconfig-enter", "conn-citycounciledc-demoedc"),
                ("rollout", "conn-citycounciledc-demoedc", "demoedc-provider"),
                ("kubeconfig-exit", "conn-citycounciledc-demoedc"),
            ],
        )
        adapter.infrastructure.deploy_helm_release.assert_called_once_with(
            "conn-citycounciledc-demoedc-demoedc",
            "demoedc-provider",
            "/tmp/values.yaml",
            cwd=adapter._edc_connector_dir(),
        )

    def test_deploy_connectors_cleans_stale_connectors_in_discovered_target_namespace(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "local"
        adapter.config = type(
            "Config",
            (),
            {
                "TIMEOUT_POD_WAIT": 120,
            },
        )
        adapter._prepare_runtime_prerequisites = lambda: ("/tmp/repo", "/tmp/python")
        adapter.load_dataspace_connectors = lambda: [
            {
                "name": "demoedc",
                "namespace": "demoedc",
                "namespace_profile": "role-aligned",
                "connectors": ["conn-citycounciledc-demoedc"],
                "connector_details": [
                    {
                        "name": "conn-citycounciledc-demoedc",
                        "role": "provider",
                        "runtime_namespace": "demoedc",
                        "active_namespace": "demoedc",
                        "planned_namespace": "demoedc-provider",
                        "registration_service_namespace": "demoedc-core",
                        "planned_registration_service_namespace": "demoedc-core",
                    }
                ],
            }
        ]
        adapter._ensure_keycloak_realm_available = lambda ds_name, keycloak_url=None: True
        adapter._conflicting_runtime_resources = lambda connector, namespace: []
        adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
        adapter._maybe_prepare_level4_local_edc_images = lambda: True
        discovery_calls = []

        def discover_existing(ds_name, namespace, include_runtime_artifacts=True):
            discovery_calls.append((ds_name, namespace, include_runtime_artifacts))
            return {"conn-staleedc-demoedc"} if namespace == "demoedc-provider" else set()

        adapter._discover_existing_connectors = discover_existing
        cleanup_calls = []
        adapter._cleanup_connector_state = lambda connector, repo_dir, ds_name, python_exec, namespace=None: cleanup_calls.append(
            (connector, namespace)
        )
        calls = []
        adapter._prepare_connector_prerequisites = lambda connector, ds_name, namespace, repo_dir, python_exec: (
            calls.append(("prepare", connector, namespace)) or True
        )
        adapter._render_values_file = lambda connector, ds_name, connectors, connector_namespace=None: (
            calls.append(("values", connector, connector_namespace)) or "/tmp/values.yaml"
        )
        adapter._edc_connector_dir = lambda: "/tmp/edc-connector-chart"
        adapter.config_adapter = mock.Mock()
        adapter.config_adapter.generate_connector_hosts.return_value = []
        adapter._wait_for_edc_deployment_rollout = lambda deployment, namespace, timeout=300, label=None: (
            calls.append(("rollout", deployment, namespace)) or True
        )
        adapter._restart_local_edc_deployments_if_needed = lambda connector, namespace, rollout_timeout=300: (
            calls.append(("restart", connector, namespace)) or True
        )
        adapter._temporary_connector_kubeconfig = lambda connector: contextlib.nullcontext()
        adapter.wait_for_all_connectors = lambda connectors: True
        adapter.infrastructure = mock.Mock()
        adapter.infrastructure.deploy_helm_release.return_value = True

        deployed = adapter.deploy_connectors()

        self.assertEqual(deployed, ["conn-citycounciledc-demoedc"])
        self.assertEqual(
            discovery_calls,
            [
                ("demoedc", "demoedc-provider", False),
            ],
        )
        self.assertEqual(cleanup_calls, [("conn-staleedc-demoedc", "demoedc-provider")])
        self.assertEqual(
            calls,
            [
                ("prepare", "conn-citycounciledc-demoedc", "demoedc-provider"),
                ("values", "conn-citycounciledc-demoedc", "demoedc-provider"),
                ("rollout", "conn-citycounciledc-demoedc", "demoedc-provider"),
            ],
        )

    def test_get_cluster_connectors_prefers_namespace_scoped_discovery_for_role_aligned_edc_dataspace(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.topology = "local"
        adapter.config = type(
            "Config",
            (),
            {
                "namespace_demo": staticmethod(lambda: "demoedc"),
            },
        )
        adapter.load_dataspace_connectors = lambda: [
            {
                "name": "demoedc",
                "namespace": "demoedc",
                "namespace_profile": "role-aligned",
                "connectors": [
                    "conn-citycounciledc-demoedc",
                    "conn-companyedc-demoedc",
                ],
                "connector_details": [
                    {
                        "name": "conn-citycounciledc-demoedc",
                        "role": "provider",
                        "runtime_namespace": "demoedc",
                        "active_namespace": "demoedc",
                        "planned_namespace": "demoedc-provider",
                    },
                    {
                        "name": "conn-companyedc-demoedc",
                        "role": "consumer",
                        "runtime_namespace": "demoedc",
                        "active_namespace": "demoedc",
                        "planned_namespace": "demoedc-consumer",
                    },
                ],
            }
        ]
        adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
        discovery_calls = []

        def discover_existing(ds_name, namespace, include_runtime_artifacts=True):
            discovery_calls.append((ds_name, namespace, include_runtime_artifacts))
            if namespace == "demoedc-provider":
                return {"conn-citycounciledc-demoedc"}
            if namespace == "demoedc-consumer":
                return {"conn-companyedc-demoedc"}
            return set()

        adapter._discover_existing_connectors = discover_existing

        connectors = adapter.get_cluster_connectors()

        self.assertEqual(
            connectors,
            ["conn-citycounciledc-demoedc", "conn-companyedc-demoedc"],
        )
        self.assertEqual(
            discovery_calls,
            [
                ("demoedc", "demoedc-provider", False),
                ("demoedc", "demoedc-consumer", False),
            ],
        )

    def test_edc_discover_existing_connectors_uses_namespace_kubeconfig_context(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.load_dataspace_connectors = lambda: [
            {
                "name": "pionera-edc",
                "namespace": "edc-control",
                "connectors": [
                    "conn-citycounciledc-pionera-edc",
                    "conn-companyedc-pionera-edc",
                ],
            }
        ]
        adapter._edc_runtime_dir = lambda ds_name=None: "/tmp/non-existent-edc-runtime"

        active_namespace = {"value": None}
        entered_contexts = []
        run_calls = []

        @contextlib.contextmanager
        def temporary_namespace_kubeconfig(namespace, dataspace=None):
            entered_contexts.append((namespace, (dataspace or {}).get("name")))
            previous = active_namespace["value"]
            active_namespace["value"] = namespace
            try:
                yield
            finally:
                active_namespace["value"] = previous

        def run_silent(command):
            run_calls.append((active_namespace["value"], command))
            if command.startswith("helm list"):
                if active_namespace["value"] == "edc-provider":
                    return "conn-citycounciledc-pionera-edc-pionera-edc 1 2026-06-07 deployed\n"
                if active_namespace["value"] == "edc-consumer":
                    return "conn-companyedc-pionera-edc-pionera-edc 1 2026-06-07 deployed\n"
            return ""

        adapter._temporary_namespace_kubeconfig = temporary_namespace_kubeconfig
        adapter.run_silent = run_silent

        provider = adapter._discover_existing_connectors(
            "pionera-edc",
            "edc-provider",
            include_runtime_artifacts=False,
        )
        consumer = adapter._discover_existing_connectors(
            "pionera-edc",
            "edc-consumer",
            include_runtime_artifacts=False,
        )

        self.assertEqual(provider, {"conn-citycounciledc-pionera-edc"})
        self.assertEqual(consumer, {"conn-companyedc-pionera-edc"})
        self.assertEqual(
            entered_contexts,
            [("edc-provider", "pionera-edc"), ("edc-consumer", "pionera-edc")],
        )
        self.assertTrue(all(namespace in {"edc-provider", "edc-consumer"} for namespace, _ in run_calls))

    def test_preview_deploy_connectors_reports_render_summary_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demoedc",
                    "namespace": "demoedc",
                    "connectors": [
                        "conn-citycounciledc-demoedc",
                    ],
                }
            ]
            adapter._conflicting_runtime_resources = lambda connector, namespace: []

            preview = adapter.preview_deploy_connectors()

        self.assertEqual(preview["status"], "ready")
        connector = preview["dataspaces"][0]["connectors"][0]
        self.assertEqual(connector["status"], "ready")
        self.assertTrue(connector["credentials_present"])
        self.assertFalse(connector["bootstrap_required"])
        self.assertIsNotNone(connector["render_summary"])
        self.assertEqual(
            connector["render_summary"]["management_api_url"],
            "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm/management/v3",
        )
        self.assertEqual(
            connector["render_summary"]["dsp_url"],
            "http://conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm/protocol",
        )
        self.assertNotIn("secret-db", str(connector["render_summary"]))
        self.assertNotIn("vault-token", str(connector["render_summary"]))

    def test_preview_deploy_connectors_exposes_namespace_plan_metadata_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_adapter(tmpdir)
            adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demoedc",
                    "namespace": "demoedc",
                    "namespace_profile": "role-aligned",
                    "namespace_roles": {
                        "registration_service_namespace": "demoedc-core",
                        "provider_namespace": "demoedc",
                        "consumer_namespace": "demoedc",
                    },
                    "planned_namespace_roles": {
                        "registration_service_namespace": "demoedc-core",
                        "provider_namespace": "demoedc-provider",
                        "consumer_namespace": "demoedc-consumer",
                    },
                    "connector_roles": {
                        "provider": "conn-citycounciledc-demoedc",
                        "consumer": "conn-companyedc-demoedc",
                        "additional": [],
                    },
                    "connector_details": [
                        {
                            "name": "conn-citycounciledc-demoedc",
                            "role": "provider",
                            "runtime_namespace": "demoedc",
                            "active_namespace": "demoedc",
                            "planned_namespace": "demoedc-provider",
                            "registration_service_namespace": "demoedc-core",
                            "planned_registration_service_namespace": "demoedc-core",
                        },
                        {
                            "name": "conn-companyedc-demoedc",
                            "role": "consumer",
                            "runtime_namespace": "demoedc",
                            "active_namespace": "demoedc",
                            "planned_namespace": "demoedc-consumer",
                            "registration_service_namespace": "demoedc-core",
                            "planned_registration_service_namespace": "demoedc-core",
                        },
                    ],
                    "connectors": [
                        "conn-citycounciledc-demoedc",
                        "conn-companyedc-demoedc",
                    ],
                }
            ]
            adapter._conflicting_runtime_resources = lambda connector, namespace: []

            preview = adapter.preview_deploy_connectors()

        dataspace = preview["dataspaces"][0]
        self.assertEqual(dataspace["namespace_profile"], "role-aligned")
        self.assertEqual(dataspace["planned_namespace_roles"]["provider_namespace"], "demoedc-provider")
        first_connector = dataspace["connectors"][0]
        second_connector = dataspace["connectors"][1]
        self.assertEqual(first_connector["role"], "provider")
        self.assertEqual(first_connector["target_namespace"], "demoedc-provider")
        self.assertEqual(first_connector["planned_namespace"], "demoedc-provider")
        self.assertEqual(first_connector["registration_service_namespace"], "demoedc-core")
        self.assertEqual(second_connector["role"], "consumer")
        self.assertEqual(second_connector["target_namespace"], "demoedc-consumer")
        self.assertEqual(second_connector["planned_namespace"], "demoedc-consumer")

    def test_preview_deploy_connectors_renders_values_with_target_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._make_role_aligned_adapter(tmpdir)
            adapter._level4_role_aligned_connector_namespaces_requested = lambda: True
            adapter.load_dataspace_connectors = lambda: [
                {
                    "name": "demoedc",
                    "namespace": "demoedc",
                    "namespace_profile": "role-aligned",
                    "namespace_roles": {
                        "registration_service_namespace": "demoedc-core",
                        "provider_namespace": "demoedc",
                        "consumer_namespace": "demoedc",
                    },
                    "planned_namespace_roles": {
                        "registration_service_namespace": "demoedc-core",
                        "provider_namespace": "demoedc-provider",
                        "consumer_namespace": "demoedc-consumer",
                    },
                    "connector_roles": {
                        "provider": "conn-citycounciledc-demoedc",
                        "consumer": "conn-companyedc-demoedc",
                        "additional": [],
                    },
                    "connector_details": [
                        {
                            "name": "conn-citycounciledc-demoedc",
                            "role": "provider",
                            "runtime_namespace": "demoedc",
                            "active_namespace": "demoedc",
                            "planned_namespace": "demoedc-provider",
                            "registration_service_namespace": "demoedc-core",
                            "planned_registration_service_namespace": "demoedc-core",
                        }
                    ],
                    "connectors": [
                        "conn-citycounciledc-demoedc",
                    ],
                }
            ]
            adapter._conflicting_runtime_resources = lambda connector, namespace: []
            recorded_namespaces = []

            def fake_values_payload(connector_name, ds_name, connector_hostnames, connector_namespace=None):
                del connector_name, ds_name, connector_hostnames
                recorded_namespaces.append(connector_namespace)
                return {
                    "connector": {
                        "name": "conn-citycounciledc-demoedc",
                        "image": {"name": "ghcr.io/proyectopionera/edc-connector", "tag": "latest"},
                        "ingress": {
                            "hostname": "conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
                            "protocol": "http",
                        },
                    },
                    "services": {
                        "registrationService": {
                            "hostname": "demoedc-registration-service.demoedc-core.svc.cluster.local:8080",
                            "protocol": "http",
                        },
                        "db": {"name": "db_conn_citycounciledc_demoedc"},
                        "minio": {"bucket": "demoedc-conn-citycounciledc-demoedc"},
                    },
                    "hostAliases": [{"hostnames": ["keycloak.dev.ed.dataspaceunit.upm"]}],
                }

            adapter._connector_values_payload = fake_values_payload

            preview = adapter.preview_deploy_connectors()

        self.assertEqual(preview["status"], "ready")
        self.assertEqual(recorded_namespaces, ["demoedc-provider"])
        connector = preview["dataspaces"][0]["connectors"][0]
        self.assertEqual(connector["target_namespace"], "demoedc-provider")
        self.assertIsNotNone(connector["render_summary"])

    def test_prepare_connector_prerequisites_recreates_partial_bootstrap_when_runtime_is_missing(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.load_connector_credentials = lambda connector: {"database": {"name": "db", "user": "user", "passwd": "pw"}}
        adapter._edc_runtime_present = lambda connector, namespace: False
        adapter.wait_for_keycloak_admin_ready = lambda: True
        adapter._ensure_keycloak_realm_available = lambda ds_name, keycloak_url=None: True
        adapter.config_adapter = EdcConnectorConfigAdapter("/tmp")
        adapter._remove_edc_values_file = lambda connector, ds_name=None: None
        cleanup_calls = []
        adapter._cleanup_connector_state = lambda connector, repo_dir, ds_name, python_exec, namespace=None: cleanup_calls.append(
            (connector, ds_name, namespace)
        )
        adapter.run = lambda cmd, cwd=None, check=False: object()
        adapter.invalidate_management_api_token = lambda connector: None
        adapter.config = type(
            "Config",
            (),
            {
                "connector_credentials_path": staticmethod(lambda connector: "/tmp/missing-creds.json"),
                "NS_COMMON": "common-srvs",
            },
        )
        adapter.setup_minio_bucket = lambda namespace, ds_name, connector, credentials_path: True
        adapter.ensure_minio_policy_attached = lambda connector, ds_name=None: True
        adapter._reconcile_connector_vault_secrets = lambda connector, ds_name, credentials=None: True

        result = adapter._prepare_connector_prerequisites(
            "conn-citycounciledc-demoedc",
            "demoedc",
            "demoedc",
            "/tmp/repo",
            "/tmp/python",
        )

        self.assertTrue(result)
        self.assertEqual(
            cleanup_calls,
            [("conn-citycounciledc-demoedc", "demoedc", "demoedc")],
        )

    def test_prepare_connector_prerequisites_recreates_when_database_credentials_are_stale(self):
        adapter = EDCConnectorsAdapter.__new__(EDCConnectorsAdapter)
        adapter.load_connector_credentials = lambda connector: {"database": {"name": "db", "user": "user", "passwd": "pw"}}
        adapter._edc_runtime_present = lambda connector, namespace: True
        adapter._connector_database_credentials_query_valid = lambda connector, pg_host=None, pg_port=None: False
        adapter.wait_for_keycloak_admin_ready = lambda: True
        adapter._ensure_keycloak_realm_available = lambda ds_name, keycloak_url=None: True
        adapter.config_adapter = EdcConnectorConfigAdapter("/tmp")
        adapter._remove_edc_values_file = lambda connector, ds_name=None: None
        cleanup_calls = []
        adapter._cleanup_connector_state = lambda connector, repo_dir, ds_name, python_exec, namespace=None: cleanup_calls.append(
            (connector, ds_name, namespace)
        )
        adapter.run = lambda cmd, cwd=None, check=False: object()
        adapter.invalidate_management_api_token = lambda connector: None
        adapter.config = type(
            "Config",
            (),
            {
                "connector_credentials_path": staticmethod(lambda connector: "/tmp/missing-creds.json"),
                "NS_COMMON": "common-srvs",
            },
        )
        adapter.setup_minio_bucket = lambda namespace, ds_name, connector, credentials_path: True
        adapter.ensure_minio_policy_attached = lambda connector, ds_name=None: True
        adapter._reconcile_connector_vault_secrets = lambda connector, ds_name, credentials=None: True

        result = adapter._prepare_connector_prerequisites(
            "conn-citycounciledc-demoedc",
            "demoedc",
            "demoedc-provider",
            "/tmp/repo",
            "/tmp/python",
        )

        self.assertTrue(result)
        self.assertEqual(
            cleanup_calls,
            [("conn-citycounciledc-demoedc", "demoedc", "demoedc-provider")],
        )


if __name__ == "__main__":
    unittest.main()
