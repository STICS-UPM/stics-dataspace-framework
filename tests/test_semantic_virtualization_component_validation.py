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
    def _suite_result(self, suite, case_id, case_group="pt5"):
        return {
            "component": "semantic-virtualization",
            "suite": suite,
            "status": "passed",
            "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
            "test_cases": [
                {
                    "test_case_id": case_id,
                    "case_group": case_group,
                    "evaluation": {"status": "passed", "assertions": []},
                }
            ],
            "evidence_index": [],
            "artifacts": {},
        }

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
            ), mock.patch.dict(
                os.environ,
                {"SEMANTIC_VIRTUALIZATION_ENABLE_UI_VALIDATION": ""},
                clear=False,
            ), mock.patch(
                "validation.components.semantic_virtualization.runner.run_morph_kgv_source_validation",
                return_value=self._suite_result("morph-kgv-source", "SV-MORPH-KGV-01", "support"),
            ), mock.patch(
                "validation.components.semantic_virtualization.runner.run_automap_source_validation",
                return_value=self._suite_result("automap-source", "SV-AUTOMAP-01", "support"),
            ), mock.patch(
                "validation.components.semantic_virtualization.runner.run_automap_deterministic_execution_validation",
                return_value=self._suite_result("automap-deterministic-execution", "SV-AUTOMAP-02"),
            ), mock.patch(
                "validation.components.semantic_virtualization.runner.run_semantic_virtualization_mapping_validation",
                return_value=self._suite_result("mapping-fixtures", "PT5-VS-01"),
            ), mock.patch(
                "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_source_validation",
                return_value=self._suite_result("gtfs-bench-official-source", "SV-GTFS-BENCH-01", "support"),
            ), mock.patch(
                "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_dataset_validation",
                return_value=self._suite_result("gtfs-bench-official-dataset", "SV-GTFS-BENCH-02", "support"),
            ), mock.patch(
                "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_materialization_validation",
                return_value=self._suite_result("gtfs-bench-official-materialization", "SV-GTFS-BENCH-03", "support"),
            ):
                result = run_semantic_virtualization_validation(
                    "http://semantic.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "semantic-virtualization")
            self.assertEqual(result["suite"], "api")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 12)
            self.assertEqual(result["summary"]["passed"], 12)
            self.assertEqual(result["phase_order"], ["preflight", "functional", "integration"])
            self.assertEqual(result["executed_cases"][1]["test_case_id"], "SV-API-04")
            self.assertEqual(result["phases"]["functional"]["summary"]["total"], 8)
            self.assertEqual(result["phases"]["integration"]["summary"]["total"], 3)
            self.assertEqual(result["pt5_summary"]["total"], 6)
            self.assertEqual(result["support_summary"]["total"], 6)
            self.assertGreaterEqual(len(result["evidence_index"]), 12)
            self.assertIn("morph_kgv_source", result["phases"]["functional"]["suites"])
            self.assertIn("automap_source", result["phases"]["functional"]["suites"])
            self.assertIn("automap_execution", result["phases"]["functional"]["suites"])
            self.assertIn("mapping_fixtures", result["phases"]["functional"]["suites"])
            self.assertIn("gtfs_bench_source", result["phases"]["functional"]["suites"])
            self.assertIn("gtfs_bench_dataset", result["phases"]["functional"]["suites"])
            self.assertIn("gtfs_bench_materialization", result["phases"]["functional"]["suites"])
            self.assertTrue(result["artifacts"]["report_json"].endswith("semantic_virtualization_component_validation.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["artifact_manifest_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-bootstrap-01-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-01-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-02-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-03-response.json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["sv-api-04-response.json"]))

    def test_run_semantic_virtualization_validation_runs_ui_functional_before_integration(self):
        calls = []

        def fake_http_get(url, timeout=20, headers=None):
            if url == "http://semantic.example.local":
                calls.append("preflight" if "preflight" not in calls else "integration-health")
                return 200, "text/html", "<html><body>Semantic Virtualization</body></html>"
            if url == "http://semantic.example.local/?query=SELECT%20WHERE%20%7B":
                calls.append("functional-api")
                return 400, "application/json", json.dumps({"message": "Expected SelectQuery"})
            if url == "http://semantic.example.local/openapi.json":
                calls.append("integration-openapi")
                return 200, "application/json", json.dumps({"paths": {"/": {"get": {}}}})
            if url.startswith("http://semantic.example.local/?query="):
                calls.append("integration-query")
                return 200, "application/sparql-results+json", json.dumps({"head": {}, "results": {}})
            raise AssertionError(f"Unexpected URL: {url}")

        def fake_ui_runner(base_url, experiment_dir=None):
            calls.append("functional-ui")
            return {
                "component": "semantic-virtualization",
                "suite": "ui",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "PT5-VS-07",
                        "case_group": "pt5",
                        "evaluation": {"status": "passed"},
                    }
                ],
                "pt5_case_results": [],
                "support_checks": [],
                "evidence_index": [],
                "artifacts": {},
            }

        def fake_functional_suite(name, case_id):
            def _run(experiment_dir=None):
                calls.append(name)
                return self._suite_result(name, case_id)

            return _run

        def fake_support_suite(name, case_id):
            def _run(experiment_dir=None):
                calls.append(name)
                return self._suite_result(name, case_id, "support")

            return _run

        with (
            mock.patch("validation.components.semantic_virtualization.runner._http_get", side_effect=fake_http_get),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_morph_kgv_source_validation",
                side_effect=fake_support_suite("functional-morph-kgv-source", "SV-MORPH-KGV-01"),
            ),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_automap_source_validation",
                side_effect=fake_support_suite("functional-automap-source", "SV-AUTOMAP-01"),
            ),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_automap_deterministic_execution_validation",
                side_effect=fake_functional_suite("functional-automap-execution", "SV-AUTOMAP-02"),
            ),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_semantic_virtualization_mapping_validation",
                side_effect=fake_functional_suite("functional-mapping", "PT5-VS-01"),
            ),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_source_validation",
                side_effect=fake_functional_suite("functional-gtfs-source", "SV-GTFS-BENCH-01"),
            ),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_dataset_validation",
                side_effect=fake_functional_suite("functional-gtfs-dataset", "SV-GTFS-BENCH-02"),
            ),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_materialization_validation",
                side_effect=fake_functional_suite("functional-gtfs-materialization", "SV-GTFS-BENCH-03"),
            ),
            mock.patch(
                "validation.components.semantic_virtualization.runner.run_semantic_virtualization_ui_validation",
                side_effect=fake_ui_runner,
            ),
            mock.patch("builtins.print") as print_mock,
        ):
            result = run_semantic_virtualization_validation("http://semantic.example.local")

        printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
        self.assertIn("Component API suite: Virtualizador functional", printed)
        self.assertIn("Component Playwright suite: Virtualizador functional", printed)
        self.assertIn("Component API suite: Virtualizador integration", printed)
        self.assertIn("✓ SV-API-03", printed)
        self.assertLess(calls.index("functional-api"), calls.index("functional-ui"))
        self.assertLess(calls.index("functional-morph-kgv-source"), calls.index("functional-ui"))
        self.assertLess(calls.index("functional-automap-source"), calls.index("functional-ui"))
        self.assertLess(calls.index("functional-automap-execution"), calls.index("functional-ui"))
        self.assertLess(calls.index("functional-mapping"), calls.index("functional-ui"))
        self.assertLess(calls.index("functional-ui"), calls.index("integration-health"))
        self.assertIn("ui", result["phases"]["functional"]["suites"])
        self.assertIn("api", result["phase_execution_channels"]["functional"])
        self.assertIn("playwright", result["phase_execution_channels"]["functional"])
        self.assertEqual(result["phase_execution_channels"]["integration"], ["api"])
        self.assertEqual(result["summary"]["total"], 13)
        self.assertEqual(result["pt5_summary"]["total"], 10)

    def test_run_semantic_virtualization_validation_uses_api_only_mode_for_edc(self):
        def fake_http_get(url, timeout=20, headers=None):
            if url == "http://semantic.example.local":
                return 200, "text/html", "<html><body>Semantic Virtualization</body></html>"
            if url == "http://semantic.example.local/?query=SELECT%20WHERE%20%7B":
                return 400, "application/json", json.dumps({"message": "Expected SelectQuery"})
            if url == "http://semantic.example.local/openapi.json":
                return 200, "application/json", json.dumps({"paths": {"/": {"get": {}}}})
            if url.startswith("http://semantic.example.local/?query="):
                return 200, "application/sparql-results+json", json.dumps({"head": {}, "results": {}})
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch("validation.components.semantic_virtualization.runner._http_get", side_effect=fake_http_get),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_morph_kgv_source_validation",
                    return_value=self._suite_result("morph-kgv-source", "SV-MORPH-KGV-01", "support"),
                ),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_automap_source_validation",
                    return_value=self._suite_result("automap-source", "SV-AUTOMAP-01", "support"),
                ),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_automap_deterministic_execution_validation",
                    return_value=self._suite_result("automap-deterministic-execution", "SV-AUTOMAP-02"),
                ),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_semantic_virtualization_mapping_validation",
                    return_value=self._suite_result("mapping-fixtures", "PT5-VS-01"),
                ),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_source_validation",
                    return_value=self._suite_result("gtfs-bench-official-source", "SV-GTFS-BENCH-01", "support"),
                ),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_dataset_validation",
                    return_value=self._suite_result("gtfs-bench-official-dataset", "SV-GTFS-BENCH-02", "support"),
                ),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_gtfs_bench_official_materialization_validation",
                    return_value=self._suite_result("gtfs-bench-official-materialization", "SV-GTFS-BENCH-03", "support"),
                ),
                mock.patch(
                    "validation.components.semantic_virtualization.runner.run_semantic_virtualization_ui_validation"
                ) as ui,
                mock.patch.dict(os.environ, {"PIONERA_ADAPTER": "edc"}, clear=True),
            ):
                result = run_semantic_virtualization_validation(
                    "http://semantic.example.local",
                    experiment_dir=tmpdir,
                )

        ui.assert_not_called()
        self.assertEqual(result["validation_mode"], "api")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"]["total"], 12)
        self.assertNotIn("ui", result["suites"])
        self.assertEqual(result["phase_execution_channels"]["preflight"], ["api"])
        self.assertEqual(result["phase_execution_channels"]["functional"], ["api"])
        self.assertEqual(result["phase_execution_channels"]["integration"], ["api"])

    def test_semantic_virtualization_is_registered_for_component_level6(self):
        registration = get_component_registration("semantic_virtualization")
        runners = registered_component_runners()

        self.assertIsNotNone(registration)
        self.assertEqual(registration.component, "semantic-virtualization")
        self.assertIn("semantic-virtualization", runners)


if __name__ == "__main__":
    unittest.main()
