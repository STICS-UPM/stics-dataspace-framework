import json
import math
import os
import time
import uuid
from datetime import datetime


class KafkaMetricsCollector:
    """Generic Kafka broker benchmarking collector."""

    STATIC_TOPIC = "STATIC_TOPIC"
    EXPERIMENT_TOPIC = "EXPERIMENT_TOPIC"

    ENV_MAPPING = {
        "bootstrap_servers": "KAFKA_BOOTSTRAP_SERVERS",
        "security_protocol": "KAFKA_SECURITY_PROTOCOL",
        "sasl_mechanism": "KAFKA_SASL_MECHANISM",
        "username": "KAFKA_USERNAME",
        "password": "KAFKA_PASSWORD",
        "topic_strategy": "KAFKA_TOPIC_STRATEGY",
        "topic_name": "KAFKA_TOPIC_NAME",
        "message_count": "KAFKA_MESSAGE_COUNT",
        "message_size_bytes": "KAFKA_MESSAGE_SIZE_BYTES",
        "poll_timeout_seconds": "KAFKA_POLL_TIMEOUT_SECONDS",
        "consumer_group_prefix": "KAFKA_CONSUMER_GROUP_PREFIX",
        "request_timeout_ms": "KAFKA_REQUEST_TIMEOUT_MS",
        "api_timeout_ms": "KAFKA_API_TIMEOUT_MS",
        "max_block_ms": "KAFKA_MAX_BLOCK_MS",
        "consumer_request_timeout_ms": "KAFKA_CONSUMER_REQUEST_TIMEOUT_MS",
        "topic_ready_timeout_seconds": "KAFKA_TOPIC_READY_TIMEOUT_SECONDS",
    }

    def __init__(
        self,
        runtime_config=None,
        adapter_config_loader=None,
        producer_class=None,
        consumer_class=None,
        admin_client_class=None,
        new_topic_class=None,
        time_provider=None,
        uuid_factory=None,
    ):
        self.runtime_config = runtime_config or {}
        self.adapter_config_loader = adapter_config_loader
        self.producer_class = producer_class
        self.consumer_class = consumer_class
        self.admin_client_class = admin_client_class
        self.new_topic_class = new_topic_class
        self.time_provider = time_provider or self._default_time_provider
        self.uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))

    @staticmethod
    def _default_time_provider():
        return time.perf_counter_ns() // 1_000_000

    def _load_adapter_config(self):
        if callable(self.adapter_config_loader):
            config = self.adapter_config_loader()
            return config if isinstance(config, dict) else {}
        if isinstance(self.adapter_config_loader, dict):
            return self.adapter_config_loader
        return {}

    def _load_env_config(self):
        config = {}
        for key, env_name in self.ENV_MAPPING.items():
            value = os.getenv(env_name)
            if value not in (None, ""):
                config[key] = value
        return config

    def _coerce_types(self, config):
        coerced = dict(config)
        for integer_key in (
            "message_count",
            "message_size_bytes",
            "poll_timeout_seconds",
            "request_timeout_ms",
            "api_timeout_ms",
            "max_block_ms",
            "consumer_request_timeout_ms",
            "topic_ready_timeout_seconds",
        ):
            if integer_key in coerced and coerced[integer_key] not in (None, ""):
                try:
                    coerced[integer_key] = int(coerced[integer_key])
                except (TypeError, ValueError):
                    pass
        return coerced

    def load_config(self, runtime_overrides=None):
        """Load Kafka config from adapter, runtime config and environment variables."""
        config = {}
        config.update(self._load_env_config())
        config.update(self._load_adapter_config())
        config.update(self.runtime_config)
        if runtime_overrides:
            config.update(runtime_overrides)
        config = self._coerce_types(config)

        config.setdefault("security_protocol", "PLAINTEXT")
        config.setdefault("topic_strategy", self.STATIC_TOPIC)
        config.setdefault("message_count", 100)
        config.setdefault("message_size_bytes", 0)
        config.setdefault("poll_timeout_seconds", 30)
        config.setdefault("consumer_group_prefix", "framework-kafka-benchmark")
        config.setdefault("request_timeout_ms", 60000)
        config.setdefault("api_timeout_ms", 60000)
        config.setdefault("max_block_ms", 60000)
        config.setdefault("consumer_request_timeout_ms", 60000)
        config.setdefault("topic_ready_timeout_seconds", 15)
        return config

    def _load_kafka_classes(self):
        producer_class = self.producer_class
        consumer_class = self.consumer_class
        admin_client_class = self.admin_client_class
        new_topic_class = self.new_topic_class

        if producer_class and consumer_class and admin_client_class and new_topic_class:
            return producer_class, consumer_class, admin_client_class, new_topic_class

        try:
            from kafka import KafkaConsumer, KafkaProducer
            from kafka.admin import KafkaAdminClient, NewTopic
            return (
                producer_class or KafkaProducer,
                consumer_class or KafkaConsumer,
                admin_client_class or KafkaAdminClient,
                new_topic_class or NewTopic,
            )
        except Exception as exc:
            raise RuntimeError(f"Kafka client library not available: {exc}") from exc

    @staticmethod
    def _sanitize_experiment_id(experiment_id):
        return str(experiment_id).replace("_", "-").replace(" ", "-")

    def _resolve_topic_name(self, config, experiment_id):
        strategy = str(config.get("topic_strategy", self.STATIC_TOPIC)).upper()
        if strategy == self.EXPERIMENT_TOPIC:
            safe_id = self._sanitize_experiment_id(experiment_id)
            return f"experiment-kafka-{safe_id}"
        topic_name = config.get("topic_name")
        if not topic_name:
            raise ValueError("Kafka topic_name is required when using STATIC_TOPIC strategy")
        return topic_name

    def _build_client_kwargs(self, config):
        kwargs = {
            "bootstrap_servers": config.get("bootstrap_servers"),
            "security_protocol": config.get("security_protocol", "PLAINTEXT"),
            "request_timeout_ms": config.get("request_timeout_ms", 60000),
            "api_version_auto_timeout_ms": config.get("api_timeout_ms", 60000),
        }
        if config.get("sasl_mechanism"):
            kwargs["sasl_mechanism"] = config.get("sasl_mechanism")
        if config.get("username"):
            kwargs["sasl_plain_username"] = config.get("username")
        if config.get("password"):
            kwargs["sasl_plain_password"] = config.get("password")
        return kwargs

    def _ensure_topic(self, admin_client, topic_name, new_topic_class):
        try:
            existing_topics = admin_client.list_topics()
        except Exception:
            existing_topics = []

        if topic_name in existing_topics:
            return

        topic = new_topic_class(name=topic_name, num_partitions=1, replication_factor=1)
        try:
            admin_client.create_topics([topic])
        except Exception as exc:
            if "TopicAlreadyExists" in type(exc).__name__:
                return
            raise

    def _wait_for_topic_ready(self, admin_client, topic_name, timeout_seconds=15):
        deadline = time.time() + max(int(timeout_seconds), 1)
        while time.time() < deadline:
            try:
                if topic_name in admin_client.list_topics():
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _build_message_payload(self, experiment_id, run_index, message_size_bytes):
        payload = {
            "experiment_id": experiment_id,
            "run_index": run_index,
            "message_id": self.uuid_factory(),
            "producer_timestamp": self.time_provider(),
        }

        if message_size_bytes and message_size_bytes > 0:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            padding_size = max(message_size_bytes - len(encoded), 0)
            if padding_size > 0:
                payload["padding"] = "x" * padding_size

        return payload

    def _serialize_payload(self, payload):
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def _deserialize_payload(self, value):
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            return json.loads(value)
        return value

    def _compute_percentile(self, values, percentile):
        ordered = sorted(values)
        if len(ordered) == 1:
            return float(ordered[0])
        rank = (len(ordered) - 1) * percentile
        lower_index = int(rank)
        upper_index = min(lower_index + 1, len(ordered) - 1)
        weight = rank - lower_index
        lower = float(ordered[lower_index])
        upper = float(ordered[upper_index])
        return lower + (upper - lower) * weight

    @staticmethod
    def _is_valid_latency(value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return not math.isnan(numeric) and not math.isinf(numeric) and numeric >= 0

    def _compute_metrics(self, latencies_ms, produced_count, consumed_count, duration_seconds, topic_name, experiment_id, run_index, invalid_latency_count=0):
        if invalid_latency_count > 0:
            return {
                "kafka_benchmark": {
                    "status": "skipped",
                    "reason": f"Detected {invalid_latency_count} invalid Kafka latency samples",
                    "experiment_id": experiment_id,
                    "run_index": run_index,
                    "topic": topic_name,
                    "messages_produced": produced_count,
                    "messages_consumed": consumed_count,
                }
            }

        if not latencies_ms:
            return {
                "kafka_benchmark": {
                    "status": "skipped",
                    "reason": "No Kafka messages were consumed for this experiment run",
                    "experiment_id": experiment_id,
                    "run_index": run_index,
                    "topic": topic_name,
                    "messages_produced": produced_count,
                    "messages_consumed": consumed_count,
                }
            }

        return {
            "kafka_benchmark": {
                "status": "completed",
                "experiment_id": experiment_id,
                "run_index": run_index,
                "topic": topic_name,
                "messages_produced": produced_count,
                "messages_consumed": consumed_count,
                "average_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2),
                "min_latency_ms": round(min(latencies_ms), 2),
                "max_latency_ms": round(max(latencies_ms), 2),
                "p50_latency_ms": round(self._compute_percentile(latencies_ms, 0.50), 2),
                "p95_latency_ms": round(self._compute_percentile(latencies_ms, 0.95), 2),
                "p99_latency_ms": round(self._compute_percentile(latencies_ms, 0.99), 2),
                "throughput_messages_per_second": round(consumed_count / max(duration_seconds, 0.001), 2),
            }
        }

    def run(self, experiment_id=None, run_index=1, runtime_overrides=None):
        """Execute an optional Kafka broker benchmark and return its metrics."""
        config = self.load_config(runtime_overrides=runtime_overrides)
        bootstrap_servers = config.get("bootstrap_servers")

        if not bootstrap_servers:
            print("[WARNING] Kafka bootstrap_servers not configured - skipping Kafka benchmark")
            return {
                "kafka_benchmark": {
                    "status": "skipped",
                    "reason": "Kafka bootstrap_servers not configured",
                    "run_index": run_index,
                }
            }

        experiment_id = experiment_id or datetime.utcnow().strftime("exp-%Y%m%d-%H%M%S")

        try:
            producer_class, consumer_class, admin_client_class, new_topic_class = self._load_kafka_classes()
            topic_name = self._resolve_topic_name(config, experiment_id)
            client_kwargs = self._build_client_kwargs(config)

            admin_client = admin_client_class(**client_kwargs)
            self._ensure_topic(admin_client, topic_name, new_topic_class)
            if not self._wait_for_topic_ready(
                admin_client,
                topic_name,
                timeout_seconds=config.get("topic_ready_timeout_seconds", 15),
            ):
                raise RuntimeError(f"Kafka topic '{topic_name}' did not become ready in time")

            producer_kwargs = dict(client_kwargs)
            producer_kwargs.setdefault("acks", "all")
            producer_kwargs.setdefault("retries", 5)
            producer_kwargs.setdefault("max_block_ms", config.get("max_block_ms", 60000))
            producer = producer_class(**producer_kwargs)
            start_timestamp = self.time_provider()

            produced_count = int(config.get("message_count", 100))
            message_size_bytes = int(config.get("message_size_bytes", 0))

            for _ in range(produced_count):
                payload = self._build_message_payload(experiment_id, run_index, message_size_bytes)
                producer.send(topic_name, self._serialize_payload(payload))

            producer.flush()

            consumer_group = f"{config.get('consumer_group_prefix', 'framework-kafka-benchmark')}-{experiment_id}-{run_index}"
            consumer = consumer_class(
                topic_name,
                group_id=consumer_group,
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                consumer_timeout_ms=config.get("consumer_request_timeout_ms", 60000),
                **client_kwargs,
            )

            deadline = self.time_provider() + int(config.get("poll_timeout_seconds", 30)) * 1000
            seen_messages = set()
            latencies_ms = []
            invalid_latency_count = 0

            while len(latencies_ms) < produced_count and self.time_provider() <= deadline:
                records = consumer.poll(timeout_ms=1000)
                for _, messages in (records or {}).items():
                    for message in messages:
                        payload = self._deserialize_payload(getattr(message, "value", message))
                        if payload.get("experiment_id") != experiment_id:
                            continue
                        if payload.get("run_index") != run_index:
                            continue
                        message_id = payload.get("message_id")
                        if message_id in seen_messages:
                            continue
                        seen_messages.add(message_id)
                        consumer_receive_timestamp = self.time_provider()
                        latency_ms = consumer_receive_timestamp - payload["producer_timestamp"]
                        if not self._is_valid_latency(latency_ms):
                            invalid_latency_count += 1
                            continue
                        latencies_ms.append(float(latency_ms))

            end_timestamp = self.time_provider()
            duration_seconds = max((end_timestamp - start_timestamp) / 1000.0, 0.001)
            consumed_count = len(latencies_ms)

            close_method = getattr(consumer, "close", None)
            if callable(close_method):
                close_method()
            close_method = getattr(admin_client, "close", None)
            if callable(close_method):
                close_method()
            close_method = getattr(producer, "close", None)
            if callable(close_method):
                close_method()

            return self._compute_metrics(
                latencies_ms,
                produced_count,
                consumed_count,
                duration_seconds,
                topic_name,
                experiment_id,
                run_index,
                invalid_latency_count=invalid_latency_count,
            )
        except Exception as exc:
            print(f"[WARNING] Kafka benchmark skipped due to configuration or connectivity error: {exc}")
            return {
                "kafka_benchmark": {
                    "status": "skipped",
                    "reason": str(exc),
                    "experiment_id": experiment_id,
                    "run_index": run_index,
                }
            }

    def describe(self) -> str:
        return "KafkaMetricsCollector benchmarks Kafka broker latency and throughput."

