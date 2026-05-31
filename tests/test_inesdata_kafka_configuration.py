import os
import tempfile
import unittest
from unittest import mock

from adapters.inesdata.adapter import InesdataAdapter
from adapters.inesdata.config import InesdataConfig


def _project_path(*parts):
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", *parts))


class InesdataKafkaConfigurationTests(unittest.TestCase):
    def _write_deployer_config(self, root_dir, lines):
        repo_dir = os.path.join(root_dir, "deployers", "inesdata")
        os.makedirs(repo_dir, exist_ok=True)
        config_path = os.path.join(repo_dir, "deployer.config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return config_path

    def test_get_kafka_config_reads_values_from_deployer_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, "kafka.env")
            with open(env_file, "w", encoding="utf-8") as handle:
                handle.write("KAFKA_CFG_SASL_ENABLED_MECHANISMS=PLAIN\n")

            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "KAFKA_BOOTSTRAP_SERVERS=kafka.example.internal:29092",
                    "KAFKA_PROVISIONER=kubernetes",
                    "KAFKA_CLUSTER_BOOTSTRAP_SERVERS=kafka.cluster.internal:39092",
                    "KAFKA_CLUSTER_ADVERTISED_HOST=cluster.kafka.internal",
                    "KAFKA_K8S_NAMESPACE=custom-kafka",
                    "KAFKA_K8S_PROBE_NAMESPACES=provider,consumer",
                    "KAFKA_K8S_SERVICE_NAME=kafka-validation",
                    "KAFKA_K8S_LOCAL_PORT=39093",
                    "KAFKA_MINIKUBE_PROFILE=pionera",
                    "KAFKA_TOPIC_NAME=edc-kafka-benchmark",
                    "KAFKA_TOPIC_STRATEGY=STATIC_TOPIC",
                    "KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT",
                    "KAFKA_SASL_MECHANISM=PLAIN",
                    "KAFKA_USERNAME=framework",
                    "KAFKA_PASSWORD=framework-secret",
                    "KAFKA_CONTAINER_NAME=kafka-sasl",
                    "KAFKA_CONTAINER_IMAGE=confluentinc/cp-kafka:7.5.2",
                    f"KAFKA_CONTAINER_ENV_FILE={env_file}",
                    "KAFKA_MESSAGE_COUNT=25",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter()
                config = adapter.get_kafka_config()

        self.assertEqual(config["bootstrap_servers"], "kafka.example.internal:29092")
        self.assertEqual(config["provisioner"], "kubernetes")
        self.assertEqual(config["cluster_bootstrap_servers"], "kafka.cluster.internal:39092")
        self.assertEqual(config["cluster_advertised_host"], "cluster.kafka.internal")
        self.assertEqual(config["k8s_namespace"], "custom-kafka")
        self.assertEqual(config["k8s_probe_namespaces"], "provider,consumer")
        self.assertEqual(config["k8s_service_name"], "kafka-validation")
        self.assertEqual(config["k8s_local_port"], "39093")
        self.assertEqual(config["minikube_profile"], "pionera")
        self.assertEqual(config["topic_name"], "edc-kafka-benchmark")
        self.assertEqual(config["topic_strategy"], "STATIC_TOPIC")
        self.assertEqual(config["security_protocol"], "SASL_PLAINTEXT")
        self.assertEqual(config["sasl_mechanism"], "PLAIN")
        self.assertEqual(config["username"], "framework")
        self.assertEqual(config["password"], "framework-secret")
        self.assertEqual(config["container_name"], "kafka-sasl")
        self.assertEqual(config["container_image"], "confluentinc/cp-kafka:7.5.2")
        self.assertEqual(config["container_env_file"], env_file)
        self.assertEqual(config["message_count"], "25")
        self.assertEqual(config["validation_backend"], "kubernetes-exec")

    def test_get_kafka_config_defaults_to_kubernetes_dataspace_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "DS_1_NAME=demo",
                    "DS_1_NAMESPACE=demo",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter()
                config = adapter.get_kafka_config()

        self.assertEqual(config["provisioner"], "kubernetes")
        self.assertEqual(config["k8s_namespace"], "demo")
        self.assertEqual(config["k8s_probe_namespaces"], "demo")
        self.assertEqual(config["k8s_service_name"], "framework-kafka")
        self.assertEqual(config["validation_backend"], "kubernetes-exec")

    def test_get_kafka_config_uses_kubernetes_exec_backend_for_kubernetes_provisioner_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "DS_1_NAME=demo",
                    "DS_1_NAMESPACE=demo",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter(topology="vm-single")
                config = adapter.get_kafka_config()

        self.assertEqual(config["topology"], "vm-single")
        self.assertEqual(config["validation_backend"], "kubernetes-exec")

    def test_get_kafka_config_allows_overriding_kubernetes_kafka_validation_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "DS_1_NAME=demo",
                    "DS_1_NAMESPACE=demo",
                    "KAFKA_EDC_VALIDATION_BACKEND=python-client",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter(topology="vm-single")
                config = adapter.get_kafka_config()

        self.assertEqual(config["validation_backend"], "python-client")

    def test_get_kafka_config_keeps_existing_role_aligned_kafka_namespace_behavior(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "DS_1_NAME=roleedcprove",
                    "DS_1_NAMESPACE=roleedcprove",
                    "DS_1_CONNECTORS=cityproof,companyproof",
                    "NAMESPACE_PROFILE=role-aligned",
                    "LEVEL4_ROLE_ALIGNED_CONNECTOR_NAMESPACES=true",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter()
                adapter.connectors.load_dataspace_connectors = mock.Mock(return_value=[
                    {
                        "name": "roleedcprove",
                        "namespace": "roleedcprove",
                        "namespace_profile": "role-aligned",
                        "connectors": [
                            "conn-cityproof-roleedcprove",
                            "conn-companyproof-roleedcprove",
                        ],
                        "connector_roles": {
                            "provider": "conn-cityproof-roleedcprove",
                            "consumer": "conn-companyproof-roleedcprove",
                        },
                        "connector_details": [
                            {
                                "name": "conn-cityproof-roleedcprove",
                                "role": "provider",
                                "active_namespace": "roleedcprove",
                                "planned_namespace": "roleedcprove-provider",
                            },
                            {
                                "name": "conn-companyproof-roleedcprove",
                                "role": "consumer",
                                "active_namespace": "roleedcprove",
                                "planned_namespace": "roleedcprove-consumer",
                            },
                        ],
                    }
                ])
                config = adapter.get_kafka_config()

        self.assertEqual(config["k8s_namespace"], "roleedcprove-provider")
        self.assertEqual(config["k8s_probe_namespaces"], "roleedcprove")

    def test_get_kafka_config_probes_provider_and_consumer_namespaces_with_control_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "DS_1_NAME=pionera",
                    "DS_1_NAMESPACE=core-control",
                    "DS_1_PROVIDER_NAMESPACE=provider",
                    "DS_1_CONSUMER_NAMESPACE=consumer",
                    "DS_1_CONNECTORS=citycouncil,company",
                    "NAMESPACE_PROFILE=role-aligned",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter()
                config = adapter.get_kafka_config()

        self.assertEqual(config["k8s_namespace"], "core-control")
        self.assertEqual(config["k8s_probe_namespaces"], "provider,consumer,core-control")

    def test_get_kafka_config_infers_vm_distributed_connector_visible_nodeport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "DS_1_NAME=pionera",
                    "DS_1_NAMESPACE=core-control",
                    "DS_1_PROVIDER_NAMESPACE=provider",
                    "DS_1_CONSUMER_NAMESPACE=consumer",
                    "VM_COMMON_IP=192.0.2.10",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter(topology="vm-distributed")
                config = adapter.get_kafka_config()

        self.assertEqual(config["k8s_namespace"], "core-control")
        self.assertEqual(config["k8s_external_service_type"], "NodePort")
        self.assertEqual(config["k8s_nodeport"], "32092")
        self.assertEqual(config["cluster_bootstrap_servers"], "192.0.2.10:32092")
        self.assertEqual(config["agreement_visibility_timeout_seconds"], "90")

    def test_is_kafka_available_uses_configured_container_name(self):
        commands = []

        def fake_run_silent(cmd, cwd=None):
            commands.append(cmd)
            return "abc123"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "KAFKA_CONTAINER_NAME=kafka-sasl",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
            ):
                adapter = InesdataAdapter(run_silent=fake_run_silent)
                self.assertTrue(adapter.is_kafka_available())

        self.assertEqual(len(commands), 1)
        self.assertIn("name=kafka-sasl", commands[0])

    def test_ensure_kafka_topic_uses_bootstrap_servers_without_container_dependency(self):
        commands = []
        admin_calls = {"kwargs": None, "created_topics": []}

        class FakeTopicAlreadyExistsError(Exception):
            pass

        class FakeNewTopic:
            def __init__(self, name, num_partitions, replication_factor):
                self.name = name
                self.num_partitions = num_partitions
                self.replication_factor = replication_factor

        class FakeKafkaAdminClient:
            def __init__(self, **kwargs):
                admin_calls["kwargs"] = kwargs
                self._topics = set()

            def list_topics(self):
                return set(self._topics)

            def create_topics(self, topics):
                for topic in topics:
                    admin_calls["created_topics"].append(topic.name)
                    self._topics.add(topic.name)

            def close(self):
                return None

        def fake_run_silent(cmd, cwd=None):
            commands.append(cmd)
            return ""

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_deployer_config(
                tmpdir,
                [
                    "KAFKA_BOOTSTRAP_SERVERS=kafka.example.internal:29092",
                    "KAFKA_SECURITY_PROTOCOL=PLAINTEXT",
                    "KAFKA_CONTAINER_NAME=kafka-sasl",
                ],
            )

            with (
                mock.patch.object(InesdataConfig, "script_dir", return_value=tmpdir),
                mock.patch.object(InesdataConfig, "deployer_config_path", return_value=config_path),
                mock.patch.object(
                    InesdataAdapter,
                    "_load_kafka_admin_dependencies",
                    return_value=(FakeKafkaAdminClient, FakeNewTopic, FakeTopicAlreadyExistsError),
                ),
            ):
                adapter = InesdataAdapter(run_silent=fake_run_silent)
                self.assertTrue(adapter.ensure_kafka_topic("edc-kafka-topic"))

        self.assertEqual(admin_calls["kwargs"]["bootstrap_servers"], "kafka.example.internal:29092")
        self.assertEqual(admin_calls["kwargs"]["security_protocol"], "PLAINTEXT")
        self.assertEqual(admin_calls["created_topics"], ["edc-kafka-topic"])
        self.assertEqual(commands, [])

    def test_connector_chart_keeps_runtime_configuration_wired(self):
        connector_config = _project_path("deployers", "inesdata", "connector", "config", "connector-configuration.properties")
        values_template = _project_path("deployers", "inesdata", "connector", "values.yaml.tpl")

        with open(connector_config, "r", encoding="utf-8") as handle:
            connector_config_content = handle.read()
        with open(values_template, "r", encoding="utf-8") as handle:
            values_template_content = handle.read()

        self.assertIn("edc.hostname={{ .Values.connector.ingress.hostname }}", connector_config_content)
        self.assertIn("edc.dsp.callback.address", connector_config_content)
        self.assertIn("edc.aws.bucket.name={{ .Values.services.minio.bucket }}", connector_config_content)
        self.assertIn("ghcr.io/proyectopionera/inesdata-connector", values_template_content)
        self.assertIn("ghcr.io/proyectopionera/inesdata-connector-interface", values_template_content)

    def test_connector_source_keeps_kafka_support_wired_when_available(self):
        source_root = _project_path("adapters", "inesdata", "sources", "inesdata-connector")
        build_gradle = os.path.join(source_root, "launchers", "connector", "build.gradle.kts")
        asset_validator = os.path.join(
            source_root,
            "extensions",
            "asset-validator",
            "src",
            "main",
            "java",
            "org",
            "upm",
            "inesdata",
            "validator",
            "InesdataAssetValidator.java",
        )
        data_address_validator = os.path.join(
            source_root,
            "extensions",
            "store-asset-api",
            "src",
            "main",
            "java",
            "org",
            "upm",
            "inesdata",
            "storageasset",
            "validation",
            "InesdataDataAddressValidator.java",
        )
        storage_asset_extension = os.path.join(
            source_root,
            "extensions",
            "store-asset-api",
            "src",
            "main",
            "java",
            "org",
            "upm",
            "inesdata",
            "storageasset",
            "StorageAssetApiExtension.java",
        )
        required_files = [
            build_gradle,
            asset_validator,
            data_address_validator,
            storage_asset_extension,
        ]
        missing_files = [path for path in required_files if not os.path.isfile(path)]
        if missing_files:
            self.skipTest("INESData connector source checkout is not available")

        with open(build_gradle, "r", encoding="utf-8") as handle:
            build_content = handle.read()
        with open(asset_validator, "r", encoding="utf-8") as handle:
            asset_validator_content = handle.read()
        with open(data_address_validator, "r", encoding="utf-8") as handle:
            data_address_validator_content = handle.read()
        with open(storage_asset_extension, "r", encoding="utf-8") as handle:
            storage_asset_extension_content = handle.read()

        self.assertIn("implementation(libs.edc.data.plane.kafka)", build_content)
        self.assertIn('case "Kafka" -> validateKafka(dataAddress);', asset_validator_content)
        self.assertIn("PROPERTY_KAFKA_BOOTSTRAP_SERVERS", asset_validator_content)
        self.assertIn('case "Kafka" -> validateKafka(dataAddress);', data_address_validator_content)
        self.assertIn("PROPERTY_KAFKA_BOOTSTRAP_SERVERS", data_address_validator_content)
        self.assertIn("validator.register(EDC_DATA_ADDRESS_TYPE, InesdataDataAddressValidator.instance());", storage_asset_extension_content)


if __name__ == "__main__":
    unittest.main()
