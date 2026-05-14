import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from validation.components.ai_model_hub.functional_runner import run_ai_model_hub_functional_validation


def _playwright_payload():
    return {
        "stats": {
            "expected": 1,
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "ai-model-hub-functional",
                "specs": [
                    {
                        "title": (
                            "MH-LING-01: FLARES-mini is published, discovered and negotiated on demand "
                            "for the linguistic validation flow"
                        ),
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
                ],
            }
        ],
    }


class AIModelHubFunctionalValidationTests(unittest.TestCase):
    def test_functional_runner_enables_opt_in_playwright_suite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _playwright_payload()

            def fake_subprocess_run(command, cwd=None, env=None):
                self.assertEqual(env["AI_MODEL_HUB_ENABLE_FUNCTIONAL_VALIDATION"], "1")
                self.assertEqual(env["AI_MODEL_HUB_BASE_URL"], "http://ai.example.local")
                self.assertEqual(env["PIONERA_PLAYWRIGHT_SUITE_NAME"], "AI Model Hub functional")
                self.assertIn("../components/ai_model_hub/functional/playwright.config.js", command)
                with open(env["PLAYWRIGHT_JSON_REPORT_FILE"], "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch(
                    "validation.components.ai_model_hub.functional_runner.subprocess.run",
                    side_effect=fake_subprocess_run,
                ),
            ):
                result = run_ai_model_hub_functional_validation(
                    "http://ai.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ai-model-hub")
            self.assertEqual(result["suite"], "linguistic-functional")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 1)
            self.assertEqual(result["functional_use_case_results"][0]["test_case_id"], "MH-LING-01")
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["json_report_file"]))

    def test_functional_runner_can_be_disabled_explicitly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"AI_MODEL_HUB_ENABLE_FUNCTIONAL_VALIDATION": ""}, clear=False):
                result = run_ai_model_hub_functional_validation(
                    "http://ai.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "functional_validation_disabled")
            self.assertEqual(result["summary"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
