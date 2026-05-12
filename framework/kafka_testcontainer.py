import tarfile
import time
from io import BytesIO
from textwrap import dedent

from testcontainers.kafka import KafkaContainer
from testcontainers.kafka import kafka_config


class FrameworkKafkaContainer(KafkaContainer):
    """Kafka container with separate advertised listeners for host and cluster clients."""

    def __init__(
        self,
        image: str = "confluentinc/cp-kafka:7.6.0",
        port: int = 9093,
        cluster_port: int = 19093,
        cluster_advertised_host: str = "host.minikube.internal",
        **kwargs,
    ) -> None:
        super().__init__(image=image, port=port, **kwargs)
        self.cluster_port = cluster_port
        self.cluster_advertised_host = cluster_advertised_host
        self.listeners = (
            f"HOST://0.0.0.0:{self.port},"
            f"CLUSTER://0.0.0.0:{self.cluster_port},"
            "BROKER://0.0.0.0:9092"
        )
        self.security_protocol_map = "BROKER:PLAINTEXT,HOST:PLAINTEXT,CLUSTER:PLAINTEXT"

        self.with_exposed_ports(self.cluster_port)
        self.with_env("KAFKA_LISTENERS", self.listeners)
        self.with_env("KAFKA_LISTENER_SECURITY_PROTOCOL_MAP", self.security_protocol_map)
        self.with_env("KAFKA_INTER_BROKER_LISTENER_NAME", "BROKER")

    def with_cluster_advertised_host(self, host: str):
        if host:
            self.cluster_advertised_host = str(host)
        return self

    def get_bootstrap_server(self) -> str:
        host = self.get_container_host_ip()
        port = self.get_exposed_port(self.port)
        return f"{host}:{port}"

    def get_cluster_bootstrap_server(self) -> str:
        port = self.get_exposed_port(self.cluster_port)
        return f"{self.cluster_advertised_host}:{port}"

    def tc_start(self) -> None:
        host = self.get_container_host_ip()
        host_port = self.get_exposed_port(self.port)
        cluster_port = self.get_exposed_port(self.cluster_port)
        if kafka_config.limit_broker_to_first_host:
            broker_listener = "BROKER://$(hostname -i | cut -d' ' -f1):9092"
        else:
            broker_listener = "BROKER://$(hostname -i):9092"
        listeners = (
            f"HOST://{host}:{host_port},"
            f"CLUSTER://{self.cluster_advertised_host}:{cluster_port},"
            f"{broker_listener}"
        )
        data = (
            dedent(
                f"""
                #!/bin/bash
                {self.boot_command}
                export KAFKA_ADVERTISED_LISTENERS={listeners}
                . /etc/confluent/docker/bash-config
                /etc/confluent/docker/configure
                /etc/confluent/docker/launch
                """
            )
            .strip()
            .encode("utf-8")
        )
        self.create_file(data, KafkaContainer.TC_START_SCRIPT)

    def create_file(self, content: bytes, path: str) -> None:
        with BytesIO() as archive, tarfile.TarFile(fileobj=archive, mode="w") as tar:
            tarinfo = tarfile.TarInfo(name=path)
            tarinfo.size = len(content)
            tarinfo.mtime = time.time()
            tar.addfile(tarinfo, BytesIO(content))
            archive.seek(0)
            self.get_wrapped_container().put_archive("/", archive)
