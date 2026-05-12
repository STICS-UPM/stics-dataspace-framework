import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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

    def test_edc_adapter_disables_kafka_transfer_validation_by_default(self):
        adapter = EdcAdapter(dry_run=True)
        self.assertFalse(adapter.supports_kafka_transfer_validation())


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

        connector_mock.assert_called_once_with("required")
        dashboard_mock.assert_called_once_with("auto")

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
            adapter._run_level4_edc_image_script = lambda script, args=None: (
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

    def test_edc_preview_components_marks_pending_support_without_deployable_urls(self):
        adapter = EdcAdapter(dry_run=True)
        adapter.config_adapter.load_deployer_config = lambda: {
            "ENVIRONMENT": "DEV",
            "DS_1_NAME": "demoedc",
            "DS_1_NAMESPACE": "demoedc",
            "COMPONENTS": "ontology-hub,ai-model-hub",
        }

        preview = adapter._preview_components()

        self.assertEqual(preview["status"], "pending-support")
        self.assertEqual(preview["action"], "skip")
        self.assertEqual(preview["configured"], ["ontology-hub", "ai-model-hub"])
        self.assertEqual(preview["deployable"], [])
        self.assertEqual(preview["pending_support"], ["ontology-hub", "ai-model-hub"])
        self.assertEqual(
            [component["status"] for component in preview["components"]],
            ["pending-support", "pending-support"],
        )
        self.assertEqual(
            [component["url"] for component in preview["components"]],
            [None, None],
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

    def _make_oidc_adapter(self, root):
        adapter = self._make_adapter(root)
        adapter.config_adapter = self.OidcEdcConnectorConfigAdapter(root)
        return adapter

    def _make_role_aligned_adapter(self, root):
        adapter = self._make_adapter(root)
        adapter.config_adapter = self.RoleAlignedEdcConnectorConfigAdapter(root)
        return adapter

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
        self.assertEqual(payload["connector"]["ingress"]["hostname"], "conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm")
        self.assertEqual(payload["connector"]["minio"]["accesskey"], "minio-access-key")
        self.assertEqual(payload["connector"]["minio"]["secretkey"], "minio-secret-key")
        self.assertEqual(payload["connector"]["transfer"]["privatekey"], "private-key")
        self.assertEqual(payload["connector"]["transfer"]["publickey"], "public-key")
        self.assertEqual(payload["services"]["keycloak"]["hostname"], "keycloak.dev.ed.dataspaceunit.upm")
        self.assertEqual(payload["services"]["minio"]["bucket"], "demoedc-conn-citycounciledc-demoedc")
        self.assertEqual(payload["services"]["vault"]["path"], "demoedc/conn-citycounciledc-demoedc/")
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
        self.assertEqual(proxy_config["cookieName"], "edc_dashboard_session")
        self.assertFalse(proxy_config["cookieSecure"])
        self.assertEqual(payload["dashboard"]["proxy"]["auth"]["connectors"], [])

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
        self.assertEqual(base_href, "/edc-dashboard/")

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
                "wait-rollout:conn-citycounciledc-demoedc",
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
                ("rollout", "conn-citycounciledc-demoedc", "demoedc-provider"),
                ("restart", "conn-citycounciledc-demoedc", "demoedc-provider"),
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
                ("restart", "conn-citycounciledc-demoedc", "demoedc-provider"),
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


if __name__ == "__main__":
    unittest.main()
