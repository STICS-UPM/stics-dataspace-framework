import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import adapters.inesdata.components as components_module
from adapters.inesdata.components import INESDataComponentsAdapter
from adapters.inesdata.infrastructure import INESDataInfrastructureAdapter
from adapters.shared.components import SharedComponentsAdapter


class FakeConfig:
    DS_NAME = "demo"

    @classmethod
    def script_dir(cls):
        return "/tmp"

    @classmethod
    def repo_dir(cls):
        return "/tmp/repo"

    @classmethod
    def namespace_demo(cls):
        return "demo"


class FakeInfrastructure:
    def __init__(self):
        self.deploy_calls = []
        self.deploy_envs = []
        self.vault_envs = []

    def ensure_local_infra_access(self):
        return True

    def ensure_vault_unsealed(self):
        self.vault_envs.append(
            (
                os.environ.get("KUBECONFIG"),
                os.environ.get("PIONERA_KUBECONFIG_ROLE"),
            )
        )
        return True

    def manage_hosts_entries(self, *args, **kwargs):
        return True

    def deploy_helm_release(self, *args, **kwargs):
        self.deploy_calls.append((args, kwargs))
        self.deploy_envs.append(
            (
                os.environ.get("KUBECONFIG"),
                os.environ.get("PIONERA_KUBECONFIG_ROLE"),
            )
        )
        return True


