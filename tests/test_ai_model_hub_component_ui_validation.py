import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from validation.components.ai_model_hub.ui_runner import (
    UI_CASE_METADATA,
    run_ai_model_hub_ui_validation,
)


def _build_playwright_results_payload():
    spec_titles = [
        "PT5-MH-01: model catalog view is reachable from the public UI",
        "PT5-MH-02: provider can register a local model asset with valid metadata",
        "PT5-MH-03: provider publication becomes visible through the consumer catalog UI",
        "PT5-MH-04: model listing view renders a controlled model card",
        "PT5-MH-05: model discovery search returns the controlled matching model",
        "PT5-MH-06: model discovery filter shell is available in the ML assets view",
        "PT5-MH-07: model details view exposes functional and technical metadata",
        "PT5-MH-08: contract negotiation from catalog registers an agreement in the consumer connector",
        "PT5-MH-12: benchmarking UI selects multiple FLARES models",
        "PT5-MH-13: benchmarking UI executes selected models with the same input",
        "PT5-MH-14: benchmarking UI renders calculated comparison metrics",
        "PT5-MH-15: benchmarking UI shows comparative table and best model summary",
    ]
    return {
        "stats": {
            "expected": len(spec_titles),
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "ai-model-hub-ui",
                "suites": [],
                "specs": [
                    {
                        "title": title,
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "passed",
                                        "attachments": [
                                            {
                                                "name": "trace",
                                                "contentType": "application/zip",
                                                "path": "trace.zip",
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                    for title in spec_titles
                ],
            }
        ],
    }


class AIModelHubComponentUIValidationTests(unittest.TestCase):
    def test_catalog_access_case_is_reported_as_mapped_ui(self):
        metadata = UI_CASE_METADATA["PT5-MH-01"]

        self.assertEqual(metadata["mapping_status"], "mapped")
        self.assertEqual(metadata["coverage_status"], "automated")
        self.assertEqual(metadata["automation_mode"], "ui")
        self.assertEqual(metadata["execution_mode"], "ui")

    def test_reinforced_discovery_cases_are_reported_as_mapped_api_ui(self):
        for case_id in ["PT5-MH-04", "PT5-MH-05", "PT5-MH-06", "PT5-MH-07"]:
            with self.subTest(case_id=case_id):
                self.assertEqual(UI_CASE_METADATA[case_id]["mapping_status"], "mapped")
                self.assertEqual(UI_CASE_METADATA[case_id]["coverage_status"], "automated")
        self.assertEqual(UI_CASE_METADATA["PT5-MH-04"]["automation_mode"], "api_ui")
        self.assertEqual(UI_CASE_METADATA["PT5-MH-05"]["automation_mode"], "api_ui")

    def test_run_ai_model_hub_ui_validation_can_be_disabled_explicitly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"AI_MODEL_HUB_ENABLE_UI_VALIDATION": ""}, clear=False):
                result = run_ai_model_hub_ui_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["suite"], "ui")
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "ui_validation_disabled")
            self.assertEqual(result["summary"]["total"], 0)
            self.assertEqual(len(result["executed_cases"]), 0)
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))

    def test_run_ai_model_hub_ui_validation_persists_playwright_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _build_playwright_results_payload()

            def fake_subprocess_run(command, cwd=None, env=None):
                self.assertEqual(env["AI_MODEL_HUB_ENABLE_UI_VALIDATION"], "1")
                self.assertEqual(env["AI_MODEL_HUB_ENABLE_BENCHMARKING_UI_DEMO"], "1")
                self.assertEqual(env["PIONERA_PLAYWRIGHT_SUITE_NAME"], "AI Model Hub functional")
                self.assertIn("PLAYWRIGHT_JSON_REPORT_FILE", env)
                with open(env["PLAYWRIGHT_JSON_REPORT_FILE"], "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.dict(os.environ, {"AI_MODEL_HUB_ENABLE_UI_VALIDATION": "1"}, clear=False),
                mock.patch(
                    "validation.components.ai_model_hub.ui_runner.subprocess.run",
                    side_effect=fake_subprocess_run,
                ),
            ):
                result = run_ai_model_hub_ui_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["suite"], "ui")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 12)
            self.assertEqual(result["summary"]["passed"], 12)
            self.assertEqual(result["pt5_summary"]["total"], 12)
            self.assertEqual(result["support_summary"]["total"], 0)
            self.assertEqual(len(result["executed_cases"]), 12)
            self.assertGreaterEqual(len(result["evidence_index"]), 12)
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["json_report_file"]))

    def test_run_ai_model_hub_ui_validation_resolves_relative_experiment_dir_against_project_root(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmpdir:
            payload = _build_playwright_results_payload()
            relative_experiment_dir = os.path.relpath(tmpdir, start=os.getcwd())

            def fake_subprocess_run(command, cwd=None, env=None):
                self.assertTrue(os.path.isabs(env["PLAYWRIGHT_JSON_REPORT_FILE"]))
                with open(env["PLAYWRIGHT_JSON_REPORT_FILE"], "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.dict(os.environ, {"AI_MODEL_HUB_ENABLE_UI_VALIDATION": "1"}, clear=False),
                mock.patch(
                    "validation.components.ai_model_hub.ui_runner.subprocess.run",
                    side_effect=fake_subprocess_run,
                ),
            ):
                result = run_ai_model_hub_ui_validation(
                    "http://ai-model-hub.example.local",
                    experiment_dir=relative_experiment_dir,
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 12)
            self.assertEqual(result["summary"]["passed"], 12)
            self.assertEqual(result["summary"]["failed"], 0)
            self.assertTrue(os.path.isabs(result["artifacts"]["json_report_file"]))
