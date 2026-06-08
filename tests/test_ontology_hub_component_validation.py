import json
import os
import tempfile
import unittest
from unittest import mock

import yaml

from validation.components.ontology_hub.integration.runner import (
    _http_get_until_stable,
    evaluate_html_page_response,
    evaluate_sparql_response,
    evaluate_term_search_response,
    run_ontology_hub_validation,
)
from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CATALOG_PATH = os.path.join(
    PROJECT_ROOT,
    "validation",
    "components",
    "ontology_hub",
    "integration",
    "test_cases.yaml",
)


class OntologyHubComponentValidationTests(unittest.TestCase):
    def _load_catalog(self):
        with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def test_integration_catalog_does_not_duplicate_inesdata_readonly_route(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        self.assertNotIn("PT5-OH-16", cases)

    def test_pt5_oh14_uses_composite_coverage_for_patterns_service(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}
        case = cases["PT5-OH-14"]

        self.assertEqual(case["coverage_status"], "automated")
        self.assertEqual(case["mapping_status"], "mapped")
        self.assertEqual(case["execution_mode"], "composite_ui_api")
        self.assertEqual(case["automation"]["mode"], "composite_ui_api")
        self.assertEqual(case["automation"]["runner_case"], "pt5_oh_14_patterns_access")
        self.assertIn("composite_evidence", case["automation"])
        self.assertIn("Functional ZIP generation", case["automation"]["notes"])

    def test_runtime_uses_configured_self_host_service_for_shared_vm_single_component(self):
        runtime = resolve_ontology_hub_runtime(
            environ={
                "UI_DATASPACE": "pionera-edc",
                "UI_TOPOLOGY": "vm-single",
                "ONTOLOGY_HUB_BASE_URL": "https://org4.pionera.oeg.fi.upm.es/ontology-hub",
                "ONTOLOGY_HUB_COMPONENTS_NAMESPACE": "components",
                "ONTOLOGY_HUB_SELF_HOST_SERVICE_NAME": "pionera-ontology-hub",
                "ONTOLOGY_HUB_SELF_HOST_SERVICE_PORT": "3333",
            }
        )

        self.assertEqual(runtime["dataspace"], "pionera-edc")
        self.assertEqual(runtime["releaseName"], "pionera-ontology-hub")
        self.assertEqual(runtime["selfHostServiceName"], "pionera-ontology-hub")
        self.assertEqual(runtime["componentsNamespace"], "components")

    def test_runtime_uses_shared_base_release_for_edc_components_by_default(self):
        runtime = resolve_ontology_hub_runtime(
            environ={
                "PIONERA_ADAPTER": "edc",
                "UI_DATASPACE": "pionera-edc",
                "ONTOLOGY_HUB_BASE_URL": "https://org1.pionera.oeg.fi.upm.es/ontology-hub",
                "ONTOLOGY_HUB_COMPONENTS_NAMESPACE": "components",
            }
        )

        self.assertEqual(runtime["dataspace"], "pionera-edc")
        self.assertEqual(runtime["releaseName"], "pionera-ontology-hub")
        self.assertEqual(runtime["componentsNamespace"], "components")

    def test_evaluate_term_search_response_passes_on_valid_json_payload(self):
        payload = {
            "results": [],
            "total_results": 0,
        }

        result = evaluate_term_search_response(
            200,
            "application/json",
            json.dumps(payload),
            expected_query="Person",
            require_results=False,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["json_type"], "dict")
        self.assertEqual(result["payload_keys"], ["results", "total_results"])

    def test_evaluate_term_search_response_fails_on_embedded_error_markers(self):
        payload = {
            "statusCode": 401,
            "msg": "missing authentication credentials",
        }

        result = evaluate_term_search_response(
            200,
            "application/json",
            json.dumps(payload),
            expected_query="Person",
        )

        self.assertEqual(result["status"], "failed")
        self.assertGreaterEqual(len(result["assertions"]), 1)

    def test_evaluate_term_search_response_fails_when_results_are_empty_but_real_content_is_required(self):
        payload = {
            "results": [],
            "total_results": 0,
            "aggregations": {"vocabs": {"buckets": []}, "tags": {"buckets": []}},
        }

        result = evaluate_term_search_response(
            200,
            "application/json",
            json.dumps(payload),
            expected_query="Person",
            expected_vocab="demohub",
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("at least one search result" in item for item in result["assertions"]))

    def test_evaluate_term_search_response_accepts_filtered_results_when_tag_bucket_is_empty(self):
        payload = {
            "total_results": 1,
            "filters": {"vocab": "s4grid", "tag": "Catalogs"},
            "aggregations": {
                "vocabs": {"buckets": [{"key": "s4grid", "doc_count": 1}]},
                "tags": {"buckets": []},
            },
            "results": [
                {
                    "prefixedName": "s4grid:Person",
                    "vocabulary": {"prefix": "s4grid"},
                    "uri": "http://schema.org/Person",
                    "tags": ["Catalogs"],
                }
            ],
        }

        result = evaluate_term_search_response(
            200,
            "application/json",
            json.dumps(payload),
            expected_query="Person",
            expected_vocab="s4grid",
            expected_tag="Catalogs",
        )

        self.assertEqual(result["status"], "passed")

    def test_evaluate_html_page_response_passes_on_expected_markers(self):
        body = "<!doctype html><html><body><h1>SPARQL</h1><a href='/dataset/api'>API</a></body></html>"

        result = evaluate_html_page_response(
            200,
            "text/html; charset=utf-8",
            body,
            required_markers=["SPARQL", "/dataset/api"],
        )

        self.assertEqual(result["status"], "passed")

    def test_evaluate_html_page_response_fails_on_embedded_server_error_page(self):
        body = "<!doctype html><html><body><h1>500 - Oops! something went wrong - 500</h1></body></html>"

        result = evaluate_html_page_response(
            200,
            "text/html; charset=utf-8",
            body,
            required_markers=["Patterns"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(
            any("embedded server error page" in item for item in result["assertions"]),
        )

    def test_evaluate_sparql_response_passes_on_boolean_true(self):
        body = json.dumps({"head": {}, "boolean": True})

        result = evaluate_sparql_response(
            200,
            "application/sparql-results+json",
            body,
        )

        self.assertEqual(result["status"], "passed")

    def test_evaluate_sparql_response_accepts_xml_boolean_true(self):
        body = """<?xml version="1.0"?>
<sparql xmlns="http://www.w3.org/2005/sparql-results#">
  <head></head>
  <boolean>true</boolean>
</sparql>
"""

        result = evaluate_sparql_response(
            200,
            "application/sparql-results+xml",
            body,
        )

        self.assertEqual(result["status"], "passed")

    def test_http_get_until_stable_retries_transient_gateway_errors(self):
        responses = [
            (502, "text/html", "Bad Gateway"),
            (200, "application/sparql-results+json", json.dumps({"boolean": True})),
        ]

        with mock.patch(
            "validation.components.ontology_hub.integration.runner._http_get",
            side_effect=responses,
        ), mock.patch("validation.components.ontology_hub.integration.runner.time.sleep") as sleep_mock:
            status, content_type, body, history = _http_get_until_stable(
                "http://ontology-hub.local/dataset/sparql?query=ASK",
                attempts=3,
                delay_seconds=0.01,
            )

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/sparql-results+json")
        self.assertIn("boolean", body)
        self.assertEqual([entry["http_status"] for entry in history], [502, 200])
        sleep_mock.assert_called_once_with(0.01)

    def test_run_ontology_hub_validation_persists_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_http_get(url, timeout=20):
                if "api/v2/term/search" in url and "tag=Services" in url:
                    payload = {
                        "total_results": 1,
                        "filters": {"vocab": "saref4grid", "tag": "Services"},
                        "aggregations": {
                            "vocabs": {"buckets": [{"key": "saref4grid", "doc_count": 1}]},
                            "tags": {"buckets": []},
                        },
                        "results": [
                            {
                                "prefixedName": ["saref4grid:Person"],
                                "vocabulary": {"prefix": "saref4grid"},
                                "uri": ["http://schema.org/Person"],
                                "tags": ["Services"],
                            }
                        ],
                    }
                    return 200, "application/json", json.dumps(payload)
                if "api/v2/term/search" in url:
                    payload = {
                        "total_results": 1,
                        "filters": {},
                        "aggregations": {
                            "vocabs": {"buckets": [{"key": "saref4grid", "doc_count": 1}]},
                            "tags": {"buckets": []},
                        },
                        "results": [
                            {
                                "prefixedName": ["saref4grid:Person"],
                                "vocabulary": {"prefix": "saref4grid"},
                                "uri": ["http://schema.org/Person"],
                                "tags": ["Services"],
                            }
                        ],
                    }
                    return 200, "application/json", json.dumps(payload)
                if "/dataset/sparql?" in url:
                    return 200, "application/sparql-results+json", json.dumps({"head": {}, "boolean": True})
                if url.endswith("/dataset/patterns?q=saref4grid"):
                    return 200, "text/html", "<html><body><h1>Patterns</h1><div>Selected vocabularies</div><input id='checkbox_saref4grid'></body></html>"
                if url.endswith("/dataset/api"):
                    return 200, "text/html", "<html><body>Pionera API /api/v2/term/search /dataset/api/v2/agent/list</body></html>"
                if url.endswith("/dataset"):
                    return 200, "text/html", "<html><body><a href='/dataset/api'>API</a><a href='/dataset/vocabs'>Vocabs</a></body></html>"
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch("validation.components.ontology_hub.integration.runner._http_get", side_effect=fake_http_get):
                with mock.patch(
                    "validation.components.ontology_hub.integration.runner._kubectl_http_get_until_stable",
                    return_value=(
                        200,
                        "application/sparql-results+json",
                        json.dumps({"head": {}, "boolean": True}),
                        [{"attempt": 1, "http_status": 200}],
                        True,
                    ),
                ):
                    result = run_ontology_hub_validation(
                        "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                        experiment_dir=tmpdir,
                    )

            self.assertEqual(result["component"], "ontology-hub")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["passed"], 5)
            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["pt5_summary"]["total"], 5)
            self.assertEqual(result["pt5_summary"]["passed"], 5)
            self.assertEqual(result["support_summary"]["total"], 0)
            self.assertTrue(all(case["case_group"] == "pt5" for case in result["executed_cases"]))
            self.assertEqual(len(result["evidence_index"]), 6)
            self.assertTrue(result["artifacts"]["report_json"].endswith("ontology_hub_validation.json"))
            self.assertTrue(result["artifacts"]["pt5-oh-08-response.json"].endswith("pt5-oh-08-response.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-oh-08-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-oh-09-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-oh-13-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-oh-14-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5-oh-15-response.json"]))


if __name__ == "__main__":
    unittest.main()
