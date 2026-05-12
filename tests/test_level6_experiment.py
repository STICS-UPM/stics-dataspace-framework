import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from framework.experiment_storage import ExperimentStorage
from framework.metrics_collector import MetricsCollector
from validation.orchestration import state as level6_state
from validation.orchestration import ui as level6_ui
from validation.orchestration.runner import Level6Runtime, run_level6
from validation.ui.reporting import aggregate_level6_ui_results, enrich_level6_ui_result


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MINIMAL_NEWMAN_REPORTS = {
    "01_environment_health.json": {
        "collection": {"info": {"name": "01 Environment Health"}},
        "run": {
            "executions": [
                {
                    "item": {"name": "Provider health"},
                    "request": {
                        "method": "GET",
                        "url": {"raw": "http://conn-a.example.local/health"},
                    },
                    "response": {
                        "code": 200,
                        "responseTime": 42,
                        "timestamp": "2026-01-01T00:00:01.000Z",
                    },
                    "cursor": {"started": "2026-01-01T00:00:00.950Z"},
                    "assertions": [{"assertion": "status is 200"}],
                },
                {
                    "item": {"name": "Consumer health"},
                    "request": {
                        "method": "GET",
                        "url": {"raw": "http://conn-b.example.local/health"},
                    },
                    "response": {
                        "code": 200,
                        "responseTime": 45,
                        "timestamp": "2026-01-01T00:00:02.000Z",
                    },
                    "cursor": {"started": "2026-01-01T00:00:01.950Z"},
                    "assertions": [{"assertion": "status is 200"}],
                },
            ],
            "failures": [],
        },
    },
    "05_consumer_negotiation.json": {
        "collection": {"info": {"name": "05 Consumer Negotiation"}},
        "run": {
            "executions": [
                {
                    "item": {"name": "Direct DSP catalog"},
                    "request": {
                        "method": "POST",
                        "url": {"raw": "http://conn-b.example.local/management/v3/catalog/request"},
                    },
                    "response": {
                        "code": 200,
                        "responseTime": 123,
                        "timestamp": "2026-01-01T00:01:01.000Z",
                    },
                    "cursor": {"started": "2026-01-01T00:01:00.800Z"},
                    "assertions": [{"assertion": "status is 200"}],
                },
                {
                    "item": {"name": "Poll agreement state"},
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "http://conn-b.example.local/management/v3/contractnegotiations/negotiation-1"
                        },
                    },
                    "response": {
                        "code": 200,
                        "responseTime": 210,
                        "timestamp": "2026-01-01T00:01:05.000Z",
                    },
                    "cursor": {"started": "2026-01-01T00:01:04.750Z"},
                    "assertions": [{"assertion": "agreement finalized"}],
                },
            ],
            "failures": [
                {
                    "source": {"name": "Poll agreement state"},
                    "error": {
                        "test": "agreement finalized",
                        "message": "expected state FINALIZED but got TERMINATED",
                    },
                }
            ],
        },
    },
    "06_consumer_transfer.json": {
        "collection": {"info": {"name": "06 Consumer Transfer"}},
        "run": {
            "executions": [
                {
                    "item": {"name": "Endpoint data reference"},
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "http://conn-b.example.local/management/v3/edrs/transfer-1/dataaddress"
                        },
                    },
                    "response": {
                        "code": 200,
                        "responseTime": 87,
                        "timestamp": "2026-01-01T00:02:01.000Z",
                    },
                    "cursor": {"started": "2026-01-01T00:02:00.900Z"},
                    "assertions": [{"assertion": "auth code is present"}],
                }
            ],
            "failures": [],
        },
    },
}


def _materialize_fixture_reports(experiment_dir):
    report_dir = ExperimentStorage.newman_reports_dir(experiment_dir)
    pair_dir = os.path.join(report_dir, "run_001", "conn-a__conn-b")
    os.makedirs(pair_dir, exist_ok=True)

    exported = []
    for file_name, report in MINIMAL_NEWMAN_REPORTS.items():
        target = os.path.join(pair_dir, file_name)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        exported.append(target)

    return exported


