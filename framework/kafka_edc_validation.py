import json
import math
import os
import subprocess
import time
import uuid
from datetime import datetime
from itertools import permutations
from urllib.parse import urlparse

import requests


class KafkaDataAddressUnsupported(RuntimeError):
    """Raised when the deployed connector does not accept Kafka data addresses."""


class KafkaTransferIncomplete(RuntimeError):
    """Raised when Kafka relays some, but not all, messages produced by the suite."""

    def __init__(self, message, metrics=None):
        super().__init__(message)
        self.metrics = metrics or {}


class KafkaEdcValidationSuite:
    """Validate an end-to-end EDC + Kafka transfer flow."""

    EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/"
    KAFKA_EDC_ASSET_PREFIX = "kafka-edc-asset-"
    KAFKA_EDC_POLICY_PREFIX = "kafka-edc-policy-"
    KAFKA_EDC_CONTRACT_PREFIX = "kafka-edc-contract-"
    DEFAULT_MESSAGE_COUNT = 10
    DEFAULT_NEGOTIATION_TIMEOUT_SECONDS = 60
    DEFAULT_TRANSFER_TIMEOUT_SECONDS = 60
    DEFAULT_EDR_TIMEOUT_SECONDS = 30
    DEFAULT_POLL_INTERVAL_SECONDS = 3
    DEFAULT_CONSUMER_POLL_TIMEOUT_SECONDS = 30
    DEFAULT_STARTUP_GRACE_SECONDS = 60
    DEFAULT_PRE_RUN_SETTLE_SECONDS = 10
    DEFAULT_LOGIN_ATTEMPTS = 3
    DEFAULT_LOGIN_RETRY_SECONDS = 2
    DEFAULT_REQUEST_ATTEMPTS = 3
    DEFAULT_REQUEST_RETRY_SECONDS = 2
    DEFAULT_PAIR_ATTEMPTS = 2
    DEFAULT_PAIR_RETRY_SECONDS = 5
    DEFAULT_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS = 30
    DEFAULT_STABILIZATION_GROUP_WAIT_SECONDS = 10
    DEFAULT_STABILIZATION_PROBE_TIMEOUT_SECONDS = 30
    DEFAULT_STABILIZATION_LATE_CONFIRMATION_SECONDS = 30
    DEFAULT_TRANSFER_LATE_CONFIRMATION_SECONDS = 30
    DEFAULT_STABILIZATION_REQUEST_TIMEOUT_MS = 5000
    DEFAULT_CONTINUE_AFTER_REQUESTED_TRANSFER_TIMEOUT = True
    DEFAULT_KUBERNETES_EXEC_USE_TOPIC_OFFSETS = False
    DEFAULT_KUBERNETES_EXEC_SCAN_MAX_MESSAGES = 100

    def __init__(
        self,
        load_connector_credentials=None,
        load_deployer_config=None,
        kafka_runtime_loader=None,
        ensure_kafka_topic=None,
        kafka_manager=None,
        experiment_storage=None,
        ds_domain_resolver=None,
        ds_name_loader=None,
        admin_client_class=None,
        new_topic_class=None,
        producer_class=None,
        consumer_class=None,
        session=None,
        time_provider=None,
        uuid_factory=None,
        protocol_address_resolver=None,
        management_url_resolver=None,
        keycloak_url_resolver=None,
    ):
        self.load_connector_credentials = load_connector_credentials
        self.load_deployer_config = load_deployer_config
        self.kafka_runtime_loader = kafka_runtime_loader
        self.ensure_kafka_topic = ensure_kafka_topic
        self.kafka_manager = kafka_manager
        self.experiment_storage = experiment_storage
        self.ds_domain_resolver = ds_domain_resolver
        self.ds_name_loader = ds_name_loader
        self.admin_client_class = admin_client_class
        self.new_topic_class = new_topic_class
        self.producer_class = producer_class
        self.consumer_class = consumer_class
        self.session = session
        self.time_provider = time_provider or self._default_time_provider
        self.uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))
        self.protocol_address_resolver = protocol_address_resolver
        self.management_url_resolver = management_url_resolver
        self.keycloak_url_resolver = keycloak_url_resolver

    @staticmethod
    def _default_time_provider():
        return time.perf_counter_ns() / 1_000_000.0

    def _require_dependency(self, dependency, name):
        if dependency is None:
            raise RuntimeError(f"KafkaEdcValidationSuite requires dependency: {name}")
        return dependency

    def _load_deployer_values(self):
        loader = self._require_dependency(self.load_deployer_config, "load_deployer_config")
        values = loader() or {}
        if not isinstance(values, dict):
            return {}
        return values

    def _load_kafka_runtime(self):
        runtime = {}
        if callable(self.kafka_runtime_loader):
            loaded = self.kafka_runtime_loader() or {}
            if isinstance(loaded, dict):
                runtime.update(loaded)

        deployer = self._load_deployer_values()
        optional_mapping = {
            "message_count": "KAFKA_EDC_MESSAGE_COUNT",
            "negotiation_timeout_seconds": "KAFKA_EDC_NEGOTIATION_TIMEOUT_SECONDS",
            "transfer_timeout_seconds": "KAFKA_EDC_TRANSFER_TIMEOUT_SECONDS",
            "edr_timeout_seconds": "KAFKA_EDC_EDR_TIMEOUT_SECONDS",
            "poll_interval_seconds": "KAFKA_EDC_POLL_INTERVAL_SECONDS",
            "consumer_poll_timeout_seconds": "KAFKA_EDC_CONSUMER_POLL_TIMEOUT_SECONDS",
            "consumer_group_prefix": "KAFKA_EDC_CONSUMER_GROUP_PREFIX",
            "cluster_bootstrap_servers": "KAFKA_CLUSTER_BOOTSTRAP_SERVERS",
            "startup_grace_seconds": "KAFKA_EDC_STARTUP_GRACE_SECONDS",
            "pre_run_settle_seconds": "KAFKA_EDC_PRE_RUN_SETTLE_SECONDS",
            "agreement_visibility_timeout_seconds": "KAFKA_EDC_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS",
            "message_sample_limit": "KAFKA_EDC_MESSAGE_SAMPLE_LIMIT",
            "late_transfer_confirmation_seconds": "KAFKA_EDC_LATE_TRANSFER_CONFIRMATION_SECONDS",
            "late_probe_confirmation_seconds": "KAFKA_EDC_LATE_PROBE_CONFIRMATION_SECONDS",
            "stabilization_group_wait_seconds": "KAFKA_EDC_STABILIZATION_GROUP_WAIT_SECONDS",
            "stabilization_probe_timeout_seconds": "KAFKA_EDC_STABILIZATION_PROBE_TIMEOUT_SECONDS",
            "kubernetes_exec_timeout_seconds": "KAFKA_EDC_KUBERNETES_EXEC_TIMEOUT_SECONDS",
            "kubernetes_exec_use_topic_offsets": "KAFKA_EDC_KUBERNETES_EXEC_USE_TOPIC_OFFSETS",
            "kubernetes_exec_scan_max_messages": "KAFKA_EDC_KUBERNETES_EXEC_SCAN_MAX_MESSAGES",
            "pair_attempts": "KAFKA_EDC_PAIR_ATTEMPTS",
            "pair_retry_seconds": "KAFKA_EDC_PAIR_RETRY_SECONDS",
            "validation_backend": "KAFKA_EDC_VALIDATION_BACKEND",
            "continue_after_requested_transfer_timeout": "KAFKA_EDC_CONTINUE_AFTER_REQUESTED_TRANSFER_TIMEOUT",
        }
        for key, config_key in optional_mapping.items():
            value = deployer.get(config_key)
            if value not in (None, ""):
                runtime[key] = value

        runtime.setdefault("message_count", self.DEFAULT_MESSAGE_COUNT)
        runtime.setdefault("negotiation_timeout_seconds", self.DEFAULT_NEGOTIATION_TIMEOUT_SECONDS)
        runtime.setdefault("transfer_timeout_seconds", self.DEFAULT_TRANSFER_TIMEOUT_SECONDS)
        runtime.setdefault("edr_timeout_seconds", self.DEFAULT_EDR_TIMEOUT_SECONDS)
        runtime.setdefault("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS)
        runtime.setdefault("consumer_poll_timeout_seconds", self.DEFAULT_CONSUMER_POLL_TIMEOUT_SECONDS)
        runtime.setdefault("consumer_group_prefix", "framework-edc-kafka")
        runtime.setdefault("startup_grace_seconds", self.DEFAULT_STARTUP_GRACE_SECONDS)
        runtime.setdefault("pre_run_settle_seconds", self.DEFAULT_PRE_RUN_SETTLE_SECONDS)
        runtime.setdefault(
            "continue_after_requested_transfer_timeout",
            self.DEFAULT_CONTINUE_AFTER_REQUESTED_TRANSFER_TIMEOUT,
        )
        runtime.setdefault(
            "agreement_visibility_timeout_seconds",
            self.DEFAULT_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS,
        )

        for integer_key in (
            "message_count",
            "negotiation_timeout_seconds",
            "transfer_timeout_seconds",
            "edr_timeout_seconds",
            "poll_interval_seconds",
            "consumer_poll_timeout_seconds",
            "startup_grace_seconds",
            "pre_run_settle_seconds",
            "agreement_visibility_timeout_seconds",
            "request_timeout_ms",
            "api_timeout_ms",
            "max_block_ms",
            "consumer_request_timeout_ms",
            "message_sample_limit",
            "late_transfer_confirmation_seconds",
            "late_probe_confirmation_seconds",
            "stabilization_group_wait_seconds",
            "stabilization_probe_timeout_seconds",
            "kubernetes_exec_timeout_seconds",
            "kubernetes_exec_scan_max_messages",
            "pair_attempts",
            "pair_retry_seconds",
        ):
            raw = runtime.get(integer_key)
            if raw in (None, ""):
                continue
            try:
                runtime[integer_key] = int(raw)
            except (TypeError, ValueError):
                pass
        return runtime

    @staticmethod
    def _runtime_int(runtime, key, default, minimum=0):
        raw = (runtime or {}).get(key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = int(default)
        return max(value, minimum)

    @staticmethod
    def _normalize_bootstrap_servers(bootstrap_servers):
        if bootstrap_servers is None:
            return []
        if isinstance(bootstrap_servers, (list, tuple, set)):
            values = bootstrap_servers
        else:
            values = str(bootstrap_servers).split(",")
        return [value.strip() for value in values if str(value).strip()]

    @staticmethod
    def _split_host_port(address):
        raw = str(address or "").strip()
        if not raw:
            return "", ""
        if "://" in raw:
            raw = raw.split("://", 1)[1]
        if raw.startswith("[") and "]:" in raw:
            host, _, port = raw.rpartition(":")
            return host.strip("[]"), port
        if raw.count(":") >= 1:
            host, port = raw.rsplit(":", 1)
            return host, port
        return raw, ""

    @classmethod
    def _derive_cluster_bootstrap_servers(cls, bootstrap_servers):
        derived = []
        for candidate in cls._normalize_bootstrap_servers(bootstrap_servers):
            host, port = cls._split_host_port(candidate)
            normalized_host = host.strip().lower()
            if normalized_host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
                for alias in ("host.minikube.internal", "host.docker.internal"):
                    value = f"{alias}:{port}" if port else alias
                    if value not in derived:
                        derived.append(value)
            elif candidate not in derived:
                derived.append(candidate)
        return ",".join(derived)

    def _ds_domain(self):
        resolver = self._require_dependency(self.ds_domain_resolver, "ds_domain_resolver")
        return resolver()

    def _dataspace_name(self):
        if callable(self.ds_name_loader):
            return self.ds_name_loader()
        return self.ds_name_loader or "demo"

    @staticmethod
    def _keycloak_base_url(config):
        keycloak_url = (
            config.get("KEYCLOAK_FRONTEND_URL")
            or config.get("KEYCLOAK_PUBLIC_URL")
            or config.get("KC_INTERNAL_URL")
            or config.get("KC_URL")
            or ""
        )
        keycloak_url = str(keycloak_url).strip()
        if keycloak_url and not keycloak_url.startswith(("http://", "https://")):
            keycloak_url = f"http://{keycloak_url}"
        return keycloak_url.rstrip("/")

    def _keycloak_realm_url(self, keycloak_url):
        base_url = self._keycloak_base_url({"KEYCLOAK_FRONTEND_URL": keycloak_url})
        dataspace = str(self._dataspace_name() or "").strip().strip("/")
        if not base_url or not dataspace:
            return base_url
        realm_suffix = f"/realms/{dataspace}"
        if base_url.endswith(realm_suffix):
            return base_url
        return f"{base_url}{realm_suffix}"

    def _login(self, connector, role_key):
        config = self._load_deployer_values()
        creds_loader = self._require_dependency(self.load_connector_credentials, "load_connector_credentials")
        connector_creds = creds_loader(connector) or {}
        connector_user = connector_creds.get("connector_user") or {}

        username = connector_user.get("user")
        password = connector_user.get("passwd")
        if not username or not password:
            raise RuntimeError(f"Missing connector_user credentials for {connector}")

        keycloak_url = ""
        resolver = self.keycloak_url_resolver
        if callable(resolver):
            keycloak_url = str(resolver() or "").strip()
        if not keycloak_url:
            keycloak_url = self._keycloak_base_url(config)
        if not keycloak_url:
            raise RuntimeError("Missing Keycloak URL in deployer.config")

        login_url = f"{self._keycloak_realm_url(keycloak_url)}/protocol/openid-connect/token"
        payload = {
            "grant_type": "password",
            "client_id": "dataspace-users",
            "username": username,
            "password": password,
            "scope": "openid profile email",
        }
        attempts = self.DEFAULT_LOGIN_ATTEMPTS
        retry_seconds = self.DEFAULT_LOGIN_RETRY_SECONDS
        last_exc = None

        for attempt in range(1, attempts + 1):
            try:
                response = self._session().post(
                    login_url,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data=payload,
                    timeout=20,
                )
                self._assert_status(response, {200}, f"{role_key} login")
                body = response.json()
                token = body.get("access_token")
                if not token:
                    raise RuntimeError(f"{role_key} login did not return access_token")
                return token
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    raise
                time.sleep(retry_seconds)

        raise last_exc or RuntimeError(f"{role_key} login failed unexpectedly")

    def _session(self):
        return self.session or requests.Session()

    @staticmethod
    def _read_field(obj, field_name):
        if not isinstance(obj, dict):
            return None
        namespaced = f"https://w3id.org/edc/v0.0.1/ns/{field_name}"
        if field_name in obj:
            return obj[field_name]
        if namespaced in obj:
            return obj[namespaced]
        properties = obj.get("properties")
        if isinstance(properties, dict):
            if field_name in properties:
                return properties[field_name]
            if namespaced in properties:
                return properties[namespaced]
        return None

    @staticmethod
    def _assert_status(response, expected_codes, label):
        if response.status_code not in set(expected_codes):
            raise RuntimeError(
                f"{label} failed with HTTP {response.status_code}: {response.text[:500]}"
            )

    @staticmethod
    def _is_transient_http_response(response):
        return getattr(response, "status_code", None) in {502, 503, 504}

    def _request_with_retry(self, method, url, *, label, accepted_statuses=None, headers=None, json_payload=None, data=None):
        attempts = max(int(self.DEFAULT_REQUEST_ATTEMPTS), 1)
        retry_seconds = max(int(self.DEFAULT_REQUEST_RETRY_SECONDS), 1)
        session = self._session()
        last_exc = None

        for attempt in range(1, attempts + 1):
            try:
                request_fn = getattr(session, method)
                kwargs = {
                    "headers": headers,
                    "timeout": 30,
                }
                if json_payload is not None:
                    kwargs["json"] = json_payload
                if data is not None:
                    kwargs["data"] = data
                response = request_fn(url, **kwargs)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt >= attempts:
                    raise
                time.sleep(retry_seconds)
                continue

            if accepted_statuses and response.status_code in set(accepted_statuses):
                return response
            if self._is_transient_http_response(response) and attempt < attempts:
                time.sleep(retry_seconds)
                continue
            return response

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{label} did not produce a response")

    def _management_url(self, connector, path):
        resolver = self.management_url_resolver
        if callable(resolver):
            resolved = str(resolver(connector, path) or "").strip()
            if resolved:
                return resolved
        credential_url = self._management_url_from_credentials(connector, path)
        if credential_url:
            return credential_url
        return f"http://{connector}.{self._ds_domain()}{path}"

    def _management_url_from_credentials(self, connector, path):
        creds_loader = self.load_connector_credentials
        if not callable(creds_loader):
            return ""
        try:
            connector_creds = creds_loader(connector) or {}
        except Exception:
            return ""
        if not isinstance(connector_creds, dict):
            return ""

        for section_name in ("public_access_urls", "access_urls"):
            urls = connector_creds.get(section_name)
            if not isinstance(urls, dict):
                continue
            base_url = str(
                urls.get("connector_management_api")
                or urls.get("connector_ingress")
                or ""
            ).strip()
            if base_url:
                return self._join_management_base_url(base_url, path)
        return ""

    @staticmethod
    def _join_management_base_url(base_url, path):
        base = str(base_url or "").strip().rstrip("/")
        suffix = str(path or "").strip()
        if not base:
            return ""
        if not suffix:
            return base
        parsed_path = urlparse(base).path.rstrip("/")
        if parsed_path.endswith("/management") and suffix.startswith("/management/"):
            suffix = suffix[len("/management"):]
        return f"{base}/{suffix.lstrip('/')}"

    def _protocol_address(self, connector):
        resolver = self.protocol_address_resolver
        if callable(resolver):
            resolved = str(resolver(connector) or "").strip()
            if resolved:
                return resolved
        return f"http://{connector}:19194/protocol"

    def _post_json(self, url, token, payload, label):
        response = self._request_with_retry(
            "post",
            url,
            label=label,
            accepted_statuses={200, 201},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json_payload=payload,
        )
        self._assert_status(response, {200, 201}, label)
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    @staticmethod
    def _json_ld_value(value):
        return [{"@value": value}]

    @classmethod
    def _expanded_kafka_address(cls, topic, bootstrap_servers):
        return {
            f"{cls.EDC_NAMESPACE}type": cls._json_ld_value("Kafka"),
            f"{cls.EDC_NAMESPACE}topic": cls._json_ld_value(topic),
            f"{cls.EDC_NAMESPACE}kafka.bootstrap.servers": cls._json_ld_value(bootstrap_servers),
        }

    @staticmethod
    def _response_text(response):
        return str(getattr(response, "text", "") or "")

    @classmethod
    def _is_kafka_dataaddress_type_validation_failure(cls, response):
        if getattr(response, "status_code", None) != 400:
            return False
        body = cls._response_text(response)
        return (
            f"{cls.EDC_NAMESPACE}type" in body
            and (
                "field is not valid" in body
                or "missing or invalid" in body
                or "mandatory value" in body
            )
        )

    def _post_kafka_payload_with_expanded_fallback(
        self,
        url,
        token,
        payload,
        expanded_payload,
        label,
    ):
        response = self._request_with_retry(
            "post",
            url,
            label=label,
            accepted_statuses={200, 201, 400},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json_payload=payload,
        )
        if self._is_kafka_dataaddress_type_validation_failure(response):
            response = self._request_with_retry(
                "post",
                url,
                label=f"{label} expanded JSON-LD fallback",
                accepted_statuses={200, 201, 400},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json_payload=expanded_payload,
            )
            if self._is_kafka_dataaddress_type_validation_failure(response):
                raise KafkaDataAddressUnsupported(
                    f"{label} is not supported by the deployed connector runtime: {self._response_text(response)}"
                )

        self._assert_status(response, {200, 201}, label)
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    def _post_json_optional_body(self, url, token, payload, label, accepted_statuses=None):
        response = self._request_with_retry(
            "post",
            url,
            label=label,
            accepted_statuses=set(accepted_statuses or {200, 201, 204}),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json_payload=payload,
        )
        self._assert_status(response, set(accepted_statuses or {200, 201, 204}), label)
        if response.status_code == 204:
            return None, response.status_code
        text = getattr(response, "text", "") or ""
        if not text.strip():
            return None, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    def _get_json(self, url, token, label, accepted_statuses=None):
        accepted_statuses = set(accepted_statuses or {200})
        response = self._request_with_retry(
            "get",
            url,
            label=label,
            accepted_statuses=accepted_statuses,
            headers={
                "Authorization": f"Bearer {token}",
            },
        )
        self._assert_status(response, accepted_statuses, label)
        if response.status_code == 204:
            return None, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    def _get_optional_json(self, url, token, label, accepted_statuses=None):
        accepted_statuses = set(accepted_statuses or {200, 404})
        response = self._request_with_retry(
            "get",
            url,
            label=label,
            accepted_statuses=accepted_statuses,
            headers={
                "Authorization": f"Bearer {token}",
            },
        )
        self._assert_status(response, accepted_statuses, label)
        if response.status_code in {204, 404}:
            return None, response.status_code
        text = getattr(response, "text", "") or ""
        if not text.strip():
            return None, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    def _delete(self, url, token, label, accepted_statuses=None):
        accepted_statuses = set(accepted_statuses or {200, 204, 404, 409})
        response = self._request_with_retry(
            "delete",
            url,
            label=label,
            accepted_statuses=accepted_statuses,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        self._assert_status(response, accepted_statuses, label)
        return response.status_code

    def _ensure_kafka_runtime(self, runtime):
        bootstrap_servers = runtime.get("bootstrap_servers")
        kafka_manager = self.kafka_manager
        if kafka_manager is not None:
            resolved = kafka_manager.ensure_kafka_running()
            if resolved:
                runtime["bootstrap_servers"] = resolved
                bootstrap_servers = resolved

        if not bootstrap_servers:
            kafka_error = getattr(kafka_manager, "last_error", None) if kafka_manager is not None else None
            if kafka_error:
                raise RuntimeError(
                    "Kafka bootstrap_servers not configured for Kafka transfer validation. "
                    f"Last runtime preparation error: {kafka_error}"
                )
            raise RuntimeError("Kafka bootstrap_servers not configured for Kafka transfer validation")

        runtime["host_bootstrap_servers"] = bootstrap_servers
        cluster_bootstrap_servers = runtime.get("cluster_bootstrap_servers")
        if not cluster_bootstrap_servers and kafka_manager is not None:
            cluster_bootstrap_servers = getattr(kafka_manager, "cluster_bootstrap_servers", None)
        if not cluster_bootstrap_servers:
            cluster_bootstrap_servers = self._derive_cluster_bootstrap_servers(bootstrap_servers)
            runtime["cluster_bootstrap_servers"] = cluster_bootstrap_servers
        else:
            runtime["cluster_bootstrap_servers"] = cluster_bootstrap_servers

        return runtime

    def _load_kafka_admin_classes(self):
        if self.admin_client_class is not None and self.new_topic_class is not None:
            return self.admin_client_class, self.new_topic_class
        try:
            from kafka.admin import KafkaAdminClient, NewTopic

            return KafkaAdminClient, NewTopic
        except Exception as exc:
            raise RuntimeError(f"Kafka client library not available for Kafka transfer validation: {exc}") from exc

    @staticmethod
    def _build_kafka_client_kwargs(runtime):
        kwargs = {
            "bootstrap_servers": runtime.get("host_bootstrap_servers") or runtime.get("bootstrap_servers"),
            "security_protocol": runtime.get("security_protocol", "PLAINTEXT"),
            "request_timeout_ms": runtime.get("request_timeout_ms", 60000),
            "api_version_auto_timeout_ms": runtime.get("api_timeout_ms", 60000),
        }
        if runtime.get("sasl_mechanism"):
            kwargs["sasl_mechanism"] = runtime.get("sasl_mechanism")
        if runtime.get("username"):
            kwargs["sasl_plain_username"] = runtime.get("username")
        if runtime.get("password"):
            kwargs["sasl_plain_password"] = runtime.get("password")
        return kwargs

    @staticmethod
    def _wait_for_topic_ready(admin_client, topic_name, timeout_seconds=15):
        deadline = time.time() + max(int(timeout_seconds), 1)
        while time.time() < deadline:
            try:
                if topic_name in admin_client.list_topics():
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _refresh_kafka_runtime(self, runtime, *, restart=False):
        kafka_manager = self.kafka_manager
        if kafka_manager is None:
            return False

        if restart:
            stop_method = getattr(kafka_manager, "stop_kafka", None)
            if callable(stop_method):
                stop_method()

        resolved_bootstrap = kafka_manager.ensure_kafka_running()
        if not resolved_bootstrap:
            return False

        runtime["bootstrap_servers"] = resolved_bootstrap
        runtime["host_bootstrap_servers"] = resolved_bootstrap
        cluster_bootstrap = getattr(kafka_manager, "cluster_bootstrap_servers", None)
        if cluster_bootstrap:
            runtime["cluster_bootstrap_servers"] = cluster_bootstrap
        return True

    @staticmethod
    def _truthy(value):
        return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}

    def _use_kubernetes_exec_topic_offsets(self, runtime):
        raw = (runtime or {}).get("kubernetes_exec_use_topic_offsets")
        if raw in (None, ""):
            return self.DEFAULT_KUBERNETES_EXEC_USE_TOPIC_OFFSETS
        return self._truthy(raw)

    def _kubernetes_consumer_start_offset(self, runtime, topic_name):
        if not self._use_kubernetes_exec_topic_offsets(runtime):
            return None
        return self._kubernetes_topic_end_offset(runtime, topic_name)

    def _kubernetes_exec_consume_window(self, runtime, message_count, probe_result=None, offset=None):
        if offset is not None:
            return max(1, int(message_count))
        probe_attempts = 0
        if isinstance(probe_result, dict):
            try:
                probe_attempts = int(probe_result.get("attempts") or 0)
            except (TypeError, ValueError):
                probe_attempts = 0
        configured = self._runtime_int(
            runtime,
            "kubernetes_exec_scan_max_messages",
            self.DEFAULT_KUBERNETES_EXEC_SCAN_MAX_MESSAGES,
            minimum=1,
        )
        # Without explicit offsets, kafka-console-consumer starts at the beginning on every
        # invocation. The destination topic may already contain stabilization probes, so the
        # scan window must be wider than the transfer payload count.
        return max(configured, int(message_count) + probe_attempts + 5)

    @staticmethod
    def _command_to_text(command):
        if isinstance(command, (list, tuple)):
            return " ".join(str(item) for item in command)
        return str(command or "").strip()

    def _kubernetes_command_failure_message(self, result, label):
        returncode = getattr(result, "returncode", "unknown")
        stderr = (getattr(result, "stderr", "") or "").strip()
        stdout = (getattr(result, "stdout", "") or "").strip()
        command = getattr(result, "_pionera_command", None) or getattr(result, "args", None)
        details = stderr or stdout
        message = f"{label} failed with exit code {returncode}"
        if details:
            message = f"{message}: {details}"
        command_text = self._command_to_text(command)
        if command_text:
            message = f"{message}. Command: {command_text}"
        return message

    def _can_hard_restart_kafka_runtime(self, runtime=None):
        kafka_manager = self.kafka_manager
        if kafka_manager is None:
            return False

        runtime = runtime if isinstance(runtime, dict) else {}
        explicit_flag = runtime.get("allow_hard_restart_on_topic_failure")
        if explicit_flag not in (None, ""):
            return self._truthy(explicit_flag)

        if bool(getattr(kafka_manager, "started_by_framework", False)):
            if str(getattr(kafka_manager, "provisioning_mode", "") or "").strip().lower().startswith("kubernetes"):
                # Do not recycle a framework-managed in-cluster broker during validation by default:
                # a hard restart drops ephemeral topics and destabilizes the running transfer flow.
                return False
            return True

        provisioning_mode = str(getattr(kafka_manager, "provisioning_mode", "") or "").strip().lower()
        return False

    def _ensure_topic_via_runtime_manager(self, runtime, topic_name):
        kafka_manager = self.kafka_manager
        ensure_topic = getattr(kafka_manager, "ensure_topic", None) if kafka_manager is not None else None
        if not callable(ensure_topic):
            return False

        try:
            ensured = bool(ensure_topic(topic_name, partitions=1, replication_factor=1))
        except Exception:
            return False

        if ensured:
            runtime["_last_topic_ensure_method"] = "runtime_manager"
        return ensured

    @staticmethod
    def _use_kubernetes_exec_backend(runtime):
        backend = str((runtime or {}).get("validation_backend") or "").strip().lower()
        if backend not in {"kubernetes-exec", "k8s-exec"}:
            return False
        provisioner = str((runtime or {}).get("provisioner") or "").strip().lower()
        return provisioner.startswith("kubernetes")

    @staticmethod
    def _kubernetes_exec_ids(runtime):
        namespace = str((runtime or {}).get("k8s_namespace") or "demo").strip() or "demo"
        service_name = str((runtime or {}).get("k8s_service_name") or "framework-kafka").strip() or "framework-kafka"
        return namespace, service_name

    def _run_kubernetes_kafka_command(self, runtime, kafka_args, input_text=None, timeout_seconds=None):
        namespace, deployment_name = self._kubernetes_exec_ids(runtime)
        command = [
            "kubectl",
            "exec",
            "-n",
            namespace,
        ]
        if input_text is not None:
            command.append("-i")
        command.extend([
            f"deployment/{deployment_name}",
            "--",
            *list(kafka_args),
        ])
        kafka_manager = self.kafka_manager
        runner = getattr(kafka_manager, "command_runner", None) if kafka_manager is not None else None
        if timeout_seconds is None:
            timeout_seconds = int((runtime or {}).get("kubernetes_exec_timeout_seconds", 30))
        command_env = None
        if kafka_manager is not None:
            env_loader = getattr(kafka_manager, "_command_environment", None)
            if callable(env_loader):
                command_env = env_loader()
        result = None
        if callable(runner):
            try:
                result = runner(command, input_text=input_text, timeout=timeout_seconds, env=command_env)
            except TypeError:
                try:
                    result = runner(command, input_text=input_text, timeout=timeout_seconds)
                except TypeError:
                    result = runner(command, input_text=input_text)
            except subprocess.TimeoutExpired as exc:
                result = subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr=exc.stderr or "Command timed out")
            try:
                setattr(result, "_pionera_command", command)
            except Exception:
                pass
            return result
        try:
            result = subprocess.run(
                command,
                text=True,
                input=input_text,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
                env=command_env,
            )
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr=exc.stderr or "Command timed out")
        try:
            setattr(result, "_pionera_command", command)
        except Exception:
            pass
        return result

    def _ensure_topic_with_kubernetes_exec(self, runtime, topic_name):
        list_result = self._run_kubernetes_kafka_command(
            runtime,
            ["kafka-topics", "--bootstrap-server", "localhost:9092", "--list"],
        )
        if getattr(list_result, "returncode", 1) != 0:
            raise RuntimeError(self._kubernetes_command_failure_message(list_result, "Kafka topic list"))
        existing_topics = set((getattr(list_result, "stdout", "") or "").splitlines())
        if topic_name not in existing_topics:
            create_result = self._run_kubernetes_kafka_command(
                runtime,
                [
                    "kafka-topics",
                    "--bootstrap-server",
                    "localhost:9092",
                    "--create",
                    "--if-not-exists",
                    "--topic",
                    topic_name,
                    "--partitions",
                    "1",
                    "--replication-factor",
                    "1",
                ],
            )
            if getattr(create_result, "returncode", 1) != 0:
                raise RuntimeError(self._kubernetes_command_failure_message(create_result, "Kafka topic create"))

        verify_result = self._run_kubernetes_kafka_command(
            runtime,
            ["kafka-topics", "--bootstrap-server", "localhost:9092", "--list"],
        )
        if getattr(verify_result, "returncode", 1) != 0:
            raise RuntimeError(self._kubernetes_command_failure_message(verify_result, "Kafka topic verify"))
        verified_topics = set((getattr(verify_result, "stdout", "") or "").splitlines())
        if topic_name not in verified_topics:
            raise RuntimeError(f"Kafka topic '{topic_name}' could not be created or verified")
        runtime["_last_topic_ensure_method"] = "kubernetes_exec"
        return True

    def _kubernetes_topic_end_offset(self, runtime, topic_name):
        result = self._run_kubernetes_kafka_command(
            runtime,
            [
                "kafka-run-class",
                "kafka.tools.GetOffsetShell",
                "--broker-list",
                "localhost:9092",
                "--topic",
                topic_name,
                "--time",
                "-1",
            ],
        )
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError(self._kubernetes_command_failure_message(result, "Kafka offset lookup"))
        for line in (getattr(result, "stdout", "") or "").splitlines():
            parts = line.strip().split(":")
            if len(parts) >= 3 and parts[0] == topic_name and parts[1] == "0":
                try:
                    return int(parts[2])
                except (TypeError, ValueError):
                    continue
        return 0

    def _ensure_topic_with_runtime(self, runtime, topic_name):
        if self._use_kubernetes_exec_backend(runtime):
            last_kubernetes_exc = None
            for attempt in (1, 2, 3):
                try:
                    if self._ensure_topic_with_kubernetes_exec(runtime, topic_name):
                        return True
                except Exception as exc:
                    last_kubernetes_exc = exc
                    if attempt < 3:
                        time.sleep(3)
                        continue
            if last_kubernetes_exc is not None:
                runtime["_last_kubernetes_topic_error"] = str(last_kubernetes_exc)

        admin_client_class, new_topic_class = self._load_kafka_admin_classes()
        last_exc = None
        hard_restart_attempted = False

        for attempt in (1, 2, 3):
            admin_client = None
            try:
                admin_client = admin_client_class(**self._build_kafka_client_kwargs(runtime))

                try:
                    existing_topics = admin_client.list_topics()
                except Exception:
                    existing_topics = []

                if topic_name not in existing_topics:
                    topic = new_topic_class(name=topic_name, num_partitions=1, replication_factor=1)
                    try:
                        admin_client.create_topics([topic])
                    except Exception as exc:
                        if "TopicAlreadyExists" not in type(exc).__name__:
                            raise

                if not self._wait_for_topic_ready(
                    admin_client,
                    topic_name,
                    timeout_seconds=runtime.get("topic_ready_timeout_seconds", 15),
                ):
                    raise RuntimeError(f"Kafka topic '{topic_name}' could not be created or verified")
                runtime["_last_topic_ensure_method"] = "runtime_admin"
                return True
            except Exception as exc:
                last_exc = exc
                if self._ensure_topic_via_runtime_manager(runtime, topic_name):
                    return True
                if attempt == 1 and self._refresh_kafka_runtime(runtime, restart=False):
                    continue

                if not hard_restart_attempted and self._can_hard_restart_kafka_runtime(runtime):
                    hard_restart_attempted = True
                    if self._refresh_kafka_runtime(runtime, restart=True):
                        continue
                raise
            finally:
                close_method = getattr(admin_client, "close", None) if admin_client is not None else None
                if callable(close_method):
                    try:
                        close_method()
                    except Exception:
                        pass

        raise last_exc or RuntimeError(f"Kafka topic '{topic_name}' could not be created or verified")

    def _topic_name(self, runtime):
        base_name = str(runtime.get("topic_name") or "edc-kafka-topic").strip() or "edc-kafka-topic"
        suffix = str(self.uuid_factory()).replace("_", "-").lower()
        return f"{base_name}-{suffix[:12]}"

    @staticmethod
    def _destination_topic_name(source_topic):
        return f"{source_topic}-sink"

    def _create_asset(self, provider, provider_jwt, source_topic, runtime, suffix):
        asset_id = f"kafka-edc-asset-{suffix}"
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
                "dct": "http://purl.org/dc/terms/",
                "dcat": "http://www.w3.org/ns/dcat#",
            },
            "@id": asset_id,
            "@type": "Asset",
            "properties": {
                "name": f"Kafka Transfer Asset {suffix}",
                "version": "1.0.0",
                "shortDescription": "Kafka topic asset for EDC validation",
                "assetType": "dataset",
                "dct:description": "Kafka topic asset for end-to-end EDC validation",
                "dcat:keyword": ["validation", "edc", "kafka"],
            },
            "dataAddress": {
                "type": "Kafka",
                "topic": source_topic,
                "kafka.bootstrap.servers": runtime["cluster_bootstrap_servers"],
            },
        }
        expanded_payload = {
            **payload,
            "dataAddress": self._expanded_kafka_address(
                source_topic,
                runtime["cluster_bootstrap_servers"],
            ),
        }
        body, status_code = self._post_kafka_payload_with_expanded_fallback(
            self._management_url(provider, "/management/v3/assets"),
            provider_jwt,
            payload,
            expanded_payload,
            "provider Kafka asset creation",
        )
        return asset_id, body.get("@id") or body.get("id") or asset_id, status_code

    def _create_policy(self, provider, provider_jwt, suffix):
        policy_id = f"kafka-edc-policy-{suffix}"
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
                "odrl": "http://www.w3.org/ns/odrl/2/",
            },
            "@id": policy_id,
            "policy": {
                "@context": "http://www.w3.org/ns/odrl.jsonld",
                "@type": "Set",
                "permission": [],
                "prohibition": [],
                "obligation": [],
            },
        }
        body, status_code = self._post_json(
            self._management_url(provider, "/management/v3/policydefinitions"),
            provider_jwt,
            payload,
            "provider policy creation",
        )
        return policy_id, body.get("@id") or body.get("id") or policy_id, status_code

    def _create_contract_definition(self, provider, provider_jwt, asset_id, policy_id, suffix):
        contract_definition_id = f"kafka-edc-contract-{suffix}"
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
            },
            "@id": contract_definition_id,
            "accessPolicyId": policy_id,
            "contractPolicyId": policy_id,
            "assetsSelector": [
                {
                    "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                    "operator": "=",
                    "operandRight": asset_id,
                }
            ],
        }
        body, status_code = self._post_json(
            self._management_url(provider, "/management/v3/contractdefinitions"),
            provider_jwt,
            payload,
            "provider contract definition creation",
        )
        return contract_definition_id, body.get("@id") or body.get("id") or contract_definition_id, status_code

    def _request_catalog(self, provider, consumer, consumer_jwt):
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
            },
            "@type": "CatalogRequest",
            "counterPartyAddress": self._protocol_address(provider),
            "counterPartyId": provider,
            "protocol": "dataspace-protocol-http",
            "querySpec": {
                "offset": 0,
                "limit": 500,
                "filterExpression": [],
            },
        }
        return self._post_json(
            self._management_url(consumer, "/management/v3/catalog/request"),
            consumer_jwt,
            payload,
            "consumer catalog request",
        )

    @staticmethod
    def _select_catalog_dataset(catalog_body, expected_asset_id, fallback_connector):
        catalog = catalog_body[0] if isinstance(catalog_body, list) and catalog_body else catalog_body
        if not isinstance(catalog, dict):
            raise RuntimeError("Catalog response is empty or invalid")

        datasets = catalog.get("dcat:dataset")
        if not datasets:
            raise RuntimeError("Catalog response does not contain dcat:dataset")
        if not isinstance(datasets, list):
            datasets = [datasets]

        dataset = next(
            (item for item in datasets if item and expected_asset_id in json.dumps(item, ensure_ascii=False)),
            None,
        )
        if dataset is None:
            raise RuntimeError(f"Catalog does not contain asset {expected_asset_id}")

        policy = dataset.get("odrl:hasPolicy")
        if isinstance(policy, list):
            policy = policy[0] if policy else None
        offer_id = policy.get("@id") if isinstance(policy, dict) else None
        if not offer_id:
            raise RuntimeError("Catalog dataset does not expose offer policy id")

        participant_id = catalog.get("dspace:participantId") or fallback_connector
        return {
            "catalog_asset_id": dataset.get("@id") or expected_asset_id,
            "offer_id": offer_id,
            "provider_participant_id": participant_id,
            "dataset": dataset,
            "catalog": catalog,
        }

    @staticmethod
    def _extract_identifier(item):
        if not isinstance(item, dict):
            return None
        return item.get("@id") or item.get("id")

    def _query_collection(self, connector, token, path, label, limit=200):
        body, _ = self._post_json(
            self._management_url(connector, path),
            token,
            {
                "@context": {
                    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
                },
                "offset": 0,
                "limit": limit,
            },
            label,
        )
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            return [body]
        return []

    def _terminate_transfer_process(self, connector, token, transfer_id, reason):
        _, status_code = self._post_json_optional_body(
            self._management_url(connector, f"/management/v3/transferprocesses/{transfer_id}/terminate"),
            token,
            {
                "@context": {
                    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
                },
                "@type": "TerminateTransfer",
                "reason": reason,
            },
            "Kafka transfer termination",
            accepted_statuses={204, 404, 409},
        )
        return status_code

    def _deprovision_transfer_process(self, connector, token, transfer_id):
        _, status_code = self._post_json_optional_body(
            self._management_url(connector, f"/management/v3/transferprocesses/{transfer_id}/deprovision"),
            token,
            None,
            "Kafka transfer deprovision",
            accepted_statuses={204, 404, 409},
        )
        return status_code

    def _wait_for_transfer_cleanup(self, connector, token, transfer_id, timeout_seconds=20):
        deadline = time.time() + max(int(timeout_seconds), 1)
        last_state = None
        terminal_states = {"TERMINATED", "DEPROVISIONED", "ENDED", "COMPLETED", "FINALIZED"}

        while time.time() <= deadline:
            body, status_code = self._get_json(
                self._management_url(connector, f"/management/v3/transferprocesses/{transfer_id}/state"),
                token,
                "Kafka transfer cleanup state lookup",
                accepted_statuses={200, 404},
            )
            if status_code == 404:
                return {"state": "NOT_FOUND", "status_code": 404}
            if isinstance(body, dict):
                last_state = body.get("state")
                if last_state in terminal_states:
                    return {"state": last_state, "status_code": status_code}
            time.sleep(1)

        return {"state": last_state or "UNKNOWN", "status_code": 200, "timed_out": True}

    def _cleanup_connector_kafka_edc_state(self, connector, token):
        summary = {
            "connector": connector,
            "terminated_transfers": [],
            "deleted_contract_definitions": [],
            "deleted_policies": [],
            "deleted_assets": [],
            "errors": [],
        }

        try:
            transfer_items = self._query_collection(
                connector,
                token,
                "/management/v3/transferprocesses/request",
                "Kafka transfer listing",
            )
            for item in transfer_items:
                transfer_id = self._extract_identifier(item)
                asset_id = self._read_field(item, "assetId") or item.get("assetId")
                if not transfer_id or not str(asset_id or "").startswith(self.KAFKA_EDC_ASSET_PREFIX):
                    continue
                try:
                    terminate_status = self._terminate_transfer_process(
                        connector,
                        token,
                        transfer_id,
                        "Framework cleanup before/after Kafka transfer validation",
                    )
                    state_info = self._wait_for_transfer_cleanup(connector, token, transfer_id)
                    deprovision_status = None
                    if state_info.get("state") not in {"DEPROVISIONED", "NOT_FOUND"}:
                        deprovision_status = self._deprovision_transfer_process(connector, token, transfer_id)
                        state_info = self._wait_for_transfer_cleanup(connector, token, transfer_id)
                    summary["terminated_transfers"].append(
                        {
                            "transfer_id": transfer_id,
                            "asset_id": asset_id,
                            "terminate_status": terminate_status,
                            "deprovision_status": deprovision_status,
                            "state": state_info.get("state"),
                            "timed_out": bool(state_info.get("timed_out")),
                        }
                    )
                except Exception as exc:
                    summary["errors"].append(f"transfer:{transfer_id}:{exc}")
        except Exception as exc:
            summary["errors"].append(f"transfer_list:{exc}")

        def delete_prefixed_resources(path, prefix, bucket, label):
            try:
                items = self._query_collection(connector, token, path, f"Kafka transfer {label} listing")
            except Exception as exc:
                summary["errors"].append(f"{label}_list:{exc}")
                return
            for item in items:
                resource_id = self._extract_identifier(item)
                if not resource_id or not str(resource_id).startswith(prefix):
                    continue
                try:
                    status_code = self._delete(
                        self._management_url(connector, f"{path.rsplit('/', 1)[0]}/{resource_id}"),
                        token,
                        f"Kafka transfer {label} deletion",
                    )
                    summary[bucket].append({"id": resource_id, "status_code": status_code})
                except Exception as exc:
                    summary["errors"].append(f"{label}:{resource_id}:{exc}")

        delete_prefixed_resources(
            "/management/v3/contractdefinitions/request",
            self.KAFKA_EDC_CONTRACT_PREFIX,
            "deleted_contract_definitions",
            "contract_definition",
        )
        delete_prefixed_resources(
            "/management/v3/policydefinitions/request",
            self.KAFKA_EDC_POLICY_PREFIX,
            "deleted_policies",
            "policy_definition",
        )
        delete_prefixed_resources(
            "/management/v3/assets/request",
            self.KAFKA_EDC_ASSET_PREFIX,
            "deleted_assets",
            "asset",
        )
        return summary

    def _cleanup_kafka_edc_state(self, provider, consumer, provider_jwt, consumer_jwt):
        summaries = []
        if consumer_jwt:
            try:
                summaries.append(self._cleanup_connector_kafka_edc_state(consumer, consumer_jwt))
            except Exception:
                pass
        if provider_jwt:
            try:
                summaries.append(self._cleanup_connector_kafka_edc_state(provider, provider_jwt))
            except Exception:
                pass
        return summaries

    @staticmethod
    def _cleanup_has_actions(cleanup_entries):
        for entry in cleanup_entries or []:
            if not isinstance(entry, dict):
                continue
            for key in (
                "terminated_transfers",
                "deleted_contract_definitions",
                "deleted_policies",
                "deleted_assets",
            ):
                if entry.get(key):
                    return True
        return False

    def _wait_for_cleanup_settlement(self, runtime, cleanup_entries):
        seconds = max(int(runtime.get("pre_run_settle_seconds", 0)), 0)
        if seconds <= 0:
            return {
                "status": "skipped",
                "seconds_waited": 0,
                "reason": "disabled",
            }
        if not self._cleanup_has_actions(cleanup_entries):
            return {
                "status": "skipped",
                "seconds_waited": 0,
                "reason": "no_cleanup_actions",
            }
        time.sleep(seconds)
        return {
            "status": "waited",
            "seconds_waited": seconds,
        }

    def _start_negotiation(self, provider, consumer, consumer_jwt, catalog_info):
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
            },
            "@type": "ContractRequest",
            "counterPartyAddress": self._protocol_address(provider),
            "protocol": "dataspace-protocol-http",
            "policy": {
                "@context": "http://www.w3.org/ns/odrl.jsonld",
                "@type": "odrl:Offer",
                "@id": catalog_info["offer_id"],
                "assigner": catalog_info["provider_participant_id"],
                "target": catalog_info["catalog_asset_id"],
                "permission": [],
                "prohibition": [],
                "obligation": [],
            },
        }
        body, status_code = self._post_json(
            self._management_url(consumer, "/management/v3/contractnegotiations"),
            consumer_jwt,
            payload,
            "consumer contract negotiation start",
        )
        negotiation_id = body.get("@id") or body.get("id")
        if not negotiation_id:
            raise RuntimeError("Negotiation creation did not return negotiation id")
        return negotiation_id, status_code

    def _query_negotiation(self, consumer, consumer_jwt, negotiation_id):
        direct_body, direct_status = self._get_json(
            self._management_url(consumer, f"/management/v3/contractnegotiations/{negotiation_id}"),
            consumer_jwt,
            "contract negotiation lookup",
            accepted_statuses={200, 404},
        )
        if direct_status == 200 and isinstance(direct_body, dict):
            return direct_body

        body, _ = self._post_json(
            self._management_url(consumer, "/management/v3/contractnegotiations/request"),
            consumer_jwt,
            {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "offset": 0,
                "limit": 100,
            },
            "contract negotiation status query",
        )
        if isinstance(body, list):
            return next(
                (
                    item for item in body
                    if isinstance(item, dict) and (item.get("@id") == negotiation_id or item.get("id") == negotiation_id)
                ),
                None,
            )
        return body if isinstance(body, dict) else None

    def _wait_for_agreement(self, consumer, consumer_jwt, negotiation_id, runtime):
        deadline = time.time() + int(runtime["negotiation_timeout_seconds"])
        last_state = None
        last_detail = None
        while time.time() <= deadline:
            negotiation = self._query_negotiation(consumer, consumer_jwt, negotiation_id)
            if negotiation:
                state = negotiation.get("state")
                last_state = state
                agreement_id = negotiation.get("contractAgreementId")
                if agreement_id:
                    return {
                        "state": state,
                        "agreement_id": agreement_id,
                        "raw": negotiation,
                    }
                if state == "TERMINATED":
                    raise RuntimeError(
                        "Negotiation reached TERMINATED state"
                        + (f": {negotiation.get('errorDetail')}" if negotiation.get("errorDetail") else "")
                    )
                last_detail = negotiation.get("errorDetail")
            time.sleep(max(1, int(runtime["poll_interval_seconds"])))

        raise RuntimeError(
            f"Negotiation {negotiation_id} did not produce contractAgreementId in time"
            + (f" (last_state={last_state}, detail={last_detail})" if last_state or last_detail else "")
        )

    def _query_contract_agreement(self, connector, token, agreement_id):
        body, status_code = self._get_optional_json(
            self._management_url(connector, f"/management/v3/contractagreements/{agreement_id}"),
            token,
            "contract agreement lookup",
            accepted_statuses={200, 404},
        )
        if status_code == 200 and isinstance(body, dict):
            return body

        body, _ = self._post_json(
            self._management_url(connector, "/management/v3/contractagreements/request"),
            token,
            {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "offset": 0,
                "limit": 100,
            },
            "contract agreement status query",
        )
        if isinstance(body, list):
            return next(
                (
                    item for item in body
                    if isinstance(item, dict) and self._extract_identifier(item) == agreement_id
                ),
                None,
            )
        if isinstance(body, dict) and self._extract_identifier(body) == agreement_id:
            return body
        return None

    def _wait_for_contract_agreement_visibility(
        self,
        provider,
        consumer,
        provider_jwt,
        consumer_jwt,
        agreement_id,
        runtime,
    ):
        timeout_seconds = max(int(runtime.get("agreement_visibility_timeout_seconds", 0)), 0)
        if timeout_seconds <= 0:
            return {
                "status": "skipped",
                "reason": "disabled",
                "seconds_waited": 0,
            }

        deadline = time.time() + timeout_seconds
        poll_seconds = max(1, int(runtime.get("poll_interval_seconds", self.DEFAULT_POLL_INTERVAL_SECONDS)))
        visible = set()
        last_errors = {}
        checks = (
            ("provider", provider, provider_jwt),
            ("consumer", consumer, consumer_jwt),
        )

        while time.time() <= deadline:
            for role, connector, token in checks:
                if role in visible:
                    continue
                try:
                    if self._query_contract_agreement(connector, token, agreement_id):
                        visible.add(role)
                        last_errors.pop(role, None)
                except Exception as exc:
                    last_errors[role] = str(exc)
            if len(visible) == len(checks):
                return {
                    "status": "visible",
                    "agreement_id": agreement_id,
                    "provider_visible": True,
                    "consumer_visible": True,
                }
            time.sleep(poll_seconds)

        missing = [role for role, _, _ in checks if role not in visible]
        detail = ", ".join(f"{role}: {last_errors[role]}" for role in missing if role in last_errors)
        raise RuntimeError(
            f"Contract agreement {agreement_id} was not visible before starting Kafka transfer "
            f"(missing={','.join(missing)})"
            + (f"; last_errors={detail}" if detail else "")
        )

    def _start_transfer(self, provider, consumer, consumer_jwt, asset_id, agreement_id, runtime, destination_topic):
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
            },
            "@type": "TransferRequest",
            "assetId": asset_id,
            "contractId": agreement_id,
            "counterPartyAddress": self._protocol_address(provider),
            "protocol": "dataspace-protocol-http",
            "transferType": "Kafka-PUSH",
            "dataDestination": {
                "type": "Kafka",
                "topic": destination_topic,
                "kafka.bootstrap.servers": runtime["cluster_bootstrap_servers"],
            },
        }
        expanded_payload = {
            **payload,
            "dataDestination": self._expanded_kafka_address(
                destination_topic,
                runtime["cluster_bootstrap_servers"],
            ),
        }
        body, status_code = self._post_kafka_payload_with_expanded_fallback(
            self._management_url(consumer, "/management/v3/transferprocesses"),
            consumer_jwt,
            payload,
            expanded_payload,
            "consumer Kafka transfer start",
        )
        transfer_id = body.get("@id") or body.get("id")
        if not transfer_id:
            raise RuntimeError("Transfer creation did not return transfer id")
        return transfer_id, status_code

    def _query_transfer(self, consumer, consumer_jwt, transfer_id):
        direct_body, direct_status = self._get_json(
            self._management_url(consumer, f"/management/v3/transferprocesses/{transfer_id}"),
            consumer_jwt,
            "transfer process lookup",
            accepted_statuses={200, 404},
        )
        if direct_status == 200 and isinstance(direct_body, dict):
            return direct_body

        body, _ = self._post_json(
            self._management_url(consumer, "/management/v3/transferprocesses/request"),
            consumer_jwt,
            {
                "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                "offset": 0,
                "limit": 100,
            },
            "transfer process status query",
        )
        if isinstance(body, list):
            return next(
                (
                    item for item in body
                    if isinstance(item, dict) and (item.get("@id") == transfer_id or item.get("id") == transfer_id)
                ),
                None,
            )
        return body if isinstance(body, dict) else None

    def _wait_for_transfer_started(self, consumer, consumer_jwt, transfer_id, runtime):
        deadline = time.time() + int(runtime["transfer_timeout_seconds"])
        last_state = None
        last_detail = None
        last_transfer = None
        success_states = {"STARTED", "COMPLETED", "FINALIZED", "ENDED", "DEPROVISIONED"}
        while time.time() <= deadline:
            transfer = self._query_transfer(consumer, consumer_jwt, transfer_id)
            if transfer:
                last_transfer = transfer
                state = transfer.get("state")
                last_state = state
                if state in success_states:
                    return {"state": state, "raw": transfer}
                if state == "TERMINATED":
                    raise RuntimeError(
                        "Transfer reached TERMINATED state"
                        + (f": {transfer.get('errorDetail')}" if transfer.get("errorDetail") else "")
                    )
                last_detail = transfer.get("errorDetail") or transfer.get("error")
            time.sleep(max(1, int(runtime["poll_interval_seconds"])))

        if (
            last_state == "REQUESTED"
            and self._truthy(runtime.get("continue_after_requested_transfer_timeout", True))
        ):
            return {
                "state": last_state,
                "raw": last_transfer or {"@id": transfer_id, "state": last_state},
                "continued_after_requested_timeout": True,
                "timeout_seconds": int(runtime["transfer_timeout_seconds"]),
            }

        raise RuntimeError(
            f"Transfer {transfer_id} did not reach a started/finalized state in time"
            + (f" (last_state={last_state}, detail={last_detail})" if last_state or last_detail else "")
        )

    def _build_kafka_client_kwargs(self, runtime, *, endpoint=None, username=None, password=None):
        kwargs = {
            "bootstrap_servers": endpoint or runtime.get("host_bootstrap_servers") or runtime.get("bootstrap_servers"),
            "security_protocol": runtime.get("security_protocol", "PLAINTEXT"),
            "request_timeout_ms": runtime.get("request_timeout_ms", 60000),
            "api_version_auto_timeout_ms": runtime.get("api_timeout_ms", 60000),
        }
        sasl_mechanism = runtime.get("sasl_mechanism")
        if sasl_mechanism:
            kwargs["sasl_mechanism"] = sasl_mechanism
        if username:
            kwargs["sasl_plain_username"] = username
        elif runtime.get("username"):
            kwargs["sasl_plain_username"] = runtime.get("username")
        if password:
            kwargs["sasl_plain_password"] = password
        elif runtime.get("password"):
            kwargs["sasl_plain_password"] = runtime.get("password")
        return kwargs

    def _load_kafka_classes(self):
        producer_class = self.producer_class
        consumer_class = self.consumer_class
        if producer_class is not None and consumer_class is not None:
            return producer_class, consumer_class

        try:
            from kafka import KafkaConsumer, KafkaProducer

            return producer_class or KafkaProducer, consumer_class or KafkaConsumer
        except Exception as exc:
            raise RuntimeError(f"Kafka client library not available: {exc}") from exc

    @staticmethod
    def _decode_message_value(value):
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _compute_percentile(values, percentile):
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

    def _build_transfer_metrics(
        self,
        *,
        status,
        produced_count,
        consumed_count,
        source_topic,
        destination_topic,
        consumer_group_id,
        latencies_ms,
        duration_seconds,
        probe_result,
        message_samples,
        missing_message_ids=None,
        late_confirmation=None,
    ):
        metrics = {
            "status": status,
            "messages_produced": produced_count,
            "messages_consumed": consumed_count,
            "source_topic": source_topic,
            "destination_topic": destination_topic,
            "consumer_group_id": consumer_group_id,
            "probe": probe_result,
            "message_samples": message_samples,
        }
        if late_confirmation:
            metrics["late_confirmation"] = late_confirmation
        if missing_message_ids:
            metrics["messages_missing"] = len(missing_message_ids)
            metrics["missing_message_ids"] = list(missing_message_ids)
        if latencies_ms:
            metrics.update(
                {
                    "average_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 2),
                    "min_latency_ms": round(min(latencies_ms), 2),
                    "max_latency_ms": round(max(latencies_ms), 2),
                    "p50_latency_ms": round(self._compute_percentile(latencies_ms, 0.50), 2),
                    "p95_latency_ms": round(self._compute_percentile(latencies_ms, 0.95), 2),
                    "p99_latency_ms": round(self._compute_percentile(latencies_ms, 0.99), 2),
                    "throughput_messages_per_second": round(consumed_count / duration_seconds, 2),
                }
            )
        return metrics

    def _raise_if_incomplete_transfer(
        self,
        *,
        produced_count,
        consumed_count,
        expected_ids,
        source_topic,
        destination_topic,
        consumer_group_id,
        latencies_ms,
        duration_seconds,
        probe_result,
        message_samples,
        timeout_seconds,
        late_confirmation=None,
    ):
        if consumed_count >= produced_count:
            return
        for sample in message_samples:
            if sample.get("status") == "produced":
                sample["status"] = "missing"
        missing_ids = sorted(expected_ids)
        metrics = self._build_transfer_metrics(
            status="incomplete",
            produced_count=produced_count,
            consumed_count=consumed_count,
            source_topic=source_topic,
            destination_topic=destination_topic,
            consumer_group_id=consumer_group_id,
            latencies_ms=latencies_ms,
            duration_seconds=duration_seconds,
            probe_result=probe_result,
            message_samples=message_samples,
            missing_message_ids=missing_ids,
            late_confirmation=late_confirmation,
        )
        missing_preview = ", ".join(missing_ids[:5])
        suffix = f"; missing message ids: {missing_preview}" if missing_preview else ""
        confirmation_suffix = ""
        if late_confirmation:
            confirmation_suffix = (
                " after the primary timeout and late confirmation window "
                f"({late_confirmation.get('timeout_seconds', 0)}s)"
            )
        raise KafkaTransferIncomplete(
            "Kafka transfer consumed only "
            f"{consumed_count}/{produced_count} produced messages "
            f"before timeout ({timeout_seconds}s){confirmation_suffix}{suffix}",
            metrics=metrics,
        )

    def _record_expected_transfer_payload(
        self,
        payload,
        *,
        expected_ids,
        sample_ids,
        message_samples,
        latencies_ms,
    ):
        if not isinstance(payload, dict) or payload.get("probe"):
            return "ignored"
        message_id = payload.get("message_id")
        if message_id not in expected_ids:
            return "ignored"
        produced_at = payload.get("producer_timestamp_ms")
        consumed_at = self.time_provider()
        try:
            latency = float(consumed_at) - float(produced_at)
        except (TypeError, ValueError):
            return "invalid"
        if math.isnan(latency) or math.isinf(latency) or latency < 0:
            return "invalid"

        expected_ids.remove(message_id)
        if message_id in sample_ids:
            for sample in message_samples:
                if sample.get("message_id") == message_id:
                    sample["status"] = "consumed"
                    sample["latency_ms"] = round(latency, 2)
                    break
        latencies_ms.append(latency)
        return "consumed"

    def _transfer_late_confirmation_seconds(self, runtime):
        try:
            return max(
                int(runtime.get(
                    "late_transfer_confirmation_seconds",
                    self.DEFAULT_TRANSFER_LATE_CONFIRMATION_SECONDS,
                )),
                0,
            )
        except (TypeError, ValueError):
            return self.DEFAULT_TRANSFER_LATE_CONFIRMATION_SECONDS

    def _wait_for_transfer_runtime_stabilization(self, runtime, transfer_process, source_topic, destination_topic=None):
        timeout_seconds = max(int(runtime.get("startup_grace_seconds", 0)), 0)
        correlation_id = None
        if isinstance(transfer_process, dict):
            correlation_id = transfer_process.get("correlationId")
            data_destination = transfer_process.get("dataDestination")
            if destination_topic is None and isinstance(data_destination, dict):
                destination_topic = data_destination.get("topic")

        if timeout_seconds <= 0:
            return {
                "strategy": "disabled",
                "seconds_waited": 0,
            }

        if self._use_kubernetes_exec_backend(runtime) and destination_topic:
            started_at = time.time()
            group_result = None
            if correlation_id:
                group_wait_seconds = min(
                    timeout_seconds,
                    self._runtime_int(
                        runtime,
                        "stabilization_group_wait_seconds",
                        self.DEFAULT_STABILIZATION_GROUP_WAIT_SECONDS,
                        minimum=1,
                    ),
                )
                group_result = self._wait_for_kubernetes_exec_consumer_group_ready(
                    runtime,
                    correlation_id,
                    source_topic,
                    timeout_seconds=group_wait_seconds,
                )
            elapsed_seconds = max(0.0, time.time() - started_at)
            remaining_seconds = max(int(timeout_seconds - elapsed_seconds), 1)
            probe_timeout_seconds = min(
                remaining_seconds,
                self._runtime_int(
                    runtime,
                    "stabilization_probe_timeout_seconds",
                    self.DEFAULT_STABILIZATION_PROBE_TIMEOUT_SECONDS,
                    minimum=1,
                ),
            )
            try:
                probe_result = self._wait_for_end_to_end_probe_with_kubernetes_exec(
                    runtime,
                    source_topic,
                    destination_topic,
                    timeout_seconds=probe_timeout_seconds,
                )
                return {
                    "strategy": "kubernetes_exec_probe_ready",
                    "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                    "group_id": (group_result or {}).get("group_id"),
                    "group_status": (group_result or {}).get("status"),
                    "state": "ProbeRelayed",
                    "member_count": (group_result or {}).get("member_count", 0),
                    "source_topic": source_topic,
                    "destination_topic": destination_topic,
                    "probe": probe_result,
                }
            except Exception as probe_exc:
                return {
                    "strategy": "kubernetes_exec_probe_timeout",
                    "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                    "correlation_id": correlation_id,
                    "group_id": (group_result or {}).get("group_id"),
                    "group_status": (group_result or {}).get("status"),
                    "last_state": None,
                    "last_member_count": (group_result or {}).get("member_count", 0),
                    "source_topic": source_topic,
                    "destination_topic": destination_topic,
                    "group_wait": group_result,
                    "probe_error": str(probe_exc),
                }

        admin_client_class, _ = self._load_kafka_admin_classes()
        stabilization_runtime = dict(runtime)
        stabilization_runtime["request_timeout_ms"] = min(
            int(stabilization_runtime.get("request_timeout_ms", 60000)),
            self.DEFAULT_STABILIZATION_REQUEST_TIMEOUT_MS,
        )
        stabilization_runtime["api_timeout_ms"] = min(
            int(stabilization_runtime.get("api_timeout_ms", 60000)),
            self.DEFAULT_STABILIZATION_REQUEST_TIMEOUT_MS,
        )
        admin_client = admin_client_class(**self._build_kafka_client_kwargs(stabilization_runtime))
        started_at = time.time()
        group_wait_seconds = min(
            timeout_seconds,
            self._runtime_int(
                runtime,
                "stabilization_group_wait_seconds",
                self.DEFAULT_STABILIZATION_GROUP_WAIT_SECONDS,
                minimum=1,
            ),
        )
        deadline = started_at + group_wait_seconds
        last_state = None
        last_member_count = 0
        matched_group_id = None

        try:
            while time.time() <= deadline:
                group_ids = []
                try:
                    listed_groups = admin_client.list_consumer_groups()
                except Exception:
                    listed_groups = []

                for group in listed_groups or []:
                    if isinstance(group, (list, tuple)) and group:
                        group_ids.append(str(group[0]))
                    else:
                        group_id = getattr(group, "group", None)
                        if group_id:
                            group_ids.append(str(group_id))

                if correlation_id:
                    matching_group_ids = [group_id for group_id in group_ids if correlation_id in group_id]
                else:
                    matching_group_ids = list(group_ids)

                for group_id in matching_group_ids:
                    try:
                        descriptions = admin_client.describe_consumer_groups([group_id])
                    except Exception:
                        continue
                    if not descriptions:
                        continue
                    description = descriptions[0]
                    last_state = str(getattr(description, "state", "") or "")
                    members = getattr(description, "members", None) or []
                    last_member_count = len(members)
                    matched_group_id = group_id
                    if last_member_count > 0 and last_state.lower() == "stable":
                        # Give the dataplane a brief extra moment after assignment before producing.
                        time.sleep(1)
                        return {
                            "strategy": "consumer_group_ready",
                            "seconds_waited": round(time.time() - started_at, 2),
                            "group_id": group_id,
                            "state": last_state,
                            "member_count": last_member_count,
                            "source_topic": source_topic,
                        }

                time.sleep(max(1, int(runtime.get("poll_interval_seconds", 1))))
        finally:
            close_method = getattr(admin_client, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception:
                    pass

        if destination_topic:
            producer = None
            consumer = None
            probe_timeout_seconds = min(
                timeout_seconds,
                self._runtime_int(
                    runtime,
                    "stabilization_probe_timeout_seconds",
                    self.DEFAULT_STABILIZATION_PROBE_TIMEOUT_SECONDS,
                    minimum=1,
                ),
            )
            try:
                producer, consumer, probe_group_id = self._open_probe_clients(runtime, destination_topic)
                probe_result = self._wait_for_end_to_end_probe(
                    runtime,
                    producer,
                    consumer,
                    source_topic,
                    timeout_seconds=probe_timeout_seconds,
                )
                return {
                    "strategy": "probe_ready",
                    "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                    "group_id": probe_group_id,
                    "state": "ProbeRelayed",
                    "member_count": 0,
                    "source_topic": source_topic,
                    "destination_topic": destination_topic,
                    "probe": probe_result,
                }
            except Exception as probe_exc:
                probe_error = str(probe_exc)
            finally:
                for client in (producer, consumer):
                    close_method = getattr(client, "close", None) if client is not None else None
                    if callable(close_method):
                        try:
                            close_method()
                        except Exception:
                            pass
        else:
            probe_error = "destination_topic_missing"

        return {
            "strategy": "timeout_without_ready_group",
            "seconds_waited": round(max(0.0, time.time() - started_at), 2),
            "correlation_id": correlation_id,
            "group_id": matched_group_id,
            "last_state": last_state,
            "last_member_count": last_member_count,
            "source_topic": source_topic,
            "destination_topic": destination_topic,
            "probe_error": probe_error,
        }

    def _wait_for_end_to_end_probe(self, runtime, producer, consumer, source_topic, *, timeout_seconds=None):
        if timeout_seconds is None:
            timeout_seconds = runtime.get("startup_grace_seconds", 0)
        timeout_seconds = max(int(timeout_seconds), 0)
        if timeout_seconds <= 0:
            return {
                "status": "skipped",
                "attempts": 0,
                "seconds_waited": 0,
            }

        started_at = time.time()
        deadline = started_at + timeout_seconds
        attempts = 0
        # EDC may relay a previous probe after the next send; keep all in-flight probes valid.
        pending_probe_ids = set()
        poll_timeout_ms = max(500, min(2000, int(runtime.get("consumer_request_timeout_ms", 60000))))

        while time.time() <= deadline:
            attempts += 1
            probe_payload = {
                "message_id": f"kafka-transfer-probe-{self.uuid_factory()}",
                "producer_timestamp_ms": self.time_provider(),
                "probe": True,
            }
            pending_probe_ids.add(probe_payload["message_id"])
            producer.send(source_topic, json.dumps(probe_payload, separators=(",", ":")).encode("utf-8"))
            producer.flush()

            probe_deadline = time.time() + max(1, int(runtime.get("poll_interval_seconds", 1)))
            while time.time() <= probe_deadline:
                records_by_partition = consumer.poll(timeout_ms=poll_timeout_ms)
                if not records_by_partition:
                    continue
                for records in records_by_partition.values():
                    for record in records:
                        payload = self._decode_message_value(getattr(record, "value", None))
                        if not isinstance(payload, dict):
                            continue
                        matched_probe_id = payload.get("message_id")
                        if matched_probe_id in pending_probe_ids:
                            return {
                                "status": "ready",
                                "attempts": attempts,
                                "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                                "probe_message_id": matched_probe_id,
                            }
            time.sleep(1)

        raise RuntimeError("Kafka transfer path did not relay a probe message in time")

    def _produce_kubernetes_exec_message(self, runtime, topic, payload):
        timeout_seconds = int(runtime.get("kubernetes_exec_timeout_seconds", 30))
        result = self._run_kubernetes_kafka_command(
            runtime,
            [
                "timeout",
                str(timeout_seconds),
                "kafka-console-producer",
                "--bootstrap-server",
                "localhost:9092",
                "--topic",
                topic,
            ],
            input_text=json.dumps(payload, separators=(",", ":")) + "\n",
            timeout_seconds=timeout_seconds + 5,
        )
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError(self._kubernetes_command_failure_message(result, "Kafka console producer"))

    def _consume_kubernetes_exec_messages(self, runtime, topic, timeout_ms=2000, max_messages=50, offset=None):
        timeout_seconds = int(runtime.get("kubernetes_exec_timeout_seconds", 30))
        kafka_args = [
            "timeout",
            str(timeout_seconds),
            "kafka-console-consumer",
            "--bootstrap-server",
            "localhost:9092",
            "--topic",
            topic,
        ]
        if offset is None:
            kafka_args.append("--from-beginning")
        else:
            kafka_args.extend(["--partition", "0", "--offset", str(int(offset))])
        kafka_args.extend([
            "--timeout-ms",
            str(int(timeout_ms)),
            "--max-messages",
            str(int(max_messages)),
        ])
        result = self._run_kubernetes_kafka_command(
            runtime,
            kafka_args,
            timeout_seconds=timeout_seconds + 5,
        )
        if getattr(result, "returncode", 0) not in (0, 124):
            raise RuntimeError(self._kubernetes_command_failure_message(result, "Kafka console consumer"))
        output = getattr(result, "stdout", "") or ""
        messages = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                decoded = self._decode_message_value(line.encode("utf-8"))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(decoded, dict):
                messages.append(decoded)
        return messages

    def _list_kubernetes_exec_consumer_groups(self, runtime):
        result = self._run_kubernetes_kafka_command(
            runtime,
            ["kafka-consumer-groups", "--bootstrap-server", "localhost:9092", "--list"],
        )
        if getattr(result, "returncode", 1) != 0:
            raise RuntimeError(self._kubernetes_command_failure_message(result, "Kafka consumer group list"))
        groups = []
        for line in (getattr(result, "stdout", "") or "").splitlines():
            group_id = line.strip()
            if group_id and group_id not in groups:
                groups.append(group_id)
        return groups

    def _describe_kubernetes_exec_consumer_group(self, runtime, group_id, source_topic=None):
        result = self._run_kubernetes_kafka_command(
            runtime,
            [
                "kafka-consumer-groups",
                "--bootstrap-server",
                "localhost:9092",
                "--describe",
                "--group",
                group_id,
            ],
        )
        if getattr(result, "returncode", 1) != 0:
            return {
                "group_id": group_id,
                "member_count": 0,
                "topics": [],
                "error": self._kubernetes_command_failure_message(result, "Kafka consumer group describe"),
            }

        topics = []
        consumer_ids = set()
        for line in (getattr(result, "stdout", "") or "").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("GROUP ") or stripped.startswith("Consumer group"):
                continue
            parts = stripped.split()
            if len(parts) < 7:
                continue
            topic = parts[1]
            consumer_id = parts[6]
            if topic != "-" and topic not in topics:
                topics.append(topic)
            if consumer_id != "-":
                consumer_ids.add(consumer_id)

        source_topic_seen = not source_topic or source_topic in topics
        return {
            "group_id": group_id,
            "member_count": len(consumer_ids),
            "topics": topics,
            "source_topic_seen": source_topic_seen,
        }

    def _wait_for_kubernetes_exec_consumer_group_ready(
        self,
        runtime,
        correlation_id,
        source_topic,
        *,
        timeout_seconds,
    ):
        correlation_id = str(correlation_id or "").strip()
        timeout_seconds = max(int(timeout_seconds or 0), 0)
        if not correlation_id or timeout_seconds <= 0:
            return {"status": "skipped", "seconds_waited": 0}

        started_at = time.time()
        deadline = started_at + timeout_seconds
        last_description = None

        while time.time() <= deadline:
            try:
                groups = self._list_kubernetes_exec_consumer_groups(runtime)
            except Exception as exc:
                return {
                    "status": "unavailable",
                    "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                    "error": str(exc),
                }

            matching_groups = [group_id for group_id in groups if correlation_id in group_id]
            for group_id in matching_groups:
                description = self._describe_kubernetes_exec_consumer_group(
                    runtime,
                    group_id,
                    source_topic=source_topic,
                )
                last_description = description
                if description.get("member_count", 0) > 0 and description.get("source_topic_seen", False):
                    time.sleep(1)
                    return {
                        "status": "ready",
                        "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                        **description,
                    }

            time.sleep(max(1, int(runtime.get("poll_interval_seconds", 1))))

        return {
            "status": "timeout",
            "seconds_waited": round(max(0.0, time.time() - started_at), 2),
            "correlation_id": correlation_id,
            "last_description": last_description,
        }

    def _find_kubernetes_exec_probe_message(
        self,
        runtime,
        destination_topic,
        probe_ids,
        *,
        offset=None,
        timeout_seconds=0,
        poll_timeout_ms=2000,
        max_messages=100,
    ):
        probe_ids = {probe_id for probe_id in probe_ids if probe_id}
        if not probe_ids:
            return None

        deadline = time.time() + max(int(timeout_seconds), 0)
        while True:
            messages = self._consume_kubernetes_exec_messages(
                runtime,
                destination_topic,
                timeout_ms=poll_timeout_ms,
                max_messages=max(max_messages, len(probe_ids) + 5),
                offset=offset,
            )
            for payload in messages:
                matched_probe_id = payload.get("message_id")
                if matched_probe_id in probe_ids:
                    return matched_probe_id

            if time.time() >= deadline:
                return None
            time.sleep(max(1, int(runtime.get("poll_interval_seconds", 1))))

    def _wait_for_end_to_end_probe_with_kubernetes_exec(self, runtime, source_topic, destination_topic, *, timeout_seconds=None):
        if timeout_seconds is None:
            timeout_seconds = runtime.get("startup_grace_seconds", 0)
        timeout_seconds = max(int(timeout_seconds), 0)
        if timeout_seconds <= 0:
            return {
                "status": "skipped",
                "attempts": 0,
                "seconds_waited": 0,
            }

        started_at = time.time()
        deadline = started_at + timeout_seconds
        attempts = 0
        # EDC may relay a previous probe after the next send; keep all in-flight probes valid.
        pending_probe_ids = set()
        poll_timeout_ms = max(500, min(2000, int(runtime.get("consumer_request_timeout_ms", 60000))))
        destination_start_offset = self._kubernetes_consumer_start_offset(runtime, destination_topic)

        while time.time() <= deadline:
            attempts += 1
            probe_payload = {
                "message_id": f"kafka-transfer-probe-{self.uuid_factory()}",
                "producer_timestamp_ms": self.time_provider(),
                "probe": True,
            }
            pending_probe_ids.add(probe_payload["message_id"])
            self._produce_kubernetes_exec_message(runtime, source_topic, probe_payload)
            matched_probe_id = self._find_kubernetes_exec_probe_message(
                runtime,
                destination_topic,
                poll_timeout_ms=poll_timeout_ms,
                max_messages=max(100, len(pending_probe_ids) + 5),
                offset=destination_start_offset,
                probe_ids=pending_probe_ids,
            )
            if matched_probe_id:
                return {
                    "status": "ready",
                    "attempts": attempts,
                    "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                    "probe_message_id": matched_probe_id,
                }
            time.sleep(max(1, int(runtime.get("poll_interval_seconds", 1))))

        late_confirmation_seconds = max(
            int(runtime.get(
                "late_probe_confirmation_seconds",
                self.DEFAULT_STABILIZATION_LATE_CONFIRMATION_SECONDS,
            )),
            0,
        )
        matched_probe_id = self._find_kubernetes_exec_probe_message(
            runtime,
            destination_topic,
            pending_probe_ids,
            offset=destination_start_offset,
            timeout_seconds=late_confirmation_seconds,
            poll_timeout_ms=poll_timeout_ms,
            max_messages=max(100, len(pending_probe_ids) + 5),
        )
        if matched_probe_id:
            return {
                "status": "ready",
                "attempts": attempts,
                "seconds_waited": round(max(0.0, time.time() - started_at), 2),
                "probe_message_id": matched_probe_id,
                "late_confirmation": True,
            }

        raise RuntimeError("Kafka transfer path did not relay a probe message in time")

    def _open_probe_clients(self, runtime, destination_topic):
        producer_class, consumer_class = self._load_kafka_classes()
        producer_kwargs = self._build_kafka_client_kwargs(runtime)
        producer_kwargs.setdefault("acks", "all")
        producer_kwargs.setdefault("retries", 5)
        producer_kwargs.setdefault("max_block_ms", runtime.get("max_block_ms", 60000))
        producer = producer_class(**producer_kwargs)

        group_id = f"{runtime.get('consumer_group_prefix', 'framework-edc-kafka')}-{str(self.uuid_factory())[:12]}"
        consumer_kwargs = self._build_kafka_client_kwargs(runtime)
        consumer_kwargs.setdefault("group_id", group_id)
        consumer_kwargs.setdefault("auto_offset_reset", "earliest")
        consumer_kwargs.setdefault("enable_auto_commit", False)
        consumer_kwargs.setdefault("consumer_timeout_ms", runtime.get("consumer_request_timeout_ms", 60000))
        consumer = consumer_class(**consumer_kwargs)

        if hasattr(consumer, "subscribe"):
            consumer.subscribe([destination_topic])
        return producer, consumer, group_id

    def _measure_transfer_latency(self, runtime, source_topic, destination_topic, probe_result=None):
        if self._use_kubernetes_exec_backend(runtime):
            return self._measure_transfer_latency_with_kubernetes_exec(
                runtime,
                source_topic,
                destination_topic,
                probe_result=probe_result,
            )

        producer = None
        consumer = None
        group_id = None

        message_count = int(runtime["message_count"])
        message_sample_limit = max(int(runtime.get("message_sample_limit", 5)), 0)
        produced_count = 0
        consumed_count = 0
        invalid_latency_count = 0
        latencies_ms = []
        message_samples = []
        sample_ids = set()
        expected_ids = set()

        try:
            producer, consumer, group_id = self._open_probe_clients(runtime, destination_topic)
            if probe_result is None:
                probe_result = self._wait_for_end_to_end_probe(runtime, producer, consumer, source_topic)
            start_ms = self.time_provider()
            for index in range(message_count):
                message_id = f"kafka-transfer-{index}-{self.uuid_factory()}"
                payload = {
                    "message_id": message_id,
                    "producer_timestamp_ms": self.time_provider(),
                }
                expected_ids.add(message_id)
                if len(message_samples) < message_sample_limit:
                    message_samples.append(
                        {
                            "message_id": message_id,
                            "source_topic": source_topic,
                            "destination_topic": destination_topic,
                            "status": "produced",
                        }
                    )
                    sample_ids.add(message_id)
                producer.send(source_topic, json.dumps(payload, separators=(",", ":")).encode("utf-8"))
                produced_count += 1
            producer.flush()

            deadline = time.time() + int(runtime["consumer_poll_timeout_seconds"])
            while time.time() <= deadline and consumed_count < message_count:
                records_by_partition = consumer.poll(timeout_ms=500)
                if not records_by_partition:
                    continue
                for records in records_by_partition.values():
                    for record in records:
                        payload = self._decode_message_value(getattr(record, "value", None))
                        if not isinstance(payload, dict):
                            continue
                        if payload.get("probe"):
                            continue
                        message_id = payload.get("message_id")
                        if message_id not in expected_ids:
                            continue
                        produced_at = payload.get("producer_timestamp_ms")
                        consumed_at = self.time_provider()
                        try:
                            latency = float(consumed_at) - float(produced_at)
                        except (TypeError, ValueError):
                            invalid_latency_count += 1
                            continue
                        if math.isnan(latency) or math.isinf(latency) or latency < 0:
                            invalid_latency_count += 1
                            continue
                        expected_ids.remove(message_id)
                        if message_id in sample_ids:
                            for sample in message_samples:
                                if sample.get("message_id") == message_id:
                                    sample["status"] = "consumed"
                                    sample["latency_ms"] = round(latency, 2)
                                    break
                        latencies_ms.append(latency)
                        consumed_count += 1
                        if consumed_count >= message_count:
                            break
                    if consumed_count >= message_count:
                        break
        finally:
            try:
                if producer is not None:
                    producer.close()
            except Exception:
                pass
            try:
                if consumer is not None:
                    consumer.close()
            except Exception:
                pass

        duration_seconds = max((self.time_provider() - start_ms) / 1000.0, 0.001)
        if invalid_latency_count > 0:
            raise RuntimeError(f"Detected {invalid_latency_count} invalid Kafka latency samples")
        if not latencies_ms:
            raise RuntimeError("No Kafka messages were consumed through the EDC transfer")
        self._raise_if_incomplete_transfer(
            produced_count=produced_count,
            consumed_count=consumed_count,
            expected_ids=expected_ids,
            source_topic=source_topic,
            destination_topic=destination_topic,
            consumer_group_id=group_id,
            latencies_ms=latencies_ms,
            duration_seconds=duration_seconds,
            probe_result=probe_result,
            message_samples=message_samples,
            timeout_seconds=runtime["consumer_poll_timeout_seconds"],
        )

        return self._build_transfer_metrics(
            status="completed",
            produced_count=produced_count,
            consumed_count=consumed_count,
            source_topic=source_topic,
            destination_topic=destination_topic,
            consumer_group_id=group_id,
            latencies_ms=latencies_ms,
            duration_seconds=duration_seconds,
            probe_result=probe_result,
            message_samples=message_samples,
        )

    def _measure_transfer_latency_with_kubernetes_exec(self, runtime, source_topic, destination_topic, probe_result=None):
        message_count = int(runtime["message_count"])
        message_sample_limit = max(int(runtime.get("message_sample_limit", 5)), 0)
        produced_count = 0
        consumed_count = 0
        invalid_latency_count = 0
        latencies_ms = []
        message_samples = []
        sample_ids = set()
        expected_ids = set()

        if probe_result is None:
            probe_result = self._wait_for_end_to_end_probe_with_kubernetes_exec(
                runtime,
                source_topic,
                destination_topic,
            )

        destination_start_offset = self._kubernetes_consumer_start_offset(runtime, destination_topic)
        consume_window = self._kubernetes_exec_consume_window(
            runtime,
            message_count,
            probe_result=probe_result,
            offset=destination_start_offset,
        )
        start_ms = self.time_provider()
        for index in range(message_count):
            message_id = f"kafka-transfer-{index}-{self.uuid_factory()}"
            payload = {
                "message_id": message_id,
                "producer_timestamp_ms": self.time_provider(),
            }
            expected_ids.add(message_id)
            if len(message_samples) < message_sample_limit:
                message_samples.append(
                    {
                        "message_id": message_id,
                        "source_topic": source_topic,
                        "destination_topic": destination_topic,
                        "status": "produced",
                    }
                )
                sample_ids.add(message_id)
            self._produce_kubernetes_exec_message(runtime, source_topic, payload)
            produced_count += 1

        deadline = time.time() + int(runtime["consumer_poll_timeout_seconds"])
        while time.time() <= deadline and consumed_count < message_count:
            messages = self._consume_kubernetes_exec_messages(
                runtime,
                destination_topic,
                timeout_ms=2000,
                max_messages=consume_window,
                offset=destination_start_offset,
            )
            for payload in messages:
                record_status = self._record_expected_transfer_payload(
                    payload,
                    expected_ids=expected_ids,
                    sample_ids=sample_ids,
                    message_samples=message_samples,
                    latencies_ms=latencies_ms,
                )
                if record_status == "invalid":
                    invalid_latency_count += 1
                    continue
                if record_status == "consumed":
                    consumed_count += 1
                if consumed_count >= message_count:
                    break
            if consumed_count >= message_count:
                break
            time.sleep(0.5)

        late_confirmation = None
        late_confirmation_seconds = self._transfer_late_confirmation_seconds(runtime)
        if consumed_count < message_count and late_confirmation_seconds > 0:
            late_started_at = time.time()
            late_deadline = late_started_at + late_confirmation_seconds
            late_consumed_before = consumed_count
            while time.time() <= late_deadline and consumed_count < message_count:
                messages = self._consume_kubernetes_exec_messages(
                    runtime,
                    destination_topic,
                    timeout_ms=2000,
                    max_messages=consume_window,
                    offset=destination_start_offset,
                )
                for payload in messages:
                    record_status = self._record_expected_transfer_payload(
                        payload,
                        expected_ids=expected_ids,
                        sample_ids=sample_ids,
                        message_samples=message_samples,
                        latencies_ms=latencies_ms,
                    )
                    if record_status == "invalid":
                        invalid_latency_count += 1
                        continue
                    if record_status == "consumed":
                        consumed_count += 1
                    if consumed_count >= message_count:
                        break
                if consumed_count >= message_count:
                    break
                time.sleep(0.5)
            late_confirmation = {
                "status": "completed" if consumed_count >= message_count else "incomplete",
                "timeout_seconds": late_confirmation_seconds,
                "seconds_waited": round(max(0.0, time.time() - late_started_at), 2),
                "messages_consumed": consumed_count - late_consumed_before,
            }

        duration_seconds = max((self.time_provider() - start_ms) / 1000.0, 0.001)
        if invalid_latency_count > 0:
            raise RuntimeError(f"Detected {invalid_latency_count} invalid Kafka latency samples")
        self._raise_if_incomplete_transfer(
            produced_count=produced_count,
            consumed_count=consumed_count,
            expected_ids=expected_ids,
            source_topic=source_topic,
            destination_topic=destination_topic,
            consumer_group_id="kubernetes-exec",
            latencies_ms=latencies_ms,
            duration_seconds=duration_seconds,
            probe_result=probe_result,
            message_samples=message_samples,
            timeout_seconds=runtime["consumer_poll_timeout_seconds"],
            late_confirmation=late_confirmation,
        )

        return self._build_transfer_metrics(
            status="completed",
            produced_count=produced_count,
            consumed_count=consumed_count,
            source_topic=source_topic,
            destination_topic=destination_topic,
            consumer_group_id="kubernetes-exec",
            latencies_ms=latencies_ms,
            duration_seconds=duration_seconds,
            probe_result=probe_result,
            message_samples=message_samples,
            late_confirmation=late_confirmation,
        )

    @staticmethod
    def _pair_artifact_path(experiment_dir, provider, consumer):
        artifact_dir = os.path.join(experiment_dir, "kafka_transfer")
        os.makedirs(artifact_dir, exist_ok=True)
        return os.path.join(artifact_dir, f"{provider}__{consumer}.json")

    def _save_pair_artifact(self, experiment_dir, provider, consumer, payload):
        if not experiment_dir:
            return None
        path = self._pair_artifact_path(experiment_dir, provider, consumer)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return path

    def _should_reset_framework_managed_kafka(self, runtime=None):
        kafka_manager = self.kafka_manager
        if kafka_manager is None or not bool(getattr(kafka_manager, "started_by_framework", False)):
            return False

        runtime = runtime if isinstance(runtime, dict) else {}
        explicit_flag = runtime.get("allow_framework_kafka_reset_between_pairs")
        if explicit_flag not in (None, ""):
            return self._truthy(explicit_flag)

        provisioning_mode = str(getattr(kafka_manager, "provisioning_mode", "") or "").strip().lower()
        if provisioning_mode.startswith("kubernetes"):
            # A retry starts a fresh transfer flow and creates fresh topics. Recycling
            # a framework-managed broker here avoids carrying an unstable coordinator
            # state from a failed Kafka relay attempt into the next attempt.
            return True
        return True

    def _is_kafka_runtime_pair_failure(self, payload):
        if not isinstance(payload, dict) or payload.get("status") == "passed":
            return False
        error_message = self._pair_error_message(payload)
        runtime_fragments = (
            "NoBrokersAvailable",
            "Kafka transfer path did not relay a probe message in time",
            "No Kafka messages were consumed through the EDC transfer",
            "Kafka transfer consumed only",
            "Kafka topic",
            "Kafka offset lookup",
            "Kafka console producer",
            "Kafka console consumer",
            "Kafka consumer group",
        )
        return any(fragment in error_message for fragment in runtime_fragments)

    def _reset_framework_managed_kafka(self, runtime=None, payload=None):
        if payload is not None and not self._is_kafka_runtime_pair_failure(payload):
            return False
        if not self._should_reset_framework_managed_kafka(runtime):
            return False
        kafka_manager = self.kafka_manager
        stop_method = getattr(kafka_manager, "stop_kafka", None) if kafka_manager is not None else None
        if callable(stop_method):
            stop_method()
            return True
        return False

    def _wait_for_post_run_settlement(self, runtime, payload):
        cleanup = (payload or {}).get("cleanup") or {}
        return self._wait_for_cleanup_settlement(runtime, cleanup.get("after_run"))

    @staticmethod
    def _pair_error_message(payload):
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or "")
        if error is None:
            return ""
        return str(error)

    def _is_transient_pair_failure(self, payload):
        if not isinstance(payload, dict) or payload.get("status") == "passed":
            return False

        error_message = self._pair_error_message(payload)
        transient_fragments = (
            "NoBrokersAvailable",
            "failed with HTTP 502",
            "failed with HTTP 503",
            "failed with HTTP 504",
            "failed with HTTP 401",
            "Request could not be authenticated",
            "Unable to obtain credentials",
            "did not produce contractAgreementId in time",
            "Kafka transfer path did not relay a probe message in time",
            "No Kafka messages were consumed through the EDC transfer",
            "Kafka transfer consumed only",
            "Kafka offset lookup",
            "Kafka console producer",
            "Kafka console consumer",
            "Kafka consumer group",
        )
        if any(fragment in error_message for fragment in transient_fragments):
            return True

        for step in payload.get("steps", []):
            if (
                step.get("name") == "wait_for_transfer_runtime_stabilization"
                and step.get("strategy") in {
                    "timeout_without_ready_group",
                    "kubernetes_exec_probe_timeout",
                    "probe_timeout",
                }
            ):
                return True
        return False

    def run_pair(self, provider, consumer, experiment_dir=None):
        runtime = self._ensure_kafka_runtime(self._load_kafka_runtime())
        source_topic = self._topic_name(runtime)
        destination_topic = self._destination_topic_name(source_topic)
        suffix = str(self.uuid_factory()).replace("_", "-").lower()[:12]
        broker_source = None
        if self.kafka_manager is not None:
            broker_source = "auto-provisioned" if getattr(self.kafka_manager, "started_by_framework", False) else "external"

        payload = {
            "provider": provider,
            "consumer": consumer,
            "status": "failed",
            "timestamp": datetime.now().isoformat(),
            "bootstrap_servers": runtime.get("host_bootstrap_servers") or runtime.get("bootstrap_servers"),
            "cluster_bootstrap_servers": runtime.get("cluster_bootstrap_servers"),
            "broker_source": broker_source,
            "validation_backend": runtime.get("validation_backend") or "python-client",
            "source_topic": source_topic,
            "destination_topic": destination_topic,
            "steps": [],
            "metrics": None,
            "error": None,
        }

        def record_step(name, status, **details):
            step = {"name": name, "status": status}
            if details:
                step.update(details)
            payload["steps"].append(step)

        provider_jwt = None
        consumer_jwt = None

        try:
            try:
                self._ensure_topic_with_runtime(runtime, source_topic)
                record_step(
                    "ensure_source_topic",
                    "passed",
                    topic=source_topic,
                    method=runtime.pop("_last_topic_ensure_method", "runtime_admin"),
                    bootstrap_servers=runtime.get("host_bootstrap_servers") or runtime.get("bootstrap_servers"),
                )
                self._ensure_topic_with_runtime(runtime, destination_topic)
                record_step(
                    "ensure_destination_topic",
                    "passed",
                    topic=destination_topic,
                    method=runtime.pop("_last_topic_ensure_method", "runtime_admin"),
                    bootstrap_servers=runtime.get("host_bootstrap_servers") or runtime.get("bootstrap_servers"),
                )
            except Exception as admin_exc:
                if callable(self.ensure_kafka_topic):
                    if not self.ensure_kafka_topic(source_topic):
                        raise RuntimeError(f"Kafka topic '{source_topic}' could not be created or verified") from admin_exc
                    record_step(
                        "ensure_source_topic",
                        "passed",
                        topic=source_topic,
                        method="fallback_callable",
                        admin_error=str(admin_exc),
                    )
                    if not self.ensure_kafka_topic(destination_topic):
                        raise RuntimeError(f"Kafka topic '{destination_topic}' could not be created or verified") from admin_exc
                    record_step(
                        "ensure_destination_topic",
                        "passed",
                        topic=destination_topic,
                        method="fallback_callable",
                        admin_error=str(admin_exc),
                    )
                else:
                    raise RuntimeError(f"Kafka topics '{source_topic}'/'{destination_topic}' could not be created or verified") from admin_exc

            provider_jwt = self._login(provider, "provider")
            record_step("provider_login", "passed")
            consumer_jwt = self._login(consumer, "consumer")
            record_step("consumer_login", "passed")
            before_run_cleanup = self._cleanup_kafka_edc_state(provider, consumer, provider_jwt, consumer_jwt)
            payload["cleanup"] = {
                "before_run": before_run_cleanup,
            }
            cleanup_settlement = self._wait_for_cleanup_settlement(runtime, before_run_cleanup)
            if cleanup_settlement.get("status") == "waited":
                record_step(
                    "wait_for_pre_run_cleanup_settlement",
                    "passed",
                    seconds_waited=cleanup_settlement["seconds_waited"],
                )
            provider_jwt = self._login(provider, "provider")
            consumer_jwt = self._login(consumer, "consumer")
            record_step("refresh_credentials_after_cleanup", "passed")

            asset_id, _, asset_status = self._create_asset(provider, provider_jwt, source_topic, runtime, suffix)
            payload["asset_id"] = asset_id
            record_step("create_kafka_asset", "passed", http_status=asset_status, asset_id=asset_id)

            policy_id, _, policy_status = self._create_policy(provider, provider_jwt, suffix)
            payload["policy_id"] = policy_id
            record_step("create_policy", "passed", http_status=policy_status, policy_id=policy_id)

            contract_definition_id, _, contract_status = self._create_contract_definition(
                provider, provider_jwt, asset_id, policy_id, suffix
            )
            payload["contract_definition_id"] = contract_definition_id
            record_step(
                "create_contract_definition",
                "passed",
                http_status=contract_status,
                contract_definition_id=contract_definition_id,
            )

            consumer_jwt = self._login(consumer, "consumer")
            record_step("refresh_consumer_credentials_before_catalog", "passed")
            catalog_body, catalog_status = self._request_catalog(provider, consumer, consumer_jwt)
            catalog_info = self._select_catalog_dataset(catalog_body, asset_id, provider)
            payload["catalog_asset_id"] = catalog_info["catalog_asset_id"]
            payload["offer_id"] = catalog_info["offer_id"]
            payload["provider_participant_id"] = catalog_info["provider_participant_id"]
            record_step(
                "request_catalog",
                "passed",
                http_status=catalog_status,
                catalog_asset_id=catalog_info["catalog_asset_id"],
                offer_id=catalog_info["offer_id"],
            )

            negotiation_id, negotiation_status = self._start_negotiation(provider, consumer, consumer_jwt, catalog_info)
            payload["negotiation_id"] = negotiation_id
            record_step(
                "start_negotiation",
                "passed",
                http_status=negotiation_status,
                negotiation_id=negotiation_id,
            )

            negotiation_result = self._wait_for_agreement(consumer, consumer_jwt, negotiation_id, runtime)
            payload["negotiation_state"] = negotiation_result["state"]
            payload["agreement_id"] = negotiation_result["agreement_id"]
            record_step(
                "wait_for_contract_agreement",
                "passed",
                state=negotiation_result["state"],
                agreement_id=negotiation_result["agreement_id"],
            )

            agreement_visibility = self._wait_for_contract_agreement_visibility(
                provider,
                consumer,
                provider_jwt,
                consumer_jwt,
                negotiation_result["agreement_id"],
                runtime,
            )
            if agreement_visibility.get("status") != "skipped":
                visibility_step = {
                    key: value for key, value in agreement_visibility.items()
                    if key != "status"
                }
                record_step(
                    "wait_for_contract_agreement_visibility",
                    "passed",
                    **visibility_step,
                )

            transfer_id, transfer_status = self._start_transfer(
                provider,
                consumer,
                consumer_jwt,
                asset_id,
                negotiation_result["agreement_id"],
                runtime,
                destination_topic,
            )
            payload["transfer_id"] = transfer_id
            record_step(
                "start_transfer",
                "passed",
                http_status=transfer_status,
                transfer_id=transfer_id,
                transfer_type="Kafka-PUSH",
                destination_topic=destination_topic,
            )

            transfer_result = self._wait_for_transfer_started(consumer, consumer_jwt, transfer_id, runtime)
            payload["transfer_state"] = transfer_result["state"]
            payload["transfer_process"] = transfer_result["raw"]
            record_step(
                "wait_for_transfer_state",
                "passed",
                state=transfer_result["state"],
                continued_after_requested_timeout=bool(
                    transfer_result.get("continued_after_requested_timeout")
                ),
            )

            stabilization = self._wait_for_transfer_runtime_stabilization(
                runtime,
                transfer_result["raw"],
                source_topic,
                destination_topic=destination_topic,
            )
            stabilization_probe = stabilization.get("probe")
            if stabilization.get("strategy") != "disabled":
                stabilization_step = {key: value for key, value in stabilization.items() if key != "probe"}
                stabilization_status = "passed"
                if str(stabilization.get("strategy") or "").endswith("_timeout"):
                    stabilization_status = "warning"
                record_step(
                    "wait_for_transfer_runtime_stabilization",
                    stabilization_status,
                    **stabilization_step,
                )

            metrics = self._measure_transfer_latency(
                runtime,
                source_topic,
                destination_topic,
                probe_result=stabilization_probe,
            )
            payload["metrics"] = metrics
            record_step(
                "measure_kafka_transfer_latency",
                "passed",
                messages_consumed=metrics["messages_consumed"],
                average_latency_ms=metrics["average_latency_ms"],
            )

            payload["status"] = "passed"
            return payload
        except Exception as exc:
            unsupported_kafka = isinstance(exc, KafkaDataAddressUnsupported)
            payload["status"] = "skipped" if unsupported_kafka else "failed"
            if unsupported_kafka:
                payload["reason"] = "kafka_dataaddress_not_supported"
            partial_metrics = getattr(exc, "metrics", None)
            if isinstance(partial_metrics, dict) and partial_metrics:
                payload["metrics"] = partial_metrics
            payload["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            record_step(
                "suite_error",
                "skipped" if unsupported_kafka else "failed",
                error=str(exc),
            )
            return payload
        finally:
            if provider_jwt or consumer_jwt:
                cleanup_payload = payload.setdefault("cleanup", {})
                cleanup_payload["after_run"] = self._cleanup_kafka_edc_state(
                    provider,
                    consumer,
                    provider_jwt,
                    consumer_jwt,
                )
            artifact_path = self._save_pair_artifact(experiment_dir, provider, consumer, payload)
            if artifact_path:
                payload["artifact_path"] = artifact_path

    def run_all(self, connectors, experiment_dir=None, progress_callback=None):
        connectors = list(connectors or [])
        results = []
        settle_runtime = self._load_kafka_runtime()
        pairings = list(permutations(connectors, 2))
        for index, (provider, consumer) in enumerate(pairings):
            result = None
            attempts = 0
            retry_reason = None
            max_attempts = self._runtime_int(
                settle_runtime,
                "pair_attempts",
                self.DEFAULT_PAIR_ATTEMPTS,
                minimum=1,
            )
            retry_seconds = self._runtime_int(
                settle_runtime,
                "pair_retry_seconds",
                self.DEFAULT_PAIR_RETRY_SECONDS,
                minimum=0,
            )

            while attempts < max_attempts:
                attempts += 1
                result = self.run_pair(provider, consumer, experiment_dir=experiment_dir)

                if result.get("status") == "passed":
                    break
                if not self._is_transient_pair_failure(result) or attempts >= max_attempts:
                    break

                retry_reason = self._pair_error_message(result)
                self._wait_for_post_run_settlement(settle_runtime, result)
                self._reset_framework_managed_kafka(settle_runtime, result)
                time.sleep(retry_seconds)

            if result is None:
                continue
            result["attempt_count"] = attempts
            result["retry_attempted"] = attempts > 1
            if retry_reason:
                result["retry_reason"] = retry_reason
                artifact_path = self._save_pair_artifact(experiment_dir, provider, consumer, result)
                if artifact_path:
                    result["artifact_path"] = artifact_path
            results.append(result)
            if callable(progress_callback):
                progress_callback(result)
            if index < len(pairings) - 1:
                self._wait_for_post_run_settlement(settle_runtime, result)
        return results
