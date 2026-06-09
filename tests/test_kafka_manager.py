import os
import subprocess
import unittest
from unittest import mock

from framework.kafka_container_factory import KafkaContainerFactory
from framework.kafka_manager import KafkaManager


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeKafkaContainer:
    def __init__(self, image):
        self.image = image
        self.started = False
        self.stopped = False
        self.cluster_host = "host.minikube.internal"

    def start(self):
        self.started = True
        return self

    def get_bootstrap_server(self):
        return "localhost:19092"

    def get_cluster_bootstrap_server(self):
        return f"{self.cluster_host}:29092"

    def with_cluster_advertised_host(self, host):
        self.cluster_host = host
        return self

    def stop(self):
        self.stopped = True


class _FailingContainerLoader:
    def __call__(self, image):
        raise RuntimeError("docker unavailable")


class _RecordingFactory(KafkaContainerFactory):
    def __init__(self):
        self.calls = []

    def create_container(self, container_class, image, config=None):
        self.calls.append({
            "container_class": container_class,
            "image": image,
            "config": dict(config or {}),
        })
        container = container_class(image)
        with_cluster_advertised_host = getattr(container, "with_cluster_advertised_host", None)
        cluster_advertised_host = (config or {}).get("cluster_advertised_host")
        if cluster_advertised_host and callable(with_cluster_advertised_host):
            updated = with_cluster_advertised_host(cluster_advertised_host)
            if updated is not None:
                container = updated
        return container


