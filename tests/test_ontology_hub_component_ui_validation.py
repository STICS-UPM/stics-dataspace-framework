import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from validation.components.ontology_hub.integration.component_runner import run_ontology_hub_component_validation
from validation.components.ontology_hub.runtime_config import resolve_ontology_hub_runtime
from validation.components.ontology_hub.integration.ui_runner import (
    UI_CASE_METADATA,
    _run_ui_preflight,
    run_ontology_hub_ui_validation,
)


def _build_playwright_results_payload():
    spec_titles = [
        "PT5-OH-09: term search filters by tag and vocabulary in the public UI",
        "PT5-OH-10: version history and version resources are exposed from the vocabulary detail page",
        "PT5-OH-11: vocabulary detail displays metadata and descriptive sections",
        "PT5-OH-12: vocabulary detail exposes statistics and LOD usage markers",
        "PT5-OH-15: public UI and API documentation are published together",
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
                "title": "ontology-hub-ui",
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


class OntologyHubComponentUIValidationTests(unittest.TestCase):
    def test_resolve_ontology_hub_runtime_reads_admin_credentials_from_chart_values(self):
        with mock.patch(
            "validation.components.ontology_hub.runtime_config._parse_key_value_file",
            return_value={
                "DS_1_NAME": "demo",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            },
        ), mock.patch(
            "validation.components.ontology_hub.runtime_config._load_chart_values",
            return_value={
                "validation": {
                    "ui": {
                        "adminEmail": "qa-admin@example.org",
                        "adminPassword": "super-secret-password",
                        "creationRepositoryUri": "https://github.com/example/repo.git",
                        "creationPrimaryLanguage": "en",
                        "creationSecondaryLanguage": "es",
                    }
                }
            },
        ):
            runtime = resolve_ontology_hub_runtime(environ={})

        self.assertEqual(runtime["adminEmail"], "qa-admin@example.org")
        self.assertEqual(runtime["adminPassword"], "super-secret-password")
        self.assertEqual(runtime["componentsNamespace"], "components")
        self.assertEqual(runtime["creationRepositoryUri"], "https://github.com/example/repo")
        self.assertEqual(runtime["creationPrimaryLanguage"], "en")
        self.assertEqual(runtime["creationSecondaryLanguage"], "es")
        self.assertEqual(runtime["uiExpectTimeoutMs"], 15000)
        self.assertEqual(runtime["uiActionTimeoutMs"], 15000)
        self.assertEqual(runtime["uiNavigationTimeoutMs"], 30000)
        self.assertEqual(runtime["uiReadyTimeoutMs"], 30000)
        self.assertEqual(runtime["preflightTimeout"], 180)

    def test_resolve_ontology_hub_runtime_reads_admin_credentials_from_secret_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            email_path = os.path.join(tmpdir, "ontology-hub-admin-email.txt")
            password_path = os.path.join(tmpdir, "ontology-hub-admin-password.txt")
            with open(email_path, "w", encoding="utf-8") as handle:
                handle.write("file-admin@example.org\n")
            with open(password_path, "w", encoding="utf-8") as handle:
                handle.write("file-secret-password\n")

            with mock.patch(
                "validation.components.ontology_hub.runtime_config._parse_key_value_file",
                return_value={},
            ):
                runtime = resolve_ontology_hub_runtime(
                    environ={
                        "ONTOLOGY_HUB_ADMIN_EMAIL_FILE": email_path,
                        "ONTOLOGY_HUB_ADMIN_PASSWORD_FILE": password_path,
                    }
                )

        self.assertEqual(runtime["adminEmail"], "file-admin@example.org")
        self.assertEqual(runtime["adminPassword"], "file-secret-password")

    def test_resolve_ontology_hub_runtime_honors_component_namespace_and_timeout_overrides(self):
        with mock.patch(
            "validation.components.ontology_hub.runtime_config._parse_key_value_file",
            return_value={
                "DS_1_NAME": "demo",
                "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                "COMPONENTS_NAMESPACE": "components",
            },
        ):
            runtime = resolve_ontology_hub_runtime(
                environ={
                    "ONTOLOGY_HUB_COMPONENTS_NAMESPACE": "custom-components",
                    "ONTOLOGY_HUB_UI_EXPECT_TIMEOUT_MS": "21000",
                    "ONTOLOGY_HUB_UI_ACTION_TIMEOUT_MS": "22000",
                    "ONTOLOGY_HUB_UI_NAVIGATION_TIMEOUT_MS": "23000",
                    "ONTOLOGY_HUB_UI_READY_TIMEOUT_MS": "24000",
                }
            )

        self.assertEqual(runtime["componentsNamespace"], "custom-components")
        self.assertEqual(runtime["uiExpectTimeoutMs"], 21000)
        self.assertEqual(runtime["uiActionTimeoutMs"], 22000)
        self.assertEqual(runtime["uiNavigationTimeoutMs"], 23000)
        self.assertEqual(runtime["uiReadyTimeoutMs"], 24000)

    def test_resolve_ontology_hub_runtime_reads_admin_credentials_from_explicit_values_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            values_path = os.path.join(tmpdir, "custom-values.yaml")
            with open(values_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            "validation:",
                            "  ui:",
                            "    adminEmail: chart-admin@example.org",
                            "    adminPassword: chart-secret-password",
                            "",
                        ]
                    )
                )

            with mock.patch(
                "validation.components.ontology_hub.runtime_config._parse_key_value_file",
                return_value={
                    "DS_1_NAME": "demo",
                    "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
                },
            ):
                runtime = resolve_ontology_hub_runtime(
                    environ={"ONTOLOGY_HUB_VALUES_FILE": values_path}
                )

        self.assertEqual(runtime["adminEmail"], "chart-admin@example.org")
        self.assertEqual(runtime["adminPassword"], "chart-secret-password")

    def test_run_ontology_hub_ui_validation_persists_playwright_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _build_playwright_results_payload()
            preflight = {
                "status": "passed",
                "ready": True,
                "strict": False,
                "shouldRunPlaywright": True,
                "blocking_failures": [],
                "probes": [],
            }

            def fake_subprocess_run(command, cwd=None, env=None):
                self.assertIn("--workers=1", command)
                self.assertIn("PLAYWRIGHT_JSON_REPORT_FILE", env)
                self.assertEqual(env["ONTOLOGY_HUB_BASE_URL"], "http://ontology-hub-demo.dev.ds.dataspaceunit.upm")
                self.assertEqual(env["ONTOLOGY_HUB_UI_WORKERS"], "1")
                with open(env["ONTOLOGY_HUB_RUNTIME_FILE"], "r", encoding="utf-8") as handle:
                    runtime = json.load(handle)
                self.assertEqual(runtime["baseUrl"], env["ONTOLOGY_HUB_BASE_URL"])
                self.assertEqual(runtime["uiWorkers"], 1)
                with open(env["PLAYWRIGHT_JSON_REPORT_FILE"], "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch(
                "validation.components.ontology_hub.integration.ui_runner.subprocess.run",
                side_effect=fake_subprocess_run,
            ), mock.patch(
                "validation.components.ontology_hub.integration.ui_runner._run_ui_preflight",
                return_value=preflight,
            ):
                result = run_ontology_hub_ui_validation(
                    "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ontology-hub")
            self.assertEqual(result["suite"], "ui")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 5)
            self.assertEqual(result["summary"]["passed"], 5)
            self.assertEqual(result["pt5_summary"]["total"], 5)
            self.assertEqual(result["support_summary"]["total"], 0)
            self.assertTrue(all(case["case_group"] == "pt5" for case in result["executed_cases"]))
            self.assertGreaterEqual(len(result["evidence_index"]), 5)
            self.assertEqual(len(result["executed_cases"]), 5)
            self.assertEqual(result["runtime"]["uiWorkers"], 1)
            self.assertEqual(result["preflight"], preflight)
            self.assertTrue(
                os.path.exists(result["artifacts"]["report_json"]),
                "Expected the synthesized UI suite report to be persisted",
            )
            self.assertTrue(
                os.path.exists(result["artifacts"]["json_report_file"]),
                "Expected the mocked Playwright JSON report to exist",
            )
            self.assertTrue(os.path.exists(result["artifacts"]["resolved_runtime_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["preflight_json"]))

            with open(result["artifacts"]["preflight_json"], "r", encoding="utf-8") as handle:
                persisted_preflight = json.load(handle)
            self.assertEqual(persisted_preflight, preflight)

    def test_run_ontology_hub_ui_validation_honors_worker_override(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"ONTOLOGY_HUB_UI_WORKERS": "5"},
            clear=False,
        ):
            payload = _build_playwright_results_payload()
            preflight = {
                "status": "passed",
                "ready": True,
                "strict": False,
                "shouldRunPlaywright": True,
                "blocking_failures": [],
                "probes": [],
            }

            def fake_subprocess_run(command, cwd=None, env=None):
                self.assertIn("--workers=5", command)
                self.assertEqual(env["ONTOLOGY_HUB_UI_WORKERS"], "5")
                with open(env["PLAYWRIGHT_JSON_REPORT_FILE"], "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch(
                "validation.components.ontology_hub.integration.ui_runner.subprocess.run",
                side_effect=fake_subprocess_run,
            ), mock.patch(
                "validation.components.ontology_hub.integration.ui_runner._run_ui_preflight",
                return_value=preflight,
            ):
                result = run_ontology_hub_ui_validation(
                    "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["runtime"]["uiWorkers"], 5)
            self.assertIn("--workers=5", result["playwright_command"])

    def test_run_ontology_hub_ui_validation_fails_fast_on_blocking_preflight(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            preflight = {
                "status": "failed",
                "ready": False,
                "strict": True,
                "shouldRunPlaywright": False,
                "blocking_failures": ["catalog_page", "search_api"],
                "fatal_failures": [],
                "probes": [
                    {
                        "id": "catalog_page",
                        "status": "failed",
                        "blocking": True,
                        "assertions": ["Missing expected page markers: search for a vocabulary"],
                    }
                ],
            }

            with mock.patch(
                "validation.components.ontology_hub.integration.ui_runner.subprocess.run",
            ) as mocked_subprocess, mock.patch(
                "validation.components.ontology_hub.integration.ui_runner._run_ui_preflight",
                return_value=preflight,
            ):
                result = run_ontology_hub_ui_validation(
                    "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    experiment_dir=tmpdir,
                )

            mocked_subprocess.assert_not_called()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["preflight"], preflight)
            self.assertEqual(result["error"]["type"], "RuntimeError")
            self.assertIn("catalog_page, search_api", result["error"]["message"])
            self.assertEqual(result["summary"]["total"], len(UI_CASE_METADATA))
            self.assertEqual(result["summary"]["failed"], len(UI_CASE_METADATA))
            self.assertTrue(all(case["evaluation"]["status"] == "failed" for case in result["executed_cases"]))
            self.assertTrue(os.path.exists(result["artifacts"]["preflight_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["resolved_runtime_json"]))

    def test_run_ui_preflight_marks_authentication_failure_as_fatal(self):
        runtime = resolve_ontology_hub_runtime(base_url="http://ontology-hub-demo.dev.ds.dataspaceunit.upm")

        with (
            mock.patch(
                "validation.components.ontology_hub.integration.ui_runner._run_html_probe",
                side_effect=[
                    {"id": "home_page", "status": "passed", "blocking": True},
                    {"id": "catalog_page", "status": "passed", "blocking": True},
                    {"id": "api_docs", "status": "passed", "blocking": True},
                    {"id": "edition_login", "status": "passed", "blocking": True},
                    {"id": "vocabulary_detail", "status": "failed", "blocking": False},
                ],
            ),
            mock.patch(
                "validation.components.ontology_hub.integration.ui_runner._run_edition_auth_probe",
                return_value={
                    "id": "edition_authentication",
                    "status": "failed",
                    "blocking": True,
                    "fatal": True,
                    "assertions": ["Las credenciales configuradas no son validas."],
                },
            ),
            mock.patch(
                "validation.components.ontology_hub.integration.ui_runner._run_search_api_probe",
                return_value={"id": "search_api", "status": "failed", "blocking": False},
            ),
        ):
            preflight = _run_ui_preflight(runtime)

        self.assertEqual(preflight["status"], "failed")
        self.assertFalse(preflight["shouldRunPlaywright"])
        self.assertEqual(preflight["fatal_failures"], ["edition_authentication"])
        self.assertIn("edition_authentication", preflight["blocking_failures"])

    def test_run_ontology_hub_component_validation_combines_api_and_ui(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            api_result = {
                "component": "ontology-hub",
                "suite": "api",
                "status": "passed",
                "summary": {"total": 5, "passed": 5, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "PT5-OH-08",
                        "type": "api",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                    {
                        "test_case_id": "PT5-OH-15",
                        "type": "api",
                        "case_group": "pt5",
                        "validation_type": "integration",
                        "dataspace_dimension": "integration",
                        "mapping_status": "partial",
                        "coverage_status": "partial",
                        "execution_mode": "api",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                ],
                "evidence_index": [{"scope": "suite", "suite": "api", "artifact_name": "report_json", "path": "api.json"}],
                "artifacts": {"report_json": os.path.join(tmpdir, "api.json")},
            }
            ui_result = {
                "component": "ontology-hub",
                "suite": "ui",
                "status": "passed",
                "summary": {"total": 5, "passed": 5, "failed": 0, "skipped": 0},
                "executed_cases": [
                    {
                        "test_case_id": "PT5-OH-15",
                        "type": "ui",
                        "case_group": "pt5",
                        "validation_type": "integration",
                        "dataspace_dimension": "integration",
                        "mapping_status": "mapped",
                        "coverage_status": "automated",
                        "execution_mode": "ui",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                    {
                        "test_case_id": "OH-LOGIN",
                        "type": "ui",
                        "case_group": "support",
                        "validation_type": "support",
                        "dataspace_dimension": "support",
                        "mapping_status": "supporting",
                        "coverage_status": "automated",
                        "execution_mode": "ui_support",
                        "evaluation": {"status": "passed", "assertions": []},
                    },
                ],
                "evidence_index": [{"scope": "suite", "suite": "ui", "artifact_name": "report_json", "path": "ui.json"}],
                "artifacts": {
                    "report_json": os.path.join(tmpdir, "ui.json"),
                    "test_results_dir": os.path.join(tmpdir, "ui", "test-results"),
                    "html_report_dir": os.path.join(tmpdir, "ui", "playwright-report"),
                    "blob_report_dir": os.path.join(tmpdir, "ui", "blob-report"),
                    "json_report_file": os.path.join(tmpdir, "ui", "results.json"),
                },
            }

            with (
                mock.patch(
                    "validation.components.ontology_hub.integration.component_runner.run_ontology_hub_validation",
                    return_value=api_result,
                ),
                mock.patch(
                    "validation.components.ontology_hub.integration.component_runner.run_ontology_hub_ui_validation",
                    return_value=ui_result,
                ),
            ):
                result = run_ontology_hub_component_validation(
                    "http://ontology-hub-demo.dev.ds.dataspaceunit.upm",
                    experiment_dir=tmpdir,
                )

            self.assertEqual(result["component"], "ontology-hub")
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["total"], 10)
            self.assertEqual(result["summary"]["passed"], 10)
            self.assertEqual(result["suites"]["api"]["status"], "passed")
            self.assertEqual(result["suites"]["ui"]["status"], "passed")
            self.assertEqual(len(result["executed_cases"]), 4)
            self.assertEqual(result["pt5_summary"]["total"], 2)
            self.assertEqual(result["pt5_summary"]["passed"], 2)
            self.assertEqual(len(result["pt5_case_results"]), 2)
            self.assertEqual(result["support_summary"]["total"], 1)
            self.assertEqual(len(result["support_checks"]), 1)
            self.assertEqual(result["pt5_case_results"][1]["test_case_id"], "PT5-OH-15")
            self.assertEqual(set(result["pt5_case_results"][1]["source_suites"]), {"api", "ui"})
            self.assertEqual(result["pt5_case_results"][1]["traceability"], ["OntHub-54", "OntHub-55"])
            self.assertEqual(result["support_checks"][0]["traceability"], [])
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_pt5_cases"], 16)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_pt5_cases"], 2)
            self.assertEqual(result["catalog_alignment"]["summary"]["uncovered_pt5_cases"], 14)
            self.assertEqual(result["catalog_alignment"]["summary"]["declared_support_checks"], 2)
            self.assertEqual(result["catalog_alignment"]["summary"]["executed_support_checks"], 1)
            self.assertEqual(result["catalog_alignment"]["summary"]["missing_support_checks"], 1)
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))
            self.assertTrue(result["artifacts"]["ui_report_json"].endswith("ui.json"))
            self.assertTrue(os.path.exists(result["artifacts"]["pt5_case_results_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["support_checks_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["evidence_index_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["findings_json"]))
            self.assertTrue(os.path.exists(result["artifacts"]["catalog_alignment_json"]))


if __name__ == "__main__":
    unittest.main()
