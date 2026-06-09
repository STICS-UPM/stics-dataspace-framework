import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


def _read_repo_file(*parts):
    with open(os.path.join(REPO_ROOT, *parts), "r", encoding="utf-8") as handle:
        return handle.read()


class InesdataModelExecutionEdrConfigTests(unittest.TestCase):
    def test_connector_model_execution_edr_wait_is_configurable_from_helm(self):
        extension = _read_repo_file(
            "adapters",
            "inesdata",
            "sources",
            "inesdata-connector",
            "extensions",
            "model-execution-api",
            "src",
            "main",
            "java",
            "org",
            "upm",
            "inesdata",
            "modelexecution",
            "ModelExecutionApiExtension.java",
        )
        controller = _read_repo_file(
            "adapters",
            "inesdata",
            "sources",
            "inesdata-connector",
            "extensions",
            "model-execution-api",
            "src",
            "main",
            "java",
            "org",
            "upm",
            "inesdata",
            "modelexecution",
            "controller",
            "ModelExecutionApiController.java",
        )
        values_template = _read_repo_file("deployers", "inesdata", "connector", "values.yaml.tpl")
        connector_config = _read_repo_file(
            "deployers",
            "inesdata",
            "connector",
            "config",
            "connector-configuration.properties",
        )

        self.assertIn("asset.infer.edr.attempts", extension)
        self.assertIn("asset.infer.edr.delay.ms", extension)
        self.assertIn("parsePositiveInt(context.getSetting(EDR_ATTEMPTS", extension)
        self.assertIn("parsePositiveLong(context.getSetting(EDR_DELAY_MS", extension)
        self.assertIn("private final int edrAttempts", controller)
        self.assertIn("private final long edrDelayMs", controller)
        self.assertIn("attempt < edrAttempts", controller)
        self.assertIn("Thread.sleep(edrDelayMs)", controller)
        self.assertIn("modelExecution:", values_template)
        self.assertIn("connector_model_execution_edr_attempts", values_template)
        self.assertIn("connector_model_execution_edr_delay_ms", values_template)
        self.assertIn("connector_ingress_proxy_read_timeout", values_template)
        self.assertIn("connector_ingress_proxy_send_timeout", values_template)
        self.assertIn("connector_ingress_proxy_connect_timeout", values_template)
        self.assertIn("asset.infer.edr.attempts={{ .Values.connector.modelExecution.edrAttempts", connector_config)
        self.assertIn("asset.infer.edr.delay.ms={{ .Values.connector.modelExecution.edrDelayMs", connector_config)

    def test_connector_ingress_timeout_exceeds_model_execution_edr_wait(self):
        ingress_template = _read_repo_file(
            "deployers",
            "inesdata",
            "connector",
            "templates",
            "connector-ingress.yaml",
        )
        values_template = _read_repo_file("deployers", "inesdata", "connector", "values.yaml.tpl")

        self.assertIn("nginx.ingress.kubernetes.io/proxy-read-timeout", ingress_template)
        self.assertIn("nginx.ingress.kubernetes.io/proxy-send-timeout", ingress_template)
        self.assertIn("nginx.ingress.kubernetes.io/proxy-connect-timeout", ingress_template)
        self.assertIn("default('300'", values_template)
        self.assertIn("default('30'", values_template)

    def test_connector_runtime_loads_httpdata_public_api_for_model_execution_edr(self):
        launcher_build = _read_repo_file(
            "adapters",
            "inesdata",
            "sources",
            "inesdata-connector",
            "launchers",
            "connector",
            "build.gradle.kts",
        )
        service_extension = _read_repo_file(
            "adapters",
            "inesdata",
            "sources",
            "inesdata-connector",
            "extensions",
            "extended-data-plane-public-api",
            "src",
            "main",
            "resources",
            "META-INF",
            "services",
            "org.eclipse.edc.spi.system.ServiceExtension",
        )
        extension = _read_repo_file(
            "adapters",
            "inesdata",
            "sources",
            "inesdata-connector",
            "extensions",
            "extended-data-plane-public-api",
            "src",
            "main",
            "java",
            "org",
            "upm",
            "inesdata",
            "extendeddataplanepublic",
            "ExtendedDataPlanePublicApiExtension.java",
        )

        self.assertIn('implementation(project(":extensions:model-execution-api"))', launcher_build)
        self.assertIn('implementation(project(":extensions:extended-data-plane-public-api"))', launcher_build)
        self.assertIn("ExtendedDataPlanePublicApiExtension", service_extension)
        self.assertIn('addGeneratorFunction("HttpData"', extension)
        self.assertNotIn("portMappingRegistry.register", extension)
        self.assertNotIn("registerResource(ApiContext.PUBLIC", extension)


if __name__ == "__main__":
    unittest.main()
