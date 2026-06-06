import itertools
import json
import os
import tempfile
import unittest
import requests
from unittest import mock
from unittest.mock import patch

from framework.kafka_edc_validation import KafkaEdcValidationSuite


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "" if payload is None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("empty body")
        return self._payload


class _FakeSession:
    def __init__(self):
        self.asset_topic = None
        self.asset_id = None
        self.destination_topic = None
        self.asset_bootstrap_servers = None
        self.destination_bootstrap_servers = None
        self.assets = {}
        self.policies = {}
        self.contracts = {}
        self.agreements = {}
        self.transfers = {}
        self.terminated_transfers = []
        self.deprovisioned_transfers = []

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if "openid-connect/token" in url:
            username = (data or {}).get("username", "user")
            return _FakeResponse(200, {"access_token": f"jwt-{username}"})

        if url.endswith("/management/v3/assets"):
            self.asset_topic = ((json or {}).get("dataAddress") or {}).get("topic")
            self.asset_bootstrap_servers = ((json or {}).get("dataAddress") or {}).get("kafka.bootstrap.servers")
            self.asset_id = (json or {}).get("@id")
            self.assets[self.asset_id] = {"@id": self.asset_id}
            return _FakeResponse(200, {"@id": json.get("@id")})

        if url.endswith("/management/v3/policydefinitions"):
            policy_id = (json or {}).get("@id")
            self.policies[policy_id] = {"@id": policy_id}
            return _FakeResponse(200, {"@id": json.get("@id")})

        if url.endswith("/management/v3/contractdefinitions"):
            contract_id = (json or {}).get("@id")
            self.contracts[contract_id] = {"@id": contract_id}
            return _FakeResponse(200, {"@id": json.get("@id")})

        if url.endswith("/management/v3/assets/request"):
            return _FakeResponse(200, list(self.assets.values()))

        if url.endswith("/management/v3/policydefinitions/request"):
            return _FakeResponse(200, list(self.policies.values()))

        if url.endswith("/management/v3/contractdefinitions/request"):
            return _FakeResponse(200, list(self.contracts.values()))

        if url.endswith("/management/v3/catalog/request"):
            return _FakeResponse(
                200,
                {
                    "dspace:participantId": "conn-provider",
                    "dcat:dataset": [
                        {
                            "@id": self.asset_id or "unknown-asset",
                            "odrl:hasPolicy": {
                                "@id": "offer-policy-id",
                            },
                            "description": f"dataset for {self.asset_id or 'unknown-asset'}",
                        }
                    ],
                },
            )

        if url.endswith("/management/v3/contractnegotiations"):
            self.agreements["agreement-1"] = {"@id": "agreement-1"}
            return _FakeResponse(200, {"@id": "neg-1"})

        if url.endswith("/management/v3/transferprocesses"):
            self.destination_topic = ((json or {}).get("dataDestination") or {}).get("topic")
            self.destination_bootstrap_servers = ((json or {}).get("dataDestination") or {}).get("kafka.bootstrap.servers")
            if self.asset_topic and self.destination_topic:
                _FakeBrokerState.routes[self.asset_topic] = self.destination_topic
            self.transfers["transfer-1"] = {
                "@id": "transfer-1",
                "state": "STARTED",
                "assetId": self.asset_id,
            }
            return _FakeResponse(200, {"@id": "transfer-1"})

        if url.endswith("/management/v3/contractnegotiations/request"):
            return _FakeResponse(200, [{"@id": "neg-1", "state": "FINALIZED", "contractAgreementId": "agreement-1"}])

        if url.endswith("/management/v3/contractagreements/request"):
            return _FakeResponse(200, list(self.agreements.values()))

        if url.endswith("/management/v3/transferprocesses/request"):
            return _FakeResponse(200, list(self.transfers.values()))

        if url.endswith("/management/v3/transferprocesses/transfer-1/terminate"):
            self.terminated_transfers.append("transfer-1")
            if "transfer-1" in self.transfers:
                self.transfers["transfer-1"]["state"] = "TERMINATED"
            return _FakeResponse(204, None)

        if url.endswith("/management/v3/transferprocesses/transfer-1/deprovision"):
            self.deprovisioned_transfers.append("transfer-1")
            if "transfer-1" in self.transfers:
                self.transfers["transfer-1"]["state"] = "DEPROVISIONED"
            return _FakeResponse(204, None)

        raise AssertionError(f"Unexpected POST URL: {url}")

    def get(self, url, headers=None, timeout=None):
        if url.endswith("/management/v3/contractnegotiations/neg-1"):
            return _FakeResponse(200, {"@id": "neg-1", "state": "FINALIZED", "contractAgreementId": "agreement-1"})

        if url.endswith("/management/v3/contractagreements/agreement-1"):
            return _FakeResponse(200, self.agreements.get("agreement-1", {"@id": "agreement-1"}))

        if url.endswith("/management/v3/transferprocesses/transfer-1"):
            return _FakeResponse(200, self.transfers.get("transfer-1", {"@id": "transfer-1", "state": "STARTED"}))

        if url.endswith("/management/v3/transferprocesses/transfer-1/state"):
            state = self.transfers.get("transfer-1", {}).get("state", "TERMINATED")
            return _FakeResponse(200, {"@type": "TransferState", "state": state})

        raise AssertionError(f"Unexpected GET URL: {url}")

    def delete(self, url, headers=None, timeout=None):
        if "/management/v3/assets/" in url:
            asset_id = url.rsplit("/", 1)[-1]
            self.assets.pop(asset_id, None)
            return _FakeResponse(204, None)
        if "/management/v3/policydefinitions/" in url:
            policy_id = url.rsplit("/", 1)[-1]
            self.policies.pop(policy_id, None)
            return _FakeResponse(204, None)
        if "/management/v3/contractdefinitions/" in url:
            contract_id = url.rsplit("/", 1)[-1]
            self.contracts.pop(contract_id, None)
            return _FakeResponse(204, None)
        raise AssertionError(f"Unexpected DELETE URL: {url}")


class _FakeMessage:
    def __init__(self, value):
        self.value = value


class _KafkaTypeFallbackSession(_FakeSession):
    def __init__(self):
        super().__init__()
        self.asset_posts = []

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if url.endswith("/management/v3/assets"):
            self.asset_posts.append(json)
            if len(self.asset_posts) == 1:
                return _FakeResponse(
                    400,
                    [
                        {
                            "message": "The value for 'https://w3id.org/edc/v0.0.1/ns/type' field is not valid",
                            "type": "ValidationFailure",
                            "path": "https://w3id.org/edc/v0.0.1/ns/type",
                            "invalidValue": None,
                        }
                    ],
                )
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)


class _KafkaUnsupportedSession(_FakeSession):
    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if url.endswith("/management/v3/assets"):
            return _FakeResponse(
                400,
                [
                    {
                        "message": "The value for 'https://w3id.org/edc/v0.0.1/ns/type' field is not valid",
                        "type": "ValidationFailure",
                        "path": "https://w3id.org/edc/v0.0.1/ns/type",
                        "invalidValue": None,
                    }
                ],
            )
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)


class _FakeBrokerState:
    topics = {}
    routes = {}

    @classmethod
    def reset(cls):
        cls.topics = {}
        cls.routes = {}