class InesdataComponentOverridesTests(unittest.TestCase):
    def _make_adapter(self, infrastructure=None):
        return INESDataComponentsAdapter(
            run=mock.Mock(return_value="ok"),
            run_silent=mock.Mock(return_value=""),
            auto_mode_getter=lambda: True,
            infrastructure_adapter=infrastructure or FakeInfrastructure(),
            config_cls=FakeConfig,
        )

    def _make_shared_adapter(self, infrastructure=None):
        return SharedComponentsAdapter(
            run=mock.Mock(return_value="ok"),
            run_silent=mock.Mock(return_value=""),
            auto_mode_getter=lambda: True,
            infrastructure_adapter=infrastructure or FakeInfrastructure(),
            config_cls=FakeConfig,
            active_adapter="inesdata",
        )

    def test_ontology_hub_hostname_prefers_deployer_config_inference(self):
        adapter = self._make_adapter()

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as handle:
            yaml.safe_dump(
                {
                    "ingress": {
                        "enabled": True,
                        "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    }
                },
                handle,
                sort_keys=False,
            )
            values_path = handle.name

        try:
            host = adapter._infer_component_hostname(
                "ontology-hub",
                values_path,
                {"DS_DOMAIN_BASE": "custom.ds.example.org"},
            )
        finally:
            os.unlink(values_path)

        self.assertEqual(host, "ontology-hub-demo.custom.ds.example.org")

    def test_ontology_hub_override_payload_derives_public_url_from_deployer_config(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {"DS_DOMAIN_BASE": "custom.ds.example.org"},
        )

        self.assertEqual(
            payload,
            {
                "ingress": {
                    "enabled": True,
                    "host": "ontology-hub-demo.custom.ds.example.org",
                },
                "env": {
                    "SELF_HOST_URL": "http://ontology-hub-demo.custom.ds.example.org",
                    "BASE_URL": "http://ontology-hub-demo.custom.ds.example.org",
                },
            },
        )

    def test_ontology_hub_override_payload_supports_org1_path_public_url(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {"COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es"},
        )

        self.assertEqual(
            payload,
            {
                "ingress": {
                    "enabled": True,
                    "host": "org1.pionera.oeg.fi.upm.es",
                    "path": "/ontology-hub(/|$)(.*)",
                    "pathType": "ImplementationSpecific",
                    "annotations": {
                        "nginx.ingress.kubernetes.io/use-regex": "true",
                        "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
                    },
                },
                "env": {
                    "SELF_HOST_URL": "http://org1.pionera.oeg.fi.upm.es/ontology-hub",
                    "BASE_URL": "https://org1.pionera.oeg.fi.upm.es/ontology-hub",
                },
                "versions": {
                    "persistence": {
                        "enabled": True,
                    },
                },
            },
        )

    def test_ontology_hub_override_payload_supports_explicit_self_host_url(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                "ONTOLOGY_HUB_SELF_HOST_URL": "http://ontology-hub.internal:3333",
            },
        )

        self.assertEqual(
            payload["env"],
            {
                "SELF_HOST_URL": "http://ontology-hub.internal:3333",
                "BASE_URL": "https://org1.pionera.oeg.fi.upm.es/ontology-hub",
            },
        )

    def test_ontology_hub_override_payload_uses_internal_service_for_vm_single(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
                "COMPONENTS_NAMESPACE": "components",
            },
        )

        self.assertEqual(
            payload["env"],
            {
                "SELF_HOST_URL": "http://demo-ontology-hub.components:3333",
                "BASE_URL": "https://org4.pionera.oeg.fi.upm.es/ontology-hub",
            },
        )

    def test_ontology_hub_override_payload_allows_vm_single_internal_service_override(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
                "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME": "custom-ontology",
                "ONTOLOGY_HUB_SELF_HOST_NAMESPACE": "custom-components",
                "ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT": "13333",
            },
        )

        self.assertEqual(
            payload["env"],
            {
                "SELF_HOST_URL": "http://custom-ontology.custom-components:13333",
                "BASE_URL": "https://org4.pionera.oeg.fi.upm.es/ontology-hub",
            },
        )

    def test_ontology_hub_versions_persistence_is_enabled_by_default_for_vm_single(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
            },
        )

        self.assertEqual(
            payload["versions"],
            {
                "persistence": {
                    "enabled": True,
                },
            },
        )

    def test_ontology_hub_disables_elasticsearch_disk_threshold_by_default_for_vm_single_k3s(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter._cluster_runtime = mock.Mock(return_value={"cluster_type": "k3s"})

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
            },
        )

        self.assertEqual(
            payload["elasticsearch"],
            {
                "diskThreshold": {
                    "enabled": False,
                },
            },
        )

    def test_ontology_hub_elasticsearch_disk_threshold_can_be_overridden(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter._cluster_runtime = mock.Mock(return_value={"cluster_type": "k3s"})

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
                "ONTOLOGY_HUB_ELASTICSEARCH_DISK_THRESHOLD_ENABLED": "true",
                "ONTOLOGY_HUB_ELASTICSEARCH_DISK_WATERMARK_HIGH": "95%",
            },
        )

        self.assertEqual(
            payload["elasticsearch"],
            {
                "diskThreshold": {
                    "enabled": True,
                    "high": "95%",
                },
            },
        )

    def test_ontology_hub_versions_persistence_can_be_disabled_for_external_topologies(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_ENABLED": "false",
                "ONTOLOGY_HUB_VERSIONS_PERSISTENCE_SIZE": "2Gi",
            },
        )

        self.assertEqual(
            payload["versions"],
            {
                "persistence": {
                    "enabled": False,
                    "size": "2Gi",
                },
            },
        )

    def test_ontology_hub_public_root_alias_ingress_routes_absolute_app_paths(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"

        ingress = adapter._ontology_hub_public_root_alias_ingress(
            "pionera-ontology-hub",
            "components",
            {
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_PATH_REWRITE": "true",
            },
        )

        self.assertIsNotNone(ingress)
        self.assertEqual(ingress["metadata"]["name"], "pionera-ontology-hub-public-root-aliases")
        self.assertEqual(ingress["metadata"]["namespace"], "components")
        self.assertEqual(ingress["spec"]["rules"][0]["host"], "org1.pionera.oeg.fi.upm.es")
        paths = ingress["spec"]["rules"][0]["http"]["paths"]
        self.assertEqual(
            [path["path"] for path in paths],
            ["/dataset", "/edition", "/css", "/js", "/img"],
        )
        self.assertTrue(all(path["pathType"] == "Prefix" for path in paths))
        self.assertTrue(all(path["backend"]["service"]["name"] == "pionera-ontology-hub" for path in paths))

    def test_ontology_hub_public_root_alias_ingress_routes_absolute_app_paths_for_vm_single(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-single"

        ingress = adapter._ontology_hub_public_root_alias_ingress(
            "pionera-ontology-hub",
            "components",
            {
                "VM_SINGLE_PUBLIC_URL": "https://org4.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_PATH_REWRITE": "true",
            },
        )

        self.assertIsNotNone(ingress)
        self.assertEqual(ingress["spec"]["rules"][0]["host"], "org4.pionera.oeg.fi.upm.es")
        self.assertEqual(ingress["metadata"]["labels"]["app.kubernetes.io/part-of"], "vm-single")
        paths = ingress["spec"]["rules"][0]["http"]["paths"]
        self.assertEqual(
            [path["path"] for path in paths],
            ["/dataset", "/edition", "/css", "/js", "/img"],
        )

    def test_ontology_hub_public_root_alias_ingress_is_external_topology_only(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "local"

        ingress = adapter._ontology_hub_public_root_alias_ingress(
            "pionera-ontology-hub",
            "components",
            {"COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es"},
        )

        self.assertIsNone(ingress)

    def test_ontology_hub_public_root_alias_apply_uses_components_kubeconfig_for_vm_distributed(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig_common": "/clusters/common.yaml",
            "k3s_kubeconfig_components": "/clusters/components.yaml",
        }
        calls = []

        def record_run(command, **_kwargs):
            calls.append(
                (
                    command,
                    os.environ.get("KUBECONFIG"),
                    os.environ.get("PIONERA_KUBECONFIG_ROLE"),
                )
            )
            return "ok"

        adapter.run = record_run

        with mock.patch.dict(
            os.environ,
            {"KUBECONFIG": "/clusters/common.yaml", "PIONERA_KUBECONFIG_ROLE": "common"},
        ):
            aliases = adapter._sync_ontology_hub_public_root_alias_ingress(
                "pionera-ontology-hub",
                "components",
                {
                    "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                    "COMPONENTS_PUBLIC_PATH_REWRITE": "true",
                },
            )
            restored = (os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE"))

        self.assertTrue(aliases)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].startswith("kubectl apply -f "))
        self.assertEqual(calls[0][1], "/clusters/components.yaml")
        self.assertEqual(calls[0][2], "components")
        self.assertEqual(restored, ("/clusters/common.yaml", "common"))

    def test_component_kubeconfig_uses_vm_single_k3s_kubeconfig(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig": "/clusters/pionera4.yaml",
        }

        with mock.patch.dict(
            os.environ,
            {"KUBECONFIG": "/clusters/minikube.yaml", "PIONERA_KUBECONFIG_ROLE": "local"},
        ):
            with adapter._temporary_component_kubeconfig({"CLUSTER_TYPE": "k3s"}):
                observed = (os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE"))
            restored = (os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE"))

        self.assertEqual(observed, ("/clusters/pionera4.yaml", "components"))
        self.assertEqual(restored, ("/clusters/minikube.yaml", "local"))

    def test_ontology_hub_public_root_alias_apply_skips_paths_owned_by_other_ingresses(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig_components": "/clusters/components.yaml",
        }
        applied = []

        def fake_run(command, **_kwargs):
            applied.append(command)
            return "ok"

        adapter.run = fake_run
        adapter.run_silent = mock.Mock(
            return_value="""{
                "items": [
                    {
                        "metadata": {"namespace": "common-srvs", "name": "common-srvs-minio-console-public-root-aliases"},
                        "spec": {
                            "rules": [
                                {
                                    "host": "org1.pionera.oeg.fi.upm.es",
                                    "http": {"paths": [{"path": "/favicon.ico"}]}
                                }
                            ]
                        }
                    }
                ]
            }"""
        )

        aliases = adapter._sync_ontology_hub_public_root_alias_ingress(
            "pionera-ontology-hub",
            "components",
            {
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_PATH_REWRITE": "true",
                "ONTOLOGY_HUB_PUBLIC_ROOT_ALIASES": "/dataset,/edition,/css,/js,/img,/favicon.ico",
            },
        )

        self.assertEqual(len(applied), 1)
        self.assertNotIn("favicon.ico", aliases)
        self.assertEqual(
            aliases,
            [
                "https://org1.pionera.oeg.fi.upm.es/dataset",
                "https://org1.pionera.oeg.fi.upm.es/edition",
                "https://org1.pionera.oeg.fi.upm.es/css",
                "https://org1.pionera.oeg.fi.upm.es/js",
                "https://org1.pionera.oeg.fi.upm.es/img",
            ],
        )

    def test_ontology_hub_override_payload_adds_host_alias_for_public_self_url(self):
        adapter = self._make_adapter()

        with mock.patch.object(
            adapter,
            "_resolve_ontology_hub_self_host_alias_ip",
            return_value="10.102.17.235",
        ):
            payload = adapter._component_values_override_payload(
                "ontology-hub",
                {"DS_DOMAIN_BASE": "custom.ds.example.org"},
            )

        self.assertEqual(
            payload,
            {
                "ingress": {
                    "enabled": True,
                    "host": "ontology-hub-demo.custom.ds.example.org",
                },
                "env": {
                    "SELF_HOST_URL": "http://ontology-hub-demo.custom.ds.example.org",
                    "BASE_URL": "http://ontology-hub-demo.custom.ds.example.org",
                },
                "hostAliases": [
                    {
                        "ip": "10.102.17.235",
                        "hostnames": ["ontology-hub-demo.custom.ds.example.org"],
                    }
                ],
            },
        )

    def test_ai_model_hub_override_payload_derives_public_url_and_connector_config(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "ai-model-hub",
            {
                "DS_DOMAIN_BASE": "custom.ds.example.org",
                "DS_1_CONNECTORS": "citycouncil,company",
            },
        )

        self.assertEqual(
            payload,
            {
                "ingress": {
                    "enabled": True,
                    "host": "ai-model-hub-demo.custom.ds.example.org",
                },
                "config": {
                    "edcConnectorConfig": [
                        {
                            "connectorName": "Consumer",
                            "managementUrl": "http://conn-company-demo.custom.ds.example.org/management",
                            "defaultUrl": "http://conn-company-demo.custom.ds.example.org/api",
                            "protocolUrl": "http://conn-company-demo.custom.ds.example.org/protocol",
                            "federatedCatalogEnabled": False,
                        },
                        {
                            "connectorName": "Provider",
                            "managementUrl": "http://conn-citycouncil-demo.custom.ds.example.org/management",
                            "defaultUrl": "http://conn-citycouncil-demo.custom.ds.example.org/api",
                            "protocolUrl": "http://conn-citycouncil-demo.custom.ds.example.org/protocol",
                            "federatedCatalogEnabled": False,
                        },
                    ]
                },
            },
        )

    def test_ai_model_hub_override_payload_uses_public_management_and_internal_protocol_urls(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "ai-model-hub",
            {
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_1_CONNECTORS": "org2,org3",
                "VM_PROVIDER_PUBLIC_URL": "https://org2.pionera.oeg.fi.upm.es",
                "VM_CONSUMER_PUBLIC_URL": "https://org3.pionera.oeg.fi.upm.es",
                "CONNECTOR_PROTOCOL_ADDRESS_MODE": "internal",
            },
        )

        self.assertEqual(
            payload["config"]["edcConnectorConfig"],
            [
                {
                    "connectorName": "Consumer",
                    "managementUrl": "https://org3.pionera.oeg.fi.upm.es/management",
                    "defaultUrl": "https://org3.pionera.oeg.fi.upm.es/api",
                    "protocolUrl": "http://conn-org3-demo.pionera.oeg.fi.upm.es/protocol",
                    "federatedCatalogEnabled": False,
                },
                {
                    "connectorName": "Provider",
                    "managementUrl": "https://org2.pionera.oeg.fi.upm.es/management",
                    "defaultUrl": "https://org2.pionera.oeg.fi.upm.es/api",
                    "protocolUrl": "http://conn-org2-demo.pionera.oeg.fi.upm.es/protocol",
                    "federatedCatalogEnabled": False,
                },
            ],
        )

    def test_ai_model_hub_override_payload_uses_vm_single_public_connector_paths(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"

        payload = adapter._component_values_override_payload(
            "ai-model-hub",
            {
                "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
                "DS_1_CONNECTORS": "org2,org3",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
            },
        )

        self.assertEqual(
            payload["config"]["edcConnectorConfig"],
            [
                {
                    "connectorName": "Consumer",
                    "managementUrl": "https://org4.pionera.oeg.fi.upm.es/c/org3/management",
                    "defaultUrl": "https://org4.pionera.oeg.fi.upm.es/c/org3/api",
                    "protocolUrl": "https://org4.pionera.oeg.fi.upm.es/c/org3/protocol",
                    "federatedCatalogEnabled": False,
                },
                {
                    "connectorName": "Provider",
                    "managementUrl": "https://org4.pionera.oeg.fi.upm.es/c/org2/management",
                    "defaultUrl": "https://org4.pionera.oeg.fi.upm.es/c/org2/api",
                    "protocolUrl": "https://org4.pionera.oeg.fi.upm.es/c/org2/protocol",
                    "federatedCatalogEnabled": False,
                },
            ],
        )

    def test_semantic_virtualization_override_payload_derives_public_url(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "semantic-virtualization",
            {"DS_DOMAIN_BASE": "custom.ds.example.org"},
        )

        self.assertEqual(
            payload,
            {
                "ingress": {
                    "enabled": True,
                    "host": "semantic-virtualization-demo.custom.ds.example.org",
                },
                "env": {
                    "SEMANTIC_VIRTUALIZATION_PUBLIC_URL": "http://semantic-virtualization-demo.custom.ds.example.org",
                },
            },
        )

    def test_semantic_virtualization_mapping_editor_override_is_opt_in(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "semantic-virtualization",
            {
                "DS_DOMAIN_BASE": "custom.ds.example.org",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
            },
        )

        self.assertEqual(
            payload["mappingEditor"],
            {
                "enabled": True,
                "ingress": {
                    "enabled": True,
                    "host": "semantic-virtualization-editor-demo.custom.ds.example.org",
                },
            },
        )

    def test_semantic_virtualization_mapping_editor_override_prefers_explicit_host(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "semantic-virtualization",
            {
                "DS_DOMAIN_BASE": "custom.ds.example.org",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST": "http://editor.example.test",
            },
        )

        self.assertEqual(
            payload["mappingEditor"]["ingress"]["host"],
            "editor.example.test",
        )

    def test_semantic_virtualization_mapping_editor_host_port_skips_ingress(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "semantic-virtualization",
            {
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL": "https://streamlit.example.org",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_EXPOSURE_MODE": "host-port",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST_PORT": "5678",
            },
        )

        self.assertEqual(
            payload["mappingEditor"],
            {
                "enabled": True,
                "hostPort": {
                    "enabled": True,
                    "port": 5678,
                },
            },
        )

    def test_semantic_virtualization_mapping_editor_nodeport_is_configurable(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "semantic-virtualization",
            {
                "DS_DOMAIN_BASE": "custom.ds.example.org",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_SERVICE_TYPE": "NodePort",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_NODE_PORT": "31078",
            },
        )

        self.assertEqual(
            payload["mappingEditor"]["service"],
            {
                "type": "NodePort",
                "nodePort": 31078,
            },
        )
        self.assertEqual(
            payload["mappingEditor"]["ingress"]["host"],
            "semantic-virtualization-editor-demo.custom.ds.example.org",
        )

    def test_component_override_payload_accepts_prebuilt_image_ref(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "ai-model-hub",
            {
                "AI_MODEL_HUB_IMAGE_REF": "registry.example.org:5000/pionera/ai-model-hub:1.0.0",
                "COMPONENTS_IMAGE_PULL_POLICY": "IfNotPresent",
            },
        )

        self.assertEqual(
            payload["image"],
            {
                "repository": "registry.example.org:5000/pionera/ai-model-hub",
                "tag": "1.0.0",
                "pullPolicy": "IfNotPresent",
            },
        )

    def test_component_override_payload_accepts_prebuilt_repository_and_tag(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "ontology-hub",
            {
                "ONTOLOGY_HUB_IMAGE_REPOSITORY": "registry.example.org/pionera/ontology-hub",
                "ONTOLOGY_HUB_IMAGE_TAG": "2026.06.05",
                "ONTOLOGY_HUB_IMAGE_PULL_POLICY": "Always",
            },
        )

        self.assertEqual(
            payload["image"],
            {
                "repository": "registry.example.org/pionera/ontology-hub",
                "tag": "2026.06.05",
                "pullPolicy": "Always",
            },
        )

    def test_component_override_payload_rejects_prebuilt_image_without_tag(self):
        adapter = self._make_adapter()

        with self.assertRaisesRegex(RuntimeError, "Invalid prebuilt component image reference"):
            adapter._component_values_override_payload(
                "ai-model-hub",
                {"AI_MODEL_HUB_IMAGE_REF": "registry.example.org/pionera/ai-model-hub"},
            )

    def test_component_override_payload_rejects_incomplete_prebuilt_image_parts(self):
        adapter = self._make_adapter()

        with self.assertRaisesRegex(RuntimeError, "Incomplete prebuilt component image configuration"):
            adapter._component_values_override_payload(
                "ontology-hub",
                {"ONTOLOGY_HUB_IMAGE_REPOSITORY": "registry.example.org/pionera/ontology-hub"},
            )

    def test_semantic_virtualization_mapping_editor_accepts_prebuilt_image_ref(self):
        adapter = self._make_adapter()

        payload = adapter._component_values_override_payload(
            "semantic-virtualization",
            {
                "DS_DOMAIN_BASE": "custom.ds.example.org",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF": "registry.example.org/pionera/mapping-editor:2.0.0",
                "COMPONENTS_IMAGE_PULL_POLICY": "IfNotPresent",
            },
        )

        self.assertEqual(
            payload["mappingEditor"]["image"],
            {
                "repository": "registry.example.org/pionera/mapping-editor",
                "tag": "2.0.0",
                "pullPolicy": "IfNotPresent",
            },
        )

    def test_effective_component_values_merges_mapping_editor_image_override(self):
        adapter = self._make_adapter()

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as handle:
            yaml.safe_dump(
                {
                    "image": {"repository": "morph-kgv", "tag": "local"},
                    "mappingEditor": {
                        "enabled": True,
                        "image": {"repository": "mapping-editor", "tag": "local"},
                    },
                },
                handle,
                sort_keys=False,
            )
            values_path = handle.name

        try:
            values = adapter._effective_component_values(
                "semantic-virtualization",
                values_path,
                {
                    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                    "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF": (
                        "registry.example.org/pionera/mapping-editor:2.0.0"
                    ),
                    "COMPONENTS_IMAGE_PULL_POLICY": "IfNotPresent",
                },
            )
        finally:
            os.unlink(values_path)

        self.assertEqual(
            values["mappingEditor"]["image"],
            {
                "repository": "registry.example.org/pionera/mapping-editor",
                "tag": "2.0.0",
                "pullPolicy": "IfNotPresent",
            },
        )

    def test_shared_components_adapter_plans_override_values_payload(self):
        adapter = self._make_shared_adapter()

        plan = adapter.plan_component_override_values(
            "ontology-hub",
            chart_dir="/tmp/chart",
            deployer_config={"DS_DOMAIN_BASE": "custom.ds.example.org"},
        )

        self.assertEqual(plan["normalized_component"], "ontology-hub")
        self.assertEqual(plan["chart_dir"], "/tmp/chart")
        self.assertTrue(plan["has_override"])
        self.assertEqual(plan["filename_prefix"], "ontology-hub-override-")
        self.assertEqual(
            plan["payload"],
            {
                "ingress": {
                    "enabled": True,
                    "host": "ontology-hub-demo.custom.ds.example.org",
                },
                "env": {
                    "SELF_HOST_URL": "http://ontology-hub-demo.custom.ds.example.org",
                    "BASE_URL": "http://ontology-hub-demo.custom.ds.example.org",
                },
            },
        )

    def test_resolve_ontology_hub_self_host_alias_ip_prefers_explicit_valid_ip(self):
        adapter = self._make_adapter()

        ip = adapter._resolve_ontology_hub_self_host_alias_ip(
            {"ONTOLOGY_HUB_SELF_HOST_ALIAS_IP": "10.102.17.235"}
        )

        self.assertEqual(ip, "10.102.17.235")

    def test_resolve_ontology_hub_self_host_alias_ip_reads_ingress_service_cluster_ip(self):
        adapter = self._make_adapter()
        adapter.run_silent = mock.Mock(return_value="10.102.17.235")

        ip = adapter._resolve_ontology_hub_self_host_alias_ip({})

        self.assertEqual(ip, "10.102.17.235")
        adapter.run_silent.assert_called_once_with(
            "kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.spec.clusterIP}'"
        )

    def test_deploy_helm_release_supports_multiple_values_files(self):
        run = mock.Mock(return_value="ok")
        infra = INESDataInfrastructureAdapter(
            run=run,
            run_silent=mock.Mock(return_value=""),
            auto_mode_getter=lambda: True,
        )

        result = infra.deploy_helm_release(
            "demo-ontology-hub",
            "demo",
            ["values-demo.yaml", "/tmp/ontology-hub-override.yaml"],
            cwd="/tmp/chart",
        )

        self.assertTrue(result)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn("-f values-demo.yaml", command)
        self.assertIn("-f /tmp/ontology-hub-override.yaml", command)
        self.assertEqual(run.call_args.kwargs["cwd"], "/tmp/chart")

    def test_deploy_helm_release_retries_transient_failure(self):
        run = mock.Mock(side_effect=[None, "ok"])
        infra = INESDataInfrastructureAdapter(
            run=run,
            run_silent=mock.Mock(return_value=""),
            auto_mode_getter=lambda: True,
        )

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_HELM_DEPLOY_ATTEMPTS": "2",
                "PIONERA_HELM_DEPLOY_RETRY_DELAY_SECONDS": "0",
            },
        ):
            result = infra.deploy_helm_release(
                "demo-semantic-virtualization",
                "components",
                ["values.yaml", "/tmp/semantic-virtualization-override.yaml"],
                cwd="/tmp/chart",
            )

        self.assertTrue(result)
        self.assertEqual(run.call_count, 2)

    def test_deploy_helm_release_returns_false_after_retry_budget(self):
        run = mock.Mock(return_value=None)
        infra = INESDataInfrastructureAdapter(
            run=run,
            run_silent=mock.Mock(return_value=""),
            auto_mode_getter=lambda: True,
        )

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_HELM_DEPLOY_ATTEMPTS": "2",
                "PIONERA_HELM_DEPLOY_RETRY_DELAY_SECONDS": "0",
            },
        ):
            result = infra.deploy_helm_release(
                "demo-semantic-virtualization",
                "components",
                "values.yaml",
                cwd="/tmp/chart",
            )

        self.assertFalse(result)
        self.assertEqual(run.call_count, 2)

    def test_legacy_component_runtime_keeps_ontology_hub_override_and_namespace(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_adapter(infrastructure=infrastructure)

        with tempfile.TemporaryDirectory() as chart_dir:
            values_file = os.path.join(chart_dir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"ingress": {"enabled": False}}, handle, sort_keys=False)

            with mock.patch.object(adapter, "_cleanup_components", return_value=None), mock.patch.object(
                adapter.config,
                "repo_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_chart_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_values_file",
                return_value=values_file,
            ), mock.patch.object(
                adapter,
                "_resolve_component_release_name",
                return_value="demo-ontology-hub",
            ), mock.patch.object(
                adapter,
                "_maybe_prepare_level6_local_image",
                return_value=False,
            ), mock.patch.object(
                adapter,
                "_wait_for_component_rollout",
                return_value=True,
            ):
                result = adapter.deploy_components(
                    ["ontology-hub"],
                    ds_name="demo",
                    namespace="components",
                    deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
                )

        self.assertEqual(result["deployed"], ["ontology-hub"])
        self.assertEqual(len(infrastructure.deploy_calls), 1)
        args, kwargs = infrastructure.deploy_calls[0]
        self.assertEqual(args[0], "demo-ontology-hub")
        self.assertEqual(args[1], "components")
        self.assertEqual(kwargs["cwd"], chart_dir)
        self.assertEqual(args[2][0], "values-demo.yaml")
        self.assertEqual(len(args[2]), 2)
        self.assertTrue(os.path.basename(args[2][1]).startswith("ontology-hub-override-"))

    def test_legacy_component_runtime_uses_vm_single_k3s_kubeconfig_for_helm(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_adapter(infrastructure=infrastructure)
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig": "/clusters/pionera4.yaml",
        }

        with tempfile.TemporaryDirectory() as chart_dir:
            values_file = os.path.join(chart_dir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"ingress": {"enabled": False}}, handle, sort_keys=False)

            with mock.patch.object(adapter, "_cleanup_components", return_value=None), mock.patch.object(
                adapter,
                "_cleanup_legacy_component_releases",
                return_value=None,
            ), mock.patch.object(
                adapter,
                "_cleanup_vm_distributed_legacy_public_path_ingresses",
                return_value=None,
            ), mock.patch.object(
                adapter.config,
                "repo_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_chart_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_values_file",
                return_value=values_file,
            ), mock.patch.object(
                adapter,
                "_resolve_component_release_name",
                return_value="demo-ai-model-hub",
            ), mock.patch.object(
                adapter,
                "_maybe_prepare_level6_local_image",
                return_value=False,
            ), mock.patch.object(
                adapter,
                "_wait_for_component_rollout",
                return_value=True,
            ), mock.patch.dict(
                os.environ,
                {"KUBECONFIG": "/clusters/minikube.yaml", "PIONERA_KUBECONFIG_ROLE": "local"},
            ):
                result = adapter.deploy_components(
                    ["ai-model-hub"],
                    ds_name="demo",
                    namespace="components",
                    deployer_config={
                        "CLUSTER_TYPE": "k3s",
                        "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
                        "VM_SINGLE_HTTP_URL": "https://org4.example.test",
                        "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "false",
                        "LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE": "true",
                    },
                )
                restored = (os.environ.get("KUBECONFIG"), os.environ.get("PIONERA_KUBECONFIG_ROLE"))

        self.assertEqual(result["deployed"], ["ai-model-hub"])
        self.assertEqual(infrastructure.vault_envs[0], ("/clusters/pionera4.yaml", "components"))
        self.assertEqual(infrastructure.deploy_envs[0], ("/clusters/pionera4.yaml", "components"))
        self.assertEqual(restored, ("/clusters/minikube.yaml", "local"))

    def test_component_image_preparation_failure_keeps_existing_deployment(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_adapter(infrastructure=infrastructure)
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig": "/clusters/pionera4.yaml",
        }

        with tempfile.TemporaryDirectory() as chart_dir:
            values_file = os.path.join(chart_dir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"image": {"repository": "example/component", "tag": "local"}}, handle, sort_keys=False)

            cleanup_components = mock.Mock(return_value=None)
            cleanup_legacy = mock.Mock(return_value=None)
            cleanup_legacy_ingresses = mock.Mock(return_value=None)
            with mock.patch.object(adapter, "_cleanup_components", cleanup_components), mock.patch.object(
                adapter,
                "_cleanup_legacy_component_releases",
                cleanup_legacy,
            ), mock.patch.object(
                adapter,
                "_cleanup_vm_distributed_legacy_public_path_ingresses",
                cleanup_legacy_ingresses,
            ), mock.patch.object(
                adapter.config,
                "repo_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_chart_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_values_file",
                return_value=values_file,
            ), mock.patch.object(
                adapter,
                "_resolve_component_release_name",
                return_value="demo-ai-model-hub",
            ), mock.patch.object(
                adapter,
                "_maybe_prepare_level6_local_image",
                side_effect=RuntimeError("image import failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Error preparing local images"):
                    adapter.deploy_components(
                        ["ai-model-hub"],
                        ds_name="demo",
                        namespace="components",
                        deployer_config={
                            "CLUSTER_TYPE": "k3s",
                            "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
                        },
                    )

        cleanup_legacy.assert_not_called()
        cleanup_components.assert_not_called()
        cleanup_legacy_ingresses.assert_not_called()
        self.assertEqual(infrastructure.deploy_calls, [])

    def test_vm_single_k3s_local_image_auto_build_disabled_keeps_existing_deployment(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_adapter(infrastructure=infrastructure)
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig": "/clusters/pionera4.yaml",
        }

        with tempfile.TemporaryDirectory() as chart_dir:
            values_file = os.path.join(chart_dir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                yaml.safe_dump({"image": {"repository": "eclipse-edc/data-dashboard", "tag": "local"}}, handle, sort_keys=False)

            cleanup_components = mock.Mock(return_value=None)
            with mock.patch.object(adapter, "_cleanup_components", cleanup_components), mock.patch.object(
                adapter.config,
                "repo_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_chart_dir",
                return_value=chart_dir,
            ), mock.patch.object(
                adapter,
                "_resolve_component_values_file",
                return_value=values_file,
            ), mock.patch.object(
                adapter,
                "_resolve_component_release_name",
                return_value="demo-ai-model-hub",
            ):
                with self.assertRaisesRegex(RuntimeError, "Local image auto-build disabled"):
                    adapter.deploy_components(
                        ["ai-model-hub"],
                        ds_name="demo",
                        namespace="components",
                        deployer_config={
                            "CLUSTER_TYPE": "k3s",
                            "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
                            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "false",
                        },
                    )

        cleanup_components.assert_not_called()
        self.assertEqual(infrastructure.deploy_calls, [])

    def test_resolve_ontology_hub_source_dir_uses_canonical_checkout_even_if_override_is_present(self):
        adapter = self._make_adapter()
        sources_dir = os.path.join(
            os.path.dirname(os.path.abspath(components_module.__file__)),
            "sources",
            "Ontology-Hub",
        )
        fallback_dockerfile = os.path.join(sources_dir, "Dockerfile")

        def fake_isfile(path):
            if path == fallback_dockerfile:
                return True
            return False

        with mock.patch("adapters.inesdata.components.os.path.isfile", side_effect=fake_isfile):
            resolved = adapter._resolve_ontology_hub_source_dir(
                {"ONTOLOGY_HUB_SOURCE_DIR": "/tmp/custom-ontology-hub"}
            )

        self.assertEqual(resolved, sources_dir)

    def test_resolve_ontology_hub_source_dir_clones_when_sources_dir_exists_but_is_empty(self):
        adapter = self._make_adapter()
        sources_dir = os.path.join(
            os.path.dirname(os.path.abspath(components_module.__file__)),
            "sources",
        )
        ontology_hub_dir = os.path.join(sources_dir, "Ontology-Hub")
        dockerfile_path = os.path.join(ontology_hub_dir, "Dockerfile")

        clone_calls = []

        def fake_isfile(path):
            return path == dockerfile_path and len(clone_calls) > 0

        def fake_run(args, check):
            clone_calls.append((tuple(args), check))
            return None

        with (
            mock.patch("adapters.inesdata.components.os.path.isdir", side_effect=lambda path: path == ontology_hub_dir),
            mock.patch("adapters.inesdata.components.os.listdir", return_value=[]),
            mock.patch("adapters.inesdata.components.os.makedirs"),
            mock.patch("adapters.inesdata.components.os.rmdir"),
            mock.patch("adapters.inesdata.components.os.path.isfile", side_effect=fake_isfile),
            mock.patch("subprocess.run", side_effect=fake_run),
        ):
            resolved = adapter._resolve_ontology_hub_source_dir({})

        self.assertEqual(resolved, ontology_hub_dir)
        self.assertEqual(
            clone_calls,
            [
                (
                    (
                        "git",
                        "clone",
                        "https://github.com/ProyectoPIONERA/Ontology-Hub.git",
                        ontology_hub_dir,
                    ),
                    True,
                )
            ],
        )

    def test_resolve_ontology_hub_source_dir_fails_when_default_checkout_is_populated_but_invalid(self):
        adapter = self._make_adapter()
        ontology_hub_dir = os.path.join(
            os.path.dirname(os.path.abspath(components_module.__file__)),
            "sources",
            "Ontology-Hub",
        )

        with (
            mock.patch("adapters.inesdata.components.os.path.isdir", side_effect=lambda path: path == ontology_hub_dir),
            mock.patch("adapters.inesdata.components.os.listdir", return_value=["README.md"]),
            mock.patch("adapters.inesdata.components.os.path.isfile", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "Ontology-Hub source directory is not usable"):
                adapter._resolve_ontology_hub_source_dir({})

    def test_resolve_morph_kgv_source_dir_clones_when_sources_dir_exists_but_is_empty(self):
        adapter = self._make_adapter()
        sources_dir = os.path.join(
            os.path.dirname(os.path.abspath(components_module.__file__)),
            "sources",
        )
        morph_kgv_dir = os.path.join(sources_dir, "morph-kgv")
        pyproject_path = os.path.join(morph_kgv_dir, "pyproject.toml")
        package_path = os.path.join(morph_kgv_dir, "src", "morph_kgc", "__init__.py")
        virt_store_path = os.path.join(morph_kgv_dir, "src", "morph_kgc", "sparql", "virt_store.py")

        clone_calls = []

        def fake_isfile(path):
            return path in {pyproject_path, package_path, virt_store_path} and len(clone_calls) > 0

        def fake_run(args, check):
            clone_calls.append((tuple(args), check))
            return None

        with (
            mock.patch("adapters.inesdata.components.os.path.isdir", side_effect=lambda path: path == morph_kgv_dir),
            mock.patch("adapters.inesdata.components.os.listdir", return_value=[]),
            mock.patch("adapters.inesdata.components.os.makedirs"),
            mock.patch("adapters.inesdata.components.os.rmdir"),
            mock.patch("adapters.inesdata.components.os.path.isfile", side_effect=fake_isfile),
            mock.patch("subprocess.run", side_effect=fake_run),
        ):
            resolved = adapter._resolve_morph_kgv_source_dir({})

        self.assertEqual(resolved, morph_kgv_dir)
        self.assertEqual(
            clone_calls,
            [
                (
                    (
                        "git",
                        "clone",
                        "https://github.com/ProyectoPIONERA/morph-kgv.git",
                        morph_kgv_dir,
                    ),
                    True,
                )
            ],
        )

    def test_resolve_mapping_editor_source_dir_clones_when_sources_dir_exists_but_is_empty(self):
        adapter = self._make_adapter()
        sources_dir = os.path.join(
            os.path.dirname(os.path.abspath(components_module.__file__)),
            "sources",
        )
        mapping_editor_dir = os.path.join(sources_dir, "mapping-editor")
        app_path = os.path.join(mapping_editor_dir, "Mapping_Editor.py")
        requirements_path = os.path.join(mapping_editor_dir, "requirements.txt")

        clone_calls = []

        def fake_isfile(path):
            return path in {app_path, requirements_path} and len(clone_calls) > 0

        def fake_run(args, check):
            clone_calls.append((tuple(args), check))
            return None

        with (
            mock.patch("adapters.inesdata.components.os.path.isdir", side_effect=lambda path: path == mapping_editor_dir),
            mock.patch("adapters.inesdata.components.os.listdir", return_value=[]),
            mock.patch("adapters.inesdata.components.os.makedirs"),
            mock.patch("adapters.inesdata.components.os.rmdir"),
            mock.patch("adapters.inesdata.components.os.path.isfile", side_effect=fake_isfile),
            mock.patch("subprocess.run", side_effect=fake_run),
        ):
            resolved = adapter._resolve_mapping_editor_source_dir({})

        self.assertEqual(resolved, mapping_editor_dir)
        self.assertEqual(
            clone_calls,
            [
                (
                    (
                        "git",
                        "clone",
                        "https://github.com/ProyectoPIONERA/mapping-editor.git",
                        mapping_editor_dir,
                    ),
                    True,
                )
            ],
        )

    def test_resolve_automap_source_dir_clones_when_sources_dir_exists_but_is_empty(self):
        adapter = self._make_adapter()
        sources_dir = os.path.join(
            os.path.dirname(os.path.abspath(components_module.__file__)),
            "sources",
        )
        automap_dir = os.path.join(sources_dir, "automap")
        required_paths = {
            os.path.join(automap_dir, "README.md"),
            os.path.join(automap_dir, "pyproject.toml"),
            os.path.join(automap_dir, "main.py"),
            os.path.join(automap_dir, "langgraph.json"),
            os.path.join(automap_dir, "agents", "schema_agent.py"),
            os.path.join(automap_dir, "graph", "workflow.py"),
            os.path.join(automap_dir, "tools", "rml_tools.py"),
            os.path.join(automap_dir, "evaluation", "metrics.py"),
        }

        clone_calls = []

        def fake_isfile(path):
            return path in required_paths and len(clone_calls) > 0

        def fake_run(args, check):
            clone_calls.append((tuple(args), check))
            return None

        with (
            mock.patch("adapters.inesdata.components.os.path.isdir", side_effect=lambda path: path == automap_dir),
            mock.patch("adapters.inesdata.components.os.listdir", return_value=[]),
            mock.patch("adapters.inesdata.components.os.makedirs"),
            mock.patch("adapters.inesdata.components.os.rmdir"),
            mock.patch("adapters.inesdata.components.os.path.isfile", side_effect=fake_isfile),
            mock.patch("subprocess.run", side_effect=fake_run),
        ):
            resolved = adapter._resolve_automap_source_dir({})

        self.assertEqual(resolved, automap_dir)
        self.assertEqual(
            clone_calls,
            [
                (
                    (
                        "git",
                        "clone",
                        "https://github.com/ProyectoPIONERA/automap.git",
                        automap_dir,
                    ),
                    True,
                )
            ],
        )

    def test_build_semantic_virtualization_image_uses_framework_api_dockerfile(self):
        adapter = self._make_adapter()

        with (
            mock.patch.object(adapter, "_resolve_morph_kgv_source_dir", return_value="/tmp/morph-kgv"),
            mock.patch.object(adapter, "_resolve_mapping_editor_source_dir", return_value="/tmp/mapping-editor") as mapping_mock,
            mock.patch.object(adapter, "_resolve_automap_source_dir", return_value="/tmp/automap") as automap_mock,
            mock.patch.object(
                adapter,
                "_semantic_virtualization_api_dockerfile",
                return_value="/tmp/semantic-api/Dockerfile",
            ),
            mock.patch.object(
                adapter,
                "_semantic_virtualization_api_server_file",
                return_value="/tmp/semantic-api/morph_kgv_http_server.py",
            ),
            mock.patch.object(
                adapter,
                "_prepare_semantic_virtualization_api_build_context",
                return_value="/tmp/morph-kgv-build-context",
            ) as build_context_mock,
            mock.patch.object(adapter, "_docker_cmd", return_value="docker"),
            mock.patch("adapters.inesdata.components.os.path.isfile", return_value=True),
            mock.patch("adapters.inesdata.components.shutil.rmtree") as rmtree_mock,
        ):
            adapter._build_semantic_virtualization_image_on_host("morph-kgv:local", {})

        adapter.run.assert_called_once_with(
            "docker build -t morph-kgv:local -f /tmp/semantic-api/Dockerfile .",
            check=False,
            cwd="/tmp/morph-kgv-build-context",
        )
        mapping_mock.assert_called_once_with({})
        automap_mock.assert_called_once_with({})
        build_context_mock.assert_called_once_with("/tmp/morph-kgv")
        rmtree_mock.assert_called_once_with("/tmp/morph-kgv-build-context", ignore_errors=True)

    def test_build_mapping_editor_image_uses_framework_dockerfile(self):
        adapter = self._make_adapter()

        with (
            mock.patch.object(adapter, "_resolve_mapping_editor_source_dir", return_value="/tmp/mapping-editor"),
            mock.patch.object(
                adapter,
                "_mapping_editor_dockerfile",
                return_value="/tmp/mapping-editor-wrapper/Dockerfile",
            ),
            mock.patch.object(adapter, "_docker_cmd", return_value="docker"),
            mock.patch("adapters.inesdata.components.os.path.isfile", return_value=True),
        ):
            adapter._build_mapping_editor_image_on_host("mapping-editor:local", {})

        adapter.run.assert_called_once_with(
            "docker build -t mapping-editor:local -f /tmp/mapping-editor-wrapper/Dockerfile .",
            check=False,
            cwd="/tmp/mapping-editor",
        )

    def test_k3s_cri_image_ref_alias_matches_container_runtime_normalization(self):
        adapter = self._make_adapter()

        self.assertEqual(
            adapter._k3s_cri_image_ref_alias("ontology-hub:local"),
            "docker.io/library/ontology-hub:local",
        )
        self.assertEqual(
            adapter._k3s_cri_image_ref_alias("eclipse-edc/data-dashboard:local"),
            "docker.io/eclipse-edc/data-dashboard:local",
        )
        self.assertEqual(
            adapter._k3s_cri_image_ref_alias("registry.example.org/ns/image:tag"),
            "registry.example.org/ns/image:tag",
        )

    def test_prepare_level6_local_image_builds_on_host_and_loads_into_minikube(self):
        adapter = self._make_adapter()
        deployer_config = {"LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true"}

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=True),
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ontology-hub",
                "/tmp/ontology-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        build_mock.assert_called_once_with("ontology-hub:local", deployer_config)
        load_mock.assert_called_once_with("minikube", "ontology-hub:local")

    def test_prepare_level6_local_image_skips_ontology_hub_when_auto_build_disabled(self):
        adapter = self._make_adapter()
        deployer_config = {"LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "false"}

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available") as minikube_available_mock,
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ontology-hub",
                "/tmp/ontology-values.yaml",
                deployer_config,
            )

        self.assertFalse(result)
        minikube_available_mock.assert_not_called()
        build_mock.assert_not_called()
        load_mock.assert_not_called()

    def test_prepare_level6_local_image_skips_ontology_hub_when_prebuilt_image_is_configured(self):
        adapter = self._make_adapter()
        deployer_config = {
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
            "ONTOLOGY_HUB_IMAGE_REF": "registry.example.org/pionera/ontology-hub:1.0.0",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available") as minikube_available_mock,
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_cluster_runtime") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ontology-hub",
                "/tmp/ontology-values.yaml",
                deployer_config,
            )

        self.assertFalse(result)
        minikube_available_mock.assert_not_called()
        build_mock.assert_not_called()
        load_mock.assert_not_called()

    def test_prepare_level6_local_image_imports_ontology_hub_into_k3s(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available") as minikube_available_mock,
            mock.patch.object(adapter, "_local_k3s_command_available", return_value=True),
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_k3s") as load_k3s_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_minikube_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ontology-hub",
                "/tmp/ontology-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        minikube_available_mock.assert_not_called()
        build_mock.assert_called_once_with("ontology-hub:local", deployer_config)
        load_k3s_mock.assert_called_once_with("ontology-hub:local", deployer_config)
        load_minikube_mock.assert_not_called()

    def test_prepare_level6_local_image_imports_ai_model_hub_into_vm_single_k3s(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "eclipse-edc/data-dashboard", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available") as minikube_available_mock,
            mock.patch.object(adapter, "_local_k3s_command_available", return_value=True),
            mock.patch.object(adapter, "_build_ai_model_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_k3s") as load_k3s_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_minikube_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ai-model-hub",
                "/tmp/ai-model-hub-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        minikube_available_mock.assert_not_called()
        build_mock.assert_called_once_with("eclipse-edc/data-dashboard:local", deployer_config)
        load_k3s_mock.assert_called_once_with("eclipse-edc/data-dashboard:local", deployer_config)
        load_minikube_mock.assert_not_called()

    def test_prepare_level6_local_image_blocks_vm_single_k3s_import_without_local_or_remote_target(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_local_k3s_command_available", return_value=False),
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_k3s") as load_k3s_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "Remote k3s image import is not configured for vm-single"):
                adapter._maybe_prepare_level6_local_image(
                    "ontology-hub",
                    "/tmp/ontology-values.yaml",
                    deployer_config,
                )

        build_mock.assert_not_called()
        load_k3s_mock.assert_not_called()

    def test_prepare_level6_local_image_blocks_vm_distributed_local_k3s_import(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_k3s") as load_k3s_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "Remote k3s image import is not configured"):
                adapter._maybe_prepare_level6_local_image(
                    "ontology-hub",
                    "/tmp/ontology-values.yaml",
                    deployer_config,
                )

        build_mock.assert_not_called()
        load_k3s_mock.assert_not_called()

    def test_prepare_level6_local_image_checks_remote_sudo_before_build(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        adapter.run = mock.Mock(return_value=None)
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
            "VM_COMPONENTS_SSH_HOST": "pionera40",
            "VM_COMPONENTS_SSH_USER": "pionera",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_k3s") as load_k3s_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "non-interactive sudo for k3s"):
                adapter._maybe_prepare_level6_local_image(
                    "ontology-hub",
                    "/tmp/ontology-values.yaml",
                    deployer_config,
                )

        probe_commands = [call.args[0] for call in adapter.run.call_args_list]
        self.assertTrue(any("sudo -n k3s ctr -n k8s.io images ls -q" in command for command in probe_commands))
        build_mock.assert_not_called()
        load_k3s_mock.assert_not_called()

    def test_prepare_level6_local_image_allows_interactive_remote_import(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        adapter.run = mock.Mock(return_value=None)
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE": "true",
            "VM_COMPONENTS_SSH_HOST": "pionera40",
            "VM_COMPONENTS_SSH_USER": "pionera",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_k3s") as load_k3s_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ontology-hub",
                "/tmp/ontology-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        adapter.run.assert_not_called()
        build_mock.assert_called_once_with("ontology-hub:local", deployer_config)
        load_k3s_mock.assert_called_once_with("ontology-hub:local", deployer_config)

    def test_model_server_image_blocks_vm_distributed_local_k3s_import_before_build(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "AI_MODEL_HUB_MODEL_SERVER_IMAGE": "model-server:latest",
        }

        with mock.patch.object(adapter, "_ai_model_hub_model_server_source_dir", return_value="/tmp/model-server"):
            with mock.patch("adapters.shared.components.os.path.isfile", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "Remote k3s image import is not configured"):
                    adapter._prepare_ai_model_hub_model_server_image(
                        "model-server:latest",
                        deployer_config,
                    )

        adapter.run.assert_not_called()

    def test_ai_model_hub_model_server_external_mode_skips_deployment(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        deployer_config = {
            "AI_MODEL_HUB_MODEL_SERVER_MODE": "external",
            "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://org1.example.test/model-server",
            "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL": "https://org1.example.test/model-server",
        }

        result = adapter._ensure_ai_model_hub_model_server("components", deployer_config)

        self.assertEqual(result["mode"], "external")
        self.assertEqual(result["service"], "http://model-server.components.svc.cluster.local:8080")
        self.assertEqual(result["connector_base_url"], "http://org1.example.test/model-server")
        self.assertEqual(result["public_url"], "https://org1.example.test/model-server")
        self.assertFalse(result["built_local_image"])
        adapter.run.assert_not_called()

    def test_ai_model_hub_model_server_uses_configurable_real_source(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        applied_manifests = []

        def fake_run(command, *args, **kwargs):
            if command.startswith("kubectl apply -f "):
                temp_path = command.rsplit(" ", 1)[1].strip("'\"")
                with open(temp_path, encoding="utf-8") as handle:
                    applied_manifests.append(handle.read())
            return "ok"

        adapter.run = mock.Mock(side_effect=fake_run)

        with tempfile.TemporaryDirectory() as source_dir:
            manifest_path = os.path.join(source_dir, "k8s-model-server.yaml")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            "apiVersion: apps/v1",
                            "kind: Deployment",
                            "metadata:",
                            "  name: model-server",
                            "  namespace: demo",
                            "spec:",
                            "  template:",
                            "    spec:",
                            "      containers:",
                            "        - name: model-server",
                            "          image: model-server:latest",
                            "          readinessProbe:",
                            "            httpGet:",
                            "              path: /api/v1/health",
                            "---",
                            "apiVersion: v1",
                            "kind: Service",
                            "metadata:",
                            "  name: model-server",
                            "  namespace: demo",
                        ]
                    )
                )

            deployer_config = {
                "AI_MODEL_HUB_MODEL_SERVER_MODE": "combined",
                "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                "AI_MODEL_HUB_MODEL_SERVER_IMAGE": "local/real-model-server:latest",
                "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://org1.example.test/model-server",
            }

            with (
                mock.patch.object(adapter, "_prepare_ai_model_hub_model_server_image", return_value=True),
                mock.patch.object(adapter, "_wait_for_component_rollout", return_value=True),
                mock.patch.object(
                    adapter,
                    "_sync_ai_model_hub_model_server_public_ingress",
                    return_value="https://org1.example.test/model-server",
                ),
            ):
                result = adapter._ensure_ai_model_hub_model_server("components-real", deployer_config)

        self.assertEqual(result["mode"], "combined")
        self.assertEqual(result["connector_base_url"], "http://org1.example.test/model-server")
        self.assertEqual(result["public_url"], "https://org1.example.test/model-server")
        self.assertTrue(result["built_local_image"])
        self.assertTrue(applied_manifests)
        rendered_manifest = applied_manifests[0]
        self.assertIn("namespace: components-real", rendered_manifest)
        self.assertIn("image: local/real-model-server:latest", rendered_manifest)
        self.assertIn("path: /models", rendered_manifest)

    def test_ai_model_hub_use_case_model_server_generates_build_context(self):
        adapter = self._make_shared_adapter()

        with tempfile.TemporaryDirectory() as source_dir:
            os.makedirs(os.path.join(source_dir, "src"), exist_ok=True)
            with open(os.path.join(source_dir, "requirements.txt"), "w", encoding="utf-8") as handle:
                handle.write("fastapi\nuvicorn\n")
            with open(os.path.join(source_dir, "src", "server.py"), "w", encoding="utf-8") as handle:
                handle.write("from fastapi import FastAPI\napp = FastAPI()\n")

            build_context, generated = adapter._prepare_ai_model_hub_model_server_build_context(
                source_dir,
                "combined",
                {
                    "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT": "8090",
                    "AI_MODEL_HUB_MODEL_SERVER_DOCKER_BASE_IMAGE": "python:3.11-slim",
                },
            )
            try:
                self.assertTrue(generated)
                with open(os.path.join(build_context, "Dockerfile"), encoding="utf-8") as handle:
                    dockerfile = handle.read()
                self.assertIn("FROM python:3.11-slim", dockerfile)
                self.assertIn("COPY use_cases /app/use_cases", dockerfile)
                self.assertIn("COPY combined_model_server /app/combined_model_server", dockerfile)
                self.assertIn('"--port", "8090"', dockerfile)
                self.assertTrue(os.path.isfile(os.path.join(build_context, "use_cases", "src", "server.py")))
                self.assertTrue(os.path.isfile(os.path.join(build_context, "combined_model_server", "server.py")))
            finally:
                shutil.rmtree(build_context, ignore_errors=True)

    def test_ai_model_hub_use_case_model_server_generates_manifest_when_missing(self):
        adapter = self._make_shared_adapter()

        with tempfile.TemporaryDirectory() as source_dir:
            manifest = adapter._render_ai_model_hub_model_server_manifest(
                source_dir,
                "components-real",
                "local/real-model-server:latest",
                "use-cases",
                {
                    "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT": "8090",
                    "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH": "/models",
                },
            )

        self.assertIn("namespace: components-real", manifest)
        self.assertIn("image: local/real-model-server:latest", manifest)
        self.assertIn("imagePullPolicy: Never", manifest)
        self.assertIn("containerPort: 8090", manifest)
        self.assertIn("path: /models", manifest)
        self.assertIn("port: 8080", manifest)

    def test_ai_model_hub_model_server_source_repository_clones_when_source_is_missing(self):
        adapter = self._make_shared_adapter()

        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = os.path.join(tmpdir, "AIModelHub-Use-Cases")
            clone_calls = []

            def fake_run(args, check):
                clone_calls.append((tuple(args), check))
                os.makedirs(os.path.join(source_dir, "src"), exist_ok=True)
                with open(os.path.join(source_dir, "requirements.txt"), "w", encoding="utf-8") as handle:
                    handle.write("fastapi\nuvicorn\n")
                with open(os.path.join(source_dir, "src", "server.py"), "w", encoding="utf-8") as handle:
                    handle.write("from fastapi import FastAPI\napp = FastAPI()\n")
                return None

            with mock.patch("adapters.shared.components.subprocess.run", side_effect=fake_run):
                resolved = adapter._ai_model_hub_model_server_source_dir(
                    {
                        "AI_MODEL_HUB_MODEL_SERVER_MODE": "combined",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY": "https://example.test/use-cases.git",
                    }
                )

        self.assertEqual(resolved, source_dir)
        self.assertEqual(
            clone_calls,
            [
                (
                    (
                        "git",
                        "clone",
                        "https://example.test/use-cases.git",
                        source_dir,
                    ),
                    True,
                )
            ],
        )

    def test_ai_model_hub_model_server_source_repository_keeps_populated_source_dir(self):
        adapter = self._make_shared_adapter()

        with tempfile.TemporaryDirectory() as source_dir:
            os.makedirs(os.path.join(source_dir, "src"), exist_ok=True)
            with open(os.path.join(source_dir, "requirements.txt"), "w", encoding="utf-8") as handle:
                handle.write("fastapi\nuvicorn\n")
            with open(os.path.join(source_dir, "src", "server.py"), "w", encoding="utf-8") as handle:
                handle.write("from fastapi import FastAPI\napp = FastAPI()\n")

            with mock.patch("adapters.shared.components.subprocess.run") as run_mock:
                resolved = adapter._ai_model_hub_model_server_source_dir(
                    {
                        "AI_MODEL_HUB_MODEL_SERVER_MODE": "combined",
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_DIR": source_dir,
                        "AI_MODEL_HUB_MODEL_SERVER_SOURCE_REPOSITORY": "https://example.test/use-cases.git",
                    }
                )

        self.assertEqual(resolved, source_dir)
        run_mock.assert_not_called()

    def test_load_image_into_k3s_uses_remote_import_for_vm_distributed_components(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        deployer_config = {
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
            "SSH_ACCESS_MODE": "bastion",
            "SSH_BASTION_HOST": "orion.example.test",
            "SSH_BASTION_PORT": "2222",
            "SSH_BASTION_USER": "jump",
            "VM_COMPONENTS_SSH_HOST": "pionera40",
            "VM_COMPONENTS_SSH_USER": "pionera",
            "VM_COMPONENTS_SSH_PORT": "22",
        }

        with mock.patch.object(adapter, "_docker_cmd", return_value="docker"):
            adapter._load_image_into_k3s("ontology-hub:local", deployer_config)

        commands = [call.args[0] for call in adapter.run.call_args_list]
        self.assertEqual("docker tag ontology-hub:local docker.io/library/ontology-hub:local", commands[0])
        self.assertIn("docker save ontology-hub:local docker.io/library/ontology-hub:local -o", commands[1])
        self.assertIn("scp -P 22 -o ProxyJump=jump@orion.example.test:2222", commands[2])
        self.assertIn("pionera@pionera40:/tmp/", commands[2])
        self.assertIn("ssh -p 22 -J jump@orion.example.test:2222 pionera@pionera40", commands[3])
        self.assertIn("sudo -n k3s ctr -n k8s.io images import", commands[3])
        self.assertIn("status=$?", commands[3])
        self.assertIn("exit $status", commands[3])

    def test_load_image_into_k3s_uses_remote_import_for_vm_single_when_local_k3s_is_missing(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter.run = mock.Mock(return_value="ok")
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "VM_SINGLE_REMOTE_IMAGE_IMPORT": "auto",
            "VM_SINGLE_SSH_HOST": "vm-single.example.test",
            "VM_SINGLE_SSH_USER": "pionera",
            "VM_SINGLE_SSH_PORT": "22",
        }

        with (
            mock.patch.object(adapter, "_docker_cmd", return_value="docker"),
            mock.patch.object(adapter, "_local_k3s_command_available", return_value=False),
        ):
            adapter._load_image_into_k3s("ontology-hub:local", deployer_config)

        commands = [call.args[0] for call in adapter.run.call_args_list]
        self.assertEqual("docker tag ontology-hub:local docker.io/library/ontology-hub:local", commands[0])
        self.assertIn("docker save ontology-hub:local docker.io/library/ontology-hub:local -o", commands[1])
        self.assertIn("scp -P 22", commands[2])
        self.assertIn("pionera@vm-single.example.test:/tmp/", commands[2])
        self.assertIn("sudo -n k3s ctr -n k8s.io images ls -q", commands[3])
        self.assertIn("ssh -p 22 pionera@vm-single.example.test", commands[4])
        self.assertIn("sudo -n k3s ctr -n k8s.io images import", commands[4])

    def test_load_image_into_k3s_prefers_vm_single_remote_when_operator_has_unrelated_k3s(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter.run = mock.Mock(return_value="ok")
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "VM_SINGLE_REMOTE_IMAGE_IMPORT": "auto",
            "VM_SINGLE_SSH_HOST": "vm-single.example.test",
            "VM_SINGLE_SSH_USER": "pionera",
        }

        with (
            mock.patch.object(adapter, "_docker_cmd", return_value="docker"),
            mock.patch.object(adapter, "_local_k3s_command_available", return_value=True),
            mock.patch.object(adapter, "_vm_single_running_on_target", return_value=False),
        ):
            adapter._load_image_into_k3s("ontology-hub:local", deployer_config)

        commands = [call.args[0] for call in adapter.run.call_args_list]
        self.assertIn("scp -P 22", commands[2])
        self.assertIn("ssh -p 22 pionera@vm-single.example.test", commands[4])
        self.assertFalse(any("sudo k3s ctr -n k8s.io images import /tmp/" in command for command in commands))

    def test_load_image_into_k3s_auto_falls_back_to_interactive_sudo_prompt(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        adapter.run = mock.Mock(side_effect=["tagged", "saved", "copied", None, "imported"])
        deployer_config = {
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT": "true",
            "VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT_INTERACTIVE": "auto",
            "SSH_ACCESS_MODE": "bastion",
            "SSH_BASTION_HOST": "orion.example.test",
            "SSH_BASTION_PORT": "2222",
            "SSH_BASTION_USER": "jump",
            "VM_COMPONENTS_SSH_HOST": "pionera40",
            "VM_COMPONENTS_SSH_USER": "pionera",
            "VM_COMPONENTS_SSH_PORT": "22",
        }

        with mock.patch.object(adapter, "_docker_cmd", return_value="docker"):
            adapter._load_image_into_k3s("ontology-hub:local", deployer_config)

        commands = [call.args[0] for call in adapter.run.call_args_list]
        self.assertEqual("docker tag ontology-hub:local docker.io/library/ontology-hub:local", commands[0])
        self.assertIn("docker save ontology-hub:local docker.io/library/ontology-hub:local -o", commands[1])
        self.assertIn("scp -P 22 -o ProxyJump=jump@orion.example.test:2222", commands[2])
        self.assertIn("sudo -n k3s ctr -n k8s.io images ls -q", commands[3])
        self.assertIn("ssh -tt", commands[4])
        self.assertIn("sudo k3s ctr -n k8s.io images import", commands[4])

    def test_load_images_into_k3s_batches_semantic_virtualization_images_for_remote_import(self):
        adapter = self._make_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter.run = mock.Mock(return_value="ok")
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "VM_SINGLE_REMOTE_IMAGE_IMPORT": "auto",
            "VM_SINGLE_SSH_HOST": "vm-single.example.test",
            "VM_SINGLE_SSH_USER": "pionera",
            "VM_SINGLE_SSH_PORT": "22",
        }

        with (
            mock.patch.object(adapter, "_docker_cmd", return_value="docker"),
            mock.patch.object(adapter, "_local_k3s_command_available", return_value=False),
        ):
            adapter._load_images_into_k3s(
                ["morph-kgv:local", "mapping-editor:local"],
                deployer_config,
            )

        commands = [call.args[0] for call in adapter.run.call_args_list]
        self.assertEqual(
            "docker tag morph-kgv:local docker.io/library/morph-kgv:local",
            commands[0],
        )
        self.assertEqual(
            "docker tag mapping-editor:local docker.io/library/mapping-editor:local",
            commands[1],
        )
        self.assertIn("docker save", commands[2])
        self.assertIn("morph-kgv:local", commands[2])
        self.assertIn("docker.io/library/morph-kgv:local", commands[2])
        self.assertIn("mapping-editor:local", commands[2])
        self.assertIn("docker.io/library/mapping-editor:local", commands[2])
        self.assertIn("scp -P 22", commands[3])
        self.assertIn("sudo -n k3s ctr -n k8s.io images ls -q", commands[4])
        self.assertIn("sudo -n k3s ctr -n k8s.io images import", commands[5])

    def test_prepare_level6_local_image_rebuilds_ontology_hub_without_consulting_host_cache(self):
        adapter = self._make_adapter()
        deployer_config = {"LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true"}

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=True),
            mock.patch.object(adapter, "_host_has_image") as host_has_image_mock,
            mock.patch.object(adapter, "_build_ontology_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ontology-hub",
                "/tmp/ontology-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        host_has_image_mock.assert_not_called()
        build_mock.assert_called_once_with("ontology-hub:local", deployer_config)
        load_mock.assert_called_once_with("minikube", "ontology-hub:local")

    def test_prepare_level6_local_image_rebuilds_ai_model_hub_even_when_cached_in_minikube(self):
        adapter = self._make_adapter()
        deployer_config = {"LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true"}

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "eclipse-edc/data-dashboard", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=True),
            mock.patch.object(adapter, "_minikube_has_image", return_value=True) as has_image_mock,
            mock.patch.object(adapter, "_build_ai_model_hub_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "ai-model-hub",
                "/tmp/ai-model-hub-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        has_image_mock.assert_not_called()
        build_mock.assert_called_once_with("eclipse-edc/data-dashboard:local", deployer_config)
        load_mock.assert_called_once_with("minikube", "eclipse-edc/data-dashboard:local")

    def test_prepare_level6_local_image_rebuilds_semantic_virtualization_even_when_cached_in_minikube(self):
        adapter = self._make_adapter()
        deployer_config = {"LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true"}

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "morph-kgv", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=True),
            mock.patch.object(adapter, "_minikube_has_image", return_value=True) as has_image_mock,
            mock.patch.object(adapter, "_build_semantic_virtualization_image_on_host") as build_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "semantic-virtualization",
                "/tmp/semantic-virtualization-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        has_image_mock.assert_not_called()
        build_mock.assert_called_once_with("morph-kgv:local", deployer_config)
        load_mock.assert_called_once_with("minikube", "morph-kgv:local")

    def test_prepare_level6_local_image_builds_mapping_editor_when_opted_in(self):
        adapter = self._make_adapter()
        deployer_config = {
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={
                    "image": {"repository": "morph-kgv", "tag": "local"},
                    "mappingEditor": {
                        "image": {"repository": "mapping-editor", "tag": "local"},
                    },
                },
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=True),
            mock.patch.object(adapter, "_build_semantic_virtualization_image_on_host") as build_api_mock,
            mock.patch.object(adapter, "_build_mapping_editor_image_on_host") as build_editor_mock,
            mock.patch.object(adapter, "_load_image_into_minikube") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "semantic-virtualization",
                "/tmp/semantic-virtualization-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        build_api_mock.assert_called_once_with("morph-kgv:local", deployer_config)
        build_editor_mock.assert_called_once_with("mapping-editor:local", deployer_config)
        self.assertEqual(
            load_mock.mock_calls,
            [
                mock.call("minikube", "morph-kgv:local"),
                mock.call("minikube", "mapping-editor:local"),
            ],
        )

    def test_prepare_level6_local_image_does_not_build_prebuilt_mapping_editor(self):
        adapter = self._make_adapter()
        deployer_config = {
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_IMAGE_REF": (
                "registry.example.org/pionera/mapping-editor:2.0.0"
            ),
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={
                    "image": {"repository": "morph-kgv", "tag": "local"},
                    "mappingEditor": {
                        "image": {"repository": "mapping-editor", "tag": "local"},
                    },
                },
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=True),
            mock.patch.object(adapter, "_build_semantic_virtualization_image_on_host") as build_api_mock,
            mock.patch.object(adapter, "_build_mapping_editor_image_on_host") as build_editor_mock,
            mock.patch.object(adapter, "_load_images_into_cluster_runtime") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "semantic-virtualization",
                "/tmp/semantic-virtualization-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        build_api_mock.assert_called_once_with("morph-kgv:local", deployer_config)
        build_editor_mock.assert_not_called()
        load_mock.assert_called_once_with(
            "minikube",
            "minikube",
            ["morph-kgv:local"],
            deployer_config,
        )

    def test_prepare_level6_local_image_imports_semantic_virtualization_images_into_k3s(self):
        adapter = self._make_adapter()
        deployer_config = {
            "LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
        }

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={
                    "image": {"repository": "morph-kgv", "tag": "local"},
                    "mappingEditor": {
                        "image": {"repository": "mapping-editor", "tag": "local"},
                    },
                },
            ),
            mock.patch.object(adapter, "_cluster_runtime", return_value={"cluster_type": "k3s"}),
            mock.patch.object(adapter, "_ensure_k3s_local_image_import_supported") as ensure_mock,
            mock.patch.object(adapter, "_build_semantic_virtualization_image_on_host") as build_api_mock,
            mock.patch.object(adapter, "_build_mapping_editor_image_on_host") as build_editor_mock,
            mock.patch.object(adapter, "_load_images_into_cluster_runtime") as load_mock,
        ):
            result = adapter._maybe_prepare_level6_local_image(
                "semantic-virtualization",
                "/tmp/semantic-virtualization-values.yaml",
                deployer_config,
            )

        self.assertTrue(result)
        self.assertEqual(
            ensure_mock.mock_calls,
            [
                mock.call("morph-kgv:local", deployer_config),
                mock.call("mapping-editor:local", deployer_config),
            ],
        )
        build_api_mock.assert_called_once_with("morph-kgv:local", deployer_config)
        build_editor_mock.assert_called_once_with("mapping-editor:local", deployer_config)
        load_mock.assert_called_once_with(
            "k3s",
            "minikube",
            ["morph-kgv:local", "mapping-editor:local"],
            deployer_config,
        )

    def test_prepare_level6_local_image_fails_when_ontology_hub_chart_does_not_use_local_tag(self):
        adapter = self._make_adapter()
        deployer_config = {"LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true"}

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "1.0.0"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "Ontology-Hub must use a local image in Level 5/6"):
                adapter._maybe_prepare_level6_local_image(
                    "ontology-hub",
                    "/tmp/ontology-values.yaml",
                    deployer_config,
                )

    def test_prepare_level6_local_image_fails_when_minikube_is_unavailable_for_ontology_hub(self):
        adapter = self._make_adapter()
        deployer_config = {"MINIKUBE_PROFILE": "custom-profile"}

        with (
            mock.patch.object(
                adapter,
                "_safe_load_yaml_file",
                return_value={"image": {"repository": "ontology-hub", "tag": "local"}},
            ),
            mock.patch.object(adapter, "_minikube_is_available", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "Minikube profile is not available for Ontology-Hub local image deployment"):
                adapter._maybe_prepare_level6_local_image(
                    "ontology-hub",
                    "/tmp/ontology-values.yaml",
                    deployer_config,
                )

    def test_wait_for_component_rollout_prefers_deployment_rollout(self):
        infrastructure = FakeInfrastructure()
        infrastructure.wait_for_deployment_rollout = mock.Mock(return_value=True)
        adapter = self._make_adapter(infrastructure=infrastructure)
        adapter._wait_for_pods_ready_by_selector = mock.Mock(return_value=True)

        result = adapter._wait_for_component_rollout(
            "demo",
            "demo-ontology-hub",
            timeout_seconds=1800,
            label="ontology-hub",
        )

        self.assertTrue(result)
        infrastructure.wait_for_deployment_rollout.assert_called_once_with(
            "demo",
            "demo-ontology-hub",
            timeout_seconds=1800,
            label="ontology-hub",
        )
        adapter._wait_for_pods_ready_by_selector.assert_not_called()

    def test_wait_for_component_rollout_falls_back_to_selector_wait_when_rollout_helper_missing(self):
        adapter = self._make_adapter()
        adapter._wait_for_pods_ready_by_selector = mock.Mock(return_value=True)

        result = adapter._wait_for_component_rollout(
            "demo",
            "demo-ontology-hub",
            timeout_seconds=1800,
            label="ontology-hub",
        )

        self.assertTrue(result)
        adapter._wait_for_pods_ready_by_selector.assert_called_once_with(
            "demo",
            "app.kubernetes.io/instance=demo-ontology-hub",
            timeout_seconds=1800,
            label="ontology-hub",
        )

    def test_write_component_values_override_file_uses_shared_override_planner_when_available(self):
        adapter = self._make_shared_adapter()
        adapter.plan_component_override_values = mock.Mock(
            return_value={
                "normalized_component": "ontology-hub",
                "chart_dir": "/tmp",
                "payload": {
                    "ingress": {
                        "enabled": True,
                        "host": "ontology-hub-demo.custom.ds.example.org",
                    }
                },
                "has_override": True,
                "filename_prefix": "ontology-hub-override-",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            override_path = adapter._write_component_values_override_file(
                tmpdir,
                "ontology-hub",
                {"DS_DOMAIN_BASE": "custom.ds.example.org"},
            )
            self.assertIsNotNone(override_path)
            with open(override_path, "r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle)

        self.assertEqual(
            payload,
            {
                "ingress": {
                    "enabled": True,
                    "host": "ontology-hub-demo.custom.ds.example.org",
                }
            },
        )
        adapter.plan_component_override_values.assert_called_once()

    def test_shared_components_adapter_resolves_runtime_metadata_from_existing_helpers(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"})
        adapter._resolve_component_chart_dir = mock.Mock(return_value="/tmp/chart")
        adapter._resolve_component_values_file = mock.Mock(return_value="/tmp/chart/values-demo.yaml")
        adapter._infer_component_hostname = mock.Mock(return_value="ontology-hub-demo.dev.ds.dataspaceunit.upm")
        adapter._resolve_component_release_name = mock.Mock(return_value="demo-ontology-hub")

        metadata = adapter.resolve_component_runtime_metadata(
            "ontology-hub",
            ds_name="demo",
            namespace="demo",
            deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

        self.assertEqual(metadata["normalized_component"], "ontology-hub")
        self.assertEqual(metadata["chart_dir"], "/tmp/chart")
        self.assertEqual(metadata["values_file"], "/tmp/chart/values-demo.yaml")
        self.assertEqual(metadata["host"], "ontology-hub-demo.dev.ds.dataspaceunit.upm")
        self.assertEqual(metadata["release_name"], "demo-ontology-hub")
        adapter._resolve_component_chart_dir.assert_called_once_with("ontology-hub")
        adapter._resolve_component_values_file.assert_called_once_with(
            "/tmp/chart",
            ds_name="demo",
            namespace="demo",
        )

    def test_shared_components_adapter_defaults_runtime_metadata_to_components_namespace(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(
            return_value={
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "NAMESPACE_PROFILE": "role-aligned",
                "DS_1_NAME": "demo",
                "DS_1_NAMESPACE": "demo",
            }
        )
        adapter._resolve_component_chart_dir = mock.Mock(return_value="/tmp/chart")
        adapter._resolve_component_values_file = mock.Mock(return_value="/tmp/chart/values-components.yaml")
        adapter._infer_component_hostname = mock.Mock(return_value="ontology-hub-demo.dev.ds.dataspaceunit.upm")
        adapter._resolve_component_release_name = mock.Mock(return_value="demo-ontology-hub")

        metadata = adapter.resolve_component_runtime_metadata(
            "ontology-hub",
            ds_name="demo",
            deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

        self.assertEqual(metadata["namespace"], "components")
        adapter._resolve_component_values_file.assert_called_once_with(
            "/tmp/chart",
            ds_name="demo",
            namespace="components",
        )

    def test_shared_components_adapter_prepares_runtime_metadata_for_batch_resolution(self):
        adapter = self._make_shared_adapter()
        adapter.resolve_component_runtime_metadata = mock.Mock(
            side_effect=[
                {
                    "normalized_component": "ontology-hub",
                    "chart_dir": "/tmp/chart",
                    "values_file": "/tmp/chart/values-demo.yaml",
                    "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    "release_name": "demo-ontology-hub",
                },
                {
                    "normalized_component": "ai-model-hub",
                    "chart_dir": "/tmp/chart-ai",
                    "values_file": "/tmp/chart-ai/values-demo.yaml",
                    "host": "",
                    "release_name": "demo-ai-model-hub",
                },
            ]
        )

        prepared = adapter.prepare_component_runtime_metadata(
            ["ontology-hub", "ai-model-hub", "registration-service"],
            ds_name="demo",
            namespace="demo",
            deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

        self.assertEqual(
            [item["normalized_component"] for item in prepared],
            ["ontology-hub", "ai-model-hub", "registration-service"],
        )
        self.assertFalse(prepared[0]["excluded"])
        self.assertIsNone(prepared[0]["error"])
        self.assertFalse(prepared[1]["excluded"])
        self.assertTrue(prepared[2]["excluded"])
        self.assertEqual(adapter.resolve_component_runtime_metadata.call_count, 2)

    def test_cleanup_legacy_component_releases_removes_demo_release_before_components_deploy(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(
            return_value={
                "NAMESPACE_PROFILE": "role-aligned",
                "DS_1_NAME": "demo",
                "DS_1_NAMESPACE": "demo",
            }
        )
        adapter._resolve_component_release_name = mock.Mock(return_value="demo-ontology-hub")
        adapter.run_silent = mock.Mock(return_value="STATUS: deployed")
        adapter._cleanup_components = mock.Mock()

        cleaned_namespace = adapter._cleanup_legacy_component_releases(
            ["ontology-hub"],
            active_namespace="components",
            ds_name="demo",
            deployer_config={"NAMESPACE_PROFILE": "role-aligned"},
        )

        self.assertEqual(cleaned_namespace, "demo")
        adapter._cleanup_components.assert_called_once_with(["ontology-hub"], "demo")
        adapter.run_silent.assert_called_once_with("helm status demo-ontology-hub -n demo")

    def test_cleanup_vm_distributed_legacy_public_path_ingress_removes_framework_route(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        adapter.run_silent = mock.Mock(
            return_value=(
                '{"metadata":{"labels":{'
                '"app.kubernetes.io/managed-by":"validation-environment",'
                '"app.kubernetes.io/part-of":"vm-distributed",'
                '"app.kubernetes.io/component":"ai-model-hub"}},'
                '"spec":{"rules":[{"host":"org1.pionera.oeg.fi.upm.es",'
                '"http":{"paths":[{"path":"/ai-model-hub(/|$)(.*)"}]}}]}}'
            )
        )
        adapter.run = mock.Mock(return_value="ok")

        removed = adapter._cleanup_vm_distributed_legacy_public_path_ingresses(
            [{"normalized": "ai-model-hub", "release_name": "pionera-ai-model-hub"}],
            namespace="components",
            deployer_config={
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_PATH_REWRITE": "true",
            },
        )

        self.assertEqual(removed, ["pionera-ai-model-hub-public-path"])
        adapter.run.assert_called_once_with(
            "kubectl delete ingress pionera-ai-model-hub-public-path -n components --ignore-not-found",
            check=False,
        )

    def test_cleanup_vm_distributed_legacy_public_path_ingress_preserves_user_route(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-distributed"
        adapter.run_silent = mock.Mock(
            return_value=(
                '{"metadata":{"labels":{'
                '"app.kubernetes.io/managed-by":"Helm",'
                '"app.kubernetes.io/component":"ai-model-hub"}},'
                '"spec":{"rules":[{"host":"org1.pionera.oeg.fi.upm.es",'
                '"http":{"paths":[{"path":"/ai-model-hub(/|$)(.*)"}]}}]}}'
            )
        )
        adapter.run = mock.Mock(return_value="ok")

        removed = adapter._cleanup_vm_distributed_legacy_public_path_ingresses(
            [{"normalized": "ai-model-hub", "release_name": "pionera-ai-model-hub"}],
            namespace="components",
            deployer_config={
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.pionera.oeg.fi.upm.es",
                "COMPONENTS_PUBLIC_PATH_REWRITE": "true",
            },
        )

        self.assertEqual(removed, [])
        adapter.run.assert_not_called()

    def test_shared_components_adapter_prepares_component_deployment_plan(self):
        adapter = self._make_shared_adapter()
        adapter.plan_component_override_values = mock.Mock(
            return_value={
                "normalized_component": "ontology-hub",
                "chart_dir": "/tmp/chart",
                "payload": {"ingress": {"enabled": True}},
                "has_override": True,
                "filename_prefix": "ontology-hub-override-",
            }
        )

        plan = adapter.prepare_component_deployment_plan(
            "ontology-hub",
            ds_name="demo",
            namespace="demo",
            deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            runtime_metadata={
                "chart_dir": "/tmp/chart",
                "values_file": "/tmp/chart/values-demo.yaml",
                "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ontology-hub",
            },
        )

        self.assertEqual(plan["normalized_component"], "ontology-hub")
        self.assertEqual(plan["chart_dir"], "/tmp/chart")
        self.assertEqual(plan["values_file"], "/tmp/chart/values-demo.yaml")
        self.assertEqual(plan["release_name"], "demo-ontology-hub")
        self.assertEqual(
            plan["override_plan"],
            {
                "normalized_component": "ontology-hub",
                "chart_dir": "/tmp/chart",
                "payload": {"ingress": {"enabled": True}},
                "has_override": True,
                "filename_prefix": "ontology-hub-override-",
            },
        )
        adapter.plan_component_override_values.assert_called_once_with(
            "ontology-hub",
            chart_dir="/tmp/chart",
            deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

    def test_shared_components_adapter_deploys_ontology_hub_runtime_via_shared_helper(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_shared_adapter(infrastructure=infrastructure)
        adapter._maybe_prepare_level6_local_image = mock.Mock(return_value=True)
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)
        adapter.verify_component_publication = mock.Mock(return_value={"verified": True})

        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write("ingress:\n  enabled: true\n")

            override_file = os.path.join(tmpdir, "ontology-hub-override.yaml")
            with open(override_file, "w", encoding="utf-8") as handle:
                handle.write("ingress:\n  enabled: true\n")

            adapter._write_component_values_override_file = mock.Mock(return_value=override_file)

            result = adapter.deploy_shared_component_runtime(
                "ontology-hub",
                deployment_plan={
                    "chart_dir": tmpdir,
                    "values_file": values_file,
                    "release_name": "demo-ontology-hub",
                    "override_plan": {"has_override": True},
                },
                namespace="demo",
                deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            )

        self.assertEqual(result["component"], "ontology-hub")
        self.assertTrue(result["built_local_image"])
        self.assertEqual(result["publication"], {"verified": True})
        self.assertEqual(len(infrastructure.deploy_calls), 1)
        deploy_args, deploy_kwargs = infrastructure.deploy_calls[0]
        self.assertEqual(deploy_args[0], "demo-ontology-hub")
        self.assertEqual(deploy_args[1], "demo")
        self.assertEqual(deploy_args[2], ["values-demo.yaml", override_file])
        self.assertEqual(deploy_kwargs["cwd"], os.path.dirname(values_file))
        adapter._maybe_prepare_level6_local_image.assert_called_once_with(
            "ontology-hub",
            values_file,
            {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )
        adapter._wait_for_component_rollout.assert_called_once_with(
            "demo",
            "demo-ontology-hub",
            timeout_seconds=1800,
            label="ontology-hub",
        )
        adapter.run.assert_called_once_with(
            "kubectl rollout restart deployment/demo-ontology-hub -n demo",
            check=False,
        )
        adapter.verify_component_publication.assert_called_once_with(
            "ontology-hub",
            deployment_plan={
                "chart_dir": os.path.dirname(values_file),
                "values_file": values_file,
                "release_name": "demo-ontology-hub",
                "override_plan": {"has_override": True},
            },
            namespace="demo",
        )
        self.assertFalse(os.path.exists(override_file))

    def test_shared_components_adapter_reuses_prepared_ontology_hub_runtime(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_shared_adapter(infrastructure=infrastructure)
        adapter._maybe_prepare_level6_local_image = mock.Mock(return_value=True)
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)
        adapter.verify_component_publication = mock.Mock(return_value={"verified": True})

        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write("ingress:\n  enabled: true\n")

            result = adapter.deploy_shared_component_runtime(
                "ontology-hub",
                deployment_plan={
                    "chart_dir": tmpdir,
                    "values_file": values_file,
                    "release_name": "demo-ontology-hub",
                    "override_plan": {"has_override": False},
                },
                namespace="demo",
                deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
                prepared_execution={
                    "component": "ontology-hub",
                    "release_name": "demo-ontology-hub",
                    "namespace": "demo",
                    "deployer_config": {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
                    "built_local_image": False,
                },
            )

        self.assertEqual(result["component"], "ontology-hub")
        self.assertFalse(result["built_local_image"])
        adapter._maybe_prepare_level6_local_image.assert_not_called()
        self.assertEqual(len(infrastructure.deploy_calls), 1)
        adapter.run.assert_not_called()
        adapter._wait_for_component_rollout.assert_called_once_with(
            "demo",
            "demo-ontology-hub",
            timeout_seconds=1800,
            label="ontology-hub",
        )
        adapter.verify_component_publication.assert_called_once_with(
            "ontology-hub",
            deployment_plan={
                "chart_dir": tmpdir,
                "values_file": values_file,
                "release_name": "demo-ontology-hub",
                "override_plan": {"has_override": False},
            },
            namespace="demo",
        )

    def test_verify_component_publication_accepts_ingress_and_public_routes(self):
        adapter = self._make_shared_adapter()
        adapter.run_silent = mock.Mock(return_value="ontology-hub-demo.dev.ds.dataspaceunit.upm")

        dataset_response = mock.Mock(status_code=200, headers={})
        edition_response = mock.Mock(status_code=302, headers={"Location": "/edition/login"})

        with mock.patch("adapters.shared.components.requests.get", side_effect=[dataset_response, edition_response]):
            result = adapter.verify_component_publication(
                "ontology-hub",
                deployment_plan={
                    "release_name": "demo-ontology-hub",
                    "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                },
                namespace="components",
                timeout_seconds=1,
                poll_interval_seconds=1,
            )

        self.assertTrue(result["verified"])
        self.assertEqual(result["ingress_host"], "ontology-hub-demo.dev.ds.dataspaceunit.upm")
        self.assertEqual(
            result["dataset_url"],
            "http://ontology-hub-demo.dev.ds.dataspaceunit.upm/dataset",
        )
        self.assertEqual(
            result["edition_url"],
            "http://ontology-hub-demo.dev.ds.dataspaceunit.upm/edition",
        )
        adapter.run_silent.assert_called_once_with(
            "kubectl get ingress demo-ontology-hub -n components -o jsonpath='{.spec.rules[0].host}'"
        )

    def test_verify_component_publication_uses_path_public_url_when_configured(self):
        adapter = self._make_shared_adapter()
        adapter.run_silent = mock.Mock(return_value="org1.pionera.oeg.fi.upm.es")

        dataset_response = mock.Mock(status_code=200, headers={})
        edition_response = mock.Mock(status_code=302, headers={"Location": "/ontology-hub/edition/login"})

        with mock.patch("adapters.shared.components.requests.get", side_effect=[dataset_response, edition_response]) as get_mock:
            result = adapter.verify_component_publication(
                "ontology-hub",
                deployment_plan={
                    "release_name": "pionera-ontology-hub",
                    "host": "org1.pionera.oeg.fi.upm.es",
                    "public_url": "https://org1.pionera.oeg.fi.upm.es/ontology-hub",
                },
                namespace="components",
                timeout_seconds=1,
                poll_interval_seconds=1,
            )

        self.assertTrue(result["verified"])
        self.assertEqual(
            result["dataset_url"],
            "https://org1.pionera.oeg.fi.upm.es/ontology-hub/dataset",
        )
        self.assertEqual(
            result["edition_url"],
            "https://org1.pionera.oeg.fi.upm.es/ontology-hub/edition",
        )
        self.assertEqual(
            [call.args[0] for call in get_mock.call_args_list],
            [
                "https://org1.pionera.oeg.fi.upm.es/ontology-hub/dataset",
                "https://org1.pionera.oeg.fi.upm.es/ontology-hub/edition",
            ],
        )

    def test_verify_component_publication_fails_when_ingress_is_missing(self):
        adapter = self._make_shared_adapter()
        adapter.run_silent = mock.Mock(return_value="")

        with self.assertRaisesRegex(RuntimeError, "ingress 'demo-ontology-hub' is missing in namespace 'components'"):
            adapter.verify_component_publication(
                "ontology-hub",
                deployment_plan={
                    "release_name": "demo-ontology-hub",
                    "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                },
                namespace="components",
                timeout_seconds=1,
                poll_interval_seconds=1,
            )

    def test_verify_component_publication_accepts_ai_model_hub_ingress_and_runtime_routes(self):
        adapter = self._make_shared_adapter()
        adapter.run_silent = mock.Mock(return_value="ai-model-hub-demo.dev.ds.dataspaceunit.upm")

        root_response = mock.Mock(status_code=200, headers={})
        config_response = mock.Mock(status_code=200, headers={})

        with mock.patch("adapters.shared.components.requests.get", side_effect=[root_response, config_response]):
            result = adapter.verify_component_publication(
                "ai-model-hub",
                deployment_plan={
                    "release_name": "demo-ai-model-hub",
                    "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                },
                namespace="components",
                timeout_seconds=1,
                poll_interval_seconds=1,
            )

        self.assertTrue(result["verified"])
        self.assertEqual(result["ingress_host"], "ai-model-hub-demo.dev.ds.dataspaceunit.upm")
        self.assertEqual(result["root_url"], "http://ai-model-hub-demo.dev.ds.dataspaceunit.upm")
        self.assertEqual(
            result["config_url"],
            "http://ai-model-hub-demo.dev.ds.dataspaceunit.upm/config/app-config.json",
        )
        adapter.run_silent.assert_called_once_with(
            "kubectl get ingress demo-ai-model-hub -n components -o jsonpath='{.spec.rules[0].host}'"
        )

    def test_shared_components_adapter_deploy_component_release_writes_override_and_cleans_it_up(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_shared_adapter(infrastructure=infrastructure)

        with tempfile.TemporaryDirectory() as tmpdir:
            values_file = os.path.join(tmpdir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                handle.write("ingress:\n  enabled: true\n")

            override_file = os.path.join(tmpdir, "ontology-hub-override.yaml")
            with open(override_file, "w", encoding="utf-8") as handle:
                handle.write("ingress:\n  enabled: true\n")

            adapter._write_component_values_override_file = mock.Mock(return_value=override_file)

            result = adapter.deploy_component_release(
                "ontology-hub",
                deployment_plan={
                    "chart_dir": tmpdir,
                    "values_file": values_file,
                    "release_name": "demo-ontology-hub",
                    "override_plan": {"has_override": True},
                },
                namespace="demo",
                deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
            )

        self.assertEqual(result["component"], "ontology-hub")
        self.assertEqual(result["values_files"], ["values-demo.yaml", override_file])
        self.assertEqual(len(infrastructure.deploy_calls), 1)
        deploy_args, deploy_kwargs = infrastructure.deploy_calls[0]
        self.assertEqual(deploy_args[0], "demo-ontology-hub")
        self.assertEqual(deploy_args[1], "demo")
        self.assertEqual(deploy_args[2], ["values-demo.yaml", override_file])
        self.assertEqual(deploy_kwargs["cwd"], os.path.dirname(values_file))
        self.assertFalse(os.path.exists(override_file))

    def test_components_restart_release_when_config_override_applied_without_image_rebuild(self):
        infrastructure = FakeInfrastructure()
        infrastructure.reconcile_vault_state_for_local_runtime = mock.Mock(return_value=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "repo")
            os.makedirs(repo_dir, exist_ok=True)

            class RuntimeConfig(FakeConfig):
                @classmethod
                def repo_dir(cls):
                    return repo_dir

            adapter = INESDataComponentsAdapter(
                run=mock.Mock(return_value="ok"),
                run_silent=mock.Mock(return_value=""),
                auto_mode_getter=lambda: True,
                infrastructure_adapter=infrastructure,
                config_cls=RuntimeConfig,
            )
            adapter.config_adapter.topology = "vm-single"
            deployer_config = {
                "TOPOLOGY": "vm-single",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "DS_1_CONNECTORS": "org2,org3",
            }
            adapter.config_adapter.load_deployer_config = mock.Mock(return_value=deployer_config)
            adapter._cleanup_components = mock.Mock()
            adapter._cleanup_legacy_component_releases = mock.Mock(return_value=None)
            adapter._resolve_component_chart_dir = mock.Mock(return_value=tmpdir)
            adapter._resolve_component_release_name = mock.Mock(return_value="demo-ai-model-hub")
            adapter._maybe_prepare_level6_local_image = mock.Mock(return_value=False)
            adapter._wait_for_component_rollout = mock.Mock(return_value=True)

            values_file = os.path.join(tmpdir, "values-demo.yaml")
            with open(values_file, "w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "image": {"repository": "ai-model-hub", "tag": "local"},
                        "ingress": {"enabled": True},
                    },
                    handle,
                    sort_keys=False,
                )
            adapter._resolve_component_values_file = mock.Mock(return_value=values_file)

            result = adapter.COMPONENTS(["ai-model-hub"], namespace="components", deployer_config=deployer_config)

        self.assertEqual(result["deployed"], ["ai-model-hub"])
        self.assertEqual(len(infrastructure.deploy_calls), 1)
        infrastructure.reconcile_vault_state_for_local_runtime.assert_called_once()
        adapter.run.assert_called_once_with(
            "kubectl rollout restart deployment/demo-ai-model-hub -n components",
            check=False,
        )
        adapter._wait_for_component_rollout.assert_called_once_with(
            "components",
            "demo-ai-model-hub",
            timeout_seconds=300,
            label="ai-model-hub",
        )

    def test_components_fail_when_local_vault_token_sync_fails(self):
        infrastructure = FakeInfrastructure()
        infrastructure.reconcile_vault_state_for_local_runtime = mock.Mock(return_value=False)
        adapter = self._make_adapter(infrastructure=infrastructure)
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={})

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "Vault token could not be synchronized"):
                adapter.COMPONENTS(["ai-model-hub"])

        infrastructure.reconcile_vault_state_for_local_runtime.assert_called_once()

    def test_shared_components_adapter_finalize_component_runtime_restarts_and_waits_for_ontology_hub(self):
        adapter = self._make_shared_adapter()
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)

        result = adapter.finalize_component_runtime(
            "ontology-hub",
            release_name="demo-ontology-hub",
            namespace="demo",
            built_local_image=True,
        )

        self.assertEqual(result["component"], "ontology-hub")
        self.assertTrue(result["built_local_image"])
        self.assertTrue(result["waited_for_rollout"])
        adapter.run.assert_called_once_with(
            "kubectl rollout restart deployment/demo-ontology-hub -n demo",
            check=False,
        )
        adapter._wait_for_component_rollout.assert_called_once_with(
            "demo",
            "demo-ontology-hub",
            timeout_seconds=1800,
            label="ontology-hub",
        )

    def test_shared_components_adapter_finalize_component_runtime_restarts_and_waits_for_semantic_virtualization(self):
        adapter = self._make_shared_adapter()
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)
        deployer_config = {"SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true"}

        result = adapter.finalize_component_runtime(
            "semantic-virtualization",
            release_name="demo-semantic-virtualization",
            namespace="components",
            built_local_image=True,
            deployer_config=deployer_config,
        )

        self.assertEqual(result["component"], "semantic-virtualization")
        self.assertTrue(result["built_local_image"])
        self.assertTrue(result["waited_for_rollout"])
        self.assertEqual(
            adapter.run.mock_calls,
            [
                mock.call(
                    "kubectl rollout restart deployment/demo-semantic-virtualization -n components",
                    check=False,
                ),
                mock.call(
                    "kubectl rollout restart deployment/demo-semantic-virtualization-editor -n components",
                    check=False,
                ),
            ],
        )
        self.assertEqual(
            adapter._wait_for_component_rollout.mock_calls,
            [
                mock.call(
                    "components",
                    "demo-semantic-virtualization",
                    timeout_seconds=900,
                    label="semantic-virtualization",
                ),
                mock.call(
                    "components",
                    "demo-semantic-virtualization-editor",
                    timeout_seconds=900,
                    label="semantic-virtualization-editor",
                ),
            ],
        )

    def test_shared_components_adapter_prepares_component_runtime_execution(self):
        adapter = self._make_shared_adapter()
        adapter._maybe_prepare_level6_local_image = mock.Mock(return_value=True)

        result = adapter.prepare_component_runtime_execution(
            "ontology-hub",
            deployment_plan={
                "values_file": "/tmp/chart/values-demo.yaml",
                "release_name": "demo-ontology-hub",
            },
            namespace="demo",
            deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

        self.assertEqual(result["component"], "ontology-hub")
        self.assertEqual(result["release_name"], "demo-ontology-hub")
        self.assertEqual(result["namespace"], "demo")
        self.assertTrue(result["built_local_image"])
        self.assertEqual(result["deployer_config"], {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"})
        adapter._maybe_prepare_level6_local_image.assert_called_once_with(
            "ontology-hub",
            "/tmp/chart/values-demo.yaml",
            {"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

    def test_shared_components_adapter_finalize_component_runtime_waits_for_ai_model_hub(self):
        adapter = self._make_shared_adapter()
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)
        adapter._ensure_ai_model_hub_model_server = mock.Mock(return_value={"enabled": False})

        result = adapter.finalize_component_runtime(
            "ai-model-hub",
            release_name="demo-ai-model-hub",
            namespace="demo",
            built_local_image=False,
            deployer_config={},
        )

        self.assertEqual(result["component"], "ai-model-hub")
        self.assertFalse(result["built_local_image"])
        self.assertTrue(result["waited_for_rollout"])
        adapter.run.assert_not_called()
        adapter._wait_for_component_rollout.assert_called_once_with(
            "demo",
            "demo-ai-model-hub",
            timeout_seconds=900,
            label="ai-model-hub",
        )
        adapter._ensure_ai_model_hub_model_server.assert_called_once_with("demo", {})

    def test_shared_components_adapter_vm_single_ai_model_hub_imports_local_image_before_rollout(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig": "/clusters/pionera4.yaml",
        }
        adapter.run_silent = mock.Mock(return_value="eclipse-edc/data-dashboard:local")
        adapter._ensure_k3s_local_image_import_supported = mock.Mock()
        adapter._build_ai_model_hub_image_on_host = mock.Mock()
        adapter._load_image_into_cluster_runtime = mock.Mock()
        adapter._host_has_image = mock.Mock(return_value=True)
        adapter._load_images_into_cluster_runtime = mock.Mock()
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)
        adapter._ensure_ai_model_hub_model_server = mock.Mock(return_value={"enabled": False})

        result = adapter.finalize_component_runtime(
            "ai-model-hub",
            release_name="demo-ai-model-hub",
            namespace="components",
            built_local_image=False,
            deployer_config={
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
            },
        )

        self.assertTrue(result["built_local_image"])
        adapter.run_silent.assert_has_calls(
            [
                mock.call(
                    "kubectl get deployment demo-ai-model-hub -n components "
                    "-o jsonpath='{.spec.template.spec.containers[0].image}'"
                ),
                mock.call(
                    "kubectl get deployment demo-ai-model-hub -n components "
                    "-o jsonpath='{range .spec.template.spec.containers[*]}{.image}{\"\\n\"}{end}'"
                ),
            ]
        )
        adapter._ensure_k3s_local_image_import_supported.assert_any_call(
            "eclipse-edc/data-dashboard:local",
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
            },
        )
        adapter._build_ai_model_hub_image_on_host.assert_called_once_with(
            "eclipse-edc/data-dashboard:local",
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
            },
        )
        adapter._load_image_into_cluster_runtime.assert_called_once_with(
            "k3s",
            "minikube",
            "eclipse-edc/data-dashboard:local",
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
            },
        )
        adapter._load_images_into_cluster_runtime.assert_called_once_with(
            "k3s",
            "minikube",
            ["eclipse-edc/data-dashboard:local"],
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
            },
        )
        adapter.run.assert_called_once_with(
            "kubectl rollout restart deployment/demo-ai-model-hub -n components",
            check=False,
        )
        adapter._wait_for_component_rollout.assert_called_once_with(
            "components",
            "demo-ai-model-hub",
            timeout_seconds=900,
            label="ai-model-hub",
        )

    def test_shared_components_adapter_vm_single_revalidates_rendered_local_image_even_when_prepared(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig": "/clusters/pionera4.yaml",
        }
        adapter.run_silent = mock.Mock(return_value="eclipse-edc/data-dashboard:local")
        adapter._ensure_k3s_local_image_import_supported = mock.Mock()
        adapter._host_has_image = mock.Mock(return_value=True)
        adapter._load_images_into_cluster_runtime = mock.Mock()
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)
        adapter._ensure_ai_model_hub_model_server = mock.Mock(return_value={"enabled": False})

        result = adapter.finalize_component_runtime(
            "ai-model-hub",
            release_name="demo-ai-model-hub",
            namespace="components",
            built_local_image=True,
            deployer_config={
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
            },
        )

        self.assertTrue(result["built_local_image"])
        adapter._load_images_into_cluster_runtime.assert_called_once_with(
            "k3s",
            "minikube",
            ["eclipse-edc/data-dashboard:local"],
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
            },
        )

    def test_shared_components_adapter_vm_single_semantic_virtualization_imports_local_images_before_rollout(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.cluster_runtime = lambda: {
            "cluster_type": "k3s",
            "k3s_kubeconfig": "/clusters/pionera4.yaml",
        }
        adapter.run_silent = mock.Mock(
            side_effect=[
                "morph-kgv:local\n",
                "mapping-editor:local\n",
            ]
        )
        adapter._ensure_k3s_local_image_import_supported = mock.Mock()
        adapter._host_has_image = mock.Mock(return_value=True)
        adapter._load_images_into_cluster_runtime = mock.Mock()
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)

        result = adapter.finalize_component_runtime(
            "semantic-virtualization",
            release_name="demo-semantic-virtualization",
            namespace="components",
            built_local_image=False,
            deployer_config={
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
            },
        )

        self.assertTrue(result["built_local_image"])
        adapter._ensure_k3s_local_image_import_supported.assert_has_calls(
            [
                mock.call(
                    "morph-kgv:local",
                    {
                        "CLUSTER_TYPE": "k3s",
                        "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
                        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                    },
                ),
                mock.call(
                    "mapping-editor:local",
                    {
                        "CLUSTER_TYPE": "k3s",
                        "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
                        "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                    },
                ),
            ]
        )
        adapter._load_images_into_cluster_runtime.assert_called_once_with(
            "k3s",
            "minikube",
            ["morph-kgv:local", "mapping-editor:local"],
            {
                "CLUSTER_TYPE": "k3s",
                "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
            },
        )
        adapter.run.assert_has_calls(
            [
                mock.call(
                    "kubectl rollout restart deployment/demo-semantic-virtualization -n components",
                    check=False,
                ),
                mock.call(
                    "kubectl rollout restart deployment/demo-semantic-virtualization-editor -n components",
                    check=False,
                ),
            ]
        )
        adapter._wait_for_component_rollout.assert_has_calls(
            [
                mock.call(
                    "components",
                    "demo-semantic-virtualization",
                    timeout_seconds=900,
                    label="semantic-virtualization",
                ),
                mock.call(
                    "components",
                    "demo-semantic-virtualization-editor",
                    timeout_seconds=900,
                    label="semantic-virtualization-editor",
                ),
            ]
        )

    def test_shared_components_adapter_finalize_component_runtime_skips_rollout_for_plain_component(self):
        adapter = self._make_shared_adapter()
        adapter._wait_for_component_rollout = mock.Mock(return_value=True)

        result = adapter.finalize_component_runtime(
            "custom-component",
            release_name="demo-custom-component",
            namespace="demo",
            built_local_image=False,
        )

        self.assertEqual(result["component"], "custom-component")
        self.assertFalse(result["built_local_image"])
        self.assertFalse(result["waited_for_rollout"])
        adapter.run.assert_not_called()
        adapter._wait_for_component_rollout.assert_not_called()

    def test_components_delegate_ontology_hub_runtime_to_shared_helper(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_shared_adapter(infrastructure=infrastructure)
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={})
        adapter._cleanup_components = mock.Mock()
        adapter._cleanup_legacy_component_releases = mock.Mock(return_value=None)
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "component": "ontology-hub",
                    "normalized_component": "ontology-hub",
                    "excluded": False,
                    "error": None,
                    "chart_dir": "/tmp/chart",
                    "values_file": "/tmp/chart/values-demo.yaml",
                    "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    "release_name": "demo-ontology-hub",
                }
            ]
        )
        adapter.prepare_component_deployment_plan = mock.Mock(
            return_value={
                "component": "ontology-hub",
                "normalized_component": "ontology-hub",
                "chart_dir": "/tmp/chart",
                "values_file": "/tmp/chart/values-demo.yaml",
                "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ontology-hub",
                "override_plan": {"has_override": True},
            }
        )
        prepared_execution = {
            "component": "ontology-hub",
            "release_name": "demo-ontology-hub",
            "namespace": "components",
            "deployer_config": {},
            "built_local_image": False,
        }
        adapter.prepare_component_runtime_execution = mock.Mock(return_value=prepared_execution)
        adapter.deploy_shared_component_runtime = mock.Mock(return_value={"component": "ontology-hub"})

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            result = adapter.COMPONENTS(["ontology-hub"])

        self.assertEqual(result["deployed"], ["ontology-hub"])
        self.assertEqual(
            result["urls"],
            {"ontology-hub": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm"},
        )
        adapter.deploy_shared_component_runtime.assert_called_once_with(
            "ontology-hub",
            deployment_plan={
                "component": "ontology-hub",
                "normalized_component": "ontology-hub",
                "chart_dir": "/tmp/chart",
                "values_file": "/tmp/chart/values-demo.yaml",
                "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ontology-hub",
                "override_plan": {"has_override": True},
            },
            namespace="components",
            deployer_config={},
            prepared_execution=prepared_execution,
        )
        adapter._cleanup_legacy_component_releases.assert_called_once_with(
            ["ontology-hub"],
            active_namespace="components",
            ds_name="demo",
            deployer_config={},
        )
        adapter._cleanup_components.assert_called_once_with(["ontology-hub"], "components")
        self.assertEqual(infrastructure.deploy_calls, [])

    def test_components_does_not_cleanup_or_deploy_when_runtime_preparation_fails(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={})
        adapter._cleanup_components = mock.Mock()
        adapter._cleanup_legacy_component_releases = mock.Mock(return_value=None)
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "component": "ontology-hub",
                    "normalized_component": "ontology-hub",
                    "excluded": False,
                    "error": None,
                    "chart_dir": "/tmp/chart",
                    "values_file": "/tmp/chart/values-demo.yaml",
                    "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    "release_name": "demo-ontology-hub",
                }
            ]
        )
        adapter.prepare_component_deployment_plan = mock.Mock(
            return_value={
                "component": "ontology-hub",
                "normalized_component": "ontology-hub",
                "chart_dir": "/tmp/chart",
                "values_file": "/tmp/chart/values-demo.yaml",
                "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ontology-hub",
                "override_plan": {"has_override": True},
            }
        )
        adapter.prepare_component_runtime_execution = mock.Mock(
            side_effect=RuntimeError("image import failed")
        )
        adapter.deploy_shared_component_runtime = mock.Mock(return_value={"component": "ontology-hub"})

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "image import failed"):
                adapter.COMPONENTS(["ontology-hub"])

        adapter._cleanup_legacy_component_releases.assert_not_called()
        adapter._cleanup_components.assert_not_called()
        adapter.deploy_shared_component_runtime.assert_not_called()

    def test_components_prepares_runtime_before_cleanup_and_deploy(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={})
        events = []
        adapter._cleanup_legacy_component_releases = mock.Mock(
            side_effect=lambda *args, **kwargs: events.append("legacy-cleanup") or None
        )
        adapter._cleanup_components = mock.Mock(side_effect=lambda *args, **kwargs: events.append("cleanup"))
        adapter.verify_component_publication = mock.Mock(return_value={"verified": True})
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "component": "ai-model-hub",
                    "normalized_component": "ai-model-hub",
                    "excluded": False,
                    "error": None,
                    "chart_dir": "/tmp/chart-ai",
                    "values_file": "/tmp/chart-ai/values-demo.yaml",
                    "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                    "release_name": "demo-ai-model-hub",
                }
            ]
        )
        adapter.prepare_component_deployment_plan = mock.Mock(
            return_value={
                "component": "ai-model-hub",
                "normalized_component": "ai-model-hub",
                "chart_dir": "/tmp/chart-ai",
                "values_file": "/tmp/chart-ai/values-demo.yaml",
                "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ai-model-hub",
                "override_plan": {"has_override": False},
            }
        )
        adapter.prepare_component_runtime_execution = mock.Mock(
            side_effect=lambda *args, **kwargs: events.append("prepare") or {
                "component": "ai-model-hub",
                "release_name": "demo-ai-model-hub",
                "namespace": "components",
                "deployer_config": {},
                "built_local_image": True,
            }
        )
        adapter.deploy_component_release = mock.Mock(
            side_effect=lambda *args, **kwargs: events.append("deploy") or {
                "component": "ai-model-hub",
                "release_name": "demo-ai-model-hub",
                "namespace": "components",
            }
        )
        adapter.finalize_component_runtime = mock.Mock(
            side_effect=lambda *args, **kwargs: events.append("finalize") or {"component": "ai-model-hub"}
        )

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            result = adapter.COMPONENTS(["ai-model-hub"])

        self.assertEqual(result["deployed"], ["ai-model-hub"])
        self.assertEqual(events, ["prepare", "legacy-cleanup", "cleanup", "deploy", "finalize"])

    def test_components_prepare_all_local_images_before_cleanup_and_component_deploy(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.topology = "vm-single"
        deployer_config = {
            "CLUSTER_TYPE": "k3s",
            "K3S_KUBECONFIG": "/clusters/pionera4.yaml",
        }
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value=deployer_config)
        components = ["ontology-hub", "ai-model-hub", "semantic-virtualization"]
        events = []

        def metadata_for(component):
            return {
                "component": component,
                "normalized_component": component,
                "excluded": False,
                "error": None,
                "chart_dir": f"/tmp/chart-{component}",
                "values_file": f"/tmp/chart-{component}/values-demo.yaml",
                "host": f"{component}-demo.dev.ds.dataspaceunit.upm",
                "release_name": f"demo-{component}",
            }

        adapter._cleanup_legacy_component_releases = mock.Mock(
            side_effect=lambda *args, **kwargs: events.append("legacy-cleanup") or None
        )
        adapter._cleanup_components = mock.Mock(side_effect=lambda *args, **kwargs: events.append("cleanup"))
        adapter._cleanup_vm_distributed_legacy_public_path_ingresses = mock.Mock(return_value=None)
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[metadata_for(component) for component in components]
        )
        adapter.prepare_component_deployment_plan = mock.Mock(
            side_effect=lambda normalized, **kwargs: {
                **metadata_for(normalized),
                "override_plan": {"has_override": False},
            }
        )
        adapter.prepare_component_runtime_execution = mock.Mock(
            side_effect=lambda normalized, **kwargs: events.append(f"prepare:{normalized}") or {
                "component": normalized,
                "release_name": f"demo-{normalized}",
                "namespace": "components",
                "deployer_config": deployer_config,
                "built_local_image": True,
            }
        )
        adapter.deploy_component_release = mock.Mock(
            side_effect=lambda normalized, **kwargs: events.append(f"deploy:{normalized}") or {
                "component": normalized,
                "release_name": f"demo-{normalized}",
                "namespace": "components",
            }
        )
        adapter.finalize_component_runtime = mock.Mock(
            side_effect=lambda normalized, **kwargs: events.append(f"finalize:{normalized}") or {
                "component": normalized,
                "release_name": f"demo-{normalized}",
            }
        )
        adapter.verify_component_publication = mock.Mock(
            side_effect=lambda normalized, **kwargs: events.append(f"verify:{normalized}") or {"verified": True}
        )

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            result = adapter.COMPONENTS(components)

        self.assertEqual(result["deployed"], components)
        self.assertEqual(
            events,
            [
                "prepare:ontology-hub",
                "prepare:ai-model-hub",
                "prepare:semantic-virtualization",
                "legacy-cleanup",
                "cleanup",
                "deploy:ontology-hub",
                "finalize:ontology-hub",
                "verify:ontology-hub",
                "deploy:ai-model-hub",
                "finalize:ai-model-hub",
                "verify:ai-model-hub",
                "deploy:semantic-virtualization",
                "finalize:semantic-virtualization",
                "verify:semantic-virtualization",
            ],
        )

    def test_components_sync_mapping_editor_hostname_when_enabled(self):
        infrastructure = FakeInfrastructure()
        infrastructure.manage_hosts_entries = mock.Mock(return_value=True)
        adapter = self._make_shared_adapter(infrastructure=infrastructure)
        deployer_config = {
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_HOST": (
                "semantic-virtualization-editor-demo.dev.ds.dataspaceunit.upm"
            ),
        }
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value=deployer_config)
        adapter._cleanup_components = mock.Mock()
        adapter._cleanup_legacy_component_releases = mock.Mock(return_value=None)
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "component": "semantic-virtualization",
                    "normalized_component": "semantic-virtualization",
                    "excluded": False,
                    "error": None,
                    "chart_dir": "/tmp/chart",
                    "values_file": "/tmp/chart/values-demo.yaml",
                    "host": "semantic-virtualization-demo.dev.ds.dataspaceunit.upm",
                    "release_name": "demo-semantic-virtualization",
                }
            ]
        )
        adapter.prepare_component_deployment_plan = mock.Mock(
            return_value={
                "component": "semantic-virtualization",
                "normalized_component": "semantic-virtualization",
                "chart_dir": "/tmp/chart",
                "values_file": "/tmp/chart/values-demo.yaml",
                "host": "semantic-virtualization-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-semantic-virtualization",
                "override_plan": {"has_override": True},
            }
        )
        adapter.prepare_component_runtime_execution = mock.Mock(
            return_value={
                "component": "semantic-virtualization",
                "release_name": "demo-semantic-virtualization",
                "namespace": "components",
                "deployer_config": deployer_config,
                "built_local_image": False,
            }
        )
        adapter.deploy_shared_component_runtime = mock.Mock(
            return_value={"component": "semantic-virtualization"}
        )

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            result = adapter.COMPONENTS(["semantic-virtualization"])

        self.assertEqual(result["deployed"], ["semantic-virtualization"])
        desired_entries = infrastructure.manage_hosts_entries.call_args.args[0]
        self.assertIn("127.0.0.1 semantic-virtualization-demo.dev.ds.dataspaceunit.upm", desired_entries)
        self.assertIn(
            "127.0.0.1 semantic-virtualization-editor-demo.dev.ds.dataspaceunit.upm",
            desired_entries,
        )

    def test_components_keep_ai_model_hub_on_legacy_runtime_path(self):
        infrastructure = FakeInfrastructure()
        adapter = self._make_shared_adapter(infrastructure=infrastructure)
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={})
        adapter._cleanup_components = mock.Mock()
        adapter._cleanup_legacy_component_releases = mock.Mock(return_value=None)
        adapter.verify_component_publication = mock.Mock(return_value={"verified": True})
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "component": "ai-model-hub",
                    "normalized_component": "ai-model-hub",
                    "excluded": False,
                    "error": None,
                    "chart_dir": "/tmp/chart-ai",
                    "values_file": "/tmp/chart-ai/values-demo.yaml",
                    "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                    "release_name": "demo-ai-model-hub",
                }
            ]
        )
        adapter.prepare_component_deployment_plan = mock.Mock(
            return_value={
                "component": "ai-model-hub",
                "normalized_component": "ai-model-hub",
                "chart_dir": "/tmp/chart-ai",
                "values_file": "/tmp/chart-ai/values-demo.yaml",
                "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ai-model-hub",
                "override_plan": {"has_override": False},
            }
        )
        adapter._maybe_prepare_level6_local_image = mock.Mock(return_value=False)
        adapter._write_component_values_override_file = mock.Mock(return_value=None)
        adapter.deploy_component_release = mock.Mock(
            return_value={
                "component": "ai-model-hub",
                "release_name": "demo-ai-model-hub",
                "namespace": "demo",
                "values_files": ["values-demo.yaml"],
            }
        )
        adapter.prepare_component_runtime_execution = mock.Mock(
            return_value={
                "component": "ai-model-hub",
                "release_name": "demo-ai-model-hub",
                "namespace": "components",
                "deployer_config": {},
                "built_local_image": False,
            }
        )
        adapter.finalize_component_runtime = mock.Mock(
            return_value={
                "component": "ai-model-hub",
                "release_name": "demo-ai-model-hub",
                "namespace": "components",
                "built_local_image": False,
                "waited_for_rollout": False,
            }
        )

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            result = adapter.COMPONENTS(["ai-model-hub"])

        self.assertEqual(result["deployed"], ["ai-model-hub"])
        self.assertEqual(
            result["urls"],
            {"ai-model-hub": "http://ai-model-hub-demo.dev.ds.dataspaceunit.upm"},
        )
        adapter.deploy_component_release.assert_called_once_with(
            "ai-model-hub",
            deployment_plan={
                "component": "ai-model-hub",
                "normalized_component": "ai-model-hub",
                "chart_dir": "/tmp/chart-ai",
                "values_file": "/tmp/chart-ai/values-demo.yaml",
                "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ai-model-hub",
                "override_plan": {"has_override": False},
            },
            namespace="components",
            deployer_config={},
        )
        adapter.prepare_component_runtime_execution.assert_called_once_with(
            "ai-model-hub",
            deployment_plan={
                "component": "ai-model-hub",
                "normalized_component": "ai-model-hub",
                "chart_dir": "/tmp/chart-ai",
                "values_file": "/tmp/chart-ai/values-demo.yaml",
                "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ai-model-hub",
                "override_plan": {"has_override": False},
            },
            namespace="components",
            deployer_config={},
        )
        adapter.finalize_component_runtime.assert_called_once_with(
            "ai-model-hub",
            release_name="demo-ai-model-hub",
            namespace="components",
            built_local_image=False,
            deployer_config={},
        )
        adapter.verify_component_publication.assert_called_once_with(
            "ai-model-hub",
            deployment_plan={
                "component": "ai-model-hub",
                "normalized_component": "ai-model-hub",
                "chart_dir": "/tmp/chart-ai",
                "values_file": "/tmp/chart-ai/values-demo.yaml",
                "host": "ai-model-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ai-model-hub",
                "override_plan": {"has_override": False},
            },
            namespace="components",
        )
        adapter._cleanup_legacy_component_releases.assert_called_once_with(
            ["ai-model-hub"],
            active_namespace="components",
            ds_name="demo",
            deployer_config={},
        )
        adapter._cleanup_components.assert_called_once_with(["ai-model-hub"], "components")
        self.assertEqual(infrastructure.deploy_calls, [])
        adapter._maybe_prepare_level6_local_image.assert_not_called()

    def test_components_skip_local_runtime_access_and_hosts_sync_for_vm_single(self):
        infrastructure = FakeInfrastructure()
        infrastructure.ensure_local_infra_access = mock.Mock(return_value=False)
        infrastructure.manage_hosts_entries = mock.Mock(return_value=True)
        adapter = self._make_shared_adapter(infrastructure=infrastructure)
        adapter.config_adapter.topology = "vm-single"
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={})
        adapter._cleanup_components = mock.Mock()
        adapter._cleanup_legacy_component_releases = mock.Mock(return_value=None)
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "component": "ontology-hub",
                    "normalized_component": "ontology-hub",
                    "excluded": False,
                    "error": None,
                    "chart_dir": "/tmp/chart",
                    "values_file": "/tmp/chart/values-demo.yaml",
                    "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    "release_name": "demo-ontology-hub",
                }
            ]
        )
        adapter.prepare_component_deployment_plan = mock.Mock(
            return_value={
                "component": "ontology-hub",
                "normalized_component": "ontology-hub",
                "chart_dir": "/tmp/chart",
                "values_file": "/tmp/chart/values-demo.yaml",
                "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                "release_name": "demo-ontology-hub",
                "override_plan": {"has_override": True},
            }
        )
        adapter.prepare_component_runtime_execution = mock.Mock(
            return_value={
                "component": "ontology-hub",
                "release_name": "demo-ontology-hub",
                "namespace": "components",
                "deployer_config": {},
                "built_local_image": False,
            }
        )
        adapter.deploy_shared_component_runtime = mock.Mock(return_value={"component": "ontology-hub"})

        with mock.patch("adapters.inesdata.components.os.path.exists", return_value=True):
            result = adapter.COMPONENTS(["ontology-hub"])

        self.assertEqual(result["deployed"], ["ontology-hub"])
        infrastructure.ensure_local_infra_access.assert_not_called()
        infrastructure.manage_hosts_entries.assert_not_called()

    def test_infer_component_urls_prefers_shared_runtime_resolver_when_available(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(return_value={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"})
        adapter.prepare_component_runtime_metadata = mock.Mock(
            side_effect=[
                [
                    {
                        "normalized_component": "ontology-hub",
                        "host": "ontology-hub-demo.dev.ds.dataspaceunit.upm",
                        "error": None,
                        "excluded": False,
                    },
                    {
                        "normalized_component": "ai-model-hub",
                        "host": "",
                        "error": None,
                        "excluded": False,
                    },
                ]
            ]
        )

        urls = adapter.infer_component_urls(["ontology-hub", "ai-model-hub"])

        self.assertEqual(
            urls,
            {"ontology-hub": "http://ontology-hub-demo.dev.ds.dataspaceunit.upm"},
        )
        adapter.prepare_component_runtime_metadata.assert_called_once_with(
            ["ontology-hub", "ai-model-hub"],
            ds_name="demo",
            namespace="components",
            deployer_config={"DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm"},
        )

    def test_infer_component_urls_includes_mapping_editor_when_enabled(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(
            return_value={
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
            }
        )
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "normalized_component": "semantic-virtualization",
                    "host": "semantic-virtualization-demo.dev.ds.dataspaceunit.upm",
                    "error": None,
                    "excluded": False,
                },
            ]
        )

        urls = adapter.infer_component_urls(["semantic-virtualization"])

        self.assertEqual(
            urls,
            {
                "semantic-virtualization": "http://semantic-virtualization-demo.dev.ds.dataspaceunit.upm",
                "semantic-virtualization-editor": "http://semantic-virtualization-editor-demo.dev.ds.dataspaceunit.upm",
            },
        )

    def test_infer_component_urls_uses_dedicated_mapping_editor_url(self):
        adapter = self._make_shared_adapter()
        adapter.config_adapter.load_deployer_config = mock.Mock(
            return_value={
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_ENABLED": "true",
                "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_URL": "https://streamlit.example.org",
            }
        )
        adapter.prepare_component_runtime_metadata = mock.Mock(
            return_value=[
                {
                    "normalized_component": "semantic-virtualization",
                    "host": "org4.pionera.oeg.fi.upm.es",
                    "public_url": "https://org4.pionera.oeg.fi.upm.es/semantic-virtualization",
                    "error": None,
                    "excluded": False,
                },
            ]
        )

        urls = adapter.infer_component_urls(["semantic-virtualization"])

        self.assertEqual(
            urls,
            {
                "semantic-virtualization": "https://org4.pionera.oeg.fi.upm.es/semantic-virtualization",
                "semantic-virtualization-editor": "https://streamlit.example.org",
            },
        )


if __name__ == "__main__":
    unittest.main()
