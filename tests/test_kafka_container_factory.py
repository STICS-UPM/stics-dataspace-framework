import os
import tempfile
import unittest

from framework.kafka_container_factory import KafkaContainerFactory


FIXTURE_ENV_FILE = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "kafka",
    "sasl.env",
)


class _FakeConfigurableKafkaContainer:
    def __init__(self, image):
        self.image = image
        self.env = {}
        self.kraft_enabled = False

    def with_env(self, key, value):
        self.env[key] = value
        return self

    def with_kraft(self):
        self.kraft_enabled = True
        return self


class KafkaContainerFactoryTests(unittest.TestCase):
    def test_load_env_file_parses_shell_style_entries(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("# comment\n")
            handle.write("export FIRST=value-1\n")
            handle.write("SECOND=\"value 2\"\n")
            env_path = handle.name

        self.addCleanup(lambda: os.path.exists(env_path) and os.unlink(env_path))

        parsed = KafkaContainerFactory.load_env_file(env_path)

        self.assertEqual(parsed, {"FIRST": "value-1", "SECOND": "value 2"})

    def test_create_container_applies_env_file_and_inline_env(self):
        factory = KafkaContainerFactory()

        container = factory.create_container(
            _FakeConfigurableKafkaContainer,
            "confluentinc/cp-kafka:latest",
            config={
                "container_env_file": FIXTURE_ENV_FILE,
                "container_env": {
                    "KAFKA_HEAP_OPTS": "-Xms512m -Xmx512m",
                },
            },
        )

        self.assertEqual(container.image, "confluentinc/cp-kafka:latest")
        self.assertTrue(container.kraft_enabled)
        self.assertEqual(container.env["KAFKA_CFG_SASL_ENABLED_MECHANISMS"], "PLAIN")
        self.assertEqual(container.env["KAFKA_CLIENT_USERS"], "framework")
        self.assertEqual(container.env["KAFKA_HEAP_OPTS"], "-Xms512m -Xmx512m")


if __name__ == "__main__":
    unittest.main()
