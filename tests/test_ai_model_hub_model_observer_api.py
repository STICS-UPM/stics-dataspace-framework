import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from validation.components.ai_model_hub.model_observer_api import (
    CASE_ID,
    build_observer_event_batch,
    resolve_model_observer_api_base_url,
    run_ai_model_hub_model_observer_validation,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.headers = {"Content-Type": "application/json"}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, run_context, bulk_status=201):
        self.run_context = run_context
        self.bulk_status = bulk_status
        self.requests = []

    def request(self, method, url, json=None, headers=None, timeout=20):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if method == "POST" and url.endswith("/api/model-observer/events/bulk"):
            return FakeResponse(
                self.bulk_status,
                {
                    "total": 3,
                    "inserted": 3,
                    "ignored": 0,
                    "eventIds": [event["eventId"] for event in self.run_context["events"]],
                },
            )
        if "/api/model-observer/timeline/" in url:
            return FakeResponse(200, {"total": 3, "items": self.run_context["events"]})
        if "/api/model-observer/agreements/" in url:
            return FakeResponse(200, {"total": 3, "items": self.run_context["events"]})
        if "/api/model-observer/benchmarks/" in url:
            benchmark_events = [
                event for event in self.run_context["events"] if event["eventType"] == "BENCHMARK_STARTED"
            ]
            return FakeResponse(200, {"total": len(benchmark_events), "items": benchmark_events})
        if "/api/model-observer/participants/" in url:
            return FakeResponse(
                200,
                {
                    "participantId": self.run_context["participant_id"],
                    "recentFailures": 0,
                    "totalsByEventType": {
                        "MODEL_DETAIL_VIEWED": 1,
                        "BENCHMARK_STARTED": 1,
                        "MODEL_EXECUTION_COMPLETED": 1,
                    },
                },
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


class FakeEdcSession:
    def __init__(self, run_context):
        self.run_context = run_context
        self.requests = []

    def request(self, method, url, json=None, headers=None, timeout=20):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if method == "POST" and url.endswith("/api/model-observer/events"):
            return FakeResponse(201, json)
        if method == "GET" and "/api/model-observer/events?" in url:
            return FakeResponse(200, self.run_context["events"])
        if method == "GET" and "/api/model-observer/assets/" in url and url.endswith("/timeline"):
            return FakeResponse(200, self.run_context["events"])
        if method == "GET" and "/api/model-observer/agreements/" in url and url.endswith("/evidence"):
            return FakeResponse(200, self.run_context["events"])
        if method == "GET" and "/api/model-observer/benchmarks?" in url:
            benchmark_events = [
                event for event in self.run_context["events"] if event["eventType"] == "BENCHMARK_STARTED"
            ]
            return FakeResponse(200, benchmark_events)
        if method == "GET" and url.endswith("/api/model-observer/participants"):
            return FakeResponse(
                200,
                [
                    {
                        "participantId": self.run_context["participant_id"],
                        "eventCount": 3,
                        "eventTypes": {
                            "MODEL_DETAIL_VIEWED": 1,
                            "BENCHMARK_STARTED": 1,
                            "MODEL_EXECUTION_COMPLETED": 1,
                        },
                    }
                ],
            )
        if method == "GET" and url.endswith("/api/model-observer/summary"):
            return FakeResponse(
                200,
                {
                    "totalEvents": 3,
                    "eventTypes": {
                        "MODEL_DETAIL_VIEWED": 1,
                        "BENCHMARK_STARTED": 1,
                        "MODEL_EXECUTION_COMPLETED": 1,
                    },
                },
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


class AIModelHubModelObserverApiTests(unittest.TestCase):
    def test_connector_interface_proxy_preserves_backend_host_header(self):
        config_path = (
            Path(__file__).resolve().parents[1]
            / "adapters"
            / "inesdata"
            / "sources"
            / "inesdata-connector-interface"
            / "docker"
            / "default.conf"
        )
        content = config_path.read_text(encoding="utf-8")

        self.assertIn("location /inesdata-connector-interface/model-observer/", content)
        self.assertIn("proxy_set_header Host $proxy_host;", content)
        self.assertNotIn("proxy_set_header Host $host;\n        proxy_set_header X-Forwarded-Proto", content)

    def test_build_observer_event_batch_uses_hashes_not_raw_payloads(self):
        batch = build_observer_event_batch("observer-test")

        self.assertEqual(len(batch["events"]), 3)
        event_types = {event["eventType"] for event in batch["events"]}
        self.assertEqual(
            event_types,
            {"MODEL_DETAIL_VIEWED", "BENCHMARK_STARTED", "MODEL_EXECUTION_COMPLETED"},
        )
        for event in batch["events"]:
            self.assertIn("payloadHash", event)
            self.assertIn("responseHash", event)
            self.assertNotIn("rawInput", event)
            self.assertNotIn("rawOutput", event)

    def test_run_model_observer_validation_passes_against_api_contract(self):
        run_context = build_observer_event_batch("observer-pass")
        session = FakeSession(run_context)

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "validation.components.ai_model_hub.model_observer_api.build_observer_event_batch",
                return_value=run_context,
            ),
        ):
            result = run_ai_model_hub_model_observer_validation(
                base_url="http://observer.example.local",
                experiment_dir=tmpdir,
                session=session,
            )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["suite"], "model-observer-api")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"], {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
            self.assertEqual(result["executed_cases"][0]["test_case_id"], CASE_ID)
            self.assertEqual(result["executed_cases"][0]["case_group"], "observer")
            self.assertEqual(result["executed_cases"][0]["evaluation"]["status"], "passed")
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["responses_json"]))

        self.assertEqual([request["method"] for request in session.requests], ["POST", "GET", "GET", "GET", "GET"])
        headers = session.requests[0]["headers"]
        self.assertNotIn("Authorization", headers)

    def test_run_model_observer_validation_uses_edc_connector_api_contract(self):
        run_context = build_observer_event_batch("observer-edc")
        session = FakeEdcSession(run_context)

        with mock.patch(
            "validation.components.ai_model_hub.model_observer_api.build_observer_event_batch",
            return_value=run_context,
        ):
            result = run_ai_model_hub_model_observer_validation(
                base_url="http://dashboard.example.local/edc-dashboard-api/connectors/provider/api",
                session=session,
                adapter_name="edc",
                auth_headers={"Authorization": "Bearer observer-token"},
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["adapter_contract"], "edc")
        self.assertEqual(
            result["observer_service_base_url"],
            "http://dashboard.example.local/edc-dashboard-api/connectors/provider/api/model-observer",
        )
        self.assertEqual(result["summary"], {"total": 1, "passed": 1, "failed": 0, "skipped": 0})
        self.assertEqual([request["method"] for request in session.requests], ["POST", "POST", "POST", "GET", "GET", "GET", "GET", "GET", "GET"])
        self.assertTrue(
            all("/events/bulk" not in request["url"] for request in session.requests),
            [request["url"] for request in session.requests],
        )
        self.assertTrue(
            all(request["headers"].get("Authorization") == "Bearer observer-token" for request in session.requests),
            [request["headers"] for request in session.requests],
        )
        self.assertEqual(result["executed_cases"][0]["adapter_contract"], "edc")

    def test_run_model_observer_validation_normalizes_api_base_url_suffix(self):
        run_context = build_observer_event_batch("observer-normalized")
        session = FakeSession(run_context)

        with mock.patch(
            "validation.components.ai_model_hub.model_observer_api.build_observer_event_batch",
            return_value=run_context,
        ):
            result = run_ai_model_hub_model_observer_validation(
                base_url="http://observer.example.local/api/model-observer",
                session=session,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            resolve_model_observer_api_base_url("http://observer.example.local/api/model-observer"),
            "http://observer.example.local",
        )
        requested_urls = [request["url"] for request in session.requests]
        self.assertTrue(
            all("/api/model-observer/api/model-observer" not in url for url in requested_urls),
            requested_urls,
        )

    def test_run_model_observer_validation_normalizes_edc_model_observer_suffix(self):
        self.assertEqual(
            resolve_model_observer_api_base_url(
                "http://dashboard.example.local/edc-dashboard-api/connectors/provider/api/model-observer",
                adapter_name="edc",
            ),
            "http://dashboard.example.local/edc-dashboard-api/connectors/provider/api",
        )

    def test_run_model_observer_validation_skips_when_base_url_is_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = run_ai_model_hub_model_observer_validation()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["summary"], {"total": 1, "passed": 0, "failed": 0, "skipped": 1})
        self.assertEqual(result["executed_cases"][0]["evaluation"]["status"], "skipped")
        self.assertIn("not configured", result["executed_cases"][0]["skip_reason"])

    def test_run_model_observer_validation_skips_when_endpoint_is_not_integrated(self):
        run_context = build_observer_event_batch("observer-missing")
        session = FakeSession(run_context, bulk_status=404)

        with mock.patch(
            "validation.components.ai_model_hub.model_observer_api.build_observer_event_batch",
            return_value=run_context,
        ):
            result = run_ai_model_hub_model_observer_validation(
                base_url="http://observer.example.local",
                session=session,
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["executed_cases"][0]["evaluation"]["status"], "skipped")
        self.assertIn("not available yet", result["executed_cases"][0]["skip_reason"])
        self.assertEqual(len(session.requests), 1)


if __name__ == "__main__":
    unittest.main()
