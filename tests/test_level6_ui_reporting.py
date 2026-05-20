import json
import os
import tempfile
import unittest

from validation.ui.reporting import (
    aggregate_level6_ui_results,
    enrich_level6_ui_result,
    load_ui_catalog,
)


def _build_core_playwright_payload():
    return {
        "stats": {
            "expected": 2,
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "adapters/inesdata/specs/01-login-readiness.spec.ts",
                "file": "adapters/inesdata/specs/01-login-readiness.spec.ts",
                "specs": [
                    {
                        "title": "01 login readiness: authentication and shell loaded",
                        "file": "adapters/inesdata/specs/01-login-readiness.spec.ts",
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "passed",
                                        "errors": [],
                                        "attachments": [
                                            {
                                                "name": "01-after-login",
                                                "contentType": "image/png",
                                                "path": "/tmp/login.png",
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            },
            {
                "title": "adapters/inesdata/specs/04-consumer-catalog.spec.ts",
                "file": "adapters/inesdata/specs/04-consumer-catalog.spec.ts",
                "specs": [
                    {
                        "title": "04 consumer catalog: listing and detail without access errors",
                        "file": "adapters/inesdata/specs/04-consumer-catalog.spec.ts",
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "passed",
                                        "errors": [],
                                        "attachments": [
                                            {
                                                "name": "trace",
                                                "contentType": "application/zip",
                                                "path": "/tmp/catalog-trace.zip",
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            },
        ],
    }


def _build_dataspace_playwright_payload():
    return {
        "stats": {
            "expected": 5,
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "adapters/inesdata/specs/03-provider-setup.spec.ts",
                "file": "adapters/inesdata/specs/03-provider-setup.spec.ts",
                "specs": [
                    {
                        "title": "03 provider setup: asset creation with file upload",
                        "file": "adapters/inesdata/specs/03-provider-setup.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "adapters/inesdata/specs/03b-provider-policy-create.spec.ts",
                "file": "adapters/inesdata/specs/03b-provider-policy-create.spec.ts",
                "specs": [
                    {
                        "title": "03b provider setup: policy creation from the UI",
                        "file": "adapters/inesdata/specs/03b-provider-policy-create.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "adapters/inesdata/specs/03c-provider-contract-definition-create.spec.ts",
                "file": "adapters/inesdata/specs/03c-provider-contract-definition-create.spec.ts",
                "specs": [
                    {
                        "title": "03c provider setup: contract definition creation from the UI",
                        "file": "adapters/inesdata/specs/03c-provider-contract-definition-create.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "adapters/inesdata/specs/05-consumer-negotiation.spec.ts",
                "file": "adapters/inesdata/specs/05-consumer-negotiation.spec.ts",
                "specs": [
                    {
                        "title": "05 consumer negotiation: visible negotiation from catalog",
                        "file": "adapters/inesdata/specs/05-consumer-negotiation.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "adapters/inesdata/specs/06-consumer-transfer.spec.ts",
                "file": "adapters/inesdata/specs/06-consumer-transfer.spec.ts",
                "specs": [
                    {
                        "title": "06 consumer transfer: visible transfer from contracts and history",
                        "file": "adapters/inesdata/specs/06-consumer-transfer.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
        ],
    }


class Level6UIReportingTests(unittest.TestCase):
    def test_load_ui_catalog_declares_core_and_ops_cases(self):
        catalog = load_ui_catalog()

        self.assertEqual(len(catalog["support_checks"]), 1)
        self.assertEqual(len(catalog["dataspace_cases"]), 16)
        self.assertEqual(len(catalog["ops_checks"]), 1)
        self.assertTrue(catalog["source_files"]["inesdata_integration"].endswith("validation/projects/inesdata/integration/test_cases.yaml"))
        self.assertEqual(catalog["support_checks"][0]["id"], "DS-UI-01")
        self.assertEqual(catalog["support_checks"][0]["operations"], ["login", "load_portal_shell"])
        self.assertEqual(catalog["dataspace_cases"][0]["id"], "DS-UI-03")
        self.assertIn("DS-UI-AMH-01", [case["id"] for case in catalog["dataspace_cases"]])
        self.assertIn("DS-UI-AMH-BROWSER-01", [case["id"] for case in catalog["dataspace_cases"]])
        self.assertIn("DS-UI-AMH-EXEC-01", [case["id"] for case in catalog["dataspace_cases"]])
        self.assertIn("DS-UI-AMH-EXEC-02", [case["id"] for case in catalog["dataspace_cases"]])
        self.assertIn("DS-UI-AMH-BENCH-01", [case["id"] for case in catalog["dataspace_cases"]])
        self.assertIn("DS-UI-AMH-DAIMO-01", [case["id"] for case in catalog["dataspace_cases"]])
        self.assertIn("DS-UI-AMH-OBS-01", [case["id"] for case in catalog["dataspace_cases"]])
        self.assertIn("DS-UI-AMH-OBS-02", [case["id"] for case in catalog["dataspace_cases"]])
        ai_model_hub_case = next(case for case in catalog["dataspace_cases"] if case["id"] == "DS-UI-AMH-01")
        self.assertEqual(
            ai_model_hub_case["operations"],
            [
                "publish_ai_model_httpdata",
                "discover_asset",
                "open_catalog_detail",
                "validate_model_metadata",
                "negotiate_contract",
                "verify_contract_agreement",
            ],
        )
        ai_model_browser_case = next(case for case in catalog["dataspace_cases"] if case["id"] == "DS-UI-AMH-BROWSER-01")
        self.assertEqual(
            ai_model_browser_case["operations"],
            [
                "publish_machine_learning_httpdata",
                "open_ai_model_browser",
                "search_model",
                "validate_model_card_metadata",
                "filter_model_results_by_source_and_storage",
                "filter_model_results_by_daimo_metadata",
                "open_contract_offer_from_browser_primary_action",
                "open_model_detail",
                "validate_model_detail_and_offer",
                "validate_browser_observer_evidence",
            ],
        )
        ai_model_execution_case = next(case for case in catalog["dataspace_cases"] if case["id"] == "DS-UI-AMH-EXEC-01")
        self.assertEqual(
            ai_model_execution_case["operations"],
            [
                "publish_machine_learning_httpdata",
                "open_ai_model_execution",
                "select_executable_model",
                "validate_execution_input_metadata",
                "validate_execution_input_schema_errors",
                "execute_model",
                "validate_execution_output",
                "inspect_execution_history",
                "validate_execution_observer_evidence",
            ],
        )
        ai_model_benchmarking_case = next(case for case in catalog["dataspace_cases"] if case["id"] == "DS-UI-AMH-BENCH-01")
        self.assertEqual(
            ai_model_benchmarking_case["operations"],
            [
                "publish_machine_learning_httpdata",
                "open_ai_model_benchmarking",
                "select_benchmark_models",
                "validate_benchmark_input",
                "obtain_model_outputs",
                "download_suggested_dataset",
                "upload_validation_dataset",
                "run_model_benchmark",
                "validate_benchmark_ranking",
                "export_benchmark_results",
                "validate_observer_benchmark_evidence",
            ],
        )
        observer_case = next(case for case in catalog["dataspace_cases"] if case["id"] == "DS-UI-AMH-OBS-01")
        self.assertEqual(observer_case["coverage_status"], "automated")
        self.assertEqual(observer_case["mapping_status"], "mapped")
        self.assertFalse(
            any(case["coverage_status"] == "automated_opt_in" for case in catalog["dataspace_cases"])
        )
        self.assertEqual(catalog["ops_checks"][0]["id"], "DS-UI-OPS-01")
        self.assertEqual(catalog["ops_checks"][0]["operations"], ["inspect_storage", "verify_bucket_visibility"])

    def test_enrich_level6_ui_result_maps_core_smoke_specs_to_catalog_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_report_file = os.path.join(tmpdir, "results.json")
            report_json = os.path.join(tmpdir, "ui_core_validation.json")
            with open(json_report_file, "w", encoding="utf-8") as handle:
                json.dump(_build_core_playwright_payload(), handle)

            result = enrich_level6_ui_result(
                {
                    "test": "ui-core-smoke",
                    "status": "passed",
                    "portal_url": "https://conn-a.example.local",
                    "specs": [
                        os.path.join("core", "01-login-readiness.spec.ts"),
                        os.path.join("core", "04-consumer-catalog.spec.ts"),
                    ],
                    "artifacts": {
                        "json_report_file": json_report_file,
                        "report_json": report_json,
                        "html_report_dir": os.path.join(tmpdir, "playwright-report"),
                        "blob_report_dir": os.path.join(tmpdir, "blob-report"),
                        "test_results_dir": os.path.join(tmpdir, "test-results"),
                    },
                }
            )

            self.assertEqual(result["suite"], "ui-core")
            self.assertEqual(result["scope"], "dataspace_ui")
            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(result["summary"]["passed"], 2)
            self.assertEqual(len(result["support_checks"]), 1)
            self.assertEqual(result["support_checks"][0]["test_case_id"], "DS-UI-01")
            self.assertEqual(len(result["dataspace_cases"]), 1)
            self.assertEqual(result["dataspace_cases"][0]["test_case_id"], "DS-UI-04")
            self.assertEqual(result["support_summary"]["passed"], 1)
            self.assertEqual(result["dataspace_summary"]["passed"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_support_checks"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_dataspace_cases"], 1)
            self.assertEqual(
                result["operations_involved"],
                ["list_catalog", "load_portal_shell", "login", "open_catalog_detail"],
            )
            self.assertEqual(result["operation_summary"]["login"]["passed"], 1)
            self.assertEqual(result["operation_summary"]["list_catalog"]["test_case_ids"], ["DS-UI-04"])
            self.assertTrue(os.path.exists(report_json))
            self.assertGreaterEqual(len(result["evidence_index"]), 4)

    def test_enrich_level6_ui_result_uses_placeholder_mapping_when_json_report_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_json = os.path.join(tmpdir, "ui_ops_validation.json")
            result = enrich_level6_ui_result(
                {
                    "test": "ui-ops-minio-console",
                    "status": "passed",
                    "provider_connector": "conn-a",
                    "consumer_connector": "conn-b",
                    "specs": [os.path.join("ops", "minio-bucket-visibility.spec.ts")],
                    "artifacts": {
                        "json_report_file": os.path.join(tmpdir, "missing-results.json"),
                        "report_json": report_json,
                    },
                }
            )

            self.assertEqual(result["suite"], "ui-ops")
            self.assertEqual(result["summary"]["total"], 1)
            self.assertEqual(result["ops_summary"]["passed"], 1)
            self.assertEqual(len(result["ops_checks"]), 1)
            self.assertEqual(result["ops_checks"][0]["test_case_id"], "DS-UI-OPS-01")
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_ops_checks"], 1)
            self.assertEqual(result["operations_involved"], ["inspect_storage", "verify_bucket_visibility"])
            self.assertEqual(result["operation_summary"]["inspect_storage"]["passed"], 1)
            self.assertTrue(os.path.exists(report_json))

    def test_aggregate_level6_ui_results_builds_experiment_level_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core_json = os.path.join(tmpdir, "core-results.json")
            with open(core_json, "w", encoding="utf-8") as handle:
                json.dump(_build_core_playwright_payload(), handle)

            core_result = enrich_level6_ui_result(
                {
                    "test": "ui-core-smoke",
                    "status": "passed",
                    "connector": "conn-a",
                    "portal_url": "https://conn-a.example.local",
                    "specs": [
                        os.path.join("core", "01-login-readiness.spec.ts"),
                        os.path.join("core", "04-consumer-catalog.spec.ts"),
                    ],
                    "artifacts": {
                        "json_report_file": core_json,
                        "report_json": os.path.join(tmpdir, "ui_core_validation.json"),
                    },
                }
            )

            ops_result = enrich_level6_ui_result(
                {
                    "test": "ui-ops-minio-console",
                    "status": "passed",
                    "provider_connector": "conn-a",
                    "consumer_connector": "conn-b",
                    "specs": [os.path.join("ops", "minio-bucket-visibility.spec.ts")],
                    "artifacts": {
                        "json_report_file": os.path.join(tmpdir, "missing-ops.json"),
                        "report_json": os.path.join(tmpdir, "ui_ops_validation.json"),
                    },
                }
            )

            summary = aggregate_level6_ui_results(
                [core_result, ops_result],
                experiment_dir=tmpdir,
            )

            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["summary"]["total"], 2)
            self.assertEqual(summary["summary"]["passed"], 2)
            self.assertEqual(summary["execution_summary"]["total"], 3)
            self.assertEqual(summary["support_summary"]["passed"], 1)
            self.assertEqual(summary["dataspace_summary"]["passed"], 1)
            self.assertEqual(summary["ops_summary"]["passed"], 1)
            self.assertEqual(summary["catalog_coverage_summary"]["support_checks"]["total"], 1)
            self.assertEqual(summary["catalog_coverage_summary"]["dataspace_cases"]["total"], 1)
            self.assertEqual(summary["catalog_coverage_summary"]["ops_checks"]["total"], 1)
            self.assertEqual(summary["catalog_alignment"]["summary"]["executed_support_checks"], 1)
            self.assertEqual(summary["catalog_alignment"]["summary"]["executed_dataspace_cases"], 1)
            self.assertEqual(summary["catalog_alignment"]["summary"]["executed_ops_checks"], 1)
            self.assertEqual(
                summary["operations_involved"],
                [
                    "inspect_storage",
                    "list_catalog",
                    "load_portal_shell",
                    "login",
                    "open_catalog_detail",
                    "verify_bucket_visibility",
                ],
            )
            self.assertEqual(summary["operation_summary"]["login"]["passed"], 1)
            self.assertEqual(summary["operation_summary"]["inspect_storage"]["passed"], 1)
            self.assertTrue(summary["artifacts"]["report_json"].endswith("ui_validation_summary.json"))
            self.assertTrue(os.path.exists(summary["artifacts"]["report_json"]))

    def test_enrich_level6_ui_result_maps_dataspace_specs_to_catalog_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_report_file = os.path.join(tmpdir, "results.json")
            report_json = os.path.join(tmpdir, "ui_dataspace_validation.json")
            with open(json_report_file, "w", encoding="utf-8") as handle:
                json.dump(_build_dataspace_playwright_payload(), handle)

            result = enrich_level6_ui_result(
                {
                    "test": "ui-core-dataspace",
                    "status": "passed",
                    "provider_connector": "conn-a",
                    "consumer_connector": "conn-b",
                    "specs": [
                        os.path.join("core", "03-provider-setup.spec.ts"),
                        os.path.join("core", "03b-provider-policy-create.spec.ts"),
                        os.path.join("core", "03c-provider-contract-definition-create.spec.ts"),
                        os.path.join("core", "05-consumer-negotiation.spec.ts"),
                        os.path.join("core", "06-consumer-transfer.spec.ts"),
                    ],
                    "artifacts": {
                        "json_report_file": json_report_file,
                        "report_json": report_json,
                    },
                }
            )

            self.assertEqual(result["suite"], "ui-core-dataspace")
            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["summary"]["passed"], 5)
            self.assertEqual(len(result["dataspace_cases"]), 5)
            self.assertEqual(
                [case["test_case_id"] for case in result["dataspace_cases"]],
                ["DS-UI-03", "DS-UI-03B", "DS-UI-03C", "DS-UI-05", "DS-UI-06"],
            )
            self.assertEqual(result["dataspace_summary"]["passed"], 5)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_dataspace_cases"], 5)
            self.assertIn("create_asset", result["operations_involved"])
            self.assertIn("start_transfer", result["operations_involved"])
            self.assertEqual(result["operation_summary"]["create_policy"]["passed"], 1)
            self.assertTrue(os.path.exists(report_json))


if __name__ == "__main__":
    unittest.main()
