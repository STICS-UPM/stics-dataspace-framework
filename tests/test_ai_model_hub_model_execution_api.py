import json
import os
import tempfile
import unittest
from unittest import mock

from tests.dataset_test_helpers import create_flares_source
from validation.components.ai_model_hub.model_execution_api import (
    AIModelHubModelExecutionApiSuite,
    COMPONENT_KEY,
    DEFAULT_EXPECTED_MODEL,
    FLARES_EXPECTED_MODEL,
    FLARES_MODEL_PATH,
    FUNCTIONAL_CASE_ID,
    build_flares_execution_context,
    default_model_url,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        if self._payload is None:
            return json.loads(self.text)
        return self._payload


class FakeSession:
    def __init__(self, *, execution_status=200, execution_payload=None):
        self.execution_status = execution_status
        self.execution_payload = execution_payload or {
            "model": DEFAULT_EXPECTED_MODEL,
            "sentiment": "positive",
            "confidence": 0.8,
        }
        self.posts = []
        self.deletes = []

    def post(self, url, timeout=30, headers=None, json=None, data=None):
        self.posts.append({"url": url, "headers": headers or {}, "json": json, "data": data})
        if "/protocol/openid-connect/token" in url:
            return FakeResponse(200, {"access_token": "token-provider"})
        if url.endswith("/management/v3/assets"):
            return FakeResponse(200, {"@id": json["@id"]})
        if url.endswith("/management/v3/modelexecutions/execute"):
            return FakeResponse(self.execution_status, self.execution_payload)
        if url.endswith("/api/infer"):
            return FakeResponse(self.execution_status, self.execution_payload)
        return FakeResponse(404, {"error": "not found"})

    def delete(self, url, timeout=30, headers=None):
        self.deletes.append({"url": url, "headers": headers or {}})
        return FakeResponse(204, None, text="")


class AIModelHubModelExecutionApiTests(unittest.TestCase):
    def _suite(self, session):
        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
        }
        return AIModelHubModelExecutionApiSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {
                "KC_URL": "auth.example.local",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "demo",
            session=session,
            uuid_factory=lambda: "fixed-uuid",
        )

    def test_run_creates_executes_and_cleans_temporary_httpdata_asset(self):
        session = FakeSession()
        suite = self._suite(session)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = suite.run(
                provider="conn-provider",
                model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
                payload={"text": "great"},
                experiment_dir=tmpdir,
            )
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            with open(result["artifacts"]["report_json"], encoding="utf-8") as handle:
                report_text = handle.read()

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["component"], COMPONENT_KEY)
        self.assertEqual(result["created_entities"]["asset_id"], "a52-model-exec-fixed-uuid")
        self.assertEqual(result["executed_cases"][0]["test_case_id"], "PT5-MH-10")
        self.assertEqual(result["executed_cases"][0]["mapping_status"], "mapped")
        self.assertEqual(result["executed_cases"][0]["coverage_status"], "automated_real_model_server")
        self.assertEqual(result["executed_cases"][0]["model_server_mode"], "external")
        self.assertEqual(result["executed_cases"][0]["evaluation"]["status"], "passed")
        self.assertNotIn("token-provider", report_text)
        self.assertNotIn("provider-pass", report_text)

        asset_requests = [entry for entry in session.posts if entry["url"].endswith("/management/v3/assets")]
        self.assertEqual(len(asset_requests), 1)
        self.assertEqual(asset_requests[0]["json"]["dataAddress"]["type"], "HttpData")
        self.assertEqual(asset_requests[0]["json"]["dataAddress"]["method"], "POST")
        self.assertNotIn("proxyPath", asset_requests[0]["json"]["dataAddress"])

        execution_requests = [
            entry for entry in session.posts if entry["url"].endswith("/management/v3/modelexecutions/execute")
        ]
        self.assertEqual(len(execution_requests), 1)
        self.assertEqual(execution_requests[0]["json"]["assetId"], "a52-model-exec-fixed-uuid")
        self.assertEqual(execution_requests[0]["json"]["payload"], {"text": "great"})
        self.assertEqual(len(session.deletes), 1)

    def test_run_cleans_temporary_asset_when_execution_fails(self):
        session = FakeSession(execution_status=500, execution_payload={"error": "boom"})
        result = self._suite(session).run(
            provider="conn-provider",
            model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
            payload={"text": "great"},
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(session.deletes), 1)
        self.assertIn("Expected HTTP 2xx", result["executed_cases"][0]["evaluation"]["assertions"][0])

    def test_run_marks_mock_model_server_evidence_when_configured(self):
        session = FakeSession()
        suite = self._suite(session)

        with mock.patch.dict(
            os.environ,
            {
                "AI_MODEL_HUB_MODEL_SERVER_ENABLED": "true",
                "AI_MODEL_HUB_MODEL_SERVER_MODE": "mock",
            },
            clear=False,
        ):
            result = suite.run(
                provider="conn-provider",
                model_url="http://model-server.components.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
                payload={"text": "great"},
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["model_server"]["mode"], "mock")
        self.assertEqual(result["executed_cases"][0]["execution_mode"], "api_mock_model_server")
        self.assertEqual(result["executed_cases"][0]["coverage_status"], "automated_mock_model_server")

    def test_run_with_flares_context_adds_functional_case_and_artifact(self):
        session = FakeSession()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_flares_source(tmpdir)
            context = build_flares_execution_context(source_dir=str(source_dir), record_id=463)
            suite = self._suite(session)
            result = suite.run(
                provider="conn-provider",
                model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
                payload=context["payload"],
                functional_context=context,
                experiment_dir=tmpdir,
            )
            functional_artifact = result["artifacts"]["mh-ling-01-flares-execution.json"]
            self.assertTrue(os.path.exists(functional_artifact))

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["passed"], 2)
        self.assertEqual([case["test_case_id"] for case in result["executed_cases"]], ["PT5-MH-10", FUNCTIONAL_CASE_ID])

        functional_case = result["executed_cases"][1]
        self.assertEqual(functional_case["coverage_status"], "partial_api_execution")
        self.assertEqual(functional_case["fixture"]["dataset"], "FLARES")
        self.assertEqual(functional_case["fixture"]["record_id"], 463)
        self.assertEqual(functional_case["fixture"]["expected_reliability"], "confiable")
        self.assertEqual(functional_case["evaluation"]["semantic_comparison_status"], "pending_flares_model_endpoint")
        self.assertIsInstance(session.posts[-1]["json"]["payload"], list)
        self.assertEqual(session.posts[-1]["json"]["payload"][0]["Id"], 463)
        self.assertEqual(session.posts[-1]["json"]["payload"][0]["5W1H_Label"], "WHO")

    def test_run_with_flares_model_server_response_validates_semantic_label(self):
        session = FakeSession(
            execution_payload={
                "model": FLARES_EXPECTED_MODEL,
                "variant": "baseline-a",
                "task": "5w1h-reliability-classification",
                "result": {"label": "confiable"},
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_flares_source(tmpdir)
            context = build_flares_execution_context(source_dir=str(source_dir), record_id=463)
            result = self._suite(session).run(
                provider="conn-provider",
                model_url=f"http://model-server.demo.svc.cluster.local:8080{FLARES_MODEL_PATH}",
                payload=context["payload"],
                expected_model=FLARES_EXPECTED_MODEL,
                functional_context=context,
                experiment_dir=tmpdir,
            )

        self.assertEqual(result["status"], "passed")
        functional_case = result["executed_cases"][1]
        self.assertEqual(functional_case["coverage_status"], "automated")
        self.assertEqual(functional_case["evaluation"]["semantic_comparison_status"], "passed")
        self.assertEqual(functional_case["evaluation"]["actual_label"], "confiable")
        self.assertNotIn("limitation", functional_case)
        self.assertIn("baseline_note", functional_case)

    def test_flares_execution_context_uses_dataset_expected_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_flares_source(tmpdir)
            context = build_flares_execution_context(source_dir=str(source_dir), record_id=106)

        self.assertEqual(context["use_case_id"], FUNCTIONAL_CASE_ID)
        self.assertEqual(context["dataset_name"], "FLARES")
        self.assertEqual(context["expected_output"]["expectedReliability"], "no confiable")
        self.assertEqual(context["payload"][0]["5W1H_Label"], "WHAT")
        self.assertEqual(context["sample"]["original_reliability_label"], "no confiable")

    def test_default_model_url_uses_components_namespace_service_dns(self):
        class Adapter:
            @staticmethod
            def load_deployer_config():
                return {"COMPONENTS_NAMESPACE": "components"}

            class config:
                @staticmethod
                def dataspace_name():
                    return "demo"

        self.assertEqual(
            default_model_url(Adapter()),
            "http://model-server.components.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
        )

    def test_default_model_url_uses_public_model_server_route_when_configured(self):
        class Adapter:
            @staticmethod
            def load_deployer_config():
                return {"COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test"}

        self.assertEqual(
            default_model_url(Adapter(), "/api/v1/nlp/twitter-sentiment"),
            "https://org1.example.test/model-server/api/v1/nlp/twitter-sentiment",
        )

    def test_default_model_url_uses_connector_route_for_vm_distributed(self):
        class Adapter:
            topology = "vm-distributed"

            @staticmethod
            def load_deployer_config():
                return {"COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test"}

        self.assertEqual(
            default_model_url(Adapter(), "/api/v1/nlp/twitter-sentiment"),
            "http://org1.example.test/model-server/api/v1/nlp/twitter-sentiment",
        )

    def test_default_model_url_respects_explicit_connector_route(self):
        class Adapter:
            topology = "vm-distributed"

            @staticmethod
            def load_deployer_config():
                return {
                    "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://components.internal/model-server",
                    "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
                }

        self.assertEqual(
            default_model_url(Adapter()),
            "http://components.internal/model-server/api/v1/nlp/ecommerce-sentiment",
        )

    def test_component_key_is_stable(self):
        self.assertEqual(COMPONENT_KEY, "ai-model-hub")

    def test_runtime_prefers_level6_public_environment_over_internal_defaults(self):
        suite = self._suite(FakeSession())

        with mock.patch.dict(
            os.environ,
            {
                "AI_MODEL_HUB_KEYCLOAK_URL": "https://org1.example.test/auth",
                "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID": "conn-provider",
                "AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER": "conn-provider",
                "AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL": "https://org2.example.test/management",
            },
            clear=False,
        ):
            runtime = suite._runtime()

            self.assertEqual(runtime["keycloak_url"], "https://org1.example.test/auth")
            self.assertEqual(
                suite._management_url("conn-provider", "/management/v3/modelexecutions/execute"),
                "https://org2.example.test/management/v3/modelexecutions/execute",
            )

    def test_edc_execution_uses_default_api_inference_endpoint_not_management(self):
        session = FakeSession()
        suite = self._suite(session)

        with mock.patch.dict(
            os.environ,
            {
                "AI_MODEL_HUB_COMPONENT_ADAPTER": "edc",
                "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID": "conn-provider",
                "AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER": "conn-provider",
                "AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL": "https://org2.example.test/management",
                "AI_MODEL_HUB_PROVIDER_DEFAULT_URL": "https://org2.example.test/api",
            },
            clear=False,
        ):
            result = suite.run(
                provider="conn-provider",
                model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
                payload={"text": "great"},
            )

        self.assertEqual(result["status"], "passed")
        asset_requests = [entry for entry in session.posts if entry["url"].endswith("/management/v3/assets")]
        self.assertEqual(asset_requests[0]["json"]["dataAddress"]["proxyPath"], "true")
        execution_requests = [entry for entry in session.posts if entry["url"].endswith("/api/infer")]
        self.assertEqual(len(execution_requests), 1)
        self.assertEqual(execution_requests[0]["url"], "https://org2.example.test/api/infer")
        self.assertFalse(any("/management/api/infer" in entry["url"] for entry in session.posts))

    def test_edc_execution_derives_default_api_url_from_management_url_when_needed(self):
        session = FakeSession()
        suite = self._suite(session)

        with mock.patch.dict(
            os.environ,
            {
                "AI_MODEL_HUB_COMPONENT_ADAPTER": "edc",
                "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID": "conn-provider",
                "AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER": "conn-provider",
                "AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL": "https://org2.example.test/management",
                "AI_MODEL_HUB_PROVIDER_DEFAULT_URL": "",
            },
            clear=False,
        ):
            result = suite.run(
                provider="conn-provider",
                model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
                payload={"text": "great"},
            )

        self.assertEqual(result["status"], "passed")
        execution_requests = [entry for entry in session.posts if entry["url"].endswith("/api/infer")]
        self.assertEqual(len(execution_requests), 1)
        self.assertEqual(execution_requests[0]["url"], "https://org2.example.test/api/infer")


if __name__ == "__main__":
    unittest.main()