class _FakeProducer:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def send(self, topic, value):
        _FakeBrokerState.topics.setdefault(topic, []).append(value)
        destination_topic = _FakeBrokerState.routes.get(topic)
        if destination_topic:
            _FakeBrokerState.topics.setdefault(destination_topic, []).append(value)

    def flush(self):
        return None

    def close(self):
        return None


class _LaggingProbeProducer(_FakeProducer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.previous_by_topic = {}

    def send(self, topic, value):
        previous_value = self.previous_by_topic.get(topic)
        destination_topic = _FakeBrokerState.routes.get(topic)
        if previous_value is not None and destination_topic:
            _FakeBrokerState.topics.setdefault(destination_topic, []).append(previous_value)
        _FakeBrokerState.topics.setdefault(topic, []).append(value)
        self.previous_by_topic[topic] = value


class _DroppingLastTransferProducer(_FakeProducer):
    def send(self, topic, value):
        payload = json.loads(value.decode("utf-8") if isinstance(value, bytes) else value)
        message_id = str(payload.get("message_id") or "")
        if message_id.startswith("kafka-transfer-2-"):
            _FakeBrokerState.topics.setdefault(topic, []).append(value)
            return
        super().send(topic, value)


class _FakeConsumer:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.topics = []
        self.offset = 0

    def subscribe(self, topics):
        self.topics = list(topics)

    def poll(self, timeout_ms=0):
        if not self.topics:
            return {}
        topic = self.topics[0]
        messages = _FakeBrokerState.topics.get(topic, [])
        if self.offset >= len(messages):
            return {}
        batch = [_FakeMessage(value) for value in messages[self.offset:]]
        self.offset = len(messages)
        return {topic: batch}

    def close(self):
        return None


class _FakeNewTopic:
    def __init__(self, name, num_partitions, replication_factor):
        self.name = name
        self.num_partitions = num_partitions
        self.replication_factor = replication_factor


class _FakeAdminClient:
    created_topics = []
    last_kwargs = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs
        self._topics = set()

    def list_topics(self):
        return set(self._topics)

    def create_topics(self, topics):
        for topic in topics:
            self._topics.add(topic.name)
            type(self).created_topics.append(topic.name)

    def list_consumer_groups(self):
        return []

    def describe_consumer_groups(self, group_ids):
        return []

    def close(self):
        return None


class _FakeGroupDescription:
    def __init__(self, state, members):
        self.state = state
        self.members = members


class _FakeAdminClientWithConsumerGroup(_FakeAdminClient):
    list_calls = 0

    def list_consumer_groups(self):
        type(self).list_calls += 1
        if type(self).list_calls < 2:
            return []
        return [("corr-1:corr-1", "consumer")]

    def describe_consumer_groups(self, group_ids):
        return [_FakeGroupDescription("Stable", [object()])]


class _FlakyAdminClient(_FakeAdminClient):
    init_calls = 0

    def __init__(self, **kwargs):
        type(self).init_calls += 1
        if type(self).init_calls == 1:
            raise RuntimeError("NoBrokersAvailable")
        super().__init__(**kwargs)


class _DoubleFlakyAdminClient(_FakeAdminClient):
    init_calls = 0

    def __init__(self, **kwargs):
        type(self).init_calls += 1
        if type(self).init_calls <= 2:
            raise RuntimeError("NoBrokersAvailable")
        super().__init__(**kwargs)


class _FakeKafkaManager:
    def __init__(self):
        self.stop_calls = 0
        self.ensure_calls = 0
        self.ensure_topic_calls = []
        self.started_by_framework = True
        self.provisioning_mode = "kubernetes"
        self.cluster_bootstrap_servers = "host.minikube.internal:39093"

    def stop_kafka(self):
        self.stop_calls += 1

    def ensure_kafka_running(self):
        self.ensure_calls += 1
        return "localhost:39093"

    def ensure_topic(self, topic_name, *, partitions=1, replication_factor=1):
        self.ensure_topic_calls.append(
            {
                "topic_name": topic_name,
                "partitions": partitions,
                "replication_factor": replication_factor,
            }
        )
        return False


class _FakeKubernetesKafkaManager(_FakeKafkaManager):
    def __init__(self):
        super().__init__()
        self.cluster_bootstrap_servers = "framework-kafka.demoedc.svc.cluster.local:9092"
        self.commands = []

    def command_runner(self, command, input_text=None):
        self.commands.append({"command": list(command), "input_text": input_text})
        if "kafka-topics" in command:
            if "--list" in command:
                return mock.Mock(returncode=0, stdout="\n".join(sorted(_FakeBrokerState.topics)) + "\n", stderr="")
            if "--create" in command:
                topic = command[command.index("--topic") + 1]
                _FakeBrokerState.topics.setdefault(topic, [])
                return mock.Mock(returncode=0, stdout="", stderr="")
        if "kafka-console-producer" in command:
            topic = command[command.index("--topic") + 1]
            for line in (input_text or "").splitlines():
                value = line.encode("utf-8")
                _FakeBrokerState.topics.setdefault(topic, []).append(value)
                destination_topic = _FakeBrokerState.routes.get(topic)
                if destination_topic:
                    _FakeBrokerState.topics.setdefault(destination_topic, []).append(value)
            return mock.Mock(returncode=0, stdout="", stderr="")
        if "kafka-console-consumer" in command:
            topic = command[command.index("--topic") + 1]
            offset = int(command[command.index("--offset") + 1]) if "--offset" in command else 0
            messages = [
                value.decode("utf-8") if isinstance(value, bytes) else str(value)
                for value in _FakeBrokerState.topics.get(topic, [])[offset:]
            ]
            return mock.Mock(returncode=0, stdout="\n".join(messages) + ("\n" if messages else ""), stderr="")
        if "kafka-run-class" in command and "kafka.tools.GetOffsetShell" in command:
            topic = command[command.index("--topic") + 1]
            offset = len(_FakeBrokerState.topics.get(topic, []))
            return mock.Mock(returncode=0, stdout=f"{topic}:0:{offset}\n", stderr="")
        return mock.Mock(returncode=1, stdout="", stderr=f"Unexpected command: {' '.join(command)}")


class _StepwiseKafkaManager(_FakeKafkaManager):
    def __init__(self, responses, *, started_by_framework=True, provisioning_mode="kubernetes"):
        super().__init__()
        self.responses = list(responses)
        self.started_by_framework = started_by_framework
        self.provisioning_mode = provisioning_mode

    def ensure_kafka_running(self):
        self.ensure_calls += 1
        if not self.responses:
            return None

        response = self.responses.pop(0)
        if isinstance(response, tuple):
            bootstrap, cluster_bootstrap = response
            self.cluster_bootstrap_servers = cluster_bootstrap
            return bootstrap
        return response


class _RetryLoginSession(_FakeSession):
    def __init__(self):
        super().__init__()
        self.login_attempts = 0

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if "openid-connect/token" in url:
            self.login_attempts += 1
            if self.login_attempts == 1:
                raise requests.exceptions.ConnectionError("connection refused")
            return _FakeResponse(200, {"access_token": "jwt-after-retry"})
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)


class _RetryGatewaySession(_FakeSession):
    def __init__(self):
        super().__init__()
        self.catalog_attempts = 0

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if url.endswith("/management/v3/catalog/request"):
            self.catalog_attempts += 1
            if self.catalog_attempts == 1:
                return _FakeResponse(
                    502,
                    [{
                        "message": "Unable to obtain credentials: Keycloak 503",
                        "type": "BadGateway",
                    }],
                )
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)


