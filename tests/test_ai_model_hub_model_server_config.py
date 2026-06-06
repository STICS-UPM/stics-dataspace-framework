import unittest

from deployers.shared.lib import ai_model_hub_model_server as model_server


class AIModelHubModelServerConfigTests(unittest.TestCase):
    def test_mode_aliases_match_existing_configuration_contract(self):
        self.assertEqual(model_server.normalize_model_server_mode(""), "mock")
        self.assertEqual(model_server.normalize_model_server_mode("deterministic"), "mock")
        self.assertEqual(model_server.normalize_model_server_mode("real"), "use-cases")
        self.assertEqual(model_server.normalize_model_server_mode("usecases"), "use-cases")
        self.assertEqual(model_server.normalize_model_server_mode("real_combined"), "combined")
        self.assertEqual(model_server.normalize_model_server_mode("remote"), "external")

    def test_mode_reads_primary_and_legacy_keys(self):
        self.assertEqual(
            model_server.model_server_mode({"AI_MODEL_HUB_MODEL_SERVER_MODE": "combined"})[0],
            "combined",
        )
        self.assertEqual(
            model_server.model_server_mode({"LEVEL5_AI_MODEL_HUB_MODEL_SERVER_MODE": "real"})[0],
            "use-cases",
        )
        self.assertEqual(
            model_server.model_server_mode({"MODEL_SERVER_MODE": "remote"})[0],
            "external",
        )

    def test_runtime_defaults_are_stable(self):
        self.assertTrue(model_server.model_server_enabled({}))
        self.assertEqual(model_server.model_server_mode({})[0], "mock")
        self.assertEqual(model_server.source_repository({}), "")
        self.assertEqual(model_server.image_ref({}), "model-server:latest")
        self.assertEqual(model_server.container_port({}), 8080)
        self.assertEqual(model_server.docker_base_image({}), "python:3.10-slim")
        self.assertEqual(model_server.readiness_path({}, "mock"), "/api/v1/health")
        self.assertEqual(model_server.readiness_path({}, "combined"), "/models")
        self.assertEqual(
            model_server.service_url("components-real"),
            "http://model-server.components-real.svc.cluster.local:8080",
        )

    def test_public_url_and_ingress_are_derived_from_component_public_base(self):
        config = {
            "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
            "AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH": "model-server",
        }

        self.assertEqual(
            model_server.public_url(config),
            "https://org1.example.test/model-server",
        )
        ingress = model_server.public_ingress("components", config, topology="vm-single")

        self.assertEqual(ingress["metadata"]["namespace"], "components")
        self.assertEqual(ingress["metadata"]["labels"]["app.kubernetes.io/part-of"], "vm-single")
        self.assertEqual(ingress["spec"]["rules"][0]["host"], "org1.example.test")
        self.assertEqual(
            ingress["spec"]["rules"][0]["http"]["paths"][0]["path"],
            "/model-server(/|$)(.*)",
        )

    def test_generated_manifest_uses_configured_port_readiness_and_pull_policy(self):
        manifest = model_server.generated_manifest(
            "components",
            "local/real-model-server:latest",
            "use-cases",
            {
                "AI_MODEL_HUB_MODEL_SERVER_CONTAINER_PORT": "8090",
                "AI_MODEL_HUB_MODEL_SERVER_READINESS_PATH": "models",
            },
        )

        self.assertIn("namespace: components", manifest)
        self.assertIn("image: local/real-model-server:latest", manifest)
        self.assertIn("imagePullPolicy: Never", manifest)
        self.assertIn("containerPort: 8090", manifest)
        self.assertIn("path: /models", manifest)
        self.assertIn("app: model-server", manifest)
        self.assertIn("matchLabels:\n      app: model-server", manifest)
        self.assertIn("selector:\n    app: model-server", manifest)


if __name__ == "__main__":
    unittest.main()
