import os


class KafkaContainerFactory:
    """Create configurable Kafka containers from runtime configuration."""

    @staticmethod
    def load_env_file(path):
        if not path:
            return {}

        env_path = os.path.abspath(path)
        values = {}
        with open(env_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if key:
                    values[key] = value
        return values

    @classmethod
    def resolve_container_env(cls, config=None):
        config = config or {}
        resolved = {}

        env_file = config.get("container_env_file")
        if env_file:
            resolved.update(cls.load_env_file(env_file))

        inline_env = config.get("container_env") or {}
        if isinstance(inline_env, dict):
            for key, value in inline_env.items():
                if key:
                    resolved[str(key)] = str(value)

        return resolved

    def create_container(self, container_class, image, config=None):
        config = config or {}
        resolved_image = config.get("container_image") or image
        container = container_class(resolved_image)

        with_kraft = getattr(container, "with_kraft", None)
        if callable(with_kraft):
            updated = with_kraft()
            if updated is not None:
                container = updated

        cluster_advertised_host = config.get("cluster_advertised_host")
        with_cluster_advertised_host = getattr(container, "with_cluster_advertised_host", None)
        if cluster_advertised_host and callable(with_cluster_advertised_host):
            updated = with_cluster_advertised_host(cluster_advertised_host)
            if updated is not None:
                container = updated

        with_env = getattr(container, "with_env", None)
        if callable(with_env):
            for key, value in self.resolve_container_env(config).items():
                updated = with_env(key, value)
                if updated is not None:
                    container = updated

        return container

    def describe(self) -> str:
        return "KafkaContainerFactory creates configurable Kafka containers."
