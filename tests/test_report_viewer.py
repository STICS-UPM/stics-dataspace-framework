import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from validation.orchestration import reports


class FakeProcess:
    pid = 12345

    def poll(self):
        return None

    def terminate(self):
        return None


class FakeSubprocess:
    def __init__(self):
        self.calls = []

    def Popen(self, command, **kwargs):
        self.calls.append({"command": command, "kwargs": kwargs})
        return FakeProcess()


class ReportViewerTests(unittest.TestCase):
    def _write_json(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _create_experiment(self, root):
        experiment = Path(root) / "experiments" / "experiment_2026-05-03_10-00-00"
        self._write_json(
            experiment / "metadata.json",
            {
                "timestamp": "2026-05-03T10:00:00",
                "adapter": "InesdataAdapter",
                "topology": "local",
                "cluster": "minikube",
            },
        )
        (experiment / "ui" / "inesdata" / "playwright-report").mkdir(parents=True)
        (experiment / "ui" / "inesdata" / "playwright-report" / "index.html").write_text(
            "<html>playwright</html>",
            encoding="utf-8",
        )
        self._write_json(
            experiment / "ui" / "inesdata" / "results.json",
            {
                "suites": [
                    {
                        "specs": [
                            {
                                "tests": [
                                    {"status": "expected"},
                                    {"status": "unexpected"},
                                ]
                            }
                        ]
                    }
                ]
            },
        )
        self._write_json(
            experiment / "test_results.json",
            [
                {"status": "pass", "test_name": "ok"},
                {"status": "fail", "test_name": "not ok"},
            ],
        )
        self._write_json(
            experiment / "newman_results.json",
            [{"checks": [{"ok": True}, {"ok": False}]}],
        )
        self._write_json(
            experiment / "kafka_transfer_results.json",
            [
                {
                    "status": "passed",
                    "metrics": {
                        "average_latency_ms": 10.5,
                        "throughput_messages_per_second": 42.0,
                    },
                }
            ],
        )
        (experiment / "level6_console.log").write_text(
            "\x1b[33;1mInteroperability Playwright suite: INESData integration\x1b[0m\n"
            "Suite: INESData integration\n"
            "\x1b[36m›\x1b[0m 01 login readiness\n"
            "\x1b[32m✓\x1b[0m 01 login readiness\n"
            "\x1b[31mProvider Management API Health failed\x1b[0m\n"
            "<console line must be escaped>\n",
            encoding="utf-8",
        )
        self._write_json(
            experiment / "local_stability_postflight.json",
            {
                "blocking_issues": [],
                "comparison": {
                    "status": "warning",
                    "warnings": [{"name": "pod_restart_delta"}],
                    "node_not_ready_delta": 0,
                },
            },
        )
        self._write_json(
            experiment / "components" / "ontology-hub" / "ontology_hub_component_validation.json",
            {
                "component": "ontology-hub",
                "status": "failed",
                "summary": {"total": 4, "passed": 3, "failed": 1, "skipped": 0},
                "phase_execution_channels": {
                    "functional": ["playwright"],
                    "integration": ["api"],
                },
                "runtime": {"adminPassword": "must-not-appear-in-dashboard"},
            },
        )
        return experiment

    def test_discovers_experiments_and_report_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._create_experiment(tmp)

            experiments = reports.discover_report_experiments(root=tmp)

        self.assertEqual(len(experiments), 1)
        experiment = experiments[0]
        self.assertEqual(experiment["name"], "experiment_2026-05-03_10-00-00")
        self.assertEqual(experiment["adapter"], "inesdata")
        self.assertEqual(experiment["topology"], "local")
        self.assertEqual(experiment["cluster_runtime"], "minikube")
        self.assertIn("Playwright", experiment["reports"])
        self.assertIn("Newman", experiment["reports"])
        self.assertIn("Kafka", experiment["reports"])
        self.assertIn("Components", experiment["reports"])
        self.assertIn("Stability", experiment["reports"])
        self.assertIn("Console", experiment["reports"])

    def test_discovers_marked_opt_in_demo_evidence_without_debug_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo = root / "experiments" / "ai-model-hub-inesdata-ui-demo-20260506-r8"
            self._write_json(
                demo / "metadata.json",
                {
                    "timestamp": "2026-05-06T15:49:45.352Z",
                    "adapter": "InesdataAdapter",
                    "topology": "vm-single",
                },
            )
            (demo / "components" / "ai-model-hub" / "inesdata-ui" / "playwright-report").mkdir(parents=True)
            (demo / "components" / "ai-model-hub" / "inesdata-ui" / "playwright-report" / "index.html").write_text(
                "<html>playwright</html>",
                encoding="utf-8",
            )
            self._write_json(
                demo / "components" / "ai-model-hub" / "inesdata-ui" / "results.json",
                {"suites": [{"specs": [{"tests": [{"status": "expected"}]}]}]},
            )
            debug_run = root / "experiments" / "ai-model-hub-inesdata-ui-demo-20260506-r7"
            self._write_json(
                debug_run / "components" / "ai-model-hub" / "inesdata-ui" / "results.json",
                {"suites": [{"specs": [{"tests": [{"status": "unexpected"}]}]}]},
            )

            experiments = reports.discover_report_experiments(root=tmp)

        names = [experiment["name"] for experiment in experiments]
        self.assertIn("ai-model-hub-inesdata-ui-demo-20260506-r8", names)
        self.assertNotIn("ai-model-hub-inesdata-ui-demo-20260506-r7", names)
        demo_experiment = next(
            experiment for experiment in experiments if experiment["name"] == "ai-model-hub-inesdata-ui-demo-20260506-r8"
        )
        self.assertIn("Playwright", demo_experiment["reports"])
        self.assertEqual(demo_experiment["adapter"], "inesdata")
        self.assertEqual(demo_experiment["topology"], "vm-single")
        self.assertEqual(demo_experiment["suites"][0]["title"], "components / ai-model-hub / inesdata-ui")
        self.assertEqual(demo_experiment["suites"][0]["status"], "passed")

    def test_dashboard_summarizes_without_leaking_runtime_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment_path = self._create_experiment(tmp)
            experiment = reports.inspect_experiment(experiment_path)

            dashboard = reports.build_experiment_dashboard(experiment)
            content = dashboard.read_text(encoding="utf-8")

        self.assertIn("Framework validation dashboard", content)
        self.assertIn("Dashboard status", content)
        self.assertIn("Cluster runtime", content)
        self.assertIn("Open ui / inesdata", content)
        self.assertIn("Audit suite", content)
        self.assertIn("INESData integration", content)
        self.assertIn("Combined Playwright", content)
        self.assertIn("Newman", content)
        self.assertIn("Kafka transfer", content)
        self.assertIn("Level 6 console log", content)
        self.assertIn(
            "<span class='ansi-bold ansi-fg-yellow'>Interoperability Playwright suite: INESData integration</span>",
            content,
        )
        self.assertIn("<span class='ansi-bold ansi-fg-cyan'>Suite: INESData integration</span>", content)
        self.assertIn("✓</span> 01 login readiness", content)
        self.assertNotIn("›</span> 01 login readiness", content)
        self.assertIn("hidden 1 transient Playwright start line", content)
        self.assertIn("Provider Management API Health failed", content)
        self.assertIn("<span class='ansi-fg-red'>Provider Management API Health failed</span>", content)
        self.assertIn("Channels: functional: Playwright; integration: API.", content)
        self.assertIn("&lt;console line must be escaped&gt;", content)
        self.assertIn("level6_console.log", content)
        self.assertNotIn("\x1b", content)
        self.assertNotIn("must-not-appear-in-dashboard", content)

    def test_dashboard_marks_kafka_transfer_incomplete_when_messages_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_10-10-00"
            self._write_json(experiment / "metadata.json", {"adapter": "InesdataAdapter", "topology": "vm-distributed"})
            self._write_json(
                experiment / "kafka_transfer_results.json",
                [
                    {
                        "status": "passed",
                        "metrics": {
                            "messages_produced": 10,
                            "messages_consumed": 8,
                            "messages_missing": 2,
                            "average_latency_ms": 12.0,
                            "throughput_messages_per_second": 3.5,
                        },
                    },
                    {
                        "status": "skipped",
                        "reason": "not_applicable",
                    }
                ],
            )

            inspected = reports.inspect_experiment(experiment)
            dashboard = reports.build_experiment_dashboard(inspected)
            content = dashboard.read_text(encoding="utf-8")

        kafka = next(suite for suite in inspected["suites"] if suite["kind"] == "kafka")
        self.assertEqual(kafka["status"], "failed")
        self.assertEqual(kafka["summary"]["total"], 2)
        self.assertEqual(kafka["summary"]["passed"], 0)
        self.assertEqual(kafka["summary"]["failed"], 1)
        self.assertEqual(kafka["summary"]["skipped"], 1)
        self.assertEqual(kafka["messages_produced"], 10)
        self.assertEqual(kafka["messages_consumed"], 8)
        self.assertEqual(kafka["messages_missing"], 2)
        self.assertEqual(kafka["incomplete_transfers"], 1)
        self.assertIn("Transfers: total 2, 0 passed, 1 failed, 1 skipped", content)
        self.assertIn("Messages: produced 10, consumed 8, missing 2", content)
        self.assertIn("Incomplete transfers: 1", content)
        self.assertEqual(inspected["result"], "Issues detected")

    def test_dashboard_renders_standalone_newman_console_log_with_ansi_colors(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_10-15-00"
            self._write_json(
                experiment / "metadata.json",
                {
                    "timestamp": "2026-05-03T10:15:00",
                    "adapter": "InesdataAdapter",
                    "topology": "local",
                },
            )
            (experiment / "newman_console.log").write_text(
                "Newman interoperability console log: /tmp/newman_console.log\n"
                "Interoperability Newman suite: Newman connector interoperability\n"
                "\x1b[32m✓\x1b[0m Provider Management API Health\n"
                "\x1b[31m✗\x1b[0m Consumer Management API Health\n"
                "Done.\n",
                encoding="utf-8",
            )

            inspected = reports.inspect_experiment(experiment)
            dashboard = reports.build_experiment_dashboard(inspected)
            content = dashboard.read_text(encoding="utf-8")

        self.assertIn("Console", inspected["reports"])
        self.assertEqual(inspected["console_logs"][0]["path"], "newman_console.log")
        self.assertIn("Newman interoperability console log", content)
        self.assertIn("Open raw newman_console.log", content)
        self.assertIn(
            "<span class='ansi-bold ansi-fg-yellow'>Interoperability Newman suite: Newman connector interoperability</span>",
            content,
        )
        self.assertNotIn("End interoperability suite", content)
        self.assertIn("<span class='ansi-fg-green'>✓</span> Provider Management API Health", content)
        self.assertIn("<span class='ansi-fg-red'>✗</span> Consumer Management API Health", content)
        self.assertIn("newman_console.log", [artifact["path"] for artifact in inspected["artifacts"]])
        self.assertNotIn("\x1b", content)

    def test_console_log_renderer_converts_ansi_to_safe_html(self):
        rendered = reports._ansi_to_html("\x1b[36;1mSuite: INESData\x1b[0m <unsafe>\n")

        self.assertIn("<span class='ansi-bold ansi-fg-cyan'>Suite: INESData</span>", rendered)
        self.assertIn("&lt;unsafe&gt;", rendered)
        self.assertNotIn("\x1b", rendered)

    def test_console_log_renderer_preserves_extended_ansi_colors(self):
        rendered = reports._ansi_to_html("\x1b[38;5;196mfailed\x1b[0m \x1b[38;2;1;2;3mcustom\x1b[0m")

        self.assertIn("style='color: #ff0000'", rendered)
        self.assertIn("style='color: #010203'", rendered)
        self.assertNotIn("\x1b", rendered)

    def test_dashboard_console_keeps_unfinished_playwright_start_line(self):
        rendered, hidden = reports._dashboard_console_content("\x1b[36m›\x1b[0m unfinished test\n")

        self.assertEqual(hidden, 0)
        self.assertIn("unfinished test", rendered)

    def test_dashboard_console_hides_completed_playwright_start_line(self):
        rendered, hidden = reports._dashboard_console_content(
            "\x1b[36m›\x1b[0m completed test\n\x1b[32m✓\x1b[0m completed test\n"
        )

        self.assertEqual(hidden, 1)
        self.assertNotIn("›\x1b[0m completed test", rendered)
        self.assertIn("✓\x1b[0m completed test", rendered)

    def test_dashboard_console_hides_carriage_return_playwright_start_line(self):
        rendered, hidden = reports._dashboard_console_content(
            "› completed test\r\x1b[2K✓ completed test\n"
        )

        self.assertEqual(hidden, 1)
        self.assertNotIn("› completed test", rendered)
        self.assertIn("\x1b[32m✓\x1b[0m completed test", rendered)

    def test_dashboard_console_sanitizes_project_root_paths(self):
        absolute_path = reports.project_root() / "experiments" / "experiment_1" / "level6_console.log"
        rendered, hidden = reports._dashboard_console_content(f"Level 6 console log: {absolute_path}\n")

        self.assertEqual(hidden, 0)
        self.assertIn("Level 6 console log: experiments/experiment_1/level6_console.log", rendered)
        self.assertNotIn(reports.project_root().as_posix(), rendered)

    def test_dashboard_console_colorizes_plain_suite_headers_and_result_prefixes(self):
        rendered, hidden = reports._dashboard_console_content(
            "Component API suite: Virtualizador integration\n"
            "✓ SV-API-01: semantic virtualization API health endpoint responds successfully\n"
            "Component Playwright suite: Virtualizador functional\n"
            "Suite: Virtualizador functional (1 test)\n"
            "✓ SV-UI-01: semantic virtualization root is reachable from a browser\n"
            "✗ SV-UI-02: failing test\n"
            "  ✓ Kafka transfer: provider -> consumer\n"
            "Component validation layer summary\n"
            "Component groups: 3/3 passed, 0 failed, 0 partial/skipped\n"
            "Component test cases: 12/13 passed, 0 failed, 1 skipped\n"
        )

        html_content = reports._ansi_to_html(rendered)

        self.assertEqual(hidden, 0)
        self.assertIn(
            "<span class='ansi-bold ansi-fg-yellow'>Component API suite: Virtualizador integration</span>",
            html_content,
        )
        self.assertIn(
            "<span class='ansi-bold ansi-fg-yellow'>Component Playwright suite: Virtualizador functional</span>",
            html_content,
        )
        self.assertIn(
            "<span class='ansi-bold ansi-fg-yellow'>Component validation layer summary</span>",
            html_content,
        )
        self.assertIn("<span class='ansi-fg-green'>✓</span> SV-API-01", html_content)
        self.assertIn("<span class='ansi-bold ansi-fg-cyan'>Suite: Virtualizador functional (1 test)</span>", html_content)
        self.assertIn("<span class='ansi-fg-green'>✓</span> SV-UI-01", html_content)
        self.assertIn("<span class='ansi-fg-red'>✗</span> SV-UI-02", html_content)
        self.assertIn("  <span class='ansi-fg-green'>✓</span> Kafka transfer: provider -&gt; consumer", html_content)
        self.assertIn(
            "<span class='ansi-fg-green'>Component groups: 3/3 passed, 0 failed, 0 partial/skipped</span>",
            html_content,
        )
        self.assertIn(
            "<span class='ansi-fg-yellow'>Component test cases: 12/13 passed, 0 failed, 1 skipped</span>",
            html_content,
        )

    def test_dashboard_console_hides_empty_component_suite_wrappers(self):
        rendered, hidden = reports._dashboard_console_content(
            "Component API suite: AI Model Hub integration\n\n"
            "Component Playwright suite: Virtualizador functional\n"
            "Suite: Virtualizador functional (1 test)\n"
            "✓ SV-UI-01: semantic virtualization root is reachable from a browser\n"
        )

        self.assertEqual(hidden, 0)
        self.assertNotIn("Component API suite: AI Model Hub integration", rendered)
        self.assertIn("Component Playwright suite: Virtualizador functional", rendered)
        self.assertIn("Suite: Virtualizador functional (1 test)", rendered)

    def test_inesdata_playwright_results_are_grouped_for_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_10-45-00"
            self._write_json(experiment / "metadata.json", {"adapter": "InesdataAdapter"})
            self._write_json(
                experiment / "ui" / "inesdata" / "results.json",
                {
                    "suites": [
                        {
                            "specs": [
                                {
                                    "file": "validation/ui/adapters/inesdata/specs/01-login-readiness.spec.ts",
                                    "tests": [{"status": "expected"}],
                                },
                                {
                                    "file": "validation/ui/adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts",
                                    "tests": [{"status": "expected"}],
                                },
                                {
                                    "file": "validation/ui/adapters/inesdata/specs/09-ai-model-hub-httpdata.spec.ts",
                                    "tests": [{"status": "unexpected"}],
                                },
                                {
                                    "file": "validation/ui/adapters/inesdata/specs/07-semantic-virtualization-httpdata.spec.ts",
                                    "tests": [{"status": "skipped"}],
                                },
                            ]
                        }
                    ]
                },
            )

            inspected = reports.inspect_experiment(experiment)
            dashboard = reports.build_experiment_dashboard(inspected)
            content = dashboard.read_text(encoding="utf-8")

        suite = next(item for item in inspected["suites"] if item["kind"] == "playwright-json")
        self.assertEqual(suite["audit_suite"], "INESData integration")
        self.assertEqual(suite["audit_group"], "4 groups")
        groups = {
            group["audit_group"]: group
            for group in suite["summary"]["groups"]
        }
        self.assertEqual(groups["Core"]["passed"], 1)
        self.assertEqual(groups["Ontology Hub"]["passed"], 1)
        self.assertEqual(groups["AI Model Hub"]["failed"], 1)
        self.assertEqual(groups["Semantic Virtualization"]["skipped"], 1)
        self.assertIn("<td>INESData integration</td><td>AI Model Hub</td><td>ui / inesdata / AI Model Hub</td>", content)
        self.assertIn("Official UI evidence in ui / inesdata Playwright report.", content)

    def test_edc_playwright_results_are_grouped_for_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_10-50-00"
            self._write_json(experiment / "metadata.json", {"adapter": "EDCAdapter"})
            self._write_json(
                experiment / "ui" / "edc" / "results.json",
                {
                    "suites": [
                        {
                            "specs": [
                                {
                                    "file": "validation/ui/adapters/edc/specs/01-login-readiness.spec.ts",
                                    "tests": [{"status": "expected"}],
                                },
                                {
                                    "file": "validation/ui/adapters/edc/specs/08-ontology-hub-edc-readonly.spec.ts",
                                    "tests": [{"status": "expected"}],
                                },
                                {
                                    "file": "validation/ui/adapters/edc/specs/09-ai-model-hub-httpdata.spec.ts",
                                    "tests": [{"status": "unexpected"}],
                                },
                                {
                                    "file": "validation/ui/adapters/edc/specs/07-semantic-virtualization-httpdata.spec.ts",
                                    "tests": [{"status": "skipped"}],
                                },
                            ]
                        }
                    ]
                },
            )

            inspected = reports.inspect_experiment(experiment)

        suite = next(item for item in inspected["suites"] if item["kind"] == "playwright-json")
        self.assertEqual(suite["audit_suite"], "EDC integration")
        self.assertEqual(suite["audit_group"], "4 groups")
        groups = {
            group["audit_group"]: group
            for group in suite["summary"]["groups"]
        }
        self.assertEqual(groups["Core"]["passed"], 1)
        self.assertEqual(groups["Ontology Hub"]["passed"], 1)
        self.assertEqual(groups["AI Model Hub"]["failed"], 1)
        self.assertEqual(groups["Semantic Virtualization"]["skipped"], 1)

    def test_dashboard_includes_optional_une_0087_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_10-30-00"
            self._write_json(experiment / "metadata.json", {"adapter": "InesdataAdapter"})
            self._write_json(
                experiment / "une_0087_alignment.json",
                {
                    "assessment_type": "non_certifying_alignment",
                    "certification_claim": False,
                    "summary": {
                        "total_criteria": 23,
                        "statuses": {
                            "covered": 14,
                            "partially_covered": 7,
                            "not_covered": 2,
                            "not_applicable": 0,
                        },
                    },
                },
            )
            (experiment / "une_0087_alignment.md").write_text("# UNE 0087 Alignment\n", encoding="utf-8")

            inspected = reports.inspect_experiment(experiment)
            dashboard = reports.build_experiment_dashboard(inspected)
            content = dashboard.read_text(encoding="utf-8")

        self.assertIn("UNE 0087", inspected["reports"])
        self.assertIn("UNE 0087 alignment", content)
        self.assertIn("Formal certification claim: no", content)
        self.assertIn("une_0087_alignment.json", content)

    def test_legacy_metadata_does_not_use_minikube_as_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_11-00-00"
            self._write_json(
                experiment / "metadata.json",
                {
                    "timestamp": "2026-05-03T11:00:00",
                    "adapter": "EdcAdapter",
                    "cluster": "minikube",
                    "environment": "minikube",
                },
            )

            inspected = reports.inspect_experiment(experiment)

        self.assertEqual(inspected["topology"], "not recorded")
        self.assertEqual(inspected["cluster_runtime"], "minikube")
        self.assertEqual(inspected["adapter"], "edc")

    def test_stability_existing_warnings_are_not_reported_as_new_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_12-00-00"
            self._write_json(
                experiment / "local_stability_postflight.json",
                {
                    "blocking_issues": [],
                    "comparison": {
                        "status": "warning",
                        "warnings": [],
                        "node_not_ready_delta": 0,
                    },
                    "snapshot": {
                        "warnings": [{"name": "pod_restarts"}],
                    },
                },
            )

            inspected = reports.inspect_experiment(experiment)

        stability = next(suite for suite in inspected["suites"] if suite["kind"] == "stability")
        self.assertEqual(stability["status"], "warning-existing")
        self.assertEqual(stability["warnings"], 0)
        self.assertEqual(stability["snapshot_warnings"], 1)
        self.assertEqual(inspected["result"], "Warnings detected")

    def test_component_playwright_json_is_not_duplicated_when_component_summary_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_13-00-00"
            self._write_json(
                experiment / "components" / "ontology-hub" / "ontology_hub_component_validation.json",
                {
                    "component": "ontology-hub",
                    "status": "failed",
                    "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
                },
            )
            self._write_json(
                experiment / "components" / "ontology-hub" / "functional" / "results.json",
                {
                    "suites": [
                        {
                            "specs": [
                                {"tests": [{"status": "unexpected"}]},
                            ]
                        }
                    ]
                },
            )

            inspected = reports.inspect_experiment(experiment)

        titles = [suite["title"] for suite in inspected["suites"]]
        self.assertEqual(titles.count("ontology-hub"), 1)
        self.assertNotIn("components / ontology-hub / functional", titles)

    def test_component_report_json_is_summarized_when_no_component_summary_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "ai-model-hub-mobility-benchmarking-api-20260506"
            self._write_json(
                experiment / "metadata.json",
                {
                    "timestamp": "2026-05-06T12:31:01",
                    "adapter_name": "inesdata",
                    "topology": "vm-single",
                },
            )
            self._write_json(
                experiment / "components" / "ai-model-hub" / "functional" / "ai_model_hub_mobility_benchmarking_api.json",
                {
                    "component": "ai-model-hub",
                    "suite": "mobility-benchmarking-api",
                    "status": "passed",
                    "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                },
            )

            experiments = reports.discover_report_experiments(root=tmp)
            inspected = experiments[0]
            dashboard = reports.build_experiment_dashboard(inspected)
            content = dashboard.read_text(encoding="utf-8")

        self.assertEqual(inspected["name"], "ai-model-hub-mobility-benchmarking-api-20260506")
        self.assertIn("Components", inspected["reports"])
        self.assertEqual(inspected["suites"][0]["kind"], "component-report")
        self.assertEqual(inspected["suites"][0]["title"], "ai-model-hub / mobility-benchmarking-api")
        self.assertIn("ai_model_hub_mobility_benchmarking_api.json", content)

    def test_component_summary_prefers_display_name_for_dashboard_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_13-30-00"
            self._write_json(
                experiment / "components" / "ontology-hub" / "ontology_hub_integration_component_validation.json",
                {
                    "component": "ontology-hub",
                    "display_name": "Ontology Hub API integration",
                    "status": "passed",
                    "summary": {"total": 5, "passed": 5, "failed": 0, "skipped": 0},
                },
            )

            inspected = reports.inspect_experiment(experiment)

        self.assertEqual(inspected["suites"][0]["title"], "Ontology Hub API integration")
        self.assertEqual(inspected["suites"][0]["audit_suite"], "Ontology Hub")
        self.assertEqual(inspected["suites"][0]["audit_group"], "API integration")

    def test_dashboard_marks_suites_with_skipped_tests_as_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_14-00-00"
            self._write_json(experiment / "metadata.json", {"adapter": "InesdataAdapter"})
            self._write_json(
                experiment / "ui" / "inesdata" / "results.json",
                {
                    "suites": [
                        {
                            "specs": [
                                {
                                    "file": "validation/ui/adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts",
                                    "tests": [
                                        {"status": "expected"},
                                        {"status": "skipped"},
                                    ],
                                },
                            ]
                        }
                    ]
                },
            )

            inspected = reports.inspect_experiment(experiment)
            dashboard = reports.build_experiment_dashboard(inspected)
            content = dashboard.read_text(encoding="utf-8")

        suite = next(item for item in inspected["suites"] if item["kind"] == "playwright-json")
        self.assertEqual(suite["status"], "partial")
        self.assertEqual(inspected["result"], "Partial")
        self.assertIn('<span class="badge warn">partial</span>', content)

    def test_component_summary_with_skipped_tests_is_not_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_14-30-00"
            self._write_json(
                experiment / "components" / "ai-model-hub" / "ai_model_hub_component_validation.json",
                {
                    "component": "ai-model-hub",
                    "status": "passed",
                    "summary": {"total": 3, "passed": 2, "failed": 0, "skipped": 1},
                },
            )

            inspected = reports.inspect_experiment(experiment)

        suite = next(item for item in inspected["suites"] if item["kind"] == "component")
        self.assertEqual(suite["status"], "partial")
        self.assertEqual(inspected["result"], "Partial")

    def test_component_summary_with_only_skipped_tests_stays_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = Path(tmp) / "experiments" / "experiment_2026-05-03_15-00-00"
            self._write_json(
                experiment / "components" / "ai-model-hub" / "ai_model_hub_component_validation.json",
                {
                    "component": "ai-model-hub",
                    "status": "skipped",
                    "summary": {"total": 3, "passed": 0, "failed": 0, "skipped": 3},
                },
            )

            inspected = reports.inspect_experiment(experiment)

        suite = next(item for item in inspected["suites"] if item["kind"] == "component")
        self.assertEqual(suite["status"], "skipped")
        self.assertEqual(inspected["result"], "Partial")

    def test_static_report_server_binds_only_to_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_subprocess = FakeSubprocess()
            result = reports.launch_static_report_server(
                tmp,
                port=9341,
                subprocess_module=fake_subprocess,
                python_executable="python3",
                wait_for_server=lambda host, port: True,
            )

        self.assertEqual(result["url"], "http://127.0.0.1:9341")
        self.assertTrue(result["ready"])
        command = fake_subprocess.calls[0]["command"]
        self.assertIn("--bind", command)
        self.assertIn("127.0.0.1", command)
        with self.assertRaises(ValueError):
            reports.launch_static_report_server(tmp, host="0.0.0.0", subprocess_module=fake_subprocess)

    def test_playwright_report_launcher_uses_official_show_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "experiments" / "experiment_1" / "ui" / "inesdata" / "playwright-report"
            report_dir.mkdir(parents=True)
            (report_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            (root / "validation" / "ui").mkdir(parents=True)
            fake_subprocess = FakeSubprocess()

            result = reports.launch_playwright_report(
                report_dir,
                root=root,
                port=9444,
                subprocess_module=fake_subprocess,
                wait_for_server=lambda host, port: True,
            )

        self.assertEqual(result["url"], "http://127.0.0.1:9444")
        self.assertTrue(result["ready"])
        command = fake_subprocess.calls[0]["command"]
        self.assertEqual(command[:3], ["npx", "playwright", "show-report"])
        self.assertIn("--host", command)
        self.assertIn("127.0.0.1", command)
        self.assertIn("--port", command)
        self.assertIn("9444", command)

    def test_local_url_open_uses_windows_cmd_fallback_when_wslview_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_cmd = root / "cmd.exe"
            fake_cmd.write_text("", encoding="utf-8")
            fake_subprocess = FakeSubprocess()

            with mock.patch("validation.orchestration.reports.shutil.which", return_value=None), mock.patch.object(
                reports, "WINDOWS_CMD_EXE", fake_cmd
            ), mock.patch.object(
                reports, "WINDOWS_POWERSHELL_EXE", root / "missing-powershell.exe"
            ), mock.patch.object(
                reports, "WINDOWS_EXPLORER_EXE", root / "missing-explorer.exe"
            ):
                result = reports.open_local_url(
                    "http://127.0.0.1:9000/framework-report/index.html",
                    subprocess_module=fake_subprocess,
                )

        self.assertTrue(result["opened"])
        self.assertEqual(result["method"], "windows-cmd-start")
        command = fake_subprocess.calls[0]["command"]
        self.assertEqual(command[:4], [str(fake_cmd), "/c", "start", ""])
        self.assertEqual(command[-1], "http://127.0.0.1:9000/framework-report/index.html")

    def test_wsl_file_url_for_path_uses_configured_distro_name(self):
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False):
            url = reports.wsl_file_url_for_path("/home/example/project with spaces/framework-report/index.html")

        self.assertEqual(
            url,
            "file://wsl.localhost/Ubuntu/home/example/project%20with%20spaces/framework-report/index.html",
        )

    def test_report_access_urls_include_wsl_and_vm_file_urls(self):
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False):
            urls = reports.report_access_urls(
                "/home/example/project with spaces/framework-report/index.html",
                server_url="http://127.0.0.1:9341",
            )

        self.assertEqual(
            urls,
            [
                {
                    "label": "Local server URL",
                    "url": "http://127.0.0.1:9341/framework-report/index.html",
                },
                {
                    "label": "WSL/Windows file URL",
                    "url": "file://wsl.localhost/Ubuntu/home/example/project%20with%20spaces/framework-report/index.html",
                },
                {
                    "label": "Linux/VM file URL",
                    "url": "file:///home/example/project%20with%20spaces/framework-report/index.html",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
