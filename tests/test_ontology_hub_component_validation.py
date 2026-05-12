import json
import os
import tempfile
import unittest
from unittest import mock

from validation.components.ontology_hub.integration.runner import (
    evaluate_html_page_response,
    evaluate_sparql_response,
    evaluate_term_search_response,
    run_ontology_hub_validation,
)


class OntologyHubComponentValidationTests(unittest.TestCase):
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

    def test_run_ontology_hub_validation_persists_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_http_get(url, timeout=20):
                if "api/v2/term/search" in url and "tag=Catalogs" in url:
                    payload = {
                        "total_results": 1,
                        "filters": {"vocab": "s4grid", "tag": "Catalogs"},
                        "aggregations": {
                            "vocabs": {"buckets": [{"key": "s4grid", "doc_count": 1}]},
                            "tags": {"buckets": []},
                        },
                        "results": [
                            {
                                "prefixedName": ["s4grid:Person"],
                                "vocabulary": {"prefix": "s4grid"},
                                "uri": ["http://schema.org/Person"],
                                "tags": ["Catalogs"],
                            }
                        ],
                    }
                    return 200, "application/json", json.dumps(payload)
                if "api/v2/term/search" in url:
                    payload = {
                        "total_results": 1,
                        "filters": {},
                        "aggregations": {
                            "vocabs": {"buckets": [{"key": "s4grid", "doc_count": 1}]},
                            "tags": {"buckets": []},
                        },
                        "results": [
                            {
                                "prefixedName": ["s4grid:Person"],
                                "vocabulary": {"prefix": "s4grid"},
                                "uri": ["http://schema.org/Person"],
                                "tags": ["Catalogs"],
                            }
                        ],
                    }
                    return 200, "application/json", json.dumps(payload)
                if "/dataset/sparql?" in url:
                    return 200, "application/sparql-results+json", json.dumps({"head": {}, "boolean": True})
                if url.endswith("/dataset/patterns?q=s4grid"):
                    return 200, "text/html", "<html><body><h1>Patterns</h1><div>Selected vocabularies</div><input id='checkbox_s4grid'></body></html>"
                if url.endswith("/dataset/api"):
                    return 200, "text/html", "<html><body>Pionera API /api/v2/term/search /dataset/api/v2/agent/list</body></html>"
                if url.endswith("/dataset"):
                    return 200, "text/html", "<html><body><a href='/dataset/api'>API</a><a href='/dataset/vocabs'>Vocabs</a></body></html>"
                raise AssertionError(f"Unexpected URL: {url}")

            with mock.patch("validation.components.ontology_hub.integration.runner._http_get", side_effect=fake_http_get):
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
