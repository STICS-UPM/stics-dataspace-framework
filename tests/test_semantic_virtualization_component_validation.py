import json
import os
import tempfile
import unittest
from unittest import mock

from validation.components.registry import (
    get_component_registration,
    registered_component_runners,
)
from validation.components.semantic_virtualization.runner import (
    evaluate_controlled_error_response,
    evaluate_http_response,
    run_semantic_virtualization_validation,
)


class SemanticVirtualizationComponentValidationTests(unittest.TestCase):
    def test_evaluate_http_response_accepts_json_capabilities_payload(self):
        result = evaluate_http_response(
            200,
            "application/json",
            json.dumps({"rml": True, "r2rml": True}),
            require_json=True,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["payload_keys"], ["r2rml", "rml"])

    def test_evaluate_http_response_fails_when_json_is_required(self):
        result = evaluate_http_response(
            200,
            "text/plain",
            "ok",
            require_json=True,
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("not valid JSON" in item for item in result["assertions"]))

    def test_evaluate_controlled_error_response_accepts_http_4xx_with_body(self):
        result = evaluate_controlled_error_response(
            400,
            "application/json",
            json.dumps({"message": "Expected SelectQuery"}),
        )

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["controlled_error"])

    def test_evaluate_controlled_error_response_rejects_successful_invalid_query(self):
        result = evaluate_controlled_error_response(
            200,
            "application/sparql-results+json",
            json.dumps({"head": {}, "results": {}}),
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("unexpectedly succeeded" in item for item in result["assertions"]))

    def test_run_semantic_virtualization_validation_persists_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_http_get(url, timeout=20, headers=None):
                if url == "http://semantic.example.local":
                    return 200, "text/html", "<html><body>Semantic Virtualization</body></html>"
                if url == "http://semantic.example.local/openapi.json":
                    return 200, "application/json", json.dumps({"paths": {"/": {"get": {}}}})
                if url == "http://semantic.example.local/?query=SELECT%20WHERE%20%7B":
                    self.assertEqual(headers, {"Accept": "application/sparql-results+json"})
                    return 400, "application/json", json.dumps({"message": "Expected SelectQuery"})
                if url.startswith("http://semantic.example.local/?query="):
                    self.assertEqual(headers, {"Accept": "application/sparql-results+json"})
                    return 200, "application/sparql-results+json", json.dumps({"head": {}, "results": {}})
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch(
                "validation.components.semantic_virtualization.runner._http_get",
                side_effect=fake_http_get,
            ):
                result = run_semantic_virtualization_validation(
                    "http://semantic.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "semantic-virtualization")
            self.assertEqual(result["suite"], "api")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["summary"]["passed"], 5)
            self.assertEqual(result["phase_order"], ["preflight", "functional", "integration"])
            self.assertEqual(result["executed_cases"][1]["test_case_id"], "SV-API-04")
            self.assertEqual(result["phases"]["functional"]["summary"]["total"], 1)
            self.assertEqual(result["phases"]["integration"]["summary"]["total"], 3)
            self.assertEqual(result["pt5_summary"]["total"], 4)
            self.assertEqual(result["support_summary"]["total"], 1)
            self.assertEqual(len(result["evidence_index"]), 6)
            self.assertTrue(result["artifacts"]["report_json"].endswith("semantic_virtualization_component_validation.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-bootstrap-01-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-01-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-02-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-03-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-04-response.json"]))

    def test_semantic_virtualization_is_registered_for_component_level6(self):
        registration = get_component_registration("semantic_virtualization")
        runners = registered_component_runners()

        self.assertIsNotNone(registration)
        self.assertEqual(registration.component, "semantic-virtualization")
        self.assertIn("semantic-virtualization", runners)


if __name__ == "__main__":
    unittest.main()
