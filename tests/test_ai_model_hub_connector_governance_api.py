import json
import os
import tempfile
import unittest
from unittest import mock

from validation.components.ai_model_hub.connector_governance_api import (
    AIModelHubConnectorGovernanceApiSuite,
    CASE_IDS,
    COMPONENT_KEY,
    SUITE_NAME,
    _adapter_management_url_resolver,
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
    def __init__(self):
        self.posts = []
        self.gets = []
        self.deletes = []

    def post(self, url, timeout=30, headers=None, json=None, data=None):
        self.posts.append({"url": url, "headers": headers or {}, "json": json, "data": data})
        if "/protocol/openid-connect/token" in url:
            return FakeResponse(200, {"access_token": f"token-{data['username']}"})
        if url.endswith("/management/v3/assets"):
            return FakeResponse(200, {"@id": json["@id"]})
        if url.endswith("/management/v3/policydefinitions"):
            return FakeResponse(200, {"@id": json["@id"]})
        if url.endswith("/management/v3/contractdefinitions"):
            return FakeResponse(200, {"@id": json["@id"]})
        if url.endswith("/management/v3/catalog/request"):
            return FakeResponse(
                200,
                {
                    "dspace:participantId": "conn-provider",
                    "dcat:dataset": [
                        {
                            "@id": "a52-amh-access-fixed-uuid",
                            "odrl:hasPolicy": {"@id": "offer-1"},
                        }
                    ],
                },
            )
        if url.endswith("/management/v3/contractnegotiations"):
            return FakeResponse(200, {"@id": "neg-1"})
        if url.endswith("/management/v3/contractagreements/request"):
            return FakeResponse(
                200,
                [
                    {
                        "@id": "agreement-1",
                        "assetId": "a52-amh-access-fixed-uuid",
                        "state": "FINALIZED",
                    }
                ],
            )
        if url.endswith("/management/v3/transferprocesses"):
            return FakeResponse(200, {"@id": "transfer-1"})
        return FakeResponse(404, {"error": "not found"})

    def get(self, url, timeout=30, headers=None):
        self.gets.append({"url": url, "headers": headers or {}})
        if url.endswith("/management/v3/contractnegotiations/neg-1"):
            return FakeResponse(200, {"@id": "neg-1", "state": "FINALIZED", "contractAgreementId": "agreement-1"})
        if url.endswith("/management/v3/contractagreements/agreement-1"):
            return FakeResponse(
                200,
                {
                    "@id": "agreement-1",
                    "assetId": "a52-amh-access-fixed-uuid",
                    "state": "FINALIZED",
                },
            )
        if url.endswith("/management/v3/transferprocesses/transfer-1"):
            return FakeResponse(200, {"@id": "transfer-1", "state": "STARTED"})
        if url.endswith("/management/v3/edrs/transfer-1/dataaddress"):
            return FakeResponse(
                200,
                {
                    "endpoint": "http://provider-proxy.example.local/public",
                    "authorization": "edr-secret",
                    "authKey": "Authorization",
                },
            )
        return FakeResponse(404, {"error": "not found"})

    def delete(self, url, timeout=30, headers=None):
        self.deletes.append({"url": url, "headers": headers or {}})
        return FakeResponse(204, None, text="")


class AIModelHubConnectorGovernanceApiTests(unittest.TestCase):
    def _suite(self, session):
        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }
        return AIModelHubConnectorGovernanceApiSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {
                "KC_URL": "auth.example.local",
                "PIONERA_ADAPTER": "inesdata",
                "AI_MODEL_HUB_NEGOTIATION_TIMEOUT_SECONDS": "1",
                "AI_MODEL_HUB_TRANSFER_TIMEOUT_SECONDS": "1",
                "AI_MODEL_HUB_POLL_INTERVAL_SECONDS": "1",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "demo",
            protocol_address_resolver=lambda connector: f"http://{connector}:19194/protocol",
            session=session,
            uuid_factory=lambda: "fixed-uuid",
        )

    def test_run_covers_connector_governance_cases_without_persisting_secrets(self):
        session = FakeSession()
        suite = self._suite(session)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = suite.run(
                provider="conn-provider",
                consumer="conn-consumer",
                model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
                model_path="/api/v1/nlp/ecommerce-sentiment",
                experiment_dir=tmpdir,
            )
            report_path = result["artifacts"]["report_json"]
            self.assertTrue(os.path.exists(report_path))
            with open(report_path, encoding="utf-8") as handle:
                report_text = handle.read()

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["component"], COMPONENT_KEY)
        self.assertEqual(result["suite"], SUITE_NAME)
        self.assertEqual(result["summary"]["total"], len(CASE_IDS))
        self.assertEqual(result["summary"]["passed"], len(CASE_IDS))
        self.assertEqual([case["test_case_id"] for case in result["executed_cases"]], CASE_IDS)
        self.assertEqual(result["created_entities"]["asset_id"], "a52-amh-access-fixed-uuid")
        self.assertEqual(result["created_entities"]["agreement_id"], "agreement-1")
        self.assertEqual(result["created_entities"]["transfer_id"], "transfer-1")
        self.assertTrue(result["created_entities"]["edr_summary"]["authorization_present"])

        self.assertNotIn("token-provider-user", report_text)
        self.assertNotIn("token-consumer-user", report_text)
        self.assertNotIn("provider-pass", report_text)
        self.assertNotIn("consumer-pass", report_text)
        self.assertNotIn("edr-secret", report_text)

        self.assertTrue(any(entry["url"].endswith("/management/v3/assets") for entry in session.posts))
        asset_request = next(entry for entry in session.posts if entry["url"].endswith("/management/v3/assets"))
        model_metadata = asset_request["json"]["properties"]["assetData"]["JS_DAIMO_Model"]
        self.assertEqual(model_metadata["daimo:taskType"], "classification")
        self.assertEqual(model_metadata["daimo:taskCategory"], "Natural Language Processing")
        self.assertEqual(model_metadata["daimo:subtask"], "text-classification")
        self.assertTrue(any(entry["url"].endswith("/management/v3/contractagreements/agreement-1") for entry in session.gets))
        self.assertTrue(any(entry["url"].endswith("/management/v3/transferprocesses") for entry in session.posts))
        self.assertEqual(len(session.deletes), 2)
        cleanup_asset_steps = [step for step in result["steps"] if step["name"] == "cleanup_asset"]
        self.assertEqual(cleanup_asset_steps[0]["status"], "skipped")

    def test_run_recovers_agreement_from_agreements_list_when_negotiation_omits_contract_id(self):
        class AgreementRecoverySession(FakeSession):
            def get(self, url, timeout=30, headers=None):
                if url.endswith("/management/v3/contractnegotiations/neg-1"):
                    self.gets.append({"url": url, "headers": headers or {}})
                    return FakeResponse(200, {"@id": "neg-1", "state": "INITIAL"})
                return super().get(url, timeout=timeout, headers=headers)

        session = AgreementRecoverySession()
        result = self._suite(session).run(
            provider="conn-provider",
            consumer="conn-consumer",
            model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["created_entities"]["agreement_id"], "agreement-1")
        agreement_steps = [step for step in result["steps"] if step["name"] == "wait_for_contract_agreement"]
        self.assertEqual(agreement_steps[0]["state"], "RECOVERED_FROM_AGREEMENTS")
        self.assertEqual(agreement_steps[0]["negotiation_state"], "INITIAL")
        self.assertTrue(
            any(entry["url"].endswith("/management/v3/contractagreements/request") for entry in session.posts)
        )

    def test_run_waits_until_negotiated_agreement_is_listed(self):
        class DelayedAgreementSession(FakeSession):
            def __init__(self):
                super().__init__()
                self.agreement_requests = 0

            def post(self, url, timeout=30, headers=None, json=None, data=None):
                if url.endswith("/management/v3/contractagreements/request"):
                    self.posts.append({"url": url, "headers": headers or {}, "json": json, "data": data})
                    self.agreement_requests += 1
                    if self.agreement_requests == 1:
                        return FakeResponse(200, [])
                    return FakeResponse(
                        200,
                        [
                            {
                                "@id": "agreement-1",
                                "assetId": "a52-amh-access-fixed-uuid",
                                "state": "FINALIZED",
                            }
                        ],
                    )
                return super().post(url, timeout=timeout, headers=headers, json=json, data=data)

            def get(self, url, timeout=30, headers=None):
                if url.endswith("/management/v3/contractagreements/agreement-1"):
                    self.gets.append({"url": url, "headers": headers or {}})
                    return FakeResponse(404, {"error": "not found"})
                return super().get(url, timeout=timeout, headers=headers)

        session = DelayedAgreementSession()
        suite = self._suite(session)

        with mock.patch("validation.components.ai_model_hub.connector_governance_api.time.sleep", return_value=None):
            result = suite.run(
                provider="conn-provider",
                consumer="conn-consumer",
                model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
            )

        self.assertEqual(result["status"], "passed")
        self.assertGreaterEqual(session.agreement_requests, 2)
        self.assertEqual(result["created_entities"]["agreements_listed"], 1)

    def test_run_can_use_direct_agreement_lookup_when_list_is_paginated(self):
        class PaginatedAgreementSession(FakeSession):
            def __init__(self):
                super().__init__()
                self.agreement_requests = 0

            def post(self, url, timeout=30, headers=None, json=None, data=None):
                if url.endswith("/management/v3/contractagreements/request"):
                    self.posts.append({"url": url, "headers": headers or {}, "json": json, "data": data})
                    self.agreement_requests += 1
                    return FakeResponse(200, [])
                return super().post(url, timeout=timeout, headers=headers, json=json, data=data)

        session = PaginatedAgreementSession()
        suite = self._suite(session)

        with mock.patch("validation.components.ai_model_hub.connector_governance_api.time.sleep", return_value=None):
            result = suite.run(
                provider="conn-provider",
                consumer="conn-consumer",
                model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(session.agreement_requests, 0)
        self.assertTrue(
            any(entry["url"].endswith("/management/v3/contractagreements/agreement-1") for entry in session.gets)
        )

    def test_run_marks_dependent_cases_failed_when_oidc_login_fails(self):
        class FailingLoginSession(FakeSession):
            def post(self, url, timeout=30, headers=None, json=None, data=None):
                if "/protocol/openid-connect/token" in url:
                    return FakeResponse(401, {"error": "invalid_grant"})
                return super().post(url, timeout=timeout, headers=headers, json=json, data=data)

        result = self._suite(FailingLoginSession()).run(
            provider="conn-provider",
            consumer="conn-consumer",
            model_url="http://model-server.demo.svc.cluster.local:8080/api/v1/nlp/ecommerce-sentiment",
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["summary"]["failed"], len(CASE_IDS))
        self.assertIn("provider OIDC login failed", result["error"]["message"])

    def test_runtime_prefers_level6_public_environment_over_internal_defaults(self):
        suite = self._suite(FakeSession())

        with mock.patch.dict(
            os.environ,
            {
                "AI_MODEL_HUB_KEYCLOAK_URL": "https://org1.example.test/auth",
                "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID": "conn-provider",
                "AI_MODEL_HUB_CONSUMER_CONNECTOR_ID": "conn-consumer",
                "AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL": "https://org2.example.test/management",
                "AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL": "https://org3.example.test/management",
                "AI_MODEL_HUB_PROVIDER_PROTOCOL_URL": "http://conn-provider.example.test/protocol",
                "AI_MODEL_HUB_CONSUMER_PROTOCOL_URL": "http://conn-consumer.example.test/protocol",
            },
            clear=False,
        ):
            runtime = suite._runtime()

            self.assertEqual(runtime["keycloak_url"], "https://org1.example.test/auth")
            self.assertEqual(
                suite._management_url("conn-provider", "/management/v3/assets"),
                "https://org2.example.test/management/v3/assets",
            )
            self.assertEqual(
                suite._management_url("conn-consumer", "/management/v3/catalog/request"),
                "https://org3.example.test/management/v3/catalog/request",
            )
            self.assertEqual(
                suite._protocol_address("conn-provider"),
                "http://conn-provider.example.test/protocol",
            )

    def test_adapter_management_resolver_prefers_generated_public_management_urls(self):
        class FakeAdapter:
            def load_connector_credentials(self, connector):
                return {
                    "connector_user": {"user": "user", "passwd": "example-pass"},
                    "public_access_urls": {
                        "connector_management_api_v3": f"https://{connector}.example.test/edc/management/v3",
                    },
                }

            class connectors:
                @staticmethod
                def build_connector_url(connector):
                    return f"https://{connector}.example.test/inesdata-connector-interface/"

        resolver = _adapter_management_url_resolver(FakeAdapter())

        self.assertEqual(
            resolver("conn-provider", "/management/v3/assets"),
            "https://conn-provider.example.test/edc/management/v3/assets",
        )

    def test_adapter_management_resolver_converts_inesdata_interface_url_to_management_url(self):
        class FakeAdapter:
            def load_connector_credentials(self, connector):
                return {"connector_user": {"user": "user", "passwd": "example-pass"}}

            class connectors:
                @staticmethod
                def build_connector_url(connector):
                    return f"http://{connector}.example.test/inesdata-connector-interface/"

        resolver = _adapter_management_url_resolver(FakeAdapter())

        self.assertEqual(
            resolver("conn-provider", "/management/v3/assets"),
            "http://conn-provider.example.test/management/v3/assets",
        )


if __name__ == "__main__":
    unittest.main()