class KafkaManagerTests(unittest.TestCase):
    def test_uses_already_running_kafka_without_starting_container(self):
        manager = KafkaManager(bootstrap_servers="localhost:9092")

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=True):
            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "localhost:9092")
        self.assertFalse(manager.started_by_framework)
        self.assertIsNone(manager.container)

    def test_auto_starts_kafka_container_when_broker_unavailable(self):
        manager = KafkaManager(
            container_class=_FakeKafkaContainer,
            runtime_config={"provisioner": "docker"},
        )

        with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "localhost:19092")
        self.assertEqual(manager.cluster_bootstrap_servers, "host.minikube.internal:29092")
        self.assertTrue(manager.started_by_framework)
        self.assertIsNotNone(manager.container)
        self.assertTrue(manager.container.started)

    def test_auto_starts_kafka_broker_in_kubernetes_by_default(self):
        manager = KafkaManager()

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=False):
            with mock.patch.object(manager, "_start_kafka_kubernetes", return_value="127.0.0.1:39092") as mocked_start:
                bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:39092")
        self.assertEqual(manager._provisioner(), "kubernetes")
        mocked_start.assert_called_once()

    def test_auto_starts_kafka_broker_in_kubernetes_when_configured(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append({"args": list(args), "input": input_text})
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
                "k8s_nodeport": "32092",
                "minikube_profile": "minikube",
            },
            command_runner=fake_runner,
        )

        with mock.patch.object(KafkaManager, "_start_kubernetes_port_forward", return_value=object()) as mocked_port_forward:
            with mock.patch.object(KafkaManager, "_wait_for_kubernetes_internal_bootstrap", return_value={"pod": "conn-a"}) as mocked_internal_wait:
                with mock.patch.object(KafkaManager, "_wait_for_kubernetes_external_service_bootstrap", return_value={"pod": "conn-a"}) as mocked_external_wait:
                    with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
                        bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:32092")
        self.assertEqual(manager.cluster_bootstrap_servers, "framework-kafka.demo.svc.cluster.local:9092")
        self.assertEqual(manager.provisioning_mode, "kubernetes")
        self.assertTrue(manager.started_by_framework)
        mocked_port_forward.assert_called_once()
        mocked_internal_wait.assert_called_once()
        mocked_external_wait.assert_called_once()
        apply_call = next(call for call in commands if call["args"] == ["kubectl", "apply", "-f", "-"])
        self.assertIn("kind: Deployment", apply_call["input"])
        self.assertIn("framework-kafka.demo.svc.cluster.local:9092", apply_call["input"])
        self.assertIn("127.0.0.1:32092", apply_call["input"])

    def test_kubernetes_start_tolerates_rollout_timeout_when_listener_checks_succeed(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append({"args": list(args), "input": input_text})
            if args[:3] == ["kubectl", "rollout", "status"]:
                return _FakeCompletedProcess(
                    returncode=1,
                    stderr="Waiting for deployment \"framework-kafka\" rollout to finish: 0 of 1 updated replicas are available...\nerror: timed out waiting for the condition",
                )
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
                "k8s_local_port": "39092",
            },
            command_runner=fake_runner,
        )

        with mock.patch.object(KafkaManager, "_wait_for_kubernetes_internal_bootstrap", return_value={"pod": "conn-a"}):
            with mock.patch.object(KafkaManager, "_wait_for_kubernetes_external_service_bootstrap", return_value={"pod": "conn-a"}):
                with mock.patch.object(KafkaManager, "_start_kubernetes_port_forward", return_value=object()):
                    with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
                        bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:39092")
        self.assertEqual(manager.cluster_bootstrap_servers, "framework-kafka.demo.svc.cluster.local:9092")
        self.assertTrue(manager.started_by_framework)
        self.assertEqual(manager.provisioning_mode, "kubernetes")
        self.assertTrue(any(call["args"][:3] == ["kubectl", "rollout", "status"] for call in commands))

    def test_kubernetes_start_recovers_existing_runtime_when_nodeport_is_already_allocated(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append({"args": list(args), "input": input_text})
            if args == ["kubectl", "apply", "-f", "-"]:
                return _FakeCompletedProcess(
                    returncode=1,
                    stderr=(
                        'The Service "framework-kafka-external" is invalid: '
                        "spec.ports[0].nodePort: Invalid value: 32092: provided port is already allocated"
                    ),
                )
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
                "k8s_external_service_type": "NodePort",
                "k8s_nodeport": "32092",
            },
            command_runner=fake_runner,
        )

        with mock.patch.object(KafkaManager, "_kubernetes_resources_exist", return_value=True):
            with mock.patch.object(KafkaManager, "_wait_for_kubernetes_internal_bootstrap", return_value={"pod": "conn-a"}):
                with mock.patch.object(KafkaManager, "_wait_for_kubernetes_external_service_bootstrap", return_value={"pod": "conn-a"}):
                    with mock.patch.object(KafkaManager, "_start_kubernetes_port_forward", return_value=object()):
                        with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
                            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:32092")
        self.assertEqual(manager.cluster_bootstrap_servers, "framework-kafka.demo.svc.cluster.local:9092")
        self.assertTrue(manager.started_by_framework)
        self.assertTrue(any(call["args"] == ["kubectl", "apply", "-f", "-"] for call in commands))

    def test_kubernetes_start_removes_stale_split_controller_in_combined_mode(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append({"args": list(args), "input": input_text})
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
                "k8s_local_port": "39092",
            },
            command_runner=fake_runner,
        )

        with mock.patch.object(KafkaManager, "_start_kubernetes_port_forward", return_value=object()):
            with mock.patch.object(KafkaManager, "_wait_for_kubernetes_internal_bootstrap", return_value={"pod": "conn-a"}):
                with mock.patch.object(KafkaManager, "_wait_for_kubernetes_external_service_bootstrap", return_value={"pod": "conn-a"}):
                    with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
                        manager.ensure_kafka_running()

        command_args = [call["args"] for call in commands]
        self.assertIn(
            [
                "kubectl",
                "delete",
                "deployment/framework-kafka-controller",
                "service/framework-kafka-controller",
                "-n",
                "demo",
                "--ignore-not-found=true",
            ],
            command_args,
        )
        delete_index = command_args.index(
            [
                "kubectl",
                "delete",
                "deployment/framework-kafka-controller",
                "service/framework-kafka-controller",
                "-n",
                "demo",
                "--ignore-not-found=true",
            ]
        )
        apply_index = command_args.index(["kubectl", "apply", "-f", "-"])
        self.assertLess(delete_index, apply_index)

    def test_auto_starts_kafka_broker_in_split_kraft_mode(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append({"args": list(args), "input": input_text})
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes-split-kraft",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
                "k8s_local_port": "39092",
            },
            command_runner=fake_runner,
        )

        with mock.patch.object(KafkaManager, "_start_kubernetes_port_forward", return_value=object()) as mocked_port_forward:
            with mock.patch.object(KafkaManager, "_wait_for_kubernetes_internal_bootstrap", return_value={"pod": "conn-a"}) as mocked_internal_wait:
                with mock.patch.object(KafkaManager, "_wait_for_kubernetes_external_service_bootstrap", return_value={"pod": "conn-a"}) as mocked_external_wait:
                    with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
                        bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:39092")
        self.assertEqual(manager.cluster_bootstrap_servers, "framework-kafka.demo.svc.cluster.local:9092")
        self.assertEqual(manager.provisioning_mode, "kubernetes-split-kraft")
        self.assertTrue(manager.started_by_framework)
        mocked_port_forward.assert_called_once()
        mocked_internal_wait.assert_called_once()
        mocked_external_wait.assert_called_once()
        apply_call = next(call for call in commands if call["args"] == ["kubectl", "apply", "-f", "-"])
        self.assertIn("name: framework-kafka-controller", apply_call["input"])
        rollout_calls = [
            call["args"] for call in commands if call["args"][:3] == ["kubectl", "rollout", "status"]
        ]
        self.assertEqual(
            rollout_calls,
            [
                [
                    "kubectl",
                    "rollout",
                    "status",
                    "deployment/framework-kafka-controller",
                    "-n",
                    "demo",
                    "--timeout=90s",
                ],
                [
                    "kubectl",
                    "rollout",
                    "status",
                    "deployment/framework-kafka",
                    "-n",
                    "demo",
                    "--timeout=90s",
                ],
            ],
        )

    def test_wait_for_kubernetes_external_service_bootstrap_uses_external_service_dns(self):
        exec_calls = []

        def fake_runner(args, input_text=None):
            if args[:4] == ["kubectl", "get", "pods", "-n"]:
                return _FakeCompletedProcess(stdout="conn-a 1/1 Running 0 1m\n")
            if args[:4] == ["kubectl", "exec", "-n", "demo"]:
                exec_calls.append(list(args))
                return _FakeCompletedProcess(returncode=0)
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={"provisioner": "kubernetes", "k8s_namespace": "demo"},
            command_runner=fake_runner,
            wait_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

        ids = manager._kubernetes_identifiers(manager._load_manager_config())
        result = manager._wait_for_kubernetes_external_service_bootstrap(ids)

        self.assertEqual(result["listener"], "external service listener")
        self.assertEqual(result["host"], "framework-kafka-external.demo.svc.cluster.local")
        self.assertEqual(result["port"], 9094)
        self.assertTrue(exec_calls)
        self.assertIn("framework-kafka-external.demo.svc.cluster.local", exec_calls[0][-1])
        self.assertEqual(exec_calls[0][-3:-1], ["sh", "-lc"])
        self.assertIn("command -v nc", exec_calls[0][-1])

    def test_wait_for_kubernetes_bootstrap_can_probe_connector_namespaces(self):
        exec_calls = []

        def fake_runner(args, input_text=None):
            if args[:4] == ["kubectl", "get", "pods", "-n"]:
                namespace = args[4]
                if namespace == "provider":
                    return _FakeCompletedProcess(stdout="conn-provider 1/1 Running 0 1m\n")
                if namespace == "consumer":
                    return _FakeCompletedProcess(stdout="conn-consumer 1/1 Running 0 1m\n")
                return _FakeCompletedProcess(stdout="registration-service 1/1 Running 0 1m\n")
            if args[:3] == ["kubectl", "exec", "-n"]:
                exec_calls.append(list(args))
                return _FakeCompletedProcess(returncode=0)
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "core-control",
                "k8s_probe_namespaces": "provider,consumer",
                "k8s_service_name": "framework-kafka",
            },
            command_runner=fake_runner,
            wait_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

        ids = manager._kubernetes_identifiers(manager._load_manager_config())
        result = manager._wait_for_kubernetes_internal_bootstrap(ids)

        self.assertEqual(ids["probe_namespaces"], ["provider", "consumer", "core-control"])
        self.assertEqual(result["namespace"], "provider")
        self.assertEqual(result["pod"], "conn-provider")
        self.assertEqual(result["host"], "framework-kafka.core-control.svc.cluster.local")
        self.assertTrue(exec_calls)
        self.assertEqual(exec_calls[0][:5], ["kubectl", "exec", "-n", "provider", "conn-provider"])
        self.assertEqual(exec_calls[0][-3:-1], ["sh", "-lc"])

    def test_vm_distributed_requires_connector_visible_bootstrap_before_autoprovisioning(self):
        manager = KafkaManager(
            runtime_config={
                "topology": "vm-distributed",
                "provisioner": "kubernetes",
                "k8s_namespace": "core-control",
                "k8s_probe_namespaces": "provider,consumer,core-control",
            },
            command_runner=mock.Mock(),
            wait_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=False):
            with mock.patch.object(manager, "start_kafka", return_value="127.0.0.1:39092") as mocked_start:
                bootstrap = manager.ensure_kafka_running()

        self.assertIsNone(bootstrap)
        mocked_start.assert_not_called()
        self.assertIn("connector-visible Kafka bootstrap server", manager.last_error)

    def test_vm_distributed_can_use_explicit_cluster_bootstrap_as_host_candidate(self):
        manager = KafkaManager(
            runtime_config={
                "topology": "vm-distributed",
                "provisioner": "kubernetes",
                "cluster_bootstrap_servers": "192.0.2.10:9094",
            },
            command_runner=mock.Mock(),
            wait_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

        with mock.patch.object(
            KafkaManager,
            "is_kafka_available",
            side_effect=lambda value: value == "192.0.2.10:9094",
        ):
            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "192.0.2.10:9094")
        self.assertEqual(manager.cluster_bootstrap_servers, "192.0.2.10:9094")

    def test_vm_distributed_nodeport_manifest_advertises_connector_visible_bootstrap(self):
        manager = KafkaManager(
            runtime_config={
                "topology": "vm-distributed",
                "provisioner": "kubernetes",
                "k8s_namespace": "core-control",
                "k8s_service_name": "framework-kafka",
                "k8s_external_service_type": "NodePort",
                "k8s_nodeport": "32092",
                "cluster_bootstrap_servers": "192.0.2.10:32092",
            }
        )

        manifest = manager._build_kubernetes_manifest(manager._load_manager_config())

        self.assertIn(
            "KAFKA_ADVERTISED_LISTENERS\n"
            "          value: \"INTERNAL://framework-kafka.core-control.svc.cluster.local:9092,EXTERNAL://192.0.2.10:32092\"",
            manifest,
        )
        self.assertIn("nodePort: 32092", manifest)
        self.assertIn("type: NodePort", manifest)

    def test_vm_distributed_does_not_autoprovision_when_explicit_bootstrap_is_unreachable(self):
        manager = KafkaManager(
            runtime_config={
                "topology": "vm-distributed",
                "provisioner": "kubernetes",
                "cluster_bootstrap_servers": "192.0.2.10:9094",
            },
            command_runner=mock.Mock(),
            wait_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=False):
            with mock.patch.object(manager, "start_kafka", return_value="127.0.0.1:39092") as mocked_start:
                bootstrap = manager.ensure_kafka_running()

        self.assertIsNone(bootstrap)
        mocked_start.assert_not_called()
        self.assertIn("was not reachable from this runner", manager.last_error)

    def test_vm_distributed_nodeport_config_can_autoprovision_when_unreachable(self):
        manager = KafkaManager(
            runtime_config={
                "topology": "vm-distributed",
                "provisioner": "kubernetes",
                "k8s_external_service_type": "NodePort",
                "cluster_bootstrap_servers": "192.0.2.10:32092",
            },
            command_runner=mock.Mock(),
            wait_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=False):
            with mock.patch.object(manager, "start_kafka", return_value="127.0.0.1:39092") as mocked_start:
                bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:39092")
        mocked_start.assert_called_once()

    def test_kubernetes_start_keeps_configured_connector_bootstrap(self):
        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "core-control",
                "k8s_service_name": "framework-kafka",
                "k8s_external_service_type": "NodePort",
                "k8s_nodeport": "32092",
                "cluster_bootstrap_servers": "192.0.2.10:32092",
            },
            command_runner=mock.Mock(return_value=_FakeCompletedProcess(stdout="")),
        )

        with mock.patch.object(KafkaManager, "_start_kubernetes_port_forward", return_value=object()):
            with mock.patch.object(KafkaManager, "_wait_for_kubernetes_internal_bootstrap", return_value={"pod": "conn-a"}):
                with mock.patch.object(KafkaManager, "_wait_for_kubernetes_external_service_bootstrap", return_value={"pod": "conn-a"}):
                    with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
                        bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:32092")
        self.assertEqual(manager.cluster_bootstrap_servers, "192.0.2.10:32092")

    def test_stop_kafka_only_stops_framework_managed_container(self):
        manager = KafkaManager(container_class=_FakeKafkaContainer)
        manager.container = _FakeKafkaContainer("confluentinc/cp-kafka:latest")
        manager.started_by_framework = True

        manager.stop_kafka()

        self.assertTrue(manager.container is None)
        self.assertFalse(manager.started_by_framework)

    def test_docker_unavailable_skips_auto_start(self):
        manager = KafkaManager(
            container_class=_FailingContainerLoader(),
            runtime_config={"provisioner": "docker"},
        )

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=False):
            bootstrap = manager.ensure_kafka_running()

        self.assertIsNone(bootstrap)
        self.assertIn("docker unavailable", manager.last_error)

    def test_prefers_environment_bootstrap_servers_when_available(self):
        manager = KafkaManager(bootstrap_servers="localhost:9092")

        with mock.patch.dict(os.environ, {"KAFKA_BOOTSTRAP_SERVERS": "env-host:19092"}, clear=False):
            with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=lambda value: value == "env-host:19092"):
                bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "env-host:19092")

    def test_reuses_framework_broker_without_losing_cluster_bootstrap_servers(self):
        manager = KafkaManager(bootstrap_servers="localhost:19092")
        manager.cluster_bootstrap_servers = "host.minikube.internal:29092"
        manager.started_by_framework = True
        manager.container = _FakeKafkaContainer("confluentinc/cp-kafka:latest")

        with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=lambda value: value == "localhost:19092"):
            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "localhost:19092")
        self.assertEqual(manager.cluster_bootstrap_servers, "host.minikube.internal:29092")
        self.assertTrue(manager.started_by_framework)

    def test_reuses_framework_kubernetes_broker_without_losing_framework_ownership(self):
        manager = KafkaManager(bootstrap_servers="127.0.0.1:32092")
        manager.cluster_bootstrap_servers = "framework-kafka.demo.svc.cluster.local:9092"
        manager.started_by_framework = True
        manager.provisioning_mode = "kubernetes"

        fake_port_forward = mock.Mock()
        fake_port_forward.poll.return_value = None
        manager.port_forward_process = fake_port_forward

        with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=lambda value: value == "127.0.0.1:32092"):
            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:32092")
        self.assertEqual(manager.cluster_bootstrap_servers, "framework-kafka.demo.svc.cluster.local:9092")
        self.assertTrue(manager.started_by_framework)
        self.assertEqual(manager.provisioning_mode, "kubernetes")

    def test_reuses_partially_started_framework_kubernetes_broker_after_timeout(self):
        manager = KafkaManager(bootstrap_servers="127.0.0.1:32092")
        manager.cluster_bootstrap_servers = "framework-kafka.demo.svc.cluster.local:9092"
        manager.started_by_framework = False
        manager.provisioning_mode = "kubernetes"

        fake_port_forward = mock.Mock()
        fake_port_forward.poll.return_value = None
        manager.port_forward_process = fake_port_forward

        with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=lambda value: value == "127.0.0.1:32092"):
            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:32092")
        self.assertEqual(manager.cluster_bootstrap_servers, "framework-kafka.demo.svc.cluster.local:9092")
        self.assertTrue(manager.started_by_framework)
        self.assertEqual(manager.provisioning_mode, "kubernetes")

    def test_start_kafka_uses_container_factory_with_runtime_config(self):
        factory = _RecordingFactory()
        manager = KafkaManager(
            container_class=_FakeKafkaContainer,
            container_factory=factory,
            runtime_config={
                "provisioner": "docker",
                "container_env_file": "/tmp/fake.env",
                "cluster_advertised_host": "cluster.kafka.internal",
            },
        )

        with mock.patch.object(KafkaManager, "is_kafka_available", side_effect=[False, True]):
            bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "localhost:19092")
        self.assertEqual(factory.calls[0]["config"]["container_env_file"], "/tmp/fake.env")
        self.assertEqual(factory.calls[0]["config"]["cluster_advertised_host"], "cluster.kafka.internal")
        self.assertEqual(manager.cluster_bootstrap_servers, "cluster.kafka.internal:29092")

    def test_kubernetes_port_forward_discards_stderr_to_avoid_blocking(self):
        manager = KafkaManager()
        ids = {
            "namespace": "demo",
            "external_service_name": "framework-kafka-external",
            "local_port": 32092,
            "external_bootstrap": "127.0.0.1:32092",
        }

        fake_process = mock.Mock()
        fake_process.poll.return_value = None

        with mock.patch("framework.kafka_manager.subprocess.Popen", return_value=fake_process) as mocked_popen:
            with mock.patch.object(KafkaManager, "is_kafka_available", return_value=True):
                returned = manager._start_kubernetes_port_forward(ids)

        self.assertIs(returned, fake_process)
        mocked_popen.assert_called_once()
        _, kwargs = mocked_popen.call_args
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(kwargs["text"])

    def test_kubernetes_manifest_uses_startup_probe_and_relaxed_liveness(self):
        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
            }
        )

        manifest = manager._build_kubernetes_manifest(manager._load_manager_config())

        self.assertIn("startupProbe:", manifest)
        self.assertIn("failureThreshold: 24", manifest)
        self.assertIn("readinessProbe:", manifest)
        self.assertIn("initialDelaySeconds: 5", manifest)
        self.assertIn("failureThreshold: 6", manifest)
        self.assertIn("livenessProbe:", manifest)
        self.assertIn("periodSeconds: 15", manifest)
        self.assertIn("KAFKA_OFFSETS_TOPIC_NUM_PARTITIONS", manifest)
        self.assertIn('value: "1"', manifest)
        self.assertIn("KAFKA_TRANSACTION_STATE_LOG_NUM_PARTITIONS", manifest)
        self.assertIn("KAFKA_BROKER_HEARTBEAT_INTERVAL_MS", manifest)
        self.assertIn('value: "3000"', manifest)
        self.assertIn("KAFKA_BROKER_SESSION_TIMEOUT_MS", manifest)
        self.assertIn('value: "60000"', manifest)
        self.assertIn("KAFKA_CONTROLLER_QUORUM_REQUEST_TIMEOUT_MS", manifest)
        self.assertIn('value: "30000"', manifest)
        self.assertIn("KAFKA_INITIAL_BROKER_REGISTRATION_TIMEOUT_MS", manifest)
        self.assertIn('value: "120000"', manifest)
        self.assertIn("resources:", manifest)
        self.assertIn('cpu: "100m"', manifest)
        self.assertIn('memory: "256Mi"', manifest)

    def test_split_kraft_manifest_uses_separate_controller_and_broker_workloads(self):
        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes-split-kraft",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
                "k8s_local_port": "39092",
            }
        )

        manifest = manager._build_kubernetes_manifest(manager._load_manager_config())

        self.assertGreaterEqual(manifest.count("kind: Deployment"), 2)
        self.assertIn("name: framework-kafka-controller", manifest)
        self.assertIn("name: framework-kafka-external", manifest)
        self.assertIn('value: "controller"', manifest)
        self.assertIn('value: "broker"', manifest)
        self.assertIn("framework-kafka-controller.demo.svc.cluster.local:9093", manifest)
        self.assertIn('value: "3000@framework-kafka-controller.demo.svc.cluster.local:9093"', manifest)

    def test_ensure_topic_uses_in_cluster_exec_for_framework_kubernetes_broker(self):
        commands = []
        list_calls = {"count": 0}

        def fake_runner(args, input_text=None):
            commands.append(list(args))
            if "--list" in args:
                list_calls["count"] += 1
                if list_calls["count"] >= 2:
                    return _FakeCompletedProcess(stdout="topic-a\n")
                return _FakeCompletedProcess(stdout="")
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
            },
            command_runner=fake_runner,
        )
        manager.started_by_framework = True
        manager.provisioning_mode = "kubernetes"

        self.assertTrue(manager.ensure_topic("topic-a"))

        self.assertEqual(len(commands), 3)
        self.assertEqual(
            commands[0][:6],
            ["kubectl", "exec", "-n", "demo", "deployment/framework-kafka", "--"],
        )
        self.assertIn("--bootstrap-server", commands[0])
        self.assertIn("localhost:9092", commands[0])
        self.assertIn("--create", commands[1])
        self.assertIn("--if-not-exists", commands[1])

    def test_ensure_topic_uses_in_cluster_exec_for_framework_split_kraft_broker(self):
        commands = []
        list_calls = {"count": 0}

        def fake_runner(args, input_text=None):
            commands.append(list(args))
            if "--list" in args:
                list_calls["count"] += 1
                if list_calls["count"] >= 2:
                    return _FakeCompletedProcess(stdout="topic-split\n")
                return _FakeCompletedProcess(stdout="")
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes-split-kraft",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
            },
            command_runner=fake_runner,
        )
        manager.started_by_framework = True
        manager.provisioning_mode = "kubernetes-split-kraft"

        self.assertTrue(manager.ensure_topic("topic-split"))

        self.assertEqual(
            commands[0][:6],
            ["kubectl", "exec", "-n", "demo", "deployment/framework-kafka", "--"],
        )
        self.assertIn("--create", commands[1])

    def test_kubernetes_port_forward_can_restart_existing_process(self):
        manager = KafkaManager()
        ids = {
            "namespace": "demo",
            "external_service_name": "framework-kafka-external",
            "local_port": 32092,
            "external_bootstrap": "127.0.0.1:32092",
        }
        existing_process = mock.Mock()
        existing_process.poll.return_value = None
        existing_process.wait.return_value = None
        manager.port_forward_process = existing_process

        new_process = mock.Mock()
        new_process.poll.return_value = None

        with mock.patch("framework.kafka_manager.subprocess.Popen", return_value=new_process):
            with mock.patch.object(KafkaManager, "is_kafka_available", return_value=True):
                returned = manager._start_kubernetes_port_forward(ids, restart_existing=True)

        self.assertIs(returned, new_process)
        existing_process.terminate.assert_called_once()
        self.assertIs(manager.port_forward_process, new_process)

    def test_ensure_kafka_running_recovers_existing_kubernetes_runtime_before_restart(self):
        manager = KafkaManager(bootstrap_servers="127.0.0.1:32092")
        manager.cluster_bootstrap_servers = "framework-kafka.demo.svc.cluster.local:9092"
        manager.started_by_framework = True
        manager.provisioning_mode = "kubernetes"

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=False):
            with mock.patch.object(manager, "_recover_existing_kubernetes_runtime", return_value="127.0.0.1:32092") as mocked_recover:
                with mock.patch.object(manager, "start_kafka", return_value="127.0.0.1:39092") as mocked_start:
                    bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:32092")
        mocked_recover.assert_called_once()
        mocked_start.assert_not_called()

    def test_kubernetes_recovery_accepts_existing_external_service_without_all_expected_resources(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append(list(args))
            if args[:2] == ["kubectl", "get"] and any(
                str(part).startswith("deployment/") for part in args
            ):
                return _FakeCompletedProcess(returncode=1, stderr="missing controller")
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes-split-kraft",
                "k8s_namespace": "edc-control",
                "k8s_service_name": "framework-kafka",
                "k8s_external_service_type": "NodePort",
                "k8s_nodeport": "32092",
            },
            command_runner=fake_runner,
        )

        with mock.patch.object(KafkaManager, "_wait_for_kubernetes_internal_bootstrap", return_value={"pod": "conn-a"}):
            with mock.patch.object(KafkaManager, "_wait_for_kubernetes_external_service_bootstrap", return_value={"pod": "conn-a"}):
                with mock.patch.object(KafkaManager, "_start_kubernetes_port_forward", return_value=object()):
                    with mock.patch.object(KafkaManager, "is_kafka_available", return_value=True):
                        bootstrap = manager._recover_existing_kubernetes_runtime()

        self.assertEqual(bootstrap, "127.0.0.1:32092")
        self.assertTrue(
            any(
                call == [
                    "kubectl",
                    "get",
                    "service",
                    "framework-kafka-external",
                    "-n",
                    "edc-control",
                ]
                for call in commands
            )
        )

    def test_ensure_kafka_running_falls_back_to_restart_after_recovery_failure(self):
        manager = KafkaManager(bootstrap_servers="127.0.0.1:32092")
        manager.cluster_bootstrap_servers = "framework-kafka.demo.svc.cluster.local:9092"
        manager.started_by_framework = True
        manager.provisioning_mode = "kubernetes"

        with mock.patch.object(KafkaManager, "is_kafka_available", return_value=False):
            with mock.patch.object(manager, "_recover_existing_kubernetes_runtime", side_effect=RuntimeError("transient failure")) as mocked_recover:
                with mock.patch.object(manager, "start_kafka", return_value="127.0.0.1:39092") as mocked_start:
                    bootstrap = manager.ensure_kafka_running()

        self.assertEqual(bootstrap, "127.0.0.1:39092")
        mocked_recover.assert_called_once()
        mocked_start.assert_called_once()

    def test_stop_kafka_kubernetes_deletes_deployment_and_services(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append(list(args))
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
            },
            command_runner=fake_runner,
        )
        manager.started_by_framework = True
        manager.provisioning_mode = "kubernetes"
        port_forward_process = mock.Mock()
        port_forward_process.poll.return_value = None
        port_forward_process.wait.return_value = None
        manager.port_forward_process = port_forward_process

        manager.stop_kafka()

        self.assertIn(
            [
                "kubectl",
                "delete",
                "deployment/framework-kafka",
                "service/framework-kafka",
                "service/framework-kafka-external",
                "-n",
                "demo",
                "--ignore-not-found=true",
            ],
            commands,
        )
        port_forward_process.terminate.assert_called_once()

    def test_stop_kafka_split_kraft_deletes_controller_broker_and_services(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append(list(args))
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes-split-kraft",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
            },
            command_runner=fake_runner,
        )
        manager.started_by_framework = True
        manager.provisioning_mode = "kubernetes-split-kraft"
        port_forward_process = mock.Mock()
        port_forward_process.poll.return_value = None
        port_forward_process.wait.return_value = None
        manager.port_forward_process = port_forward_process

        manager.stop_kafka()

        self.assertIn(
            [
                "kubectl",
                "delete",
                "deployment/framework-kafka-controller",
                "service/framework-kafka-controller",
                "deployment/framework-kafka",
                "service/framework-kafka",
                "service/framework-kafka-external",
                "-n",
                "demo",
                "--ignore-not-found=true",
            ],
            commands,
        )
        port_forward_process.terminate.assert_called_once()

    def test_stop_kafka_kubernetes_cleans_partial_framework_startups(self):
        commands = []

        def fake_runner(args, input_text=None):
            commands.append(list(args))
            return _FakeCompletedProcess(stdout="")

        manager = KafkaManager(
            runtime_config={
                "provisioner": "kubernetes",
                "k8s_namespace": "demo",
                "k8s_service_name": "framework-kafka",
            },
            command_runner=fake_runner,
        )
        manager.started_by_framework = False
        manager.provisioning_mode = "kubernetes"
        manager.bootstrap_servers = "127.0.0.1:39092"
        manager.cluster_bootstrap_servers = "framework-kafka.demo.svc.cluster.local:9092"
        port_forward_process = mock.Mock()
        port_forward_process.poll.return_value = None
        port_forward_process.wait.return_value = None
        manager.port_forward_process = port_forward_process

        manager.stop_kafka()

        self.assertIn(
            [
                "kubectl",
                "delete",
                "deployment/framework-kafka",
                "service/framework-kafka",
                "service/framework-kafka-external",
                "-n",
                "demo",
                "--ignore-not-found=true",
            ],
            commands,
        )
        port_forward_process.terminate.assert_called_once()
        self.assertIsNone(manager.bootstrap_servers)
        self.assertIsNone(manager.cluster_bootstrap_servers)
        self.assertIsNone(manager.provisioning_mode)


if __name__ == "__main__":
    unittest.main()

