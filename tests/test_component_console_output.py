import contextlib
import io
import os
import unittest
from unittest import mock

from validation.components.console_output import (
    print_component_case_result,
    print_component_suite_header,
    print_component_validation_summary,
    print_interoperability_suite_header,
)


class ComponentConsoleOutputTests(unittest.TestCase):
    def test_component_case_output_is_indented(self):
        case = {
            "test_case_id": "SV-API-01",
            "description": "semantic virtualization API health endpoint responds successfully",
            "evaluation": {"status": "passed"},
        }

        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False), contextlib.redirect_stdout(buffer):
            print_component_case_result(case)

        self.assertEqual(
            buffer.getvalue(),
            "  ✓ SV-API-01: semantic virtualization API health endpoint responds successfully\n",
        )

    def test_component_validation_summary_groups_by_phase_and_channel(self):
        component_results = [
            {
                "component": "ontology-hub",
                "status": "passed",
                "phase_order": ["functional", "integration"],
                "phase_execution_channels": {
                    "functional": ["playwright"],
                    "integration": ["api"],
                },
                "phases": {
                    "functional": {
                        "display_name": "Ontology Hub functional",
                        "status": "passed",
                        "summary": {"total": 25, "passed": 25, "failed": 0, "skipped": 0},
                    },
                    "integration": {
                        "display_name": "Ontology Hub API integration",
                        "status": "passed",
                        "summary": {"total": 7, "passed": 7, "failed": 0, "skipped": 0},
                    },
                },
            },
            {
                "component": "ai-model-hub",
                "status": "passed",
                "phase_order": ["preflight", "functional", "integration"],
                "phase_execution_channels": {
                    "preflight": ["api"],
                    "functional": ["api", "playwright"],
                    "integration": ["api"],
                },
                "phases": {
                    "preflight": {
                        "status": "passed",
                        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                    },
                    "functional": {
                        "status": "passed",
                        "summary": {"total": 16, "passed": 16, "failed": 0, "skipped": 0},
                    },
                    "integration": {
                        "status": "passed",
                        "summary": {"total": 10, "passed": 10, "failed": 0, "skipped": 0},
                    },
                },
            },
        ]

        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False), contextlib.redirect_stdout(buffer):
            print_component_validation_summary(component_results)

        printed = buffer.getvalue()
        self.assertIn("Component validation layer summary", printed)
        self.assertIn("Ontology Hub", printed)
        self.assertIn("Functional", printed)
        self.assertIn("Integration", printed)
        self.assertNotIn("Phase", printed)
        self.assertNotIn("Ontology Hub functional", printed)
        self.assertNotIn("Ontology Hub API integration", printed)
        self.assertIn("UI", printed)
        self.assertIn("API, UI", printed)
        self.assertNotIn("Playwright", printed)
        self.assertIn("✓ passed", printed)
        self.assertNotIn("✓ passed Component groups:", printed)
        self.assertIn("Component groups: 2/2 passed, 0 failed, 0 partial/skipped", printed)
        self.assertIn("Component test cases: 59/59 passed, 0 failed, 0 skipped", printed)
        self.assertIn("Scope: component validation layer only", printed)

    def test_component_suite_header_uses_single_trailing_line_break(self):
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False), contextlib.redirect_stdout(buffer):
            print_component_suite_header("Virtualizador functional", "playwright")

        self.assertEqual(
            buffer.getvalue(),
            "\nComponent Playwright suite: Virtualizador functional\n",
        )

    def test_component_validation_summary_counts_are_colored_without_status_icon(self):
        component_results = [
            {
                "component": "ontology-hub",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
            }
        ]

        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True), contextlib.redirect_stdout(buffer):
            print_component_validation_summary(component_results)

        printed = buffer.getvalue()
        self.assertNotIn("✓ passed Component groups:", printed)
        self.assertIn("\033[32mComponent groups:\033[0m", printed)
        self.assertIn("\033[32mComponent test cases:\033[0m", printed)
        self.assertIn("\033[32m1/1 passed\033[0m", printed)
        self.assertIn("\033[32m0 failed\033[0m", printed)
        self.assertIn("\033[33m0 partial/skipped\033[0m", printed)

    def test_component_validation_summary_title_is_yellow_when_color_is_forced(self):
        component_results = [
            {
                "component": "ontology-hub",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
            }
        ]

        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True), contextlib.redirect_stdout(buffer):
            print_component_validation_summary(component_results)

        self.assertIn("\033[33;1mComponent validation layer summary\033[0m", buffer.getvalue())

    def test_component_validation_summary_surfaces_skipped_cases_without_hiding_layer_scope(self):
        component_results = [
            {
                "component": "ai-model-hub",
                "status": "passed",
                "phases": {
                    "functional": {
                        "status": "passed",
                        "summary": {"total": 2, "passed": 1, "failed": 0, "skipped": 1},
                    }
                },
                "phase_order": ["functional"],
            }
        ]

        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False), contextlib.redirect_stdout(buffer):
            print_component_validation_summary(component_results)

        printed = buffer.getvalue()
        self.assertIn("- partial", printed)
        self.assertIn("Component groups: 0/1 passed, 0 failed, 1 partial/skipped", printed)
        self.assertIn("Component test cases: 1/2 passed, 0 failed, 1 skipped", printed)
        self.assertIn("Scope: component validation layer only", printed)

    def test_interoperability_suite_headers_are_yellow_when_color_is_forced(self):
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, {"FORCE_COLOR": "1"}, clear=True), contextlib.redirect_stdout(buffer):
            print_interoperability_suite_header("Kafka transfer interoperability", "Kafka")

        printed = buffer.getvalue()
        self.assertIn("\033[33;1mInteroperability Kafka suite: Kafka transfer interoperability\033[0m", printed)
        self.assertNotIn("End interoperability suite", printed)


if __name__ == "__main__":
    unittest.main()