def _build_level6_readiness_payload(status="passed", gates=None):
    return {
        "status": status,
        "timestamp": "2026-03-27T00:00:00",
        "connectors": ["conn-a", "conn-b"],
        "timeout_seconds": 90.0,
        "poll_interval_seconds": 3.0,
        "total_duration_seconds": 1.25,
        "gates": list(gates or []),
    }


def _build_level6_ui_results_payload():
    return {
        "stats": {
            "expected": 2,
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "core/01-login-readiness.spec.ts",
                "file": "core/01-login-readiness.spec.ts",
                "specs": [
                    {
                        "title": "01 login readiness: authentication and shell loaded",
                        "file": "core/01-login-readiness.spec.ts",
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
                "title": "core/04-consumer-catalog.spec.ts",
                "file": "core/04-consumer-catalog.spec.ts",
                "specs": [
                    {
                        "title": "04 consumer catalog: listing and detail without access errors",
                        "file": "core/04-consumer-catalog.spec.ts",
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


def _build_level6_ui_dataspace_results_payload():
    return {
        "stats": {
            "expected": 5,
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "core/03-provider-setup.spec.ts",
                "file": "core/03-provider-setup.spec.ts",
                "specs": [
                    {
                        "title": "03 provider setup: asset creation with file upload",
                        "file": "core/03-provider-setup.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "core/03b-provider-policy-create.spec.ts",
                "file": "core/03b-provider-policy-create.spec.ts",
                "specs": [
                    {
                        "title": "03b provider setup: policy creation from the UI",
                        "file": "core/03b-provider-policy-create.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "core/03c-provider-contract-definition-create.spec.ts",
                "file": "core/03c-provider-contract-definition-create.spec.ts",
                "specs": [
                    {
                        "title": "03c provider setup: contract definition creation from the UI",
                        "file": "core/03c-provider-contract-definition-create.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "core/05-consumer-negotiation.spec.ts",
                "file": "core/05-consumer-negotiation.spec.ts",
                "specs": [
                    {
                        "title": "05 consumer negotiation: visible negotiation from catalog",
                        "file": "core/05-consumer-negotiation.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
            {
                "title": "core/06-consumer-transfer.spec.ts",
                "file": "core/06-consumer-transfer.spec.ts",
                "specs": [
                    {
                        "title": "06 consumer transfer: visible transfer from contracts and history",
                        "file": "core/06-consumer-transfer.spec.ts",
                        "tests": [{"results": [{"status": "passed", "errors": [], "attachments": []}]}],
                    }
                ],
            },
        ],
    }


def _build_level6_ui_ops_results_payload():
    return {
        "stats": {
            "expected": 1,
            "unexpected": 0,
            "flaky": 0,
            "skipped": 0,
        },
        "suites": [
            {
                "title": "ops/minio-bucket-visibility.spec.ts",
                "file": "ops/minio-bucket-visibility.spec.ts",
                "specs": [
                    {
                        "title": "ops minio visibility: provider and consumer buckets are visible",
                        "file": "ops/minio-bucket-visibility.spec.ts",
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "passed",
                                        "errors": [],
                                        "attachments": [
                                            {
                                                "name": "bucket-visibility",
                                                "contentType": "image/png",
                                                "path": "/tmp/minio.png",
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


def _save_level6_state(experiment_dir, connectors, **kwargs):
    return level6_state.save_level6_experiment_state(
        experiment_dir,
        connectors,
        experiment_storage=ExperimentStorage,
        aggregate_ui_results=aggregate_level6_ui_results,
        **kwargs,
    )


def _create_script_root(base_dir, *, ui_enabled=False, ops_enabled=True):
    script_root = SimpleNamespace(name=os.path.join(base_dir, "script-root"))
    if ui_enabled:
        ui_dir = os.path.join(script_root.name, "validation", "ui")
        os.makedirs(os.path.join(ui_dir, "ops"), exist_ok=True)
        if ops_enabled:
            with open(os.path.join(ui_dir, level6_ui.LEVEL6_UI_OPS_CONFIG), "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            with open(os.path.join(ui_dir, level6_ui.LEVEL6_UI_OPS_SPEC), "w", encoding="utf-8") as handle:
                handle.write("// test fixture\n")
    return script_root


def _build_runtime(
    experiment_dir,
    *,
    connectors=None,
    script_root=None,
    subprocess_module=None,
    ui_dataspace=False,
    ui_ops=True,
    kafka_edc=False,
    component_validation=False,
    component_results=None,
):
    connectors = connectors or ["conn-a", "conn-b"]
    script_root = script_root or SimpleNamespace(name=os.path.join(experiment_dir, "script-root"))
    subprocess_module = subprocess_module or mock.Mock()
    subprocess_module.run.return_value = mock.Mock(returncode=0)
    validation_engine = mock.Mock()
    validation_engine.last_storage_checks = []
    validation_engine.run_all_dataspace_tests.return_value = ["pair-report.json"]
    metrics_collector = MetricsCollector(experiment_storage=ExperimentStorage)
    run_kafka_benchmark = mock.Mock(return_value=None)
    run_kafka_edc_validation = mock.Mock(return_value=[])
    if kafka_edc:
        run_kafka_edc_validation.return_value = [
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "status": "passed",
                "metrics": {
                    "messages_consumed": 5,
                    "average_latency_ms": 12.5,
                },
            },
            {
                "provider": "conn-b",
                "consumer": "conn-a",
                "status": "failed",
                "error": {
                    "type": "RuntimeError",
                    "message": "EDR did not expose authKey/authCode",
                },
            },
        ]
    run_component_validations = mock.Mock(return_value=component_results or [])

    def run_ui_smoke(ui_test_dir, connector, portal_url, portal_user, portal_pass, experiment_dir):
        return level6_ui.run_ui_smoke(
            ui_test_dir,
            connector,
            portal_url,
            portal_user,
            portal_pass,
            experiment_dir,
            subprocess_module=subprocess_module,
            enrich_result=enrich_level6_ui_result,
            environment={},
        )

    def run_ui_dataspace(ui_test_dir, provider_connector, consumer_connector, experiment_dir):
        return level6_ui.run_ui_dataspace(
            ui_test_dir,
            provider_connector,
            consumer_connector,
            experiment_dir,
            subprocess_module=subprocess_module,
            enrich_result=enrich_level6_ui_result,
            environment={},
        )

    def run_ui_ops(ui_test_dir, provider_connector, consumer_connector, experiment_dir):
        return level6_ui.run_ui_ops(
            ui_test_dir,
            provider_connector,
            consumer_connector,
            experiment_dir,
            subprocess_module=subprocess_module,
            enrich_result=enrich_level6_ui_result,
            environment={},
        )

    runtime = Level6Runtime(
        newman_executor=mock.Mock(is_available=mock.Mock(return_value=True)),
        ensure_connectors_ready=mock.Mock(return_value=connectors),
        ensure_connector_hosts=mock.Mock(return_value=None),
        validate_connectors_deployment=mock.Mock(return_value=True),
        ensure_all_minio_policies=mock.Mock(return_value=None),
        wait_for_keycloak_readiness=mock.Mock(return_value=True),
        wait_for_validation_ready=mock.Mock(return_value=_build_level6_readiness_payload()),
        validation_engine=validation_engine,
        metrics_collector=metrics_collector,
        experiment_storage=mock.Mock(
            create_experiment_directory=mock.Mock(return_value=experiment_dir),
            save_experiment_metadata=ExperimentStorage.save_experiment_metadata,
            newman_reports_dir=ExperimentStorage.newman_reports_dir,
        ),
        save_experiment_state=_save_level6_state,
        should_run_kafka_edc_validation=mock.Mock(return_value=kafka_edc),
        run_kafka_edc_validation=run_kafka_edc_validation,
        run_kafka_benchmark=run_kafka_benchmark,
        should_run_ui_dataspace=mock.Mock(return_value=ui_dataspace),
        should_run_ui_ops=mock.Mock(
            side_effect=lambda ui_test_dir: ui_ops and level6_ui.ui_ops_suite_available(ui_test_dir)
        ),
        should_run_component_validation=mock.Mock(return_value=component_validation),
        run_component_validations=run_component_validations,
        script_dir=mock.Mock(return_value=script_root.name),
        load_connector_credentials=mock.Mock(
            return_value={
                "connector_user": {
                    "user": "portal-user",
                    "passwd": "portal-pass",
                }
            }
        ),
        build_connector_url=mock.Mock(side_effect=lambda connector: f"https://{connector}.example.local"),
        run_ui_smoke=run_ui_smoke,
        run_ui_dataspace=run_ui_dataspace,
        run_ui_ops=run_ui_ops,
    )
    handles = SimpleNamespace(
        script_root=script_root,
        subprocess_module=subprocess_module,
        validation_engine=validation_engine,
        run_kafka_benchmark=run_kafka_benchmark,
        run_kafka_edc_validation=run_kafka_edc_validation,
        run_component_validations=run_component_validations,
    )
    return runtime, handles


class Level6ExperimentTests(unittest.TestCase):
    def test_run_level6_creates_experiment_before_validation_and_passes_experiment_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, handles = _build_runtime(tmpdir, ui_dataspace=False)

            run_level6(runtime)

            metadata_path = os.path.join(tmpdir, "metadata.json")
            experiment_results_path = os.path.join(tmpdir, "experiment_results.json")
            newman_reports_dir = os.path.join(tmpdir, "newman_reports")

            handles.validation_engine.run_all_dataspace_tests.assert_called_once_with(
                ["conn-a", "conn-b"],
                experiment_dir=tmpdir,
            )
            handles.run_kafka_benchmark.assert_called_once_with(tmpdir)
            runtime.ensure_connector_hosts.assert_called_once_with(["conn-a", "conn-b"])
            self.assertTrue(os.path.exists(metadata_path))
            self.assertTrue(os.path.exists(experiment_results_path))
            self.assertTrue(os.path.isdir(newman_reports_dir))

            with open(experiment_results_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(stored["source"], "validation.orchestration:level6")
            self.assertEqual(stored["status"], "completed")
            self.assertEqual(stored["level6_readiness"]["status"], "passed")
            self.assertEqual(stored["validation_reports"], ["pair-report.json"])
            self.assertEqual(stored["storage_checks"], [])
            self.assertEqual(stored["kafka_edc_results"], [])
            self.assertEqual(stored["ui_results"], [])
            self.assertEqual(stored["ui_validation"]["status"], "not_run")
            self.assertEqual(stored["component_results"], [])
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "raw_requests.jsonl")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "aggregated_metrics.json")))

    def test_run_level6_persists_storage_checks_exposed_by_validation_engine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, handles = _build_runtime(tmpdir, ui_dataspace=False)

            def run_validation(connectors, experiment_dir=None):
                handles.validation_engine.last_storage_checks = [
                    {
                        "provider": "conn-a",
                        "consumer": "conn-b",
                        "status": "passed",
                        "bucket_name": "demo-conn-b",
                    }
                ]
                return ["pair-report.json"]

            handles.validation_engine.run_all_dataspace_tests.side_effect = run_validation

            run_level6(runtime)

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(stored["storage_checks"]), 1)
            self.assertEqual(stored["storage_checks"][0]["status"], "passed")
            self.assertEqual(stored["storage_checks"][0]["bucket_name"], "demo-conn-b")

    def test_run_level6_persists_failed_state_when_validation_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, handles = _build_runtime(tmpdir, ui_dataspace=False)
            handles.validation_engine.run_all_dataspace_tests.side_effect = RuntimeError("validation boom")

            with self.assertRaisesRegex(RuntimeError, "validation boom"):
                run_level6(runtime)

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(stored["status"], "failed")
            self.assertEqual(stored["error"]["type"], "RuntimeError")
            self.assertIn("validation boom", stored["error"]["message"])
            self.assertEqual(stored["storage_checks"], [])
            self.assertEqual(stored["kafka_edc_results"], [])
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "raw_requests.jsonl")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "aggregated_metrics.json")))

    def test_run_level6_fails_when_readiness_probe_does_not_converge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, _handles = _build_runtime(tmpdir, ui_dataspace=False)
            failed_readiness = _build_level6_readiness_payload(
                status="failed",
                gates=[
                    {
                        "gate": "management_api_smoke:conn-a",
                        "status": "failed",
                        "attempts": 3,
                        "error": "HTTP 401",
                    }
                ],
            )
            runtime.wait_for_validation_ready.return_value = failed_readiness

            with self.assertRaisesRegex(RuntimeError, "Level 6 validation readiness check failed"):
                run_level6(runtime)

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(stored["status"], "failed")
            self.assertEqual(stored["level6_readiness"]["status"], "failed")
            self.assertEqual(stored["level6_readiness"]["gates"][0]["gate"], "management_api_smoke:conn-a")

    def test_run_level6_collects_metrics_from_exported_newman_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, handles = _build_runtime(tmpdir, ui_dataspace=False)
            handles.validation_engine.run_all_dataspace_tests.side_effect = (
                lambda connectors, experiment_dir=None: _materialize_fixture_reports(experiment_dir)
            )

            run_level6(runtime)

            with open(os.path.join(tmpdir, "aggregated_metrics.json"), "r", encoding="utf-8") as handle:
                aggregated_metrics = json.load(handle)
            with open(os.path.join(tmpdir, "test_results.json"), "r", encoding="utf-8") as handle:
                test_results = json.load(handle)
            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(test_results), 5)
            self.assertEqual(len(stored["newman_request_metrics"]), 5)
            self.assertEqual(stored["storage_checks"], [])
            self.assertEqual(stored["kafka_edc_results"], [])
            self.assertIn("request_metrics", aggregated_metrics)
            self.assertEqual(aggregated_metrics["test_summary"]["tests_failed"], 1)

    def test_run_level6_routes_ui_smoke_evidence_into_experiment_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_root = _create_script_root(tmpdir, ui_enabled=True)

            def fake_subprocess_run(command, cwd=None, env=None):
                payload = (
                    _build_level6_ui_ops_results_payload()
                    if env.get("PLAYWRIGHT_OPS_JSON_REPORT_FILE")
                    else _build_level6_ui_results_payload()
                )
                output_path = env.get("PLAYWRIGHT_OPS_JSON_REPORT_FILE") or env["PLAYWRIGHT_JSON_REPORT_FILE"]
                with open(output_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                return mock.Mock(returncode=0)

            subprocess_module = mock.Mock()
            subprocess_module.run.side_effect = fake_subprocess_run
            runtime, handles = _build_runtime(
                tmpdir,
                script_root=script_root,
                subprocess_module=subprocess_module,
                ui_dataspace=False,
            )

            run_level6(runtime)

            self.assertEqual(handles.subprocess_module.run.call_count, 3)

            first_call = handles.subprocess_module.run.call_args_list[0]
            first_command = first_call.args[0]
            first_env = first_call.kwargs["env"]
            ui_test_dir = os.path.join(script_root.name, "validation", "ui")

            self.assertEqual(first_command[:3], ["npx", "playwright", "test"])
            self.assertEqual(first_command[3:], list(level6_ui.LEVEL6_UI_SMOKE_SPECS))
            self.assertEqual(first_call.kwargs["cwd"], ui_test_dir)
            self.assertEqual(first_env["PORTAL_BASE_URL"], "https://conn-a.example.local")
            self.assertEqual(first_env["PORTAL_USER"], "portal-user")
            self.assertEqual(first_env["PORTAL_PASSWORD"], "portal-pass")
            self.assertEqual(
                first_env["PLAYWRIGHT_OUTPUT_DIR"],
                os.path.join(tmpdir, "ui", "conn-a", "test-results"),
            )

            ops_call = handles.subprocess_module.run.call_args_list[2]
            self.assertEqual(
                ops_call.args[0],
                [
                    "npx",
                    "playwright",
                    "test",
                    "--config",
                    level6_ui.LEVEL6_UI_OPS_CONFIG,
                    level6_ui.LEVEL6_UI_OPS_SPEC,
                ],
            )

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(stored["ui_results"]), 3)
            self.assertEqual(stored["ui_results"][0]["test"], "ui-core-smoke")
            self.assertEqual(stored["ui_results"][0]["status"], "passed")
            self.assertEqual(stored["ui_results"][0]["suite"], "ui-core")
            self.assertEqual(stored["ui_results"][0]["summary"]["total"], 2)
            self.assertEqual(stored["ui_results"][0]["support_checks"][0]["test_case_id"], "DS-UI-01")
            self.assertEqual(stored["ui_results"][0]["dataspace_cases"][0]["test_case_id"], "DS-UI-04")
            self.assertEqual(stored["ui_results"][2]["test"], "ui-ops-minio-console")
            self.assertEqual(stored["ui_results"][2]["suite"], "ui-ops")
            self.assertEqual(stored["ui_results"][2]["ops_checks"][0]["test_case_id"], "DS-UI-OPS-01")
            self.assertEqual(stored["ui_validation"]["status"], "passed")
            self.assertEqual(stored["ui_validation"]["summary"]["total"], 3)
            self.assertEqual(stored["ui_validation"]["support_summary"]["passed"], 2)
            self.assertEqual(stored["ui_validation"]["dataspace_summary"]["passed"], 2)
            self.assertEqual(stored["ui_validation"]["ops_summary"]["passed"], 1)
            self.assertTrue(os.path.exists(stored["ui_validation"]["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(stored["ui_results"][0]["artifacts"]["report_json"]))

    def test_run_level6_runs_ui_dataspace_suite_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_root = _create_script_root(tmpdir, ui_enabled=True)

            def fake_subprocess_run(command, cwd=None, env=None):
                if env.get("PLAYWRIGHT_OPS_JSON_REPORT_FILE"):
                    output_path = env["PLAYWRIGHT_OPS_JSON_REPORT_FILE"]
                    with open(output_path, "w", encoding="utf-8") as handle:
                        json.dump(_build_level6_ui_ops_results_payload(), handle)
                    self.assertEqual(env["UI_PROVIDER_CONNECTOR"], "conn-a")
                    self.assertEqual(env["UI_CONSUMER_CONNECTOR"], "conn-b")
                    return mock.Mock(returncode=0)
                if command[3:] == list(level6_ui.LEVEL6_UI_SMOKE_SPECS):
                    output_path = env["PLAYWRIGHT_JSON_REPORT_FILE"]
                    with open(output_path, "w", encoding="utf-8") as handle:
                        json.dump(_build_level6_ui_results_payload(), handle)
                    return mock.Mock(returncode=0)
                if command[3] == "--workers=1" and command[4:] == list(level6_ui.LEVEL6_UI_DATASPACE_SPECS):
                    output_path = env["PLAYWRIGHT_JSON_REPORT_FILE"]
                    with open(output_path, "w", encoding="utf-8") as handle:
                        json.dump(_build_level6_ui_dataspace_results_payload(), handle)
                    self.assertEqual(env["UI_PROVIDER_CONNECTOR"], "conn-a")
                    self.assertEqual(env["UI_CONSUMER_CONNECTOR"], "conn-b")
                    self.assertEqual(env["PORTAL_TEST_FILE_MB"], "10")
                    return mock.Mock(returncode=0)
                raise AssertionError(f"Unexpected command: {command}")

            subprocess_module = mock.Mock()
            subprocess_module.run.side_effect = fake_subprocess_run
            runtime, _handles = _build_runtime(
                tmpdir,
                script_root=script_root,
                subprocess_module=subprocess_module,
                ui_dataspace=True,
            )

            run_level6(runtime)

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(stored["ui_results"]), 4)
            self.assertEqual(stored["ui_results"][2]["test"], "ui-core-dataspace")
            self.assertEqual(stored["ui_results"][2]["status"], "passed")
            self.assertEqual(stored["ui_results"][2]["suite"], "ui-core-dataspace")
            self.assertEqual(stored["ui_results"][2]["provider_connector"], "conn-a")
            self.assertEqual(stored["ui_results"][2]["consumer_connector"], "conn-b")
            self.assertEqual(stored["ui_results"][2]["dataspace_summary"]["passed"], 5)
            self.assertEqual(stored["ui_results"][2]["dataspace_cases"][0]["test_case_id"], "DS-UI-03")
            self.assertEqual(stored["ui_results"][3]["test"], "ui-ops-minio-console")
            self.assertEqual(
                stored["ui_results"][2]["artifacts"]["report_json"],
                os.path.join(tmpdir, "ui-dataspace", "conn-a__conn-b", "ui_dataspace_validation.json"),
            )

    def test_run_level6_marks_ui_smoke_skipped_when_playwright_command_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_root = _create_script_root(tmpdir, ui_enabled=True)
            subprocess_module = mock.Mock()
            subprocess_module.run.side_effect = FileNotFoundError("npx not found")
            runtime, _handles = _build_runtime(
                tmpdir,
                script_root=script_root,
                subprocess_module=subprocess_module,
                ui_dataspace=False,
            )

            run_level6(runtime)

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(stored["ui_results"]), 3)
            self.assertEqual(stored["ui_results"][0]["status"], "skipped")
            self.assertIsNone(stored["ui_results"][0]["exit_code"])
            self.assertEqual(stored["ui_results"][0]["error"]["type"], "FileNotFoundError")
            self.assertIn("npx not found", stored["ui_results"][0]["error"]["message"])
            self.assertEqual(stored["ui_results"][0]["suite"], "ui-core")
            self.assertEqual(stored["ui_results"][0]["summary"]["total"], 2)
            self.assertEqual(stored["ui_results"][2]["suite"], "ui-ops")
            self.assertEqual(stored["ui_validation"]["status"], "skipped")
            self.assertEqual(stored["ui_validation"]["summary"]["total"], 3)
            self.assertEqual(stored["ui_validation"]["summary"]["skipped"], 3)
            self.assertTrue(os.path.exists(stored["ui_results"][0]["artifacts"]["report_json"]))
            self.assertTrue(os.path.exists(stored["ui_validation"]["artifacts"]["report_json"]))

    def test_run_level6_can_disable_default_ui_ops_suite_explicitly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_root = _create_script_root(tmpdir, ui_enabled=True)

            def fake_subprocess_run(command, cwd=None, env=None):
                with open(env["PLAYWRIGHT_JSON_REPORT_FILE"], "w", encoding="utf-8") as handle:
                    json.dump(_build_level6_ui_results_payload(), handle)
                return mock.Mock(returncode=0)

            subprocess_module = mock.Mock()
            subprocess_module.run.side_effect = fake_subprocess_run
            runtime, handles = _build_runtime(
                tmpdir,
                script_root=script_root,
                subprocess_module=subprocess_module,
                ui_dataspace=False,
                ui_ops=False,
            )

            run_level6(runtime)

            self.assertEqual(handles.subprocess_module.run.call_count, 2)

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(stored["ui_results"]), 2)
            self.assertTrue(all(result["test"] != "ui-ops-minio-console" for result in stored["ui_results"]))

    def test_run_level6_runs_component_validation_when_enabled(self):
        component_results = [
            {
                "component": "ontology-hub",
                "status": "passed",
                "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
                "suites": {
                    "api": {"status": "passed"},
                    "ui": {"status": "passed"},
                },
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, handles = _build_runtime(
                tmpdir,
                component_validation=True,
                component_results=component_results,
                ui_dataspace=False,
            )

            run_level6(runtime)

            handles.run_component_validations.assert_called_once_with(tmpdir)
            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(stored["component_results"]), 1)
            self.assertEqual(stored["component_results"][0]["component"], "ontology-hub")
            self.assertEqual(stored["component_results"][0]["status"], "passed")

    def test_run_level6_skips_component_validation_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, handles = _build_runtime(
                tmpdir,
                component_validation=False,
                component_results=[{"component": "ontology-hub", "status": "passed"}],
                ui_dataspace=False,
            )

            run_level6(runtime)

            handles.run_component_validations.assert_not_called()
            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(stored["component_results"], [])

    def test_run_level6_runs_optional_kafka_edc_validation_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime, handles = _build_runtime(tmpdir, kafka_edc=True, ui_dataspace=False)

            run_level6(runtime)

            handles.run_kafka_edc_validation.assert_called_once_with(["conn-a", "conn-b"], tmpdir)
            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)

            self.assertEqual(len(stored["kafka_edc_results"]), 2)
            self.assertEqual(stored["kafka_edc_results"][0]["status"], "passed")
            self.assertEqual(stored["kafka_edc_results"][0]["metrics"]["messages_consumed"], 5)
            self.assertEqual(stored["kafka_edc_results"][1]["status"], "failed")
            self.assertIn("authKey/authCode", stored["kafka_edc_results"][1]["error"]["message"])


if __name__ == "__main__":
    unittest.main()