class _DelayedAgreementSession(_FakeSession):
    def __init__(self):
        super().__init__()
        self.agreement_query_calls = 0
        self.agreement_visible = False
        self.transfer_started_after_visibility = False

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if url.endswith("/management/v3/contractagreements/request"):
            self.agreement_query_calls += 1
            if self.agreement_query_calls < 3:
                return _FakeResponse(200, [])
            self.agreement_visible = True
        if url.endswith("/management/v3/transferprocesses"):
            self.transfer_started_after_visibility = self.agreement_visible
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)

    def get(self, url, headers=None, timeout=None):
        if url.endswith("/management/v3/contractagreements/agreement-1"):
            return _FakeResponse(404, None)
        return super().get(url, headers=headers, timeout=timeout)


class KafkaEdcValidationSuiteTests(unittest.TestCase):
    def setUp(self):
        _FakeBrokerState.reset()
        _FakeAdminClient.created_topics = []
        _FakeAdminClient.last_kwargs = None
        _FakeAdminClientWithConsumerGroup.created_topics = []
        _FakeAdminClientWithConsumerGroup.last_kwargs = None
        _FakeAdminClientWithConsumerGroup.list_calls = 0
        _FlakyAdminClient.created_topics = []
        _FlakyAdminClient.last_kwargs = None
        _FlakyAdminClient.init_calls = 0
        _DoubleFlakyAdminClient.created_topics = []
        _DoubleFlakyAdminClient.last_kwargs = None
        _DoubleFlakyAdminClient.init_calls = 0

    def test_protocol_address_uses_resolver_when_available(self):
        suite = KafkaEdcValidationSuite(
            protocol_address_resolver=lambda connector: (
                f"http://{connector}.roleedcprove-provider.svc.cluster.local:19194/protocol"
            ),
        )

        self.assertEqual(
            suite._protocol_address("conn-cityproof-roleedcprove"),
            "http://conn-cityproof-roleedcprove.roleedcprove-provider.svc.cluster.local:19194/protocol",
        )

    def test_run_pair_executes_edc_kafka_flow_and_persists_artifact(self):
        ensured_topics = []
        counter = itertools.count(1000, 5)
        session = _FakeSession()

        def time_provider():
            return float(next(counter))

        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }

        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak.local",
                "KAFKA_CLUSTER_BOOTSTRAP_SERVERS": "broker-cluster:29092",
            },
            kafka_runtime_loader=lambda: {
                "bootstrap_servers": "localhost:9092",
                "topic_name": "edc-kafka-suite",
                "message_count": 3,
                "security_protocol": "PLAINTEXT",
                "consumer_poll_timeout_seconds": 5,
                "startup_grace_seconds": 0,
            },
            ensure_kafka_topic=lambda topic_name: ensured_topics.append(topic_name) or True,
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeNewTopic,
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            session=session,
            time_provider=time_provider,
            uuid_factory=iter(["testcase", "id1", "id2", "id3", "id4", "id5", "id6", "id7", "id8", "id9"]).__next__,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = suite.run_pair("conn-provider", "conn-consumer", experiment_dir=tmpdir)

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["agreement_id"], "agreement-1")
            self.assertEqual(result["transfer_state"], "STARTED")
            self.assertEqual(result["metrics"]["messages_produced"], 3)
            self.assertEqual(result["metrics"]["messages_consumed"], 3)
            self.assertEqual(len(result["metrics"]["message_samples"]), 3)
            self.assertEqual(result["metrics"]["message_samples"][0]["status"], "consumed")
            self.assertTrue(result["metrics"]["message_samples"][0]["message_id"].startswith("kafka-transfer-"))
            self.assertTrue(result["artifact_path"].endswith("kafka_transfer/conn-provider__conn-consumer.json"))
            self.assertTrue(os.path.exists(result["artifact_path"]))
            self.assertEqual(ensured_topics, [])
            self.assertEqual(result["bootstrap_servers"], "localhost:9092")
            self.assertEqual(result["cluster_bootstrap_servers"], "broker-cluster:29092")
            self.assertEqual(result["source_topic"], _FakeAdminClient.created_topics[0])
            self.assertEqual(result["destination_topic"], _FakeAdminClient.created_topics[1])
            self.assertEqual(result["steps"][-1]["name"], "measure_kafka_transfer_latency")
            self.assertEqual(session.asset_bootstrap_servers, "broker-cluster:29092")
            self.assertEqual(session.destination_bootstrap_servers, "broker-cluster:29092")
            self.assertIn("transfer-1", session.terminated_transfers)
            self.assertIn("transfer-1", session.deprovisioned_transfers)

    def test_run_pair_fails_when_transfer_consumes_only_part_of_produced_messages(self):
        counter = itertools.count(1000, 5)
        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }

        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak.local",
                "KAFKA_CLUSTER_BOOTSTRAP_SERVERS": "broker-cluster:29092",
            },
            kafka_runtime_loader=lambda: {
                "bootstrap_servers": "localhost:9092",
                "topic_name": "edc-kafka-suite",
                "message_count": 3,
                "security_protocol": "PLAINTEXT",
                "consumer_poll_timeout_seconds": 1,
                "startup_grace_seconds": 0,
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeNewTopic,
            producer_class=_DroppingLastTransferProducer,
            consumer_class=_FakeConsumer,
            session=_FakeSession(),
            time_provider=lambda: float(next(counter)),
            uuid_factory=iter(["partial", "suffix", "id1", "id2", "id3", "id4"]).__next__,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = suite.run_pair("conn-provider", "conn-consumer", experiment_dir=tmpdir)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["type"], "KafkaTransferIncomplete")
        self.assertIn("consumed only 2/3", result["error"]["message"])
        self.assertEqual(result["metrics"]["status"], "incomplete")
        self.assertEqual(result["metrics"]["messages_produced"], 3)
        self.assertEqual(result["metrics"]["messages_consumed"], 2)
        self.assertEqual(result["metrics"]["messages_missing"], 1)
        self.assertEqual(result["metrics"]["message_samples"][2]["status"], "missing")

    def test_run_pair_uses_kubernetes_exec_backend_for_framework_kubernetes_broker(self):
        counter = itertools.count(2000, 5)
        session = _FakeSession()
        kafka_manager = _FakeKubernetesKafkaManager()
        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }

        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {
                "bootstrap_servers": "127.0.0.1:39092",
                "cluster_bootstrap_servers": "framework-kafka.demoedc.svc.cluster.local:9092",
                "provisioner": "kubernetes",
                "validation_backend": "kubernetes-exec",
                "k8s_namespace": "demoedc",
                "k8s_service_name": "framework-kafka",
                "topic_name": "edc-kafka-suite",
                "message_count": 2,
                "security_protocol": "PLAINTEXT",
                "consumer_poll_timeout_seconds": 5,
                "startup_grace_seconds": 5,
                "poll_interval_seconds": 1,
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=session,
            time_provider=lambda: float(next(counter)),
            uuid_factory=iter(["k8scase", "suffix", "probe", "id1", "id2", "id3", "id4"]).__next__,
        )

        result = suite.run_pair("conn-provider", "conn-consumer")

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["validation_backend"], "kubernetes-exec")
        self.assertEqual(result["metrics"]["messages_produced"], 2)
        self.assertEqual(result["metrics"]["messages_consumed"], 2)
        self.assertEqual(result["metrics"]["consumer_group_id"], "kubernetes-exec")
        self.assertEqual(result["steps"][0]["method"], "kubernetes_exec")
        self.assertEqual(result["steps"][1]["method"], "kubernetes_exec")
        stabilization_steps = [
            step for step in result["steps"]
            if step.get("name") == "wait_for_transfer_runtime_stabilization"
        ]
        self.assertEqual(stabilization_steps[0]["strategy"], "kubernetes_exec_probe_ready")
        self.assertEqual(session.asset_bootstrap_servers, "framework-kafka.demoedc.svc.cluster.local:9092")
        self.assertEqual(session.destination_bootstrap_servers, "framework-kafka.demoedc.svc.cluster.local:9092")
        self.assertEqual(_FakeAdminClient.created_topics, [])
        self.assertTrue(
            any(
                command["command"][:5] == ["kubectl", "exec", "-n", "demoedc", "deployment/framework-kafka"]
                for command in kafka_manager.commands
            )
        )
        self.assertTrue(
            any(
                "-i" in command["command"] and "kafka-console-producer" in command["command"]
                for command in kafka_manager.commands
            )
        )
        self.assertTrue(
            any(
                "--from-beginning" in command["command"] and "kafka-console-consumer" in command["command"]
                for command in kafka_manager.commands
            )
        )
        self.assertFalse(
            any(
                "--offset" in command["command"] and "kafka-console-consumer" in command["command"]
                for command in kafka_manager.commands
            )
        )

    def test_run_pair_waits_for_contract_agreement_visibility_before_transfer(self):
        session = _DelayedAgreementSession()
        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }

        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak.local",
                "KAFKA_CLUSTER_BOOTSTRAP_SERVERS": "broker-cluster:29092",
            },
            kafka_runtime_loader=lambda: {
                "bootstrap_servers": "localhost:9092",
                "topic_name": "edc-kafka-suite",
                "message_count": 1,
                "security_protocol": "PLAINTEXT",
                "consumer_poll_timeout_seconds": 5,
                "startup_grace_seconds": 0,
                "agreement_visibility_timeout_seconds": 10,
                "poll_interval_seconds": 1,
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeNewTopic,
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            session=session,
            time_provider=lambda: 1000.0,
            uuid_factory=iter(["visibility", "id1", "id2", "id3", "id4", "id5"]).__next__,
        )

        with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
            result = suite.run_pair("conn-provider", "conn-consumer")

        step_names = [step["name"] for step in result["steps"]]
        self.assertEqual(result["status"], "passed")
        self.assertIn("wait_for_contract_agreement_visibility", step_names)
        self.assertLess(
            step_names.index("wait_for_contract_agreement_visibility"),
            step_names.index("start_transfer"),
        )
        self.assertTrue(session.transfer_started_after_visibility)
        self.assertGreaterEqual(session.agreement_query_calls, 3)
        sleep_mock.assert_any_call(1)

    def test_create_asset_retries_with_expanded_json_ld_kafka_dataaddress(self):
        session = _KafkaTypeFallbackSession()
        suite = KafkaEdcValidationSuite(
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            ds_domain_resolver=lambda: "example.local",
            session=session,
        )

        asset_id, returned_id, status_code = suite._create_asset(
            "conn-provider",
            "jwt-provider",
            "source-topic",
            {"cluster_bootstrap_servers": "broker-cluster:29092"},
            "suffix",
        )

        self.assertEqual(asset_id, "kafka-edc-asset-suffix")
        self.assertEqual(returned_id, "kafka-edc-asset-suffix")
        self.assertEqual(status_code, 200)
        self.assertEqual(len(session.asset_posts), 2)
        self.assertEqual(session.asset_posts[0]["dataAddress"]["type"], "Kafka")
        expanded_address = session.asset_posts[1]["dataAddress"]
        self.assertEqual(
            expanded_address["https://w3id.org/edc/v0.0.1/ns/type"][0]["@value"],
            "Kafka",
        )
        self.assertEqual(
            expanded_address["https://w3id.org/edc/v0.0.1/ns/topic"][0]["@value"],
            "source-topic",
        )

    def test_run_pair_skips_when_deployed_connector_rejects_kafka_dataaddress(self):
        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak.local",
                "KAFKA_CLUSTER_BOOTSTRAP_SERVERS": "broker-cluster:29092",
            },
            kafka_runtime_loader=lambda: {
                "bootstrap_servers": "localhost:9092",
                "topic_name": "edc-kafka-suite",
                "startup_grace_seconds": 0,
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeNewTopic,
            session=_KafkaUnsupportedSession(),
            uuid_factory=iter(["topic", "suffix"]).__next__,
        )

        result = suite.run_pair("conn-provider", "conn-consumer")

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "kafka_dataaddress_not_supported")
        self.assertEqual(result["error"]["type"], "KafkaDataAddressUnsupported")

    def test_run_pair_uses_runtime_bootstrap_servers_to_ensure_topic(self):
        fallback_topics = []
        counter = itertools.count(2000, 5)
        session = _FakeSession()

        def time_provider():
            return float(next(counter))

        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }

        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {
                "bootstrap_servers": "broker-runtime:29092",
                "topic_name": "edc-kafka-suite",
                "message_count": 2,
                "security_protocol": "PLAINTEXT",
                "consumer_poll_timeout_seconds": 5,
                "startup_grace_seconds": 0,
            },
            ensure_kafka_topic=lambda topic_name: fallback_topics.append(topic_name) or True,
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeNewTopic,
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            session=session,
            time_provider=time_provider,
            uuid_factory=iter(["runtimecase", "id1", "id2", "id3", "id4", "id5", "id6", "id7"]).__next__,
        )

        result = suite.run_pair("conn-provider", "conn-consumer")

        self.assertEqual(result["status"], "passed")
        self.assertEqual(fallback_topics, [])
        self.assertEqual(_FakeAdminClient.last_kwargs["bootstrap_servers"], "broker-runtime:29092")
        self.assertEqual(_FakeAdminClient.created_topics, [result["source_topic"], result["destination_topic"]])
        self.assertEqual(result["steps"][0]["method"], "runtime_admin")
        self.assertEqual(result["cluster_bootstrap_servers"], "broker-runtime:29092")
        self.assertEqual(session.asset_bootstrap_servers, "broker-runtime:29092")
        self.assertEqual(session.destination_bootstrap_servers, "broker-runtime:29092")

    def test_run_pair_derives_cluster_bootstrap_servers_from_localhost_runtime(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {
                "bootstrap_servers": "localhost:39092",
                "topic_name": "edc-kafka-suite",
                "message_count": 1,
                "security_protocol": "PLAINTEXT",
                "consumer_poll_timeout_seconds": 5,
                "startup_grace_seconds": 0,
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeNewTopic,
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            session=_FakeSession(),
            time_provider=lambda: 1000.0,
            uuid_factory=iter(["derivecase", "id1", "id2", "id3", "id4", "id5", "id6"]).__next__,
        )

        runtime = suite._ensure_kafka_runtime(suite._load_kafka_runtime())

        self.assertEqual(runtime["host_bootstrap_servers"], "localhost:39092")
        self.assertEqual(
            runtime["cluster_bootstrap_servers"],
            "host.minikube.internal:39092,host.docker.internal:39092",
        )

    def test_runtime_surfaces_last_kafka_preparation_error_when_bootstrap_missing(self):
        class _FailingKafkaManager:
            cluster_bootstrap_servers = None
            last_error = "Kafka port-forward did not expose the external bootstrap server in time"

            @staticmethod
            def ensure_kafka_running():
                return None

        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=_FailingKafkaManager(),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Last runtime preparation error: Kafka port-forward did not expose the external bootstrap server in time",
        ):
            suite._ensure_kafka_runtime(suite._load_kafka_runtime())

    def test_wait_for_transfer_runtime_stabilization_waits_for_consumer_group(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClientWithConsumerGroup,
            new_topic_class=_FakeNewTopic,
            session=_FakeSession(),
        )

        fake_clock = itertools.count(100)

        with patch("framework.kafka_edc_validation.time.time", side_effect=lambda: float(next(fake_clock))):
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                result = suite._wait_for_transfer_runtime_stabilization(
                    {
                        "bootstrap_servers": "broker-runtime:29092",
                        "host_bootstrap_servers": "broker-runtime:29092",
                        "startup_grace_seconds": 5,
                        "poll_interval_seconds": 1,
                    },
                    {"correlationId": "corr-1"},
                    "source-topic",
                )

        self.assertEqual(result["strategy"], "consumer_group_ready")
        self.assertEqual(result["group_id"], "corr-1:corr-1")
        self.assertEqual(result["state"], "Stable")
        self.assertEqual(result["member_count"], 1)
        self.assertEqual(_FakeAdminClientWithConsumerGroup.last_kwargs["request_timeout_ms"], 5000)
        self.assertEqual(_FakeAdminClientWithConsumerGroup.last_kwargs["api_version_auto_timeout_ms"], 5000)

    def test_wait_for_transfer_runtime_stabilization_falls_back_to_probe(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FakeAdminClient,
            new_topic_class=_FakeNewTopic,
            session=_FakeSession(),
        )

        fake_clock = itertools.count(100)

        with patch.object(suite, "_open_probe_clients", return_value=(mock.Mock(), mock.Mock(), "probe-group")):
            with patch.object(
                suite,
                "_wait_for_end_to_end_probe",
                return_value={
                    "status": "ready",
                    "attempts": 2,
                    "seconds_waited": 4.0,
                    "probe_message_id": "probe-1",
                },
            ) as probe_mock:
                with patch("framework.kafka_edc_validation.time.time", side_effect=lambda: float(next(fake_clock))):
                    with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                        result = suite._wait_for_transfer_runtime_stabilization(
                            {
                                "bootstrap_servers": "broker-runtime:29092",
                                "host_bootstrap_servers": "broker-runtime:29092",
                                "startup_grace_seconds": 60,
                                "poll_interval_seconds": 1,
                            },
                            {
                                "correlationId": "corr-2",
                                "dataDestination": {
                                    "topic": "destination-topic",
                                },
                            },
                            "source-topic",
                        )

        self.assertEqual(result["strategy"], "probe_ready")
        self.assertEqual(result["group_id"], "probe-group")
        self.assertEqual(result["state"], "ProbeRelayed")
        self.assertEqual(result["destination_topic"], "destination-topic")
        self.assertEqual(result["probe"]["probe_message_id"], "probe-1")
        probe_mock.assert_called_once()

    def test_wait_for_cleanup_settlement_only_waits_when_cleanup_did_work(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            session=_FakeSession(),
        )

        with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
            waited = suite._wait_for_cleanup_settlement(
                {"pre_run_settle_seconds": 7},
                [{"connector": "conn-a", "terminated_transfers": [{"transfer_id": "t-1"}]}],
            )
            skipped = suite._wait_for_cleanup_settlement(
                {"pre_run_settle_seconds": 7},
                [{"connector": "conn-a", "terminated_transfers": []}],
            )

        self.assertEqual(waited["status"], "waited")
        self.assertEqual(waited["seconds_waited"], 7)
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["reason"], "no_cleanup_actions")
        sleep_mock.assert_called_once_with(7)

    def test_ensure_topic_with_runtime_retries_after_soft_broker_refresh(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_FlakyAdminClient,
            new_topic_class=_FakeNewTopic,
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        runtime = {
            "bootstrap_servers": "localhost:39092",
            "host_bootstrap_servers": "localhost:39092",
            "cluster_bootstrap_servers": "host.minikube.internal:39092",
        }

        self.assertTrue(suite._ensure_topic_with_runtime(runtime, "topic-a"))
        self.assertEqual(kafka_manager.stop_calls, 0)
        self.assertEqual(kafka_manager.ensure_calls, 1)
        self.assertEqual(runtime["bootstrap_servers"], "localhost:39093")
        self.assertEqual(runtime["cluster_bootstrap_servers"], "host.minikube.internal:39093")

    def test_ensure_topic_with_runtime_uses_hard_restart_only_after_soft_refresh_fails(self):
        kafka_manager = _StepwiseKafkaManager(
            [
                ("localhost:39092", "host.minikube.internal:39092"),
                ("localhost:39093", "host.minikube.internal:39093"),
            ]
        )
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_DoubleFlakyAdminClient,
            new_topic_class=_FakeNewTopic,
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        runtime = {
            "bootstrap_servers": "localhost:39091",
            "host_bootstrap_servers": "localhost:39091",
            "cluster_bootstrap_servers": "host.minikube.internal:39091",
            "allow_hard_restart_on_topic_failure": True,
        }

        self.assertTrue(suite._ensure_topic_with_runtime(runtime, "topic-b"))
        self.assertEqual(kafka_manager.ensure_calls, 2)
        self.assertEqual(kafka_manager.stop_calls, 1)
        self.assertEqual(runtime["bootstrap_servers"], "localhost:39093")
        self.assertEqual(runtime["cluster_bootstrap_servers"], "host.minikube.internal:39093")

    def test_ensure_topic_with_runtime_does_not_hard_restart_framework_kubernetes_broker_by_default(self):
        kafka_manager = _StepwiseKafkaManager(
            [
                ("localhost:39092", "host.minikube.internal:39092"),
            ]
        )
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_DoubleFlakyAdminClient,
            new_topic_class=_FakeNewTopic,
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        runtime = {
            "bootstrap_servers": "localhost:39091",
            "host_bootstrap_servers": "localhost:39091",
            "cluster_bootstrap_servers": "host.minikube.internal:39091",
        }

        with self.assertRaises(RuntimeError):
            suite._ensure_topic_with_runtime(runtime, "topic-c")

        self.assertEqual(kafka_manager.ensure_calls, 1)
        self.assertEqual(kafka_manager.stop_calls, 0)

    def test_ensure_topic_with_runtime_does_not_hard_restart_framework_split_kraft_broker_by_default(self):
        kafka_manager = _StepwiseKafkaManager(
            [
                ("localhost:39092", "host.minikube.internal:39092"),
            ],
            provisioning_mode="kubernetes-split-kraft",
        )
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_DoubleFlakyAdminClient,
            new_topic_class=_FakeNewTopic,
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        runtime = {
            "bootstrap_servers": "localhost:39091",
            "host_bootstrap_servers": "localhost:39091",
            "cluster_bootstrap_servers": "host.minikube.internal:39091",
        }

        with self.assertRaises(RuntimeError):
            suite._ensure_topic_with_runtime(runtime, "topic-c-split")

        self.assertEqual(kafka_manager.ensure_calls, 1)
        self.assertEqual(kafka_manager.stop_calls, 0)

    def test_ensure_topic_with_runtime_uses_runtime_manager_fallback_for_framework_kubernetes(self):
        kafka_manager = _FakeKafkaManager()
        kafka_manager.ensure_topic = mock.Mock(return_value=True)
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            admin_client_class=_DoubleFlakyAdminClient,
            new_topic_class=_FakeNewTopic,
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        runtime = {
            "bootstrap_servers": "localhost:39091",
            "host_bootstrap_servers": "localhost:39091",
            "cluster_bootstrap_servers": "host.minikube.internal:39091",
        }

        self.assertTrue(suite._ensure_topic_with_runtime(runtime, "topic-d"))

        kafka_manager.ensure_topic.assert_called_once_with(
            "topic-d",
            partitions=1,
            replication_factor=1,
        )
        self.assertEqual(runtime["_last_topic_ensure_method"], "runtime_manager")
        self.assertEqual(kafka_manager.ensure_calls, 0)
        self.assertEqual(kafka_manager.stop_calls, 0)

    def test_login_retries_transient_keycloak_failure(self):
        session = _RetryLoginSession()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            session=session,
        )

        with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
            token = suite._login("conn-a", "consumer")

        self.assertEqual(token, "jwt-after-retry")
        self.assertEqual(session.login_attempts, 2)
        sleep_mock.assert_called_once_with(2)

    def test_login_uses_keycloak_url_resolver_when_present(self):
        session = _FakeSession()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            session=session,
            keycloak_url_resolver=lambda: "http://127.0.0.1:38080",
        )

        token = suite._login("conn-a", "consumer")

        self.assertEqual(token, "jwt-user")

    def test_management_url_uses_management_url_resolver_when_present(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            management_url_resolver=lambda connector, path: f"http://127.0.0.1:39193{path}",
        )

        url = suite._management_url("conn-a", "/management/v3/assets/request")

        self.assertEqual(url, "http://127.0.0.1:39193/management/v3/assets/request")

    def test_management_url_uses_public_access_url_from_credentials(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"},
                "public_access_urls": {
                    "connector_management_api": "https://org2.example.test/management",
                },
                "access_urls": {
                    "connector_management_api": "http://conn-org2.example.test/management",
                },
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
        )

        url = suite._management_url("conn-org2", "/management/v3/assets/request")

        self.assertEqual(url, "https://org2.example.test/management/v3/assets/request")

    def test_management_url_falls_back_to_internal_access_url_from_credentials(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"},
                "access_urls": {
                    "connector_management_api": "http://conn-org2.example.test/management",
                },
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
        )

        url = suite._management_url("conn-org2", "/management/v3/assets/request")

        self.assertEqual(url, "http://conn-org2.example.test/management/v3/assets/request")

    def test_wait_for_transfer_started_can_continue_from_requested_state_to_probe(self):
        session = _FakeSession()
        session.transfers["transfer-1"] = {"@id": "transfer-1", "state": "REQUESTED"}
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            session=session,
        )

        with patch("framework.kafka_edc_validation.time.time", side_effect=[0, 0, 4]):
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                result = suite._wait_for_transfer_started(
                    "conn-consumer",
                    "jwt",
                    "transfer-1",
                    {
                        "transfer_timeout_seconds": 1,
                        "poll_interval_seconds": 1,
                        "continue_after_requested_transfer_timeout": True,
                    },
                )

        self.assertEqual(result["state"], "REQUESTED")
        self.assertTrue(result["continued_after_requested_timeout"])

    def test_wait_for_transfer_started_can_keep_strict_requested_timeout(self):
        session = _FakeSession()
        session.transfers["transfer-1"] = {"@id": "transfer-1", "state": "REQUESTED"}
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            session=session,
        )

        with patch("framework.kafka_edc_validation.time.time", side_effect=[0, 0, 4]):
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                with self.assertRaises(RuntimeError):
                    suite._wait_for_transfer_started(
                        "conn-consumer",
                        "jwt",
                        "transfer-1",
                        {
                            "transfer_timeout_seconds": 1,
                            "poll_interval_seconds": 1,
                            "continue_after_requested_transfer_timeout": False,
                        },
                    )

    def test_post_json_retries_transient_bad_gateway_response(self):
        session = _RetryGatewaySession()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            session=session,
        )

        with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
            body, status_code = suite._request_catalog("conn-provider", "conn-consumer", "jwt-consumer")

        self.assertEqual(status_code, 200)
        self.assertEqual(session.catalog_attempts, 2)
        self.assertIn("dcat:dataset", body)
        sleep_mock.assert_called_once_with(2)

    def test_run_all_preserves_framework_managed_kafka_between_successful_pairs(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        with patch.object(suite, "run_pair", side_effect=[
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed"},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed"},
        ]) as run_pair_mock:
            results = suite.run_all(["conn-a", "conn-b"], experiment_dir="/tmp/unused")

        self.assertEqual(len(results), 2)
        self.assertEqual(run_pair_mock.call_count, 2)
        self.assertEqual(kafka_manager.stop_calls, 0)

    def test_end_to_end_probe_accepts_delayed_previous_probe(self):
        _FakeBrokerState.routes["source-topic"] = "destination-topic"
        suite = KafkaEdcValidationSuite()
        producer = _LaggingProbeProducer()
        consumer = _FakeConsumer()
        consumer.subscribe(["destination-topic"])

        result = suite._wait_for_end_to_end_probe(
            {
                "poll_interval_seconds": 1,
                "consumer_request_timeout_ms": 500,
            },
            producer,
            consumer,
            "source-topic",
            timeout_seconds=3,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["attempts"], 2)
        self.assertTrue(result["probe_message_id"].startswith("kafka-transfer-probe-"))

    def test_kubernetes_exec_probe_accepts_late_sink_confirmation(self):
        suite = KafkaEdcValidationSuite(uuid_factory=lambda: "late")
        runtime = {
            "consumer_request_timeout_ms": 500,
            "poll_interval_seconds": 1,
            "late_probe_confirmation_seconds": 5,
        }

        with patch.object(suite, "_kubernetes_topic_end_offset", return_value=0):
            with patch.object(suite, "_produce_kubernetes_exec_message") as producer_mock:
                with patch.object(
                    suite,
                    "_find_kubernetes_exec_probe_message",
                    side_effect=[None, "kafka-transfer-probe-late"],
                ) as find_probe_mock:
                    with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                        with patch("framework.kafka_edc_validation.time.time", side_effect=[0, 0, 2, 2]):
                            result = suite._wait_for_end_to_end_probe_with_kubernetes_exec(
                                runtime,
                                "source-topic",
                                "destination-topic",
                                timeout_seconds=1,
                            )

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["late_confirmation"])
        self.assertEqual(result["probe_message_id"], "kafka-transfer-probe-late")
        producer_mock.assert_called_once()
        self.assertEqual(find_probe_mock.call_count, 2)
        late_confirmation_call = find_probe_mock.call_args_list[-1]
        self.assertEqual(late_confirmation_call.kwargs["timeout_seconds"], 5)
        self.assertIsNone(late_confirmation_call.kwargs["offset"])

    def test_kubernetes_exec_probe_can_opt_in_to_offset_lookup(self):
        suite = KafkaEdcValidationSuite(uuid_factory=lambda: "offset")
        runtime = {
            "consumer_request_timeout_ms": 500,
            "poll_interval_seconds": 1,
            "late_probe_confirmation_seconds": 0,
            "kubernetes_exec_use_topic_offsets": "true",
        }

        with patch.object(suite, "_kubernetes_topic_end_offset", return_value=7) as offset_mock:
            with patch.object(suite, "_produce_kubernetes_exec_message") as producer_mock:
                with patch.object(
                    suite,
                    "_find_kubernetes_exec_probe_message",
                    return_value="kafka-transfer-probe-offset",
                ) as find_probe_mock:
                    result = suite._wait_for_end_to_end_probe_with_kubernetes_exec(
                        runtime,
                        "source-topic",
                        "destination-topic",
                        timeout_seconds=1,
                    )

        self.assertEqual(result["status"], "ready")
        offset_mock.assert_called_once_with(runtime, "destination-topic")
        producer_mock.assert_called_once()
        self.assertEqual(find_probe_mock.call_args.kwargs["offset"], 7)

    def test_kubernetes_exec_measure_accepts_late_transfer_confirmation(self):
        ids = iter(["id1", "id2"])
        counter = itertools.count(1000, 5)
        suite = KafkaEdcValidationSuite(
            uuid_factory=ids.__next__,
            time_provider=lambda: float(next(counter)),
        )
        runtime = {
            "message_count": 2,
            "message_sample_limit": 2,
            "consumer_poll_timeout_seconds": 1,
            "late_transfer_confirmation_seconds": 5,
        }
        late_messages = [
            {"message_id": "kafka-transfer-0-id1", "producer_timestamp_ms": 1000},
            {"message_id": "kafka-transfer-1-id2", "producer_timestamp_ms": 1005},
        ]

        with patch.object(suite, "_kubernetes_topic_end_offset", return_value=0):
            with patch.object(suite, "_produce_kubernetes_exec_message"):
                with patch.object(suite, "_consume_kubernetes_exec_messages", return_value=late_messages):
                    with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                        with patch("framework.kafka_edc_validation.time.time", side_effect=[0, 2, 2, 2, 3]):
                            metrics = suite._measure_transfer_latency_with_kubernetes_exec(
                                runtime,
                                "source-topic",
                                "destination-topic",
                                probe_result={"status": "ready"},
                            )

        self.assertEqual(metrics["status"], "completed")
        self.assertEqual(metrics["messages_produced"], 2)
        self.assertEqual(metrics["messages_consumed"], 2)
        self.assertEqual(metrics["late_confirmation"]["status"], "completed")
        self.assertEqual(metrics["late_confirmation"]["messages_consumed"], 2)

    def test_kubernetes_exec_measure_scans_past_probe_messages_without_offsets(self):
        ids = iter(["id1", "id2"])
        counter = itertools.count(1000, 5)
        suite = KafkaEdcValidationSuite(
            uuid_factory=ids.__next__,
            time_provider=lambda: float(next(counter)),
        )
        runtime = {
            "message_count": 2,
            "message_sample_limit": 2,
            "consumer_poll_timeout_seconds": 1,
            "late_transfer_confirmation_seconds": 0,
        }
        observed_consume_calls = []

        def fake_consume(runtime_arg, topic, timeout_ms=2000, max_messages=50, offset=None):
            observed_consume_calls.append({
                "max_messages": max_messages,
                "offset": offset,
            })
            probes = [
                {"message_id": f"kafka-transfer-probe-{index}", "probe": True}
                for index in range(5)
            ]
            transfer_messages = [
                {"message_id": "kafka-transfer-0-id1", "producer_timestamp_ms": 1000},
                {"message_id": "kafka-transfer-1-id2", "producer_timestamp_ms": 1005},
            ]
            return probes + transfer_messages

        with patch.object(suite, "_produce_kubernetes_exec_message"):
            with patch.object(suite, "_consume_kubernetes_exec_messages", side_effect=fake_consume):
                metrics = suite._measure_transfer_latency_with_kubernetes_exec(
                    runtime,
                    "source-topic",
                    "destination-topic",
                    probe_result={"status": "ready", "attempts": 5},
                )

        self.assertEqual(metrics["status"], "completed")
        self.assertEqual(metrics["messages_produced"], 2)
        self.assertEqual(metrics["messages_consumed"], 2)
        self.assertGreaterEqual(observed_consume_calls[0]["max_messages"], 100)
        self.assertIsNone(observed_consume_calls[0]["offset"])

    def test_kubernetes_exec_stabilization_waits_for_dataplane_group_before_probe(self):
        suite = KafkaEdcValidationSuite()
        runtime = {
            "provisioner": "kubernetes",
            "validation_backend": "kubernetes-exec",
            "startup_grace_seconds": 60,
            "poll_interval_seconds": 1,
        }
        transfer_process = {
            "correlationId": "corr-1",
            "dataDestination": {
                "topic": "destination-topic",
            },
        }

        with patch("framework.kafka_edc_validation.time.time", side_effect=[0, 30, 30, 35]):
            with patch.object(
                suite,
                "_wait_for_kubernetes_exec_consumer_group_ready",
                return_value={
                    "status": "ready",
                    "seconds_waited": 30,
                    "group_id": "corr-1:corr-1",
                    "member_count": 1,
                },
            ) as group_mock:
                with patch.object(
                    suite,
                    "_wait_for_end_to_end_probe_with_kubernetes_exec",
                    return_value={
                        "status": "ready",
                        "attempts": 1,
                        "seconds_waited": 5,
                        "probe_message_id": "probe-1",
                    },
                ) as probe_mock:
                    result = suite._wait_for_transfer_runtime_stabilization(
                        runtime,
                        transfer_process,
                        "source-topic",
                    )

        self.assertEqual(result["strategy"], "kubernetes_exec_probe_ready")
        self.assertEqual(result["group_id"], "corr-1:corr-1")
        self.assertEqual(result["group_status"], "ready")
        self.assertEqual(result["member_count"], 1)
        group_mock.assert_called_once_with(
            runtime,
            "corr-1",
            "source-topic",
            timeout_seconds=10,
        )
        probe_mock.assert_called_once_with(
            runtime,
            "source-topic",
            "destination-topic",
            timeout_seconds=30,
        )

    def test_run_all_retries_transient_pair_failure_once(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        run_pair_results = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "failed",
                "error": {
                    "type": "RuntimeError",
                    "message": "Kafka transfer path did not relay a probe message in time",
                },
                "steps": [
                    {
                        "name": "wait_for_transfer_runtime_stabilization",
                        "strategy": "timeout_without_ready_group",
                    }
                ],
            },
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed", "steps": []},
        ]

        with patch.object(suite, "run_pair", side_effect=run_pair_results) as run_pair_mock:
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        self.assertEqual(run_pair_mock.call_count, 3)
        self.assertEqual(kafka_manager.stop_calls, 1)
        self.assertTrue(results[0]["retry_attempted"])
        self.assertEqual(results[0]["attempt_count"], 2)
        self.assertIn("Kafka transfer path did not relay", results[0]["retry_reason"])
        sleep_mock.assert_called_once_with(5)

    def test_run_all_retries_when_negotiation_stays_initial(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        run_pair_results = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "failed",
                "error": {
                    "type": "RuntimeError",
                    "message": (
                        "Negotiation neg-1 did not produce contractAgreementId in time "
                        "(last_state=INITIAL, detail=None)"
                    ),
                },
                "steps": [
                    {"name": "start_negotiation", "status": "passed"},
                    {"name": "suite_error", "status": "failed"},
                ],
            },
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed", "steps": []},
        ]

        with patch.object(suite, "run_pair", side_effect=run_pair_results) as run_pair_mock:
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        self.assertEqual(run_pair_mock.call_count, 3)
        self.assertEqual(kafka_manager.stop_calls, 0)
        self.assertTrue(results[0]["retry_attempted"])
        self.assertEqual(results[0]["attempt_count"], 2)
        self.assertIn("did not produce contractAgreementId", results[0]["retry_reason"])
        sleep_mock.assert_called_once_with(5)

    def test_run_all_retries_when_first_attempt_consumes_no_messages(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        run_pair_results = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "failed",
                "error": {
                    "type": "RuntimeError",
                    "message": "No Kafka messages were consumed through the EDC transfer",
                },
                "steps": [],
            },
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed", "steps": []},
        ]

        with patch.object(suite, "run_pair", side_effect=run_pair_results) as run_pair_mock:
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        self.assertEqual(run_pair_mock.call_count, 3)
        self.assertEqual(kafka_manager.stop_calls, 1)
        self.assertTrue(results[0]["retry_attempted"])
        self.assertEqual(results[0]["attempt_count"], 2)
        self.assertIn("No Kafka messages were consumed", results[0]["retry_reason"])
        sleep_mock.assert_called_once_with(5)

    def test_run_all_retries_when_first_attempt_consumes_partial_messages(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        run_pair_results = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "failed",
                "error": {
                    "type": "KafkaTransferIncomplete",
                    "message": "Kafka transfer consumed only 9/10 produced messages before timeout",
                },
                "steps": [],
            },
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed", "steps": []},
        ]

        with patch.object(suite, "run_pair", side_effect=run_pair_results) as run_pair_mock:
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        self.assertEqual(run_pair_mock.call_count, 3)
        self.assertEqual(kafka_manager.stop_calls, 1)
        self.assertTrue(results[0]["retry_attempted"])
        self.assertEqual(results[0]["attempt_count"], 2)
        self.assertIn("consumed only 9/10", results[0]["retry_reason"])
        sleep_mock.assert_called_once_with(5)

    def test_run_all_retries_transient_authentication_failure_once(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        run_pair_results = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "failed",
                "error": {
                    "type": "RuntimeError",
                    "message": "provider Kafka asset creation failed with HTTP 401: Request could not be authenticated",
                },
                "steps": [],
            },
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed", "steps": []},
        ]

        with patch.object(suite, "run_pair", side_effect=run_pair_results) as run_pair_mock:
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        self.assertEqual(run_pair_mock.call_count, 3)
        self.assertTrue(results[0]["retry_attempted"])
        self.assertEqual(results[0]["attempt_count"], 2)
        self.assertIn("HTTP 401", results[0]["retry_reason"])
        sleep_mock.assert_called_once_with(5)

    def test_run_all_can_opt_in_to_reset_framework_kubernetes_kafka_between_retry_attempts(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {"allow_framework_kafka_reset_between_pairs": True},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        run_pair_results = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "failed",
                "error": {
                    "type": "RuntimeError",
                    "message": "Kafka transfer path did not relay a probe message in time",
                },
                "steps": [
                    {
                        "name": "wait_for_transfer_runtime_stabilization",
                        "strategy": "timeout_without_ready_group",
                    }
                ],
            },
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed", "steps": []},
        ]

        with patch.object(suite, "run_pair", side_effect=run_pair_results):
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        self.assertEqual(kafka_manager.stop_calls, 1)
        self.assertTrue(results[0]["retry_attempted"])

    def test_run_all_keeps_reset_behavior_for_framework_managed_docker_kafka(self):
        kafka_manager = _StepwiseKafkaManager([], provisioning_mode="docker")
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        run_pair_results = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "failed",
                "error": {
                    "type": "RuntimeError",
                    "message": "No Kafka messages were consumed through the EDC transfer",
                },
                "steps": [],
            },
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed", "steps": []},
        ]

        with patch.object(suite, "run_pair", side_effect=run_pair_results):
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None):
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        self.assertEqual(kafka_manager.stop_calls, 1)

    def test_run_all_waits_between_pairs_when_cleanup_after_run_exists(self):
        kafka_manager = _FakeKafkaManager()
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {"pre_run_settle_seconds": 7},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            kafka_manager=kafka_manager,
            session=_FakeSession(),
        )

        with patch.object(suite, "run_pair", side_effect=[
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "passed",
                "cleanup": {
                    "after_run": [
                        {"terminated_transfers": [{"transfer_id": "transfer-1"}]},
                    ]
                },
            },
            {"provider": "conn-b", "consumer": "conn-a", "status": "passed"},
        ]):
            with patch("framework.kafka_edc_validation.time.sleep", return_value=None) as sleep_mock:
                results = suite.run_all(["conn-a", "conn-b"], experiment_dir=None)

        self.assertEqual(len(results), 2)
        sleep_mock.assert_called_once_with(7)
        self.assertEqual(kafka_manager.stop_calls, 0)

    def test_run_all_emits_progress_after_each_completed_pair(self):
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            session=_FakeSession(),
        )

        progress_events = []

        with patch.object(suite, "run_pair", side_effect=[
            {"provider": "conn-a", "consumer": "conn-b", "status": "passed", "steps": []},
            {"provider": "conn-b", "consumer": "conn-a", "status": "failed", "steps": []},
        ]):
            results = suite.run_all(
                ["conn-a", "conn-b"],
                experiment_dir=None,
                progress_callback=lambda result: progress_events.append(
                    (
                        result.get("provider"),
                        result.get("consumer"),
                        result.get("status"),
                        result.get("attempt_count"),
                    )
                ),
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(
            progress_events,
            [
                ("conn-a", "conn-b", "passed", 1),
                ("conn-b", "conn-a", "failed", 1),
            ],
        )

    def test_measure_transfer_latency_reuses_existing_probe_result(self):
        _FakeBrokerState.routes["source-topic"] = "destination-topic"
        counter = itertools.count(1000, 5)
        suite = KafkaEdcValidationSuite(
            load_connector_credentials=lambda connector: {
                "connector_user": {"user": "user", "passwd": "pass"}
            },
            load_deployer_config=lambda: {"KC_URL": "http://keycloak.local"},
            kafka_runtime_loader=lambda: {},
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "dataspace",
            producer_class=_FakeProducer,
            consumer_class=_FakeConsumer,
            session=_FakeSession(),
            time_provider=lambda: float(next(counter)),
            uuid_factory=iter(["metriccase", "id1", "id2", "id3", "id4", "id5", "id6", "id7", "id8", "id9"]).__next__,
        )

        with patch.object(suite, "_wait_for_end_to_end_probe") as probe_mock:
            metrics = suite._measure_transfer_latency(
                {
                    "bootstrap_servers": "broker-runtime:29092",
                    "host_bootstrap_servers": "broker-runtime:29092",
                    "message_count": 3,
                    "consumer_poll_timeout_seconds": 5,
                },
                "source-topic",
                "destination-topic",
                probe_result={
                    "status": "ready",
                    "attempts": 1,
                    "seconds_waited": 2.0,
                    "probe_message_id": "probe-ready",
                },
            )

        probe_mock.assert_not_called()
        self.assertEqual(metrics["messages_produced"], 3)
        self.assertEqual(metrics["messages_consumed"], 3)
        self.assertEqual(metrics["probe"]["probe_message_id"], "probe-ready")
        self.assertGreater(metrics["throughput_messages_per_second"], 0)


if __name__ == "__main__":
    unittest.main()
