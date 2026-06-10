import os
import shlex
import socket
import subprocess
import time
from textwrap import dedent

from .kafka_container_factory import KafkaContainerFactory
from .kafka_testcontainer import FrameworkKafkaContainer


class KafkaManager:
    """Ensures a Kafka broker is available for optional benchmarks."""

    def __init__(
        self,
        bootstrap_servers=None,
        runtime_config=None,
        adapter_config_loader=None,
        container_class=None,
        container_factory=None,
        command_runner=None,
        image="confluentinc/cp-kafka:latest",
        wait_timeout_seconds=90,
        poll_interval_seconds=1,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.runtime_config = runtime_config or {}
        self.adapter_config_loader = adapter_config_loader
        self.container_class = container_class
        self.container_factory = container_factory or KafkaContainerFactory()
        self.command_runner = command_runner or self._default_command_runner
        self.image = image
        self.wait_timeout_seconds = wait_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.container = None
        self.port_forward_process = None
        self.started_by_framework = False
        self.last_error = None
        self.cluster_bootstrap_servers = None
        self.provisioning_mode = None

    @staticmethod
    def _default_command_runner(args, input_text=None, timeout=None, env=None):
        return subprocess.run(
            args,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=env,
        )

    def _load_adapter_config(self):
        if callable(self.adapter_config_loader):
            config = self.adapter_config_loader()
            return config if isinstance(config, dict) else {}
        if isinstance(self.adapter_config_loader, dict):
            return self.adapter_config_loader
        return {}

    def _candidate_bootstrap_servers(self):
        candidates = []
        env_bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        env_cluster_bootstrap = os.getenv("KAFKA_CLUSTER_BOOTSTRAP_SERVERS")
        adapter_config = self._load_adapter_config()
        adapter_bootstrap = adapter_config.get("bootstrap_servers")
        adapter_cluster_bootstrap = adapter_config.get("cluster_bootstrap_servers")
        runtime_bootstrap = self.runtime_config.get("bootstrap_servers")
        runtime_cluster_bootstrap = self.runtime_config.get("cluster_bootstrap_servers")

        for candidate in (
            env_bootstrap,
            runtime_bootstrap,
            adapter_bootstrap,
            self.bootstrap_servers,
            env_cluster_bootstrap,
            runtime_cluster_bootstrap,
            adapter_cluster_bootstrap,
        ):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _load_manager_config(self):
        config = {}
        config.update(self._load_adapter_config())
        config.update(self.runtime_config)
        config.setdefault("provisioner", config.get("provisioner") or "kubernetes")
        config.setdefault("cluster_advertised_host", config.get("cluster_advertised_host") or "host.minikube.internal")
        config.setdefault("k8s_namespace", config.get("k8s_namespace") or "demo")
        config.setdefault("k8s_service_name", config.get("k8s_service_name") or "framework-kafka")
        config.setdefault("k8s_nodeport", config.get("k8s_nodeport") or "32092")
        config.setdefault("k8s_local_port", config.get("k8s_local_port") or config.get("k8s_nodeport") or "39092")
        config.setdefault("minikube_profile", config.get("minikube_profile") or "minikube")
        return config

    def _provisioner(self):
        return str(self._load_manager_config().get("provisioner") or "kubernetes").strip().lower()

    @staticmethod
    def _truthy(value):
        return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _is_kubernetes_provisioner(provisioner):
        normalized = str(provisioner or "").strip().lower()
        return normalized in {"kubernetes", "kubernetes-split-kraft"}

    def _has_connector_visible_bootstrap(self, config):
        for candidate in (
            os.getenv("KAFKA_BOOTSTRAP_SERVERS"),
            os.getenv("KAFKA_CLUSTER_BOOTSTRAP_SERVERS"),
            config.get("bootstrap_servers"),
            config.get("cluster_bootstrap_servers"),
        ):
            if str(candidate or "").strip():
                return True
        return False

    def _skips_vm_distributed_internal_autoprovision(self, config):
        topology = str(config.get("topology") or "").strip().lower()
        if topology != "vm-distributed":
            return False
        if not self._is_kubernetes_provisioner(config.get("provisioner")):
            return False
        external_service_type = str(config.get("k8s_external_service_type") or "").strip().lower()
        if external_service_type in {"nodeport", "loadbalancer"} and self._has_connector_visible_bootstrap(config):
            return False
        if self._truthy(
            config.get("allow_internal_clusterip")
            or os.getenv("KAFKA_VM_DISTRIBUTED_ALLOW_INTERNAL_CLUSTERIP")
        ):
            return False
        return True

    def _requires_configured_kubernetes_external_service(self, config):
        topology = str(config.get("topology") or "").strip().lower()
        if topology != "vm-distributed":
            return False
        if not self._is_kubernetes_provisioner(config.get("provisioner")):
            return False
        external_service_type = str(config.get("k8s_external_service_type") or "").strip().lower()
        return external_service_type in {"nodeport", "loadbalancer"}

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
    def _parse_host_port(address):
        address = str(address).strip()
        if "://" in address:
            address = address.split("://", 1)[1]
        if address.count(":") > 1 and address.startswith("["):
            host, _, port = address.rpartition(":")
            return host.strip("[]"), int(port or 9092)
        if ":" in address:
            host, port = address.rsplit(":", 1)
            return host, int(port or 9092)
        return address, 9092

    @classmethod
    def is_kafka_available(cls, bootstrap_servers):
        """Attempt a basic TCP connection to determine broker availability."""
        for address in cls._normalize_bootstrap_servers(bootstrap_servers):
            try:
                host, port = cls._parse_host_port(address)
                with socket.create_connection((host, port), timeout=2):
                    return True
            except Exception:
                continue
        return False

    def _load_container_class(self):
        if self.container_class is not None:
            return self.container_class

        try:
            return FrameworkKafkaContainer
        except Exception as exc:
            raise RuntimeError(
                f"testcontainers Kafka support is not available: {exc}"
            ) from exc

    def _command_environment(self):
        kubeconfig = str((self._load_manager_config() or {}).get("k8s_kubeconfig") or "").strip()
        if not kubeconfig:
            return None
        env = os.environ.copy()
        env["KUBECONFIG"] = os.path.abspath(os.path.expanduser(kubeconfig))
        role = str((self._load_manager_config() or {}).get("k8s_kubeconfig_role") or "common").strip()
        if role:
            env["PIONERA_KUBECONFIG_ROLE"] = role
        return env

    def _call_command_runner(self, args, input_text=None, timeout=None):
        env = self._command_environment()
        try:
            return self.command_runner(args, input_text=input_text, timeout=timeout, env=env)
        except TypeError:
            try:
                return self.command_runner(args, input_text=input_text, timeout=timeout)
            except TypeError:
                return self.command_runner(args, input_text=input_text)

    def _run_command(self, args, input_text=None, timeout=None):
        result = self._call_command_runner(args, input_text=input_text, timeout=timeout)
        if getattr(result, "returncode", 1) != 0:
            stdout = (getattr(result, "stdout", "") or "").strip()
            stderr = (getattr(result, "stderr", "") or "").strip()
            combined = "\n".join(part for part in (stdout, stderr) if part).strip()
            raise RuntimeError(combined or f"Command failed: {' '.join(args)}")
        return result

    @staticmethod
    def _is_nodeport_already_allocated_error(error):
        text = str(error or "").lower()
        return "nodeport" in text and ("already allocated" in text or "provided port is already allocated" in text)

    def _resolve_minikube_ip(self, config):
        configured_ip = str(config.get("minikube_ip") or "").strip()
        if configured_ip:
            return configured_ip
        profile = str(config.get("minikube_profile") or "minikube").strip() or "minikube"
        try:
            result = self._run_command(["minikube", "-p", profile, "ip"])
            resolved_ip = (getattr(result, "stdout", "") or "").strip()
            if resolved_ip:
                return resolved_ip
        except Exception:
            pass
        return "192.168.49.2"

    def _kubernetes_identifiers(self, config):
        provisioner = str(config.get("provisioner") or "kubernetes").strip().lower() or "kubernetes"
        split_kraft = provisioner == "kubernetes-split-kraft"
        namespace = str(config.get("k8s_namespace") or "demo").strip() or "demo"
        service_name = str(config.get("k8s_service_name") or "framework-kafka").strip() or "framework-kafka"
        local_port = int(str(config.get("k8s_local_port") or "39092").strip() or "39092")
        nodeport = int(str(config.get("k8s_nodeport") or "32092").strip() or "32092")
        external_service_type = str(config.get("k8s_external_service_type") or "ClusterIP").strip() or "ClusterIP"
        internal_bootstrap = f"{service_name}.{namespace}.svc.cluster.local:9092"
        external_bootstrap = f"127.0.0.1:{local_port}"
        probe_namespaces = self._normalize_kubernetes_probe_namespaces(
            config.get("k8s_probe_namespaces"),
            namespace,
        )
        return {
            "provisioner": provisioner,
            "split_kraft": split_kraft,
            "namespace": namespace,
            "probe_namespaces": probe_namespaces,
            "service_name": service_name,
            "external_service_name": f"{service_name}-external",
            "external_service_type": external_service_type,
            "deployment_name": service_name,
            "controller_service_name": f"{service_name}-controller",
            "controller_deployment_name": f"{service_name}-controller",
            "controller_bootstrap": f"{service_name}-controller.{namespace}.svc.cluster.local:9093",
            "controller_node_id": int(str(config.get("k8s_controller_node_id") or "3000").strip() or "3000"),
            "broker_node_id": int(str(config.get("k8s_broker_node_id") or "1").strip() or "1"),
            "nodeport": nodeport,
            "local_port": local_port,
            "internal_bootstrap": internal_bootstrap,
            "external_service_bootstrap": f"{service_name}-external.{namespace}.svc.cluster.local:9094",
            "external_bootstrap": external_bootstrap,
        }

    def _kubernetes_external_advertised_bootstrap(self, config, ids):
        configured = self._normalize_bootstrap_servers(config.get("cluster_bootstrap_servers"))
        if configured:
            return configured[0]
        return ids["external_bootstrap"]

    def _kubernetes_connector_bootstrap(self, config, ids):
        configured = self._normalize_bootstrap_servers(config.get("cluster_bootstrap_servers"))
        if configured:
            return configured[0]
        return ids["internal_bootstrap"]

    @staticmethod
    def _kubernetes_external_service_type(ids):
        service_type = str(ids.get("external_service_type") or "ClusterIP").strip() or "ClusterIP"
        normalized = service_type.lower()
        if normalized == "nodeport":
            return "NodePort"
        if normalized == "loadbalancer":
            return "LoadBalancer"
        return "ClusterIP"

    def _kubernetes_external_service_nodeport_yaml(self, ids):
        if self._kubernetes_external_service_type(ids) != "NodePort":
            return ""
        return f"\n                nodePort: {ids['nodeport']}"

    @staticmethod
    def _normalize_kubernetes_probe_namespaces(raw_namespaces, kafka_namespace):
        if isinstance(raw_namespaces, (list, tuple, set)):
            candidates = raw_namespaces
        else:
            candidates = str(raw_namespaces or "").split(",")

        namespaces = []
        for candidate in candidates:
            namespace = str(candidate or "").strip()
            if namespace and namespace not in namespaces:
                namespaces.append(namespace)

        kafka_namespace = str(kafka_namespace or "").strip()
        if kafka_namespace and kafka_namespace not in namespaces:
            namespaces.append(kafka_namespace)
        return namespaces

    @staticmethod
    def _kubernetes_cluster_id():
        return "MkU3OEVBNTcwNTJENDM2Qk"

    def _ensure_topic_in_kubernetes(self, topic_name, *, partitions=1, replication_factor=1):
        ids = self._kubernetes_identifiers(self._load_manager_config())
        exec_prefix = [
            "kubectl",
            "exec",
            "-n",
            ids["namespace"],
            f"deployment/{ids['deployment_name']}",
            "--",
            "kafka-topics",
            "--bootstrap-server",
            "localhost:9092",
        ]

        list_result = self._run_command(exec_prefix + ["--list"])
        existing_topics = set((getattr(list_result, "stdout", "") or "").splitlines())
        if topic_name in existing_topics:
            return True

        self._run_command(
            exec_prefix
            + [
                "--create",
                "--if-not-exists",
                "--topic",
                topic_name,
                "--partitions",
                str(int(partitions or 1)),
                "--replication-factor",
                str(int(replication_factor or 1)),
            ]
        )

        verify_result = self._run_command(exec_prefix + ["--list"])
        verified_topics = set((getattr(verify_result, "stdout", "") or "").splitlines())
        return topic_name in verified_topics

    def ensure_topic(self, topic_name, *, partitions=1, replication_factor=1):
        if not str(topic_name or "").strip():
            return False

        if bool(self.started_by_framework) and self._is_kubernetes_provisioner(self.provisioning_mode):
            return self._ensure_topic_in_kubernetes(
                str(topic_name).strip(),
                partitions=partitions,
                replication_factor=replication_factor,
            )

        return False

    @staticmethod
    def _kubernetes_resource_refs(ids):
        refs = []
        if ids.get("split_kraft"):
            refs.extend(
                [
                    f"deployment/{ids['controller_deployment_name']}",
                    f"service/{ids['controller_service_name']}",
                ]
            )
        refs.extend(
            [
                f"deployment/{ids['deployment_name']}",
                f"service/{ids['service_name']}",
                f"service/{ids['external_service_name']}",
            ]
        )
        return refs

    @staticmethod
    def _kubernetes_stale_resource_refs(ids):
        if ids.get("split_kraft"):
            return []
        return [
            f"deployment/{ids['controller_deployment_name']}",
            f"service/{ids['controller_service_name']}",
        ]

    def _cleanup_stale_kubernetes_resources(self, ids):
        stale_refs = self._kubernetes_stale_resource_refs(ids)
        if not stale_refs:
            return
        self._run_command(
            ["kubectl", "delete"]
            + stale_refs
            + ["-n", ids["namespace"], "--ignore-not-found=true"]
        )

    @staticmethod
    def _kubernetes_rollout_targets(ids):
        targets = []
        if ids.get("split_kraft"):
            targets.append(f"deployment/{ids['controller_deployment_name']}")
        targets.append(f"deployment/{ids['deployment_name']}")
        return targets

    @staticmethod
    def _kubernetes_probe_excluded_prefixes(ids):
        prefixes = [ids["deployment_name"]]
        if ids.get("split_kraft"):
            prefixes.append(ids["controller_deployment_name"])
        return tuple(prefixes)

    def _build_kubernetes_manifest(self, config):
        ids = self._kubernetes_identifiers(config)
        if ids.get("split_kraft"):
            return self._build_kubernetes_split_kraft_manifest(config, ids)
        return self._build_kubernetes_combined_manifest(config, ids)

    @staticmethod
    def _config_value(config, key, default):
        value = (config or {}).get(key)
        if value in (None, ""):
            return default
        return str(value)

    def _kubernetes_resources_yaml(self, config, indent="                    "):
        cpu_request = self._config_value(config, "k8s_cpu_request", "500m")
        memory_request = self._config_value(config, "k8s_memory_request", "1Gi")
        cpu_limit = self._config_value(config, "k8s_cpu_limit", "")
        memory_limit = self._config_value(config, "k8s_memory_limit", "")
        lines = [
            f"{indent}resources:",
            f"{indent}  requests:",
            f"{indent}    cpu: \"{cpu_request}\"",
            f"{indent}    memory: \"{memory_request}\"",
        ]
        if cpu_limit or memory_limit:
            lines.append(f"{indent}  limits:")
            if cpu_limit:
                lines.append(f"{indent}    cpu: \"{cpu_limit}\"")
            if memory_limit:
                lines.append(f"{indent}    memory: \"{memory_limit}\"")
        return "\n".join(lines)

    def _kafka_heap_env_yaml(self, config, indent="                    "):
        heap_opts = self._config_value(config, "kafka_heap_opts", "")
        if not heap_opts:
            return ""
        return f'{indent}- name: KAFKA_HEAP_OPTS\n{indent}  value: "{heap_opts}"\n'

    def _kafka_broker_heartbeat_interval_ms(self, config):
        return self._config_value(config, "kafka_broker_heartbeat_interval_ms", "3000")

    def _kafka_broker_session_timeout_ms(self, config):
        return self._config_value(config, "kafka_broker_session_timeout_ms", "60000")

    def _kafka_controller_quorum_request_timeout_ms(self, config):
        return self._config_value(config, "kafka_controller_quorum_request_timeout_ms", "30000")

    def _kafka_initial_broker_registration_timeout_ms(self, config):
        return self._config_value(config, "kafka_initial_broker_registration_timeout_ms", "120000")

    def _kafka_group_initial_rebalance_delay_ms(self, config):
        return self._config_value(config, "kafka_group_initial_rebalance_delay_ms", "0")

    def _build_kubernetes_combined_manifest(self, config, ids=None):
        ids = ids or self._kubernetes_identifiers(config)
        image = str(config.get("container_image") or self.image)
        service_name = ids["service_name"]
        deployment_name = ids["deployment_name"]
        namespace = ids["namespace"]
        external_service_name = ids["external_service_name"]
        external_bootstrap = self._kubernetes_external_advertised_bootstrap(config, ids)
        internal_bootstrap = ids["internal_bootstrap"]
        external_service_type = self._kubernetes_external_service_type(ids)
        external_service_nodeport = self._kubernetes_external_service_nodeport_yaml(ids)
        cluster_id = self._kubernetes_cluster_id()
        resources_yaml = self._kubernetes_resources_yaml(config)
        heap_env_yaml = self._kafka_heap_env_yaml(config)
        heartbeat_interval_ms = self._kafka_broker_heartbeat_interval_ms(config)
        session_timeout_ms = self._kafka_broker_session_timeout_ms(config)
        quorum_request_timeout_ms = self._kafka_controller_quorum_request_timeout_ms(config)
        broker_registration_timeout_ms = self._kafka_initial_broker_registration_timeout_ms(config)
        rebalance_delay_ms = self._kafka_group_initial_rebalance_delay_ms(config)
        return dedent(
            f"""
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: {deployment_name}
              namespace: {namespace}
              labels:
                app: {service_name}
                managed-by: inesdata-framework
            spec:
              replicas: 1
              strategy:
                type: Recreate
              selector:
                matchLabels:
                  app: {service_name}
              template:
                metadata:
                  labels:
                    app: {service_name}
                    managed-by: inesdata-framework
                spec:
                  containers:
                  - name: kafka
                    image: {image}
                    imagePullPolicy: IfNotPresent
                    ports:
                    - containerPort: 9092
                      name: internal
                    - containerPort: 9093
                      name: controller
                    - containerPort: 9094
                      name: external
                    env:
                    - name: CLUSTER_ID
                      value: "{cluster_id}"
{heap_env_yaml}                    - name: KAFKA_NODE_ID
                      value: "1"
                    - name: KAFKA_PROCESS_ROLES
                      value: "broker,controller"
                    - name: KAFKA_LISTENERS
                      value: "INTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093,EXTERNAL://0.0.0.0:9094"
                    - name: KAFKA_ADVERTISED_LISTENERS
                      value: "INTERNAL://{internal_bootstrap},EXTERNAL://{external_bootstrap}"
                    - name: KAFKA_LISTENER_SECURITY_PROTOCOL_MAP
                      value: "INTERNAL:PLAINTEXT,CONTROLLER:PLAINTEXT,EXTERNAL:PLAINTEXT"
                    - name: KAFKA_INTER_BROKER_LISTENER_NAME
                      value: "INTERNAL"
                    - name: KAFKA_CONTROLLER_LISTENER_NAMES
                      value: "CONTROLLER"
                    - name: KAFKA_CONTROLLER_QUORUM_VOTERS
                      value: "1@localhost:9093"
                    - name: KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR
                      value: "1"
                    - name: KAFKA_OFFSETS_TOPIC_NUM_PARTITIONS
                      value: "1"
                    - name: KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR
                      value: "1"
                    - name: KAFKA_TRANSACTION_STATE_LOG_NUM_PARTITIONS
                      value: "1"
                    - name: KAFKA_TRANSACTION_STATE_LOG_MIN_ISR
                      value: "1"
                    - name: KAFKA_BROKER_HEARTBEAT_INTERVAL_MS
                      value: "{heartbeat_interval_ms}"
                    - name: KAFKA_BROKER_SESSION_TIMEOUT_MS
                      value: "{session_timeout_ms}"
                    - name: KAFKA_CONTROLLER_QUORUM_REQUEST_TIMEOUT_MS
                      value: "{quorum_request_timeout_ms}"
                    - name: KAFKA_INITIAL_BROKER_REGISTRATION_TIMEOUT_MS
                      value: "{broker_registration_timeout_ms}"
                    - name: KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS
                      value: "{rebalance_delay_ms}"
                    - name: KAFKA_AUTO_CREATE_TOPICS_ENABLE
                      value: "true"
                    - name: KAFKA_LOG_DIRS
                      value: "/var/lib/kafka/data/kraft-combined-logs"
{resources_yaml}
                    startupProbe:
                      tcpSocket:
                        port: 9092
                      periodSeconds: 5
                      failureThreshold: 24
                    readinessProbe:
                      tcpSocket:
                        port: 9092
                      initialDelaySeconds: 5
                      periodSeconds: 5
                      failureThreshold: 6
                    livenessProbe:
                      tcpSocket:
                        port: 9092
                      periodSeconds: 15
                      failureThreshold: 6
                    volumeMounts:
                    - name: kafka-data
                      mountPath: /var/lib/kafka/data
                  volumes:
                  - name: kafka-data
                    emptyDir: {{}}
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: {service_name}
              namespace: {namespace}
              labels:
                app: {service_name}
                managed-by: inesdata-framework
            spec:
              selector:
                app: {service_name}
              ports:
              - name: internal
                port: 9092
                targetPort: 9092
              type: ClusterIP
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: {external_service_name}
              namespace: {namespace}
              labels:
                app: {service_name}
                managed-by: inesdata-framework
            spec:
              selector:
                app: {service_name}
              ports:
              - name: external
                port: 9094
                targetPort: 9094{external_service_nodeport}
              type: {external_service_type}
            """
        ).strip()

    def _build_kubernetes_split_kraft_manifest(self, config, ids=None):
        ids = ids or self._kubernetes_identifiers(config)
        image = str(config.get("container_image") or self.image)
        service_name = ids["service_name"]
        deployment_name = ids["deployment_name"]
        namespace = ids["namespace"]
        controller_service_name = ids["controller_service_name"]
        controller_deployment_name = ids["controller_deployment_name"]
        external_service_name = ids["external_service_name"]
        external_bootstrap = self._kubernetes_external_advertised_bootstrap(config, ids)
        internal_bootstrap = ids["internal_bootstrap"]
        controller_bootstrap = ids["controller_bootstrap"]
        controller_node_id = ids["controller_node_id"]
        broker_node_id = ids["broker_node_id"]
        external_service_type = self._kubernetes_external_service_type(ids)
        external_service_nodeport = self._kubernetes_external_service_nodeport_yaml(ids)
        cluster_id = self._kubernetes_cluster_id()
        resources_yaml = self._kubernetes_resources_yaml(config)
        heap_env_yaml = self._kafka_heap_env_yaml(config)
        heartbeat_interval_ms = self._kafka_broker_heartbeat_interval_ms(config)
        session_timeout_ms = self._kafka_broker_session_timeout_ms(config)
        quorum_request_timeout_ms = self._kafka_controller_quorum_request_timeout_ms(config)
        broker_registration_timeout_ms = self._kafka_initial_broker_registration_timeout_ms(config)
        rebalance_delay_ms = self._kafka_group_initial_rebalance_delay_ms(config)
        return dedent(
            f"""
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: {controller_deployment_name}
              namespace: {namespace}
              labels:
                app: {controller_service_name}
                managed-by: inesdata-framework
                kafka-role: controller
            spec:
              replicas: 1
              strategy:
                type: Recreate
              selector:
                matchLabels:
                  app: {controller_service_name}
              template:
                metadata:
                  labels:
                    app: {controller_service_name}
                    managed-by: inesdata-framework
                    kafka-role: controller
                spec:
                  containers:
                  - name: kafka-controller
                    image: {image}
                    imagePullPolicy: IfNotPresent
                    ports:
                    - containerPort: 9093
                      name: controller
                    env:
                    - name: CLUSTER_ID
                      value: "{cluster_id}"
{heap_env_yaml}                    - name: KAFKA_NODE_ID
                      value: "{controller_node_id}"
                    - name: KAFKA_PROCESS_ROLES
                      value: "controller"
                    - name: KAFKA_LISTENERS
                      value: "CONTROLLER://0.0.0.0:9093"
                    - name: KAFKA_LISTENER_SECURITY_PROTOCOL_MAP
                      value: "CONTROLLER:PLAINTEXT"
                    - name: KAFKA_CONTROLLER_LISTENER_NAMES
                      value: "CONTROLLER"
                    - name: KAFKA_CONTROLLER_QUORUM_VOTERS
                      value: "{controller_node_id}@{controller_bootstrap}"
                    - name: KAFKA_CONTROLLER_QUORUM_REQUEST_TIMEOUT_MS
                      value: "{quorum_request_timeout_ms}"
                    - name: KAFKA_LOG_DIRS
                      value: "/var/lib/kafka/data/kraft-controller-logs"
{resources_yaml}
                    startupProbe:
                      tcpSocket:
                        port: 9093
                      periodSeconds: 5
                      failureThreshold: 24
                    readinessProbe:
                      tcpSocket:
                        port: 9093
                      initialDelaySeconds: 5
                      periodSeconds: 5
                      failureThreshold: 6
                    livenessProbe:
                      tcpSocket:
                        port: 9093
                      periodSeconds: 15
                      failureThreshold: 6
                    volumeMounts:
                    - name: kafka-data
                      mountPath: /var/lib/kafka/data
                  volumes:
                  - name: kafka-data
                    emptyDir: {{}}
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: {controller_service_name}
              namespace: {namespace}
              labels:
                app: {controller_service_name}
                managed-by: inesdata-framework
                kafka-role: controller
            spec:
              selector:
                app: {controller_service_name}
              ports:
              - name: controller
                port: 9093
                targetPort: 9093
              type: ClusterIP
            ---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: {deployment_name}
              namespace: {namespace}
              labels:
                app: {service_name}
                managed-by: inesdata-framework
                kafka-role: broker
            spec:
              replicas: 1
              strategy:
                type: Recreate
              selector:
                matchLabels:
                  app: {service_name}
              template:
                metadata:
                  labels:
                    app: {service_name}
                    managed-by: inesdata-framework
                    kafka-role: broker
                spec:
                  containers:
                  - name: kafka
                    image: {image}
                    imagePullPolicy: IfNotPresent
                    ports:
                    - containerPort: 9092
                      name: internal
                    - containerPort: 9094
                      name: external
                    env:
                    - name: CLUSTER_ID
                      value: "{cluster_id}"
{heap_env_yaml}                    - name: KAFKA_NODE_ID
                      value: "{broker_node_id}"
                    - name: KAFKA_PROCESS_ROLES
                      value: "broker"
                    - name: KAFKA_LISTENERS
                      value: "INTERNAL://0.0.0.0:9092,EXTERNAL://0.0.0.0:9094"
                    - name: KAFKA_ADVERTISED_LISTENERS
                      value: "INTERNAL://{internal_bootstrap},EXTERNAL://{external_bootstrap}"
                    - name: KAFKA_LISTENER_SECURITY_PROTOCOL_MAP
                      value: "INTERNAL:PLAINTEXT,CONTROLLER:PLAINTEXT,EXTERNAL:PLAINTEXT"
                    - name: KAFKA_INTER_BROKER_LISTENER_NAME
                      value: "INTERNAL"
                    - name: KAFKA_CONTROLLER_LISTENER_NAMES
                      value: "CONTROLLER"
                    - name: KAFKA_CONTROLLER_QUORUM_VOTERS
                      value: "{controller_node_id}@{controller_bootstrap}"
                    - name: KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR
                      value: "1"
                    - name: KAFKA_OFFSETS_TOPIC_NUM_PARTITIONS
                      value: "1"
                    - name: KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR
                      value: "1"
                    - name: KAFKA_TRANSACTION_STATE_LOG_NUM_PARTITIONS
                      value: "1"
                    - name: KAFKA_TRANSACTION_STATE_LOG_MIN_ISR
                      value: "1"
                    - name: KAFKA_BROKER_HEARTBEAT_INTERVAL_MS
                      value: "{heartbeat_interval_ms}"
                    - name: KAFKA_BROKER_SESSION_TIMEOUT_MS
                      value: "{session_timeout_ms}"
                    - name: KAFKA_CONTROLLER_QUORUM_REQUEST_TIMEOUT_MS
                      value: "{quorum_request_timeout_ms}"
                    - name: KAFKA_INITIAL_BROKER_REGISTRATION_TIMEOUT_MS
                      value: "{broker_registration_timeout_ms}"
                    - name: KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS
                      value: "{rebalance_delay_ms}"
                    - name: KAFKA_AUTO_CREATE_TOPICS_ENABLE
                      value: "true"
                    - name: KAFKA_LOG_DIRS
                      value: "/var/lib/kafka/data/kraft-broker-logs"
{resources_yaml}
                    startupProbe:
                      tcpSocket:
                        port: 9092
                      periodSeconds: 5
                      failureThreshold: 24
                    readinessProbe:
                      tcpSocket:
                        port: 9092
                      initialDelaySeconds: 5
                      periodSeconds: 5
                      failureThreshold: 6
                    livenessProbe:
                      tcpSocket:
                        port: 9092
                      periodSeconds: 15
                      failureThreshold: 6
                    volumeMounts:
                    - name: kafka-data
                      mountPath: /var/lib/kafka/data
                  volumes:
                  - name: kafka-data
                    emptyDir: {{}}
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: {service_name}
              namespace: {namespace}
              labels:
                app: {service_name}
                managed-by: inesdata-framework
            spec:
              selector:
                app: {service_name}
              ports:
              - name: internal
                port: 9092
                targetPort: 9092
              type: ClusterIP
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: {external_service_name}
              namespace: {namespace}
              labels:
                app: {service_name}
                managed-by: inesdata-framework
            spec:
              selector:
                app: {service_name}
              ports:
              - name: external
                port: 9094
                targetPort: 9094{external_service_nodeport}
              type: {external_service_type}
            """
        ).strip()

    def _stop_kubernetes_port_forward(self):
        if self.port_forward_process is None:
            return
        try:
            if self.port_forward_process.poll() is None:
                self.port_forward_process.terminate()
                try:
                    self.port_forward_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.port_forward_process.kill()
        finally:
            self.port_forward_process = None

    def _start_kubernetes_port_forward(self, ids, restart_existing=False):
        if restart_existing:
            self._stop_kubernetes_port_forward()

        if self.port_forward_process is not None and self.port_forward_process.poll() is None:
            return self.port_forward_process

        command = [
            "kubectl",
            "port-forward",
            "-n",
            ids["namespace"],
            f"service/{ids['external_service_name']}",
            f"{ids['local_port']}:9094",
        ]
        self.port_forward_process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            # kubectl port-forward writes connection traces to stderr; if that
            # stream is piped but never drained, the forward can block mid-run.
            stderr=subprocess.DEVNULL,
            text=True,
            env=self._command_environment(),
        )

        deadline = time.time() + self.wait_timeout_seconds
        while time.time() < deadline:
            if self.port_forward_process.poll() is not None:
                raise RuntimeError("Kafka port-forward process exited unexpectedly")
            if self.is_kafka_available(ids["external_bootstrap"]):
                return self.port_forward_process
            time.sleep(self.poll_interval_seconds)

        raise RuntimeError("Kafka port-forward did not expose the external bootstrap server in time")

    def _kubernetes_resources_exist(self, ids):
        try:
            self._run_command(["kubectl", "get"] + self._kubernetes_resource_refs(ids) + ["-n", ids["namespace"]])
            return True
        except Exception:
            return False

    def _kubernetes_external_service_exists(self, ids):
        try:
            self._run_command(
                [
                    "kubectl",
                    "get",
                    "service",
                    ids["external_service_name"],
                    "-n",
                    ids["namespace"],
                ]
            )
            return True
        except Exception:
            return False

    def _list_kubernetes_probe_pods(self, namespace, excluded_prefixes=None):
        excluded_prefixes = tuple(excluded_prefixes or ())
        result = self._run_command(["kubectl", "get", "pods", "-n", namespace, "--no-headers"])
        pods = []
        for line in (getattr(result, "stdout", "") or "").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            name, ready, status = parts[0], parts[1], parts[2]
            if excluded_prefixes and any(name.startswith(prefix) for prefix in excluded_prefixes):
                continue
            if status != "Running":
                continue
            if "/" in ready:
                try:
                    ready_count, total_count = ready.split("/", 1)
                    if int(ready_count) < int(total_count):
                        continue
                except Exception:
                    pass
            pods.append(name)
        return pods

    def _wait_for_kubernetes_internal_bootstrap(self, ids):
        host, port = self._parse_host_port(ids["internal_bootstrap"])
        return self._wait_for_kubernetes_namespace_listener(
            ids,
            host=host,
            port=port,
            listener_label="internal bootstrap server",
        )

    def _wait_for_kubernetes_external_service_bootstrap(self, ids):
        host, port = self._parse_host_port(ids["external_service_bootstrap"])
        return self._wait_for_kubernetes_namespace_listener(
            ids,
            host=host,
            port=port,
            listener_label="external service listener",
        )

    @staticmethod
    def _kubernetes_listener_probe_script(host, port):
        host_value = str(host)
        port_value = str(int(port))
        nc_host = shlex.quote(host_value)
        bash_probe = shlex.quote(f"</dev/tcp/{host_value}/{port_value}")
        return (
            "if command -v nc >/dev/null 2>&1; then "
            f"nc -vz -w 3 {nc_host} {port_value} >/dev/null 2>&1; "
            "elif command -v bash >/dev/null 2>&1; then "
            "if command -v timeout >/dev/null 2>&1; then "
            f"timeout 3 bash -lc {bash_probe}; "
            "else "
            f"bash -lc {bash_probe}; "
            "fi; "
            "else "
            "exit 127; "
            "fi"
        )

    def _wait_for_kubernetes_namespace_listener(self, ids, *, host, port, listener_label):
        deadline = time.time() + self.wait_timeout_seconds
        excluded_prefixes = self._kubernetes_probe_excluded_prefixes(ids)
        probe_namespaces = ids.get("probe_namespaces") or [ids["namespace"]]

        while time.time() < deadline:
            namespace_pods = []
            for namespace in probe_namespaces:
                try:
                    pods = self._list_kubernetes_probe_pods(namespace, excluded_prefixes=excluded_prefixes)
                except Exception:
                    pods = []
                if pods:
                    namespace_pods.append((namespace, pods))

            namespace_pods.sort(
                key=lambda item: 0 if any(pod.startswith("conn-") for pod in item[1]) else 1
            )

            for namespace, pods in namespace_pods:
                preferred_pods = [pod for pod in pods if pod.startswith("conn-")]
                candidate_pods = preferred_pods or pods

                for pod_name in candidate_pods:
                    probe_command = self._kubernetes_listener_probe_script(host, port)
                    result = self._call_command_runner(
                        [
                            "kubectl",
                            "exec",
                            "-n",
                            namespace,
                            pod_name,
                            "--",
                            "sh",
                            "-lc",
                            probe_command,
                        ]
                    )
                    if getattr(result, "returncode", 1) == 0:
                        return {
                            "namespace": namespace,
                            "pod": pod_name,
                            "host": host,
                            "port": port,
                            "listener": listener_label,
                        }
            time.sleep(self.poll_interval_seconds)

        raise RuntimeError(
            f"Kafka {listener_label} did not become reachable from namespace pods in time "
            f"(probe namespaces: {', '.join(probe_namespaces)})"
        )

    def _start_kafka_kubernetes(self):
        config = self._load_manager_config()
        manifest = self._build_kubernetes_manifest(config)
        ids = self._kubernetes_identifiers(config)
        connector_bootstrap = self._kubernetes_connector_bootstrap(config, ids)
        self.bootstrap_servers = ids["external_bootstrap"]
        self.cluster_bootstrap_servers = connector_bootstrap
        self.provisioning_mode = ids["provisioner"]
        rollout_error = None

        self._cleanup_stale_kubernetes_resources(ids)
        try:
            self._run_command(["kubectl", "apply", "-f", "-"], input_text=manifest)
        except Exception as exc:
            if not self._is_nodeport_already_allocated_error(exc):
                raise
            recovered_bootstrap = self._recover_existing_kubernetes_runtime()
            if recovered_bootstrap:
                return recovered_bootstrap
            raise
        rollout_errors = []
        for rollout_target in self._kubernetes_rollout_targets(ids):
            try:
                self._run_command(
                    [
                        "kubectl",
                        "rollout",
                        "status",
                        rollout_target,
                        "-n",
                        ids["namespace"],
                        f"--timeout={self.wait_timeout_seconds}s",
                    ]
                )
            except Exception as exc:
                rollout_errors.append(f"{rollout_target}: {exc}")
        if rollout_errors:
            rollout_error = "; ".join(rollout_errors)

        try:
            self._wait_for_kubernetes_internal_bootstrap(ids)
            self._wait_for_kubernetes_external_service_bootstrap(ids)
            self._start_kubernetes_port_forward(ids)
        except Exception as exc:
            if rollout_error:
                raise RuntimeError(f"{exc}. Earlier deployment rollout error: {rollout_error}") from exc
            raise

        deadline = time.time() + self.wait_timeout_seconds
        while time.time() < deadline:
            if self.is_kafka_available(ids["external_bootstrap"]):
                self.container = None
                self.started_by_framework = True
                self.bootstrap_servers = ids["external_bootstrap"]
                self.cluster_bootstrap_servers = connector_bootstrap
                self.provisioning_mode = ids["provisioner"]
                self.last_error = None
                return ids["external_bootstrap"]
            time.sleep(self.poll_interval_seconds)

        if rollout_error:
            raise RuntimeError(
                "Kafka Kubernetes broker was deployed but the external bootstrap server did not become reachable in time. "
                f"Earlier deployment rollout error: {rollout_error}"
            )
        raise RuntimeError("Kafka Kubernetes broker was deployed but the external bootstrap server did not become reachable in time")

    def _recover_existing_kubernetes_runtime(self):
        config = self._load_manager_config()
        ids = self._kubernetes_identifiers(config)
        connector_bootstrap = self._kubernetes_connector_bootstrap(config, ids)
        for candidate in self._candidate_bootstrap_servers():
            if self.is_kafka_available(candidate):
                self.container = None
                self.started_by_framework = False
                self.bootstrap_servers = candidate
                self.cluster_bootstrap_servers = connector_bootstrap
                self.provisioning_mode = ids["provisioner"]
                self.last_error = None
                return candidate
        if not self._kubernetes_resources_exist(ids) and not self._kubernetes_external_service_exists(ids):
            return None

        self._wait_for_kubernetes_internal_bootstrap(ids)
        self._wait_for_kubernetes_external_service_bootstrap(ids)
        self._start_kubernetes_port_forward(ids, restart_existing=True)

        deadline = time.time() + self.wait_timeout_seconds
        while time.time() < deadline:
            if self.is_kafka_available(ids["external_bootstrap"]):
                self.container = None
                self.started_by_framework = True
                self.bootstrap_servers = ids["external_bootstrap"]
                self.cluster_bootstrap_servers = connector_bootstrap
                self.provisioning_mode = ids["provisioner"]
                self.last_error = None
                return ids["external_bootstrap"]
            time.sleep(self.poll_interval_seconds)

        raise RuntimeError(
            "Kafka Kubernetes broker exists but the external bootstrap server did not recover in time"
        )

    def _start_kafka_container(self):
        """Start a Kafka container and wait until the broker becomes available."""
        container_class = self._load_container_class()
        container = self.container_factory.create_container(
            container_class,
            self.image,
            config=self._load_manager_config(),
        )
        container.start()

        bootstrap_servers = None
        get_bootstrap_server = getattr(container, "get_bootstrap_server", None)
        get_cluster_bootstrap_server = getattr(container, "get_cluster_bootstrap_server", None)
        if callable(get_bootstrap_server):
            bootstrap_servers = get_bootstrap_server()
        else:
            bootstrap_servers = getattr(container, "bootstrap_servers", None)
        cluster_bootstrap_servers = None
        if callable(get_cluster_bootstrap_server):
            cluster_bootstrap_servers = get_cluster_bootstrap_server()

        deadline = time.time() + self.wait_timeout_seconds
        while time.time() < deadline:
            if bootstrap_servers and self.is_kafka_available(bootstrap_servers):
                self.container = container
                self.started_by_framework = True
                self.bootstrap_servers = bootstrap_servers
                self.cluster_bootstrap_servers = cluster_bootstrap_servers
                self.provisioning_mode = "docker"
                self.last_error = None
                return bootstrap_servers
            time.sleep(self.poll_interval_seconds)

        stop_method = getattr(container, "stop", None)
        if callable(stop_method):
            stop_method()
        raise RuntimeError("Kafka container started but broker did not become available in time")

    def start_kafka(self):
        if self._is_kubernetes_provisioner(self._provisioner()):
            return self._start_kafka_kubernetes()
        return self._start_kafka_container()

    def ensure_kafka_running(self):
        """Return reachable bootstrap servers or try to auto-start Kafka."""
        config = self._load_manager_config()
        requires_kubernetes_external_service = self._requires_configured_kubernetes_external_service(config)
        kubernetes_external_service_verified = None
        previous_bootstrap_servers = self.bootstrap_servers
        previous_cluster_bootstrap_servers = self.cluster_bootstrap_servers
        previous_started_by_framework = self.started_by_framework
        previous_provisioning_mode = self.provisioning_mode
        for candidate in self._candidate_bootstrap_servers():
            if self.is_kafka_available(candidate):
                if requires_kubernetes_external_service:
                    if kubernetes_external_service_verified is None:
                        kubernetes_external_service_verified = self._kubernetes_external_service_exists(
                            self._kubernetes_identifiers(config)
                        )
                    if not kubernetes_external_service_verified:
                        continue
                self.bootstrap_servers = candidate
                explicit_cluster_bootstrap_servers = (
                    os.getenv("KAFKA_CLUSTER_BOOTSTRAP_SERVERS")
                    or config.get("cluster_bootstrap_servers")
                )
                if explicit_cluster_bootstrap_servers:
                    self.cluster_bootstrap_servers = explicit_cluster_bootstrap_servers
                elif candidate == previous_bootstrap_servers and previous_cluster_bootstrap_servers:
                    self.cluster_bootstrap_servers = previous_cluster_bootstrap_servers
                else:
                    self.cluster_bootstrap_servers = None
                framework_managed_kubernetes = (
                    self._is_kubernetes_provisioner(previous_provisioning_mode)
                    and self.port_forward_process is not None
                    and self.port_forward_process.poll() is None
                )
                framework_managed_container = self.container is not None
                self.started_by_framework = (
                    candidate == previous_bootstrap_servers
                    and (
                        (previous_started_by_framework and (framework_managed_container or framework_managed_kubernetes))
                        or (self._is_kubernetes_provisioner(previous_provisioning_mode) and framework_managed_kubernetes)
                    )
                )
                self.last_error = None
                return candidate

        if self._skips_vm_distributed_internal_autoprovision(config):
            if self._has_connector_visible_bootstrap(config):
                self.last_error = (
                    "vm-distributed Kafka validation requires a reachable connector-visible Kafka bootstrap server. "
                    "A Kafka bootstrap was configured, but it was not reachable from this runner. Check "
                    "KAFKA_BOOTSTRAP_SERVERS/KAFKA_CLUSTER_BOOTSTRAP_SERVERS and the network path from the "
                    "validation runner and every connector VM/cluster."
                )
            else:
                self.last_error = (
                    "vm-distributed Kafka validation requires a connector-visible Kafka bootstrap server. "
                    "Configure KAFKA_BOOTSTRAP_SERVERS or KAFKA_CLUSTER_BOOTSTRAP_SERVERS with an address "
                    "reachable from every connector VM/cluster; the framework will not use an auto-provisioned "
                    "Kubernetes ClusterIP because connector clusters cannot resolve it."
                )
            print(f"[WARNING] Kafka auto-provisioning skipped: {self.last_error}")
            return None

        recovery_error = None
        framework_managed_kubernetes = self._is_kubernetes_provisioner(previous_provisioning_mode) and (
            previous_started_by_framework
            or previous_cluster_bootstrap_servers
            or previous_bootstrap_servers
            or self.port_forward_process is not None
        )
        if framework_managed_kubernetes:
            try:
                recovered_bootstrap = self._recover_existing_kubernetes_runtime()
                if recovered_bootstrap:
                    return recovered_bootstrap
            except Exception as exc:
                recovery_error = str(exc)

        try:
            return self.start_kafka()
        except Exception as exc:
            if recovery_error:
                self.last_error = f"{recovery_error}; restart fallback failed: {exc}"
            else:
                self.last_error = str(exc)
            print(f"[WARNING] Kafka auto-provisioning failed: {self.last_error}")
            return None

    def stop_kafka(self):
        """Stop the Kafka container only if it was started by the framework."""
        if self._is_kubernetes_provisioner(self.provisioning_mode):
            try:
                config = self._load_manager_config()
                ids = self._kubernetes_identifiers(config)
                try:
                    self._stop_kubernetes_port_forward()
                    self._run_command(
                        ["kubectl", "delete"]
                        + self._kubernetes_resource_refs(ids)
                        + ["-n", ids["namespace"], "--ignore-not-found=true"]
                    )
                except Exception as exc:
                    print(f"[WARNING] Failed to stop Kafka Kubernetes broker cleanly: {exc}")
            finally:
                self.container = None
                self.port_forward_process = None
                self.started_by_framework = False
                self.bootstrap_servers = None
                self.cluster_bootstrap_servers = None
                self.provisioning_mode = None
            return

        if not self.started_by_framework or self.container is None:
            return

        try:
            stop_method = getattr(self.container, "stop", None)
            if callable(stop_method):
                stop_method()
        except Exception as exc:
            print(f"[WARNING] Failed to stop Kafka container cleanly: {exc}")
        finally:
            self.container = None
            self.port_forward_process = None
            self.started_by_framework = False
            self.bootstrap_servers = None
            self.cluster_bootstrap_servers = None
            self.provisioning_mode = None

    def describe(self) -> str:
        return "KafkaManager ensures a Kafka broker is available for benchmarks."

