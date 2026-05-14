import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from validation.components.semantic_virtualization.ui_runner import run_semantic_virtualization_ui_validation


def _playwright_payload():
    titles = [
        "SV-UI-01: semantic virtualization root is reachable from a browser",
        "SV-UI-03: semantic virtualization query endpoint is reachable from Playwright",
        "PT5-VS-07: mapping editor graphical UI is reachable",
    ]
    return {
        "stats": {
            "expected": len(titles),
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "semantic-virtualization-ui",
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
                                                "name": "screenshot",
                                                "contentType": "image/png",
                                                "path": "step.png",
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                    for title in titles
                ],
            }
        ],
    }


class SemanticVirtualizationUIValidationTests(unittest.TestCase):
    def test_ui_runner_enables_mapping_editor_opt_in_suite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _playwright_payload()

            def fake_subprocess_run(command, cwd=None, env=None):
                self.assertEqual(env["SEMANTIC_VIRTUALIZATION_BASE_URL"], "http://sv.example.local")
                self.assertEqual(env["SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI"], "1")
                self.assertEqual(env["PIONERA_PLAYWRIGHT_SUITE_NAME"], "Virtualizador functional")
                self.assertIn("../components/semantic_virtualization/ui/playwright.config.js", command)
                with open(env["PLAYWRIGHT_JSON_REPORT_FILE"], "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                return subprocess.CompletedProcess(command, 0)

            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch(
                    "validation.components.semantic_virtualization.ui_runner.subprocess.run",
                    side_effect=fake_subprocess_run,
                ),
            ):
                result = run_semantic_virtualization_ui_validation(
                    "http://sv.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "semantic-virtualization")
            self.assertEqual(result["suite"], "ui")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 3)
            self.assertEqual(result["pt5_summary"]["total"], 2)
            self.assertEqual(result["support_summary"]["total"], 1)
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["json_report_file"]))

    def test_ui_runner_can_be_disabled_explicitly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"SEMANTIC_VIRTUALIZATION_ENABLE_UI_VALIDATION": ""}, clear=False):
                result = run_semantic_virtualization_ui_validation(
                    "http://sv.example.local",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "ui_validation_disabled")
            self.assertEqual(result["summary"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
