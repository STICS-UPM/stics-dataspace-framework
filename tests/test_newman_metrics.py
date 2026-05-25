import json
import os
import tempfile
import unittest
from unittest import mock

from framework.experiment_runner import ExperimentRunner
from framework.experiment_storage import ExperimentStorage
from framework.graph_builder import GraphBuilder
from framework.metrics_collector import MetricsCollector
from framework.newman_executor import NewmanExecutor
from framework.validation_engine import ValidationEngine


class _FakeAxis:
    def bar(self, *args, **kwargs):
        return None

    def hist(self, *args, **kwargs):
        return None

    def set_title(self, *args, **kwargs):
        return None

    def set_ylabel(self, *args, **kwargs):
        return None

    def set_xlabel(self, *args, **kwargs):
        return None

    def tick_params(self, *args, **kwargs):
        return None

    def set_xticks(self, *args, **kwargs):
        return None

    def set_xticklabels(self, *args, **kwargs):
        return None

    def legend(self, *args, **kwargs):
        return None


class _FakeFigure:
    def tight_layout(self):
        return None

    def savefig(self, path, dpi=None):
        with open(path, "wb") as f:
            f.write(b"fake-png")


class _FakePlotBackend:
    @staticmethod
    def subplots(figsize=None):
        return _FakeFigure(), _FakeAxis()

    @staticmethod
    def close(figure):
        return None


class NewmanMetricsTests(unittest.TestCase):
    @mock.patch("framework.newman_executor.subprocess.run")
    def test_run_newman_enables_json_reporter_and_export(self, mock_run):
        mock_run.return_value.returncode = 0
        executor = NewmanExecutor()

        with mock.patch.object(executor, "load_test_scripts", return_value="pm.test('ok')"):
            report_path = executor.run_newman(
                "validation/core/collections/01_environment_health.json",
                {"provider": "conn-a"},
                report_path="experiments/exp-1/newman_reports/report.json",
            )

        self.assertEqual(report_path, "experiments/exp-1/newman_reports/report.json")
        command = mock_run.call_args.args[0]
        self.assertIn("--reporters", command)
        self.assertIn("cli,json", command)
        self.assertIn("--reporter-json-export", command)
        self.assertIn("experiments/exp-1/newman_reports/report.json", command)

    @mock.patch("framework.newman_executor.subprocess.run")
    def test_run_newman_delays_async_catalog_negotiation_and_transfer_collections(self, mock_run):
        mock_run.return_value.returncode = 0
        executor = NewmanExecutor()

        with mock.patch.object(executor, "load_test_scripts", return_value="pm.test('ok')"):
            for collection_name in (
                "04_consumer_catalog.json",
                "05_consumer_negotiation.json",
                "06_consumer_transfer.json",
            ):
                executor.run_newman(
                    f"validation/core/collections/{collection_name}",
                    {"provider": "conn-a"},
                    report_path=f"experiments/exp-1/newman_reports/{collection_name}",
                )

        for call in mock_run.call_args_list:
            command = call.args[0]
            self.assertIn("--delay-request", command)
            delay_index = command.index("--delay-request")
            self.assertEqual(command[delay_index + 1], str(executor.ASYNC_COLLECTION_DELAY_REQUEST_MS))

    def test_run_validation_collections_returns_report_paths(self):
        executor = NewmanExecutor()

        def fake_run_newman(path, env, report_path=None, environment_path=None):
            if path.endswith("04_consumer_catalog.json"):
                executor._write_environment_values(
                    environment_path,
                    {
                        "e2e_offer_policy_id": "offer-123",
                        "e2e_catalog_asset_id": "asset-123",
                    },
                )
            return report_path

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                executor,
                "run_newman",
                side_effect=fake_run_newman,
            ), mock.patch.object(
                executor,
                "_should_wait_for_contract_agreement",
                return_value=False,
            ):
                reports = executor.run_validation_collections({"provider": "conn-a"}, report_dir=tmpdir)

        self.assertEqual(len(reports), 6)
        self.assertTrue(reports[0].endswith("01_environment_health.json"))
        self.assertTrue(reports[-1].endswith("06_consumer_transfer.json"))

    def test_run_validation_collections_waits_for_contract_agreement_after_collection_05(self):
        executor = NewmanExecutor()

        def fake_run_newman(path, env, report_path=None, environment_path=None):
            if path.endswith("04_consumer_catalog.json"):
                executor._write_environment_values(
                    environment_path,
                    {
                        "e2e_offer_policy_id": "offer-123",
                        "e2e_catalog_asset_id": "asset-123",
                    },
                )
            return report_path

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                executor,
                "run_newman",
                side_effect=fake_run_newman,
            ) as mock_run, mock.patch.object(
                executor,
                "_should_wait_for_contract_agreement",
                return_value=True,
            ), mock.patch.object(
                executor,
                "wait_for_contract_agreement",
                return_value="agreement-123",
            ) as mock_wait:
                reports = executor.run_validation_collections({"provider": "conn-a"}, report_dir=tmpdir)

        self.assertEqual(len(reports), 6)
        self.assertTrue(mock_run.call_args_list[4].args[0].endswith("05_consumer_negotiation.json"))
        mock_wait.assert_called_once()
        self.assertTrue(mock_wait.call_args.args[0].endswith("environment.json"))

    def test_detects_recoverable_dsp_negotiation_failure_from_report(self):
        executor = NewmanExecutor()
        report = {
            "run": {
                "failures": [
                    {
                        "source": {"name": "Check Negotiation Status"},
                        "error": {
                            "name": "AssertionError",
                            "test": "Negotiation did not end in a terminated state",
                            "message": (
                                "Negotiation neg-1 reached TERMINATED state; "
                                "consumer-side errorDetail is empty"
                            ),
                        },
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "05_consumer_negotiation.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f)

            detail = executor._newman_negotiation_failure_detail(report_path)

        self.assertIn("TERMINATED", detail)
        self.assertIn("Check Negotiation Status", detail)

    @mock.patch("framework.newman_executor.time.sleep", return_value=None)
    def test_run_validation_collections_recovers_dsp_negotiation_failure_once(self, mock_sleep):
        executor = NewmanExecutor()
        executed = []

        def write_report(report_path, failures=None):
            if not report_path:
                return
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "collection": {
                            "info": {
                                "name": os.path.splitext(os.path.basename(report_path))[0]
                            }
                        },
                        "run": {
                            "failures": failures or [],
                            "executions": [],
                        },
                    },
                    f,
                )

        def fake_run_newman(path, env, report_path=None, environment_path=None):
            executed.append((os.path.basename(path), os.path.basename(report_path or "")))
            recovery = bool(report_path and "_recovery_02" in report_path)
            if path.endswith("04_consumer_catalog.json"):
                executor._write_environment_values(
                    environment_path,
                    {
                        "e2e_offer_policy_id": "offer-recovery" if recovery else "offer-initial",
                        "e2e_catalog_asset_id": "asset-recovery" if recovery else "asset-initial",
                    },
                )
            if path.endswith("05_consumer_negotiation.json"):
                executor._write_environment_values(
                    environment_path,
                    {
                        "e2e_negotiation_id": "neg-recovery" if recovery else "neg-initial",
                        "e2e_agreement_id": "",
                    },
                )
                failures = [] if recovery else [
                    {
                        "source": {"name": "Check Negotiation Status"},
                        "error": {
                            "name": "AssertionError",
                            "test": "Negotiation did not end in a terminated state",
                            "message": "Negotiation neg-initial reached TERMINATED state",
                        },
                    }
                ]
                write_report(report_path, failures=failures)
                return report_path
            write_report(report_path)
            return report_path

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                executor,
                "run_newman",
                side_effect=fake_run_newman,
            ), mock.patch.object(
                executor,
                "wait_for_contract_agreement",
                side_effect=[
                    RuntimeError("Timed out waiting for contractAgreementId before transfer"),
                    "agreement-recovered",
                ],
            ) as mock_wait, mock.patch.dict(os.environ, {
                "PIONERA_NEWMAN_DSP_NEGOTIATION_RECOVERY_DELAY_SECONDS": "0",
            }):
                reports = executor.run_validation_collections(
                    {"provider": "conn-a"},
                    report_dir=tmpdir,
                )
                archived_report_path = os.path.join(tmpdir, "05_consumer_negotiation.json.recovered")
                self.assertTrue(os.path.exists(archived_report_path))

        executed_names = [item[0] for item in executed]
        report_names = [item[1] for item in executed]
        self.assertEqual(executed_names.count("04_consumer_catalog.json"), 2)
        self.assertEqual(executed_names.count("05_consumer_negotiation.json"), 2)
        self.assertIn("04_consumer_catalog_recovery_02.json", report_names)
        self.assertIn("05_consumer_negotiation_recovery_02.json", report_names)
        self.assertNotIn("05_consumer_negotiation.json", [os.path.basename(path) for path in reports])
        self.assertTrue(reports[-1].endswith("06_consumer_transfer.json"))
        self.assertEqual(mock_wait.call_count, 2)
        mock_sleep.assert_called_once_with(0.0)

    def test_run_validation_collections_stops_when_catalog_vars_are_missing(self):
        executor = NewmanExecutor()

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                executor,
                "run_newman",
                side_effect=lambda path, env, report_path=None, environment_path=None: report_path,
            ) as mock_run:
                with self.assertRaisesRegex(RuntimeError, "e2e_offer_policy_id, e2e_catalog_asset_id"):
                    executor.run_validation_collections({"provider": "conn-a"}, report_dir=tmpdir)

        self.assertEqual(mock_run.call_count, 4)
        self.assertTrue(mock_run.call_args_list[-1].args[0].endswith("04_consumer_catalog.json"))

    @mock.patch("framework.newman_executor.requests.post")
    def test_management_api_preflight_checks_provider_consumer_and_catalog(self, mock_post):
        executor = NewmanExecutor()
        login_response = mock.Mock(status_code=200)
        login_response.json.return_value = {"access_token": "token-123"}
        assets_response = mock.Mock(status_code=200)
        assets_response.json.return_value = []
        negotiations_response = mock.Mock(status_code=200)
        negotiations_response.json.return_value = []
        catalog_response = mock.Mock(status_code=200)
        catalog_response.json.return_value = {"dcat:dataset": []}
        mock_post.side_effect = [
            login_response,
            login_response,
            assets_response,
            negotiations_response,
            catalog_response,
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            diagnostics = executor.run_management_api_preflight(
                {
                    "provider": "conn-a",
                    "consumer": "conn-b",
                    "provider_user": "provider-user",
                    "provider_password": "provider-pass",
                    "consumer_user": "consumer-user",
                    "consumer_password": "consumer-pass",
                    "dsDomain": "example.local",
                    "dataspace": "demo",
                    "keycloakUrl": "http://auth.example.local",
                    "keycloakClientId": "dataspace-users",
                    "providerParticipantId": "conn-a",
                    "providerProtocolAddress": "http://conn-a:19194/protocol",
                },
                report_dir=tmpdir,
            )

            report_path = os.path.join(tmpdir, "00_management_api_preflight.json")
            with open(report_path, "r", encoding="utf-8") as f:
                persisted = json.load(f)

        self.assertEqual(len(diagnostics["checks"]), 5)
        self.assertTrue(all(check["ok"] for check in diagnostics["checks"]))
        self.assertEqual(persisted["provider"], "conn-a")
        self.assertEqual(mock_post.call_count, 5)
        self.assertIn(
            "auth.example.local/realms/demo/protocol/openid-connect/token",
            mock_post.call_args_list[0].args[0],
        )
        self.assertIn(
            "conn-a.example.local/management/v3/assets/request",
            mock_post.call_args_list[2].args[0],
        )
        self.assertIn(
            "conn-b.example.local/management/v3/catalog/request",
            mock_post.call_args_list[4].args[0],
        )

    @mock.patch("framework.newman_executor.requests.post")
    def test_management_api_preflight_refreshes_provider_token_after_authentication_failure(self, mock_post):
        executor = NewmanExecutor()
        provider_login_response = mock.Mock(status_code=200)
        provider_login_response.json.return_value = {"access_token": "provider-token-old"}
        provider_refresh_response = mock.Mock(status_code=200)
        provider_refresh_response.json.return_value = {"access_token": "provider-token-new"}
        consumer_login_response = mock.Mock(status_code=200)
        consumer_login_response.json.return_value = {"access_token": "consumer-token"}
        unauthorized_response = mock.Mock(status_code=401)
        unauthorized_response.text = '[{"message":"Request could not be authenticated","type":"AuthenticationFailed"}]'
        assets_response = mock.Mock(status_code=200)
        assets_response.json.return_value = []
        negotiations_response = mock.Mock(status_code=200)
        negotiations_response.json.return_value = []
        catalog_response = mock.Mock(status_code=200)
        catalog_response.json.return_value = {"dcat:dataset": []}
        mock_post.side_effect = [
            provider_login_response,
            consumer_login_response,
            unauthorized_response,
            provider_refresh_response,
            assets_response,
            negotiations_response,
            catalog_response,
        ]

        diagnostics = executor.run_management_api_preflight(
            {
                "provider": "conn-a",
                "consumer": "conn-b",
                "provider_user": "provider-user",
                "provider_password": "provider-pass",
                "consumer_user": "consumer-user",
                "consumer_password": "consumer-pass",
                "dsDomain": "example.local",
                "dataspace": "demo",
                "keycloakUrl": "http://auth.example.local",
                "keycloakClientId": "dataspace-users",
                "providerParticipantId": "conn-a",
                "providerProtocolAddress": "http://conn-a:19194/protocol",
            },
        )

        self.assertTrue(all(check["ok"] for check in diagnostics["checks"]))
        self.assertEqual(mock_post.call_count, 7)
        first_assets_headers = mock_post.call_args_list[2].kwargs["headers"]
        second_assets_headers = mock_post.call_args_list[4].kwargs["headers"]
        self.assertEqual(first_assets_headers["Authorization"], "Bearer provider-token-old")
        self.assertEqual(second_assets_headers["Authorization"], "Bearer provider-token-new")

    @mock.patch("framework.newman_executor.requests.post")
    def test_management_api_preflight_raises_with_diagnostic_when_management_auth_fails(self, mock_post):
        executor = NewmanExecutor()
        provider_login_response_1 = mock.Mock(status_code=200)
        provider_login_response_1.json.return_value = {"access_token": "provider-token-1"}
        provider_login_response_2 = mock.Mock(status_code=200)
        provider_login_response_2.json.return_value = {"access_token": "provider-token-2"}
        provider_login_response_3 = mock.Mock(status_code=200)
        provider_login_response_3.json.return_value = {"access_token": "provider-token-3"}
        consumer_login_response = mock.Mock(status_code=200)
        consumer_login_response.json.return_value = {"access_token": "consumer-token"}
        unauthorized_response = mock.Mock(status_code=401)
        unauthorized_response.text = '[{"message":"Request could not be authenticated","type":"AuthenticationFailed"}]'
        negotiations_response = mock.Mock(status_code=200)
        negotiations_response.json.return_value = []
        catalog_response = mock.Mock(status_code=200)
        catalog_response.json.return_value = {"dcat:dataset": []}
        mock_post.side_effect = [
            provider_login_response_1,
            consumer_login_response,
            unauthorized_response,
            provider_login_response_2,
            unauthorized_response,
            provider_login_response_3,
            unauthorized_response,
            negotiations_response,
            catalog_response,
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(RuntimeError, "provider-assets-request: provider assets preflight returned HTTP 401"):
                executor.run_management_api_preflight(
                    {
                        "provider": "conn-a",
                        "consumer": "conn-b",
                        "provider_user": "provider-user",
                        "provider_password": "provider-pass",
                        "consumer_user": "consumer-user",
                        "consumer_password": "consumer-pass",
                        "dsDomain": "example.local",
                        "dataspace": "demo",
                        "keycloakUrl": "http://auth.example.local",
                        "keycloakClientId": "dataspace-users",
                        "providerParticipantId": "conn-a",
                        "providerProtocolAddress": "http://conn-a:19194/protocol",
                    },
                    report_dir=tmpdir,
                )

            report_path = os.path.join(tmpdir, "00_management_api_preflight.json")
            with open(report_path, "r", encoding="utf-8") as f:
                persisted = json.load(f)

        failed_checks = [check for check in persisted["checks"] if not check["ok"]]
        self.assertEqual(len(failed_checks), 1)
        self.assertEqual(failed_checks[0]["name"], "provider-assets-request")
        self.assertIn("HTTP 401", failed_checks[0]["detail"])

    def test_environment_health_collection_loads_health_script(self):
        executor = NewmanExecutor()

        script = executor.load_test_scripts("validation/core/collections/01_environment_health.json")

        self.assertIn("Environment health tests", script)
        self.assertIn("Provider Management API Health", script)

    def test_detects_transient_auth_failure_from_newman_report(self):
        executor = NewmanExecutor()
        report = {
            "run": {
                "failures": [
                    {
                        "source": {"name": "Consumer Login"},
                        "error": {
                            "name": "AssertionError",
                            "test": "Response body is valid JSON",
                            "message": "Response body is not valid JSON",
                        },
                    }
                ],
                "executions": [
                    {
                        "item": {"name": "Consumer Login"},
                        "response": {
                            "code": 503,
                            "status": "Service Temporarily Unavailable",
                            "header": [
                                {"key": "Content-Type", "value": "text/html"}
                            ],
                        },
                    }
                ],
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "06_consumer_transfer.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f)

            detail = executor._newman_auth_failure_detail(report_path)

        self.assertIn("Consumer Login returned HTTP 503", detail)
        self.assertIn("text/html", detail)

    def test_detects_transient_management_api_auth_failure_from_newman_report(self):
        executor = NewmanExecutor()
        body = b'[{"message":"Request could not be authenticated","type":"AuthenticationFailed"}]'
        report = {
            "run": {
                "failures": [
                    {
                        "source": {"name": "Consumer Management API Health"},
                        "error": {
                            "name": "AssertionError",
                            "test": "Consumer Management API Health authenticates successfully",
                            "message": "Consumer Management API Health returned HTTP 401",
                        },
                    }
                ],
                "executions": [
                    {
                        "item": {"name": "Consumer Management API Health"},
                        "response": {
                            "code": 401,
                            "status": "Unauthorized",
                            "header": [
                                {"key": "Content-Type", "value": "application/json"}
                            ],
                            "stream": {
                                "type": "Buffer",
                                "data": list(body),
                            },
                        },
                    }
                ],
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "01_environment_health.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f)

            detail = executor._newman_auth_failure_detail(report_path)

        self.assertIn("Consumer Management API Health returned transient HTTP 401", detail)
        self.assertIn("application/json", detail)

    @mock.patch("framework.newman_executor.time.sleep", return_value=None)
    @mock.patch("framework.newman_executor.subprocess.run")
    def test_run_newman_retries_transient_auth_failure(self, mock_run, mock_sleep):
        executor = NewmanExecutor()
        call_count = {"value": 0}

        def write_report(path, failures):
            report = {
                "collection": {"info": {"name": "06 Consumer Transfer"}},
                "run": {
                    "failures": failures,
                    "executions": [
                        {
                            "item": {"name": "Consumer Login"},
                            "response": {
                                "code": 503 if failures else 200,
                                "status": "Service Temporarily Unavailable" if failures else "OK",
                                "header": [
                                    {
                                        "key": "Content-Type",
                                        "value": "text/html" if failures else "application/json",
                                    }
                                ],
                            },
                        }
                    ],
                },
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f)

        def fake_run(cmd, check=False, capture_output=False, text=True):
            call_count["value"] += 1
            report_path = cmd[cmd.index("--reporter-json-export") + 1]
            if call_count["value"] == 1:
                write_report(
                    report_path,
                    [
                        {
                            "source": {"name": "Consumer Login"},
                            "error": {
                                "test": "Response body is valid JSON",
                                "message": "Response body is not valid JSON",
                            },
                        }
                    ],
                )
                return mock.Mock(returncode=1)

            write_report(report_path, [])
            return mock.Mock(returncode=0)

        mock_run.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "06_consumer_transfer.json")
            with mock.patch.object(executor, "ensure_available", return_value=["newman"]), \
                    mock.patch.object(executor, "load_test_scripts", return_value="pm.test('ok')"), \
                    mock.patch.dict(os.environ, {
                        "PIONERA_NEWMAN_TRANSIENT_AUTH_ATTEMPTS": "2",
                        "PIONERA_NEWMAN_TRANSIENT_AUTH_RETRY_DELAY_SECONDS": "0",
                    }):
                returned_path = executor.run_newman(
                    "validation/core/collections/06_consumer_transfer.json",
                    {"provider": "conn-a"},
                    report_path=report_path,
                )

            with open(report_path, "r", encoding="utf-8") as f:
                final_report = json.load(f)

        self.assertEqual(returned_path, report_path)
        self.assertEqual(call_count["value"], 2)
        mock_sleep.assert_called_once_with(0.0)
        self.assertEqual(final_report["run"]["failures"], [])

    @mock.patch("framework.newman_executor.time.sleep", return_value=None)
    @mock.patch("framework.newman_executor.requests.get")
    def test_wait_for_contract_agreement_updates_environment_when_available(self, mock_get, _mock_sleep):
        executor = NewmanExecutor()
        pending_response = mock.Mock(status_code=200)
        pending_response.json.return_value = {"@id": "neg-1", "state": "IN_PROGRESS"}
        ready_response = mock.Mock(status_code=200)
        ready_response.json.return_value = {
            "@id": "neg-1",
            "state": "FINALIZED",
            "contractAgreementId": "agreement-123",
        }
        mock_get.side_effect = [pending_response, ready_response]

        with tempfile.TemporaryDirectory() as tmpdir:
            environment_path = os.path.join(tmpdir, "environment.json")
            executor._write_environment_file(
                {
                    "consumer": "conn-b",
                    "dsDomain": "example.local",
                    "consumer_jwt": "token-123",
                    "e2e_negotiation_id": "neg-1",
                },
                environment_path,
            )

            agreement_id = executor.wait_for_contract_agreement(
                environment_path,
                timeout=1,
                poll_interval=0,
            )
            _, env_values = executor._read_environment_values(environment_path)

        self.assertEqual(agreement_id, "agreement-123")
        self.assertEqual(env_values["e2e_agreement_id"], "agreement-123")
        self.assertTrue(mock_get.call_args_list[0].args[0].endswith("/management/v3/contractnegotiations/neg-1"))

    def test_find_negotiation_does_not_fallback_to_stale_entry_when_id_is_missing(self):
        executor = NewmanExecutor()
        body = [
            {
                "@id": "old-negotiation",
                "state": "FINALIZED",
                "contractAgreementId": "stale-agreement",
            }
        ]

        self.assertIsNone(executor._find_negotiation(body, "new-negotiation"))

    @mock.patch("framework.newman_executor.requests.get")
    def test_wait_for_contract_agreement_raises_when_timeout_expires(self, mock_get):
        executor = NewmanExecutor()
        pending_response = mock.Mock(status_code=200)
        pending_response.json.return_value = {"@id": "neg-1", "state": "IN_PROGRESS"}
        mock_get.return_value = pending_response

        with tempfile.TemporaryDirectory() as tmpdir:
            environment_path = os.path.join(tmpdir, "environment.json")
            executor._write_environment_file(
                {
                    "consumer": "conn-b",
                    "dsDomain": "example.local",
                    "consumer_jwt": "token-123",
                    "e2e_negotiation_id": "neg-1",
                },
                environment_path,
            )

            with self.assertRaisesRegex(RuntimeError, "Timed out waiting for contractAgreementId"):
                executor.wait_for_contract_agreement(
                    environment_path,
                    timeout=0,
                    poll_interval=0,
                )

    @mock.patch("framework.newman_executor.requests.post")
    @mock.patch("framework.newman_executor.requests.get")
    def test_wait_for_contract_agreement_reports_provider_detail_when_terminated(self, mock_get, mock_post):
        executor = NewmanExecutor()
        consumer_response = mock.Mock(status_code=200)
        consumer_response.json.return_value = {"@id": "neg-1", "state": "TERMINATED"}
        provider_response = mock.Mock(status_code=200)
        provider_response.json.return_value = [
            {
                "@id": "provider-neg-1",
                "type": "PROVIDER",
                "state": "TERMINATED",
                "counterPartyId": "conn-b",
                "createdAt": 2,
                "errorDetail": "Failed to send agreement to consumer: 401 Unauthorized",
            }
        ]
        mock_get.return_value = consumer_response
        mock_post.return_value = provider_response

        with tempfile.TemporaryDirectory() as tmpdir:
            environment_path = os.path.join(tmpdir, "environment.json")
            executor._write_environment_file(
                {
                    "provider": "conn-a",
                    "consumer": "conn-b",
                    "dsDomain": "example.local",
                    "provider_jwt": "provider-token",
                    "consumer_jwt": "consumer-token",
                    "e2e_negotiation_id": "neg-1",
                },
                environment_path,
            )

            with self.assertRaisesRegex(RuntimeError, "provider_side=.*401 Unauthorized"):
                executor.wait_for_contract_agreement(
                    environment_path,
                    timeout=1,
                    poll_interval=0,
                )

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(mock_post.call_count, 1)
        self.assertIn(
            "conn-a.example.local/management/v3/contractnegotiations/request",
            mock_post.call_args_list[0].args[0],
        )

    def test_parse_newman_report_extracts_request_metrics(self):
        collector = MetricsCollector()
        report = {
            "collection": {"info": {"name": "03_provider_setup"}},
            "run": {
                "executions": [
                    {
                        "item": {"name": "Create Asset"},
                        "request": {"url": {"raw": "http://example.test/management/v3/assets"}},
                        "response": {"code": 200, "responseTime": 42},
                        "cursor": {"started": "2026-03-07T10:00:00.000Z"}
                    },
                    {
                        "item": {"name": "List Assets"},
                        "request": {"url": {"path": ["management", "v3", "assets", "request"]}},
                        "response": {"code": 400, "responseTime": 17},
                        "cursor": {"started": "2026-03-07T10:00:01.000Z"}
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = os.path.join(tmpdir, "run_003")
            os.makedirs(run_dir, exist_ok=True)
            report_path = os.path.join(run_dir, "03_provider_setup.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f)

            metrics = collector.parse_newman_report(report_path)

        self.assertEqual(metrics, [
            {
                "timestamp": "2026-03-07T10:00:00.000Z",
                "endpoint": "http://example.test/management/v3/assets",
                "method": None,
                "status_code": 200,
                "latency_ms": 42,
                "iteration": 3,
                "run_index": 3,
                "run": 3,
                "request_name": "Create Asset",
                "request": "Create Asset",
                "collection": "03_provider_setup",
                "response_time_ms": 42,
                "experiment_id": None,
            },
            {
                "timestamp": "2026-03-07T10:00:01.000Z",
                "endpoint": "/management/v3/assets/request",
                "method": None,
                "status_code": 400,
                "latency_ms": 17,
                "iteration": 3,
                "run_index": 3,
                "run": 3,
                "request_name": "List Assets",
                "request": "List Assets",
                "collection": "03_provider_setup",
                "response_time_ms": 17,
                "experiment_id": None,
            }
        ])

    def test_collect_newman_request_metrics_aggregates_directory_and_saves(self):
        collector = MetricsCollector(experiment_storage=ExperimentStorage)
        sample_report = {
            "collection": {"info": {"name": "01_environment_health"}},
            "run": {
                "executions": [
                    {
                        "item": {"name": "Health"},
                        "request": {"url": {"raw": "http://example.test/health"}},
                        "response": {"code": 200, "responseTime": 11},
                        "cursor": {"started": "2026-03-07T10:00:00.000Z"}
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = ExperimentStorage.newman_reports_dir(tmpdir)
            run_dir = os.path.join(report_dir, "run_001")
            pair_dir = os.path.join(run_dir, "conn-a__conn-b")
            os.makedirs(pair_dir, exist_ok=True)
            report_path = os.path.join(pair_dir, "01_environment_health.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(sample_report, f)

            metrics = collector.collect_newman_request_metrics(report_dir, experiment_dir=tmpdir)
            raw_path = os.path.join(tmpdir, "raw_requests.jsonl")
            aggregated_path = os.path.join(tmpdir, "aggregated_metrics.json")

            self.assertTrue(os.path.exists(raw_path))
            self.assertTrue(os.path.exists(aggregated_path))

            with open(raw_path, "r", encoding="utf-8") as f:
                raw_lines = [line.rstrip("\n") for line in f]
            with open(aggregated_path, "r", encoding="utf-8") as f:
                aggregated = json.load(f)

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["request_name"], "Health")
        self.assertEqual(metrics[0]["run_index"], 1)
        self.assertEqual(len(raw_lines), 1)
        self.assertEqual(json.loads(raw_lines[0])["request_name"], "Health")
        self.assertIn("request_metrics", aggregated)
        self.assertIn("http://example.test/health", aggregated["request_metrics"])
        self.assertEqual(aggregated["request_metrics"]["http://example.test/health"]["count"], 1)

    def test_graph_builder_generates_expected_graph_files(self):
        builder = GraphBuilder()
        aggregated_metrics = {
            "Create Asset": {
                "count": 3,
                "average_latency_ms": 45.0,
                "min_latency_ms": 38.0,
                "max_latency_ms": 55.0,
                "p50_latency_ms": 42.0,
                "p95_latency_ms": 53.7,
                "p99_latency_ms": 54.74,
            },
            "List Assets": {
                "count": 2,
                "average_latency_ms": 11.0,
                "min_latency_ms": 10.0,
                "max_latency_ms": 12.0,
                "p50_latency_ms": 11.0,
                "p95_latency_ms": 11.9,
                "p99_latency_ms": 11.98,
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ExperimentStorage.save_aggregated_metrics(aggregated_metrics, tmpdir)
            ExperimentStorage.save_raw_request_metrics_jsonl([
                {"request_name": "Create Asset", "endpoint": "/management/v3/assets", "latency_ms": 42, "iteration": 1},
                {"request_name": "Create Asset", "endpoint": "/management/v3/assets", "latency_ms": 38, "iteration": 1},
                {"request_name": "List Assets", "endpoint": "/management/v3/assets/request", "latency_ms": 12, "iteration": 2},
            ], tmpdir)
            graph_paths = builder.build(tmpdir)

            self.assertEqual(set(graph_paths.keys()), {
                "latency_boxplot",
                "latency_histogram",
                "endpoint_latency_bar",
                "latency_over_iterations",
            })
            for path in graph_paths.values():
                self.assertTrue(os.path.exists(path))
                self.assertIn(f"{os.sep}graphs{os.sep}", path)
                self.assertGreater(os.path.getsize(path), 0)

    def test_graph_builder_generates_optional_kafka_graphs(self):
        builder = GraphBuilder()

        with tempfile.TemporaryDirectory() as tmpdir:
            ExperimentStorage.save_aggregated_metrics({
                "Create Asset": {
                    "count": 1,
                    "average_latency_ms": 10.0,
                    "min_latency_ms": 10.0,
                    "max_latency_ms": 10.0,
                    "p50_latency_ms": 10.0,
                    "p95_latency_ms": 10.0,
                    "p99_latency_ms": 10.0,
                }
            }, tmpdir)
            ExperimentStorage.save_kafka_metrics_json({
                "broker_source": "auto-provisioned",
                "runs": [
                    {"kafka_benchmark": {"status": "completed", "run_index": 1, "average_latency_ms": 6.5, "p50_latency_ms": 5.0, "p95_latency_ms": 7.0, "p99_latency_ms": 9.0, "throughput_messages_per_second": 100.0}},
                    {"kafka_benchmark": {"status": "skipped", "run_index": 99, "reason": "ignored"}},
                    {"kafka_benchmark": {"status": "completed", "run_index": 2, "average_latency_ms": 7.5, "p50_latency_ms": 6.0, "p95_latency_ms": 8.0, "p99_latency_ms": 10.0, "throughput_messages_per_second": 120.0}},
                ]
            }, tmpdir)

            graph_paths = builder.build(tmpdir)

            self.assertIn("kafka_latency_histogram", graph_paths)
            self.assertIn("kafka_throughput_bar", graph_paths)
            self.assertIn("kafka_latency_percentiles", graph_paths)
            self.assertTrue(os.path.exists(graph_paths["kafka_latency_histogram"]))
            self.assertTrue(os.path.exists(graph_paths["kafka_throughput_bar"]))
            self.assertTrue(os.path.exists(graph_paths["kafka_latency_percentiles"]))

    def test_graph_builder_skips_when_aggregated_metrics_missing(self):
        builder = GraphBuilder()

        with tempfile.TemporaryDirectory() as tmpdir:
            graph_paths = builder.build(tmpdir)

        self.assertEqual(graph_paths, {})

    def test_experiment_runner_invokes_graph_builder_after_completion(self):
        class FakeAdapter:
            def deploy_infrastructure(self):
                return None
            def deploy_dataspace(self):
                return None
            def deploy_connectors(self):
                return ["conn-a", "conn-b"]

        class FakeValidationEngine:
            def run(self, connectors, experiment_dir=None, run_index=None):
                return [{"report": "ok", "run_index": run_index}]

        class FakeMetricsCollector:
            def collect(self, connectors, experiment_dir=None, run_index=None):
                return [{"source": connectors[0], "target": connectors[1], "run_index": run_index}]
            def collect_newman_request_metrics(self, report_dir, experiment_dir=None):
                ExperimentStorage.save_aggregated_metrics({
                    "Health": {
                        "count": 1,
                        "average_latency_ms": 11.0,
                        "min_latency_ms": 11.0,
                        "max_latency_ms": 11.0,
                        "p50_latency_ms": 11.0,
                        "p95_latency_ms": 11.0,
                        "p99_latency_ms": 11.0,
                    }
                }, experiment_dir)
                return [{"request_name": "Health", "run_index": 1, "latency_ms": 11}]

        class FakeGraphBuilder:
            def __init__(self):
                self.called_with = None
            def build(self, experiment_dir):
                self.called_with = experiment_dir
                graphs_dir = os.path.join(experiment_dir, "graphs")
                os.makedirs(graphs_dir, exist_ok=True)
                output = os.path.join(graphs_dir, "request_latency_avg.png")
                with open(output, "wb") as f:
                    f.write(b"fake-png")
                return {"request_latency_avg": output}

        graph_builder = FakeGraphBuilder()
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=FakeAdapter(),
                    validation_engine=FakeValidationEngine(),
                    metrics_collector=FakeMetricsCollector(),
                    experiment_storage=ExperimentStorage,
                    graph_builder=graph_builder,
                )
                result = runner.run()

        self.assertEqual(graph_builder.called_with, result["experiment_dir"])
        self.assertIn("graphs", result)
        self.assertIn("request_latency_avg", result["graphs"])
        self.assertTrue(result["graphs"]["request_latency_avg"].endswith("request_latency_avg.png"))

    def test_experiment_runner_continues_when_graph_generation_fails(self):
        class FakeAdapter:
            def deploy_infrastructure(self):
                return None
            def deploy_dataspace(self):
                return None
            def deploy_connectors(self):
                return ["conn-a", "conn-b"]

        class FakeValidationEngine:
            def run(self, connectors, experiment_dir=None, run_index=None):
                return []

        class FakeMetricsCollector:
            def collect(self, connectors, experiment_dir=None, run_index=None):
                return []
            def collect_newman_request_metrics(self, report_dir, experiment_dir=None):
                ExperimentStorage.save_aggregated_metrics({
                    "Health": {
                        "count": 1,
                        "average_latency_ms": 11.0,
                        "min_latency_ms": 11.0,
                        "max_latency_ms": 11.0,
                        "p50_latency_ms": 11.0,
                        "p95_latency_ms": 11.0,
                        "p99_latency_ms": 11.0,
                    }
                }, experiment_dir)
                return []

        class FailingGraphBuilder:
            def build(self, experiment_dir):
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=FakeAdapter(),
                    validation_engine=FakeValidationEngine(),
                    metrics_collector=FakeMetricsCollector(),
                    experiment_storage=ExperimentStorage,
                    graph_builder=FailingGraphBuilder(),
                )
                result = runner.run()

        self.assertEqual(result["graphs"], {})

    def test_aggregate_newman_request_metrics_groups_and_computes_percentiles(self):
        collector = MetricsCollector()
        metrics = [
            {"request": "Create Asset", "latency_ms": 42},
            {"request": "Create Asset", "latency_ms": 38},
            {"request": "Create Asset", "latency_ms": 55},
            {"request": "List Assets", "latency_ms": 10},
            {"request": "List Assets", "latency_ms": 12},
        ]

        aggregated = collector.aggregate_newman_request_metrics(metrics)

        self.assertEqual(aggregated["Create Asset"]["count"], 3)
        self.assertEqual(aggregated["Create Asset"]["average_latency_ms"], 45.0)
        self.assertEqual(aggregated["Create Asset"]["min_latency_ms"], 38.0)
        self.assertEqual(aggregated["Create Asset"]["max_latency_ms"], 55.0)
        self.assertEqual(aggregated["Create Asset"]["p50_latency_ms"], 42.0)
        self.assertEqual(aggregated["List Assets"]["count"], 2)
        self.assertEqual(aggregated["List Assets"]["p50_latency_ms"], 11.0)
        self.assertGreaterEqual(
            aggregated["Create Asset"]["p99_latency_ms"],
            aggregated["Create Asset"]["p95_latency_ms"],
        )

    def test_aggregate_newman_request_metrics_handles_single_sample(self):
        collector = MetricsCollector()
        aggregated = collector.aggregate_newman_request_metrics([
            {"request_name": "Create Asset", "latency_ms": 42}
        ])

        self.assertEqual(aggregated, {
            "Create Asset": {
                "count": 1,
                "request_count": 1,
                "error_rate": 0.0,
                "mean_latency": 42.0,
                "average_latency_ms": 42.0,
                "min_latency_ms": 42.0,
                "max_latency_ms": 42.0,
                "p50": 42.0,
                "p95": 42.0,
                "p99": 42.0,
                "p50_latency_ms": 42.0,
                "p95_latency_ms": 42.0,
                "p99_latency_ms": 42.0,
                "methods": [],
            }
        })

    def test_aggregate_newman_request_metrics_ignores_invalid_entries(self):
        collector = MetricsCollector()
        aggregated = collector.aggregate_newman_request_metrics([
            {"request_name": "Create Asset", "latency_ms": 42},
            {"request_name": "Create Asset", "latency_ms": None},
            {"request_name": "Create Asset", "latency_ms": "bad"},
            {"latency_ms": 10},
        ])

        self.assertEqual(aggregated["Create Asset"]["count"], 1)
        self.assertEqual(len(aggregated), 1)

    def test_validation_engine_passes_experiment_dir_to_executor(self):
        fake_executor = mock.Mock()
        fake_executor.run_validation_collections.return_value = ["report.json"]
        engine = ValidationEngine(
            newman_executor=fake_executor,
            load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak-admin.local",
                "KC_INTERNAL_URL": "http://keycloak.local",
            },
            cleanup_test_entities=lambda connector: None,
            validation_test_entities_absent=lambda connector: (True, []),
            ds_domain_resolver=lambda: "example.local",
            ds_name="demo",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            reports = engine.run(["conn-a", "conn-b"], experiment_dir=tmpdir)

        self.assertEqual(reports, ["report.json", "report.json"])
        self.assertEqual(fake_executor.run_validation_collections.call_count, 2)
        env_vars = fake_executor.run_validation_collections.call_args.args[0]
        self.assertEqual(env_vars["keycloakUrl"], "http://keycloak.local")
        self.assertEqual(env_vars["keycloakClientId"], "dataspace-users")
        self.assertIn(engine._safe_scope_part(os.path.basename(tmpdir)), env_vars["e2e_run_scope"])
        self.assertIn("conn-b", env_vars["e2e_run_scope"])
        self.assertIn("conn-a", env_vars["e2e_run_scope"])
        report_dir = fake_executor.run_validation_collections.call_args.kwargs["report_dir"]
        self.assertIn("newman_reports", report_dir)

    def test_validation_engine_runs_management_preflight_before_collections(self):
        executor = NewmanExecutor()
        with mock.patch.object(
            executor,
            "run_management_api_preflight",
            return_value={"checks": []},
        ) as preflight_mock, mock.patch.object(
            executor,
            "run_validation_collections",
            return_value=["report.json"],
        ) as run_mock:
            engine = ValidationEngine(
                newman_executor=executor,
                load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
                load_deployer_config=lambda: {
                    "KC_URL": "http://keycloak-admin.local",
                    "KC_INTERNAL_URL": "http://keycloak.local",
                },
                cleanup_test_entities=lambda connector: None,
                validation_test_entities_absent=lambda connector: (True, []),
                ds_domain_resolver=lambda: "example.local",
                ds_name="demo",
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                reports = engine.run_dataspace_validation(
                    "conn-a",
                    "conn-b",
                    experiment_dir=tmpdir,
                    run_index=1,
                )

        self.assertEqual(reports, ["report.json"])
        preflight_mock.assert_called_once()
        run_mock.assert_called_once()
        self.assertEqual(preflight_mock.call_args.args[0]["provider"], "conn-a")
        self.assertEqual(preflight_mock.call_args.args[0]["consumer"], "conn-b")

    def test_provider_setup_collection_uses_dynamic_transfer_object_name(self):
        with open("validation/core/collections/03_provider_setup.json", "r", encoding="utf-8") as handle:
            collection = json.load(handle)

        create_asset = next(
            item for item in collection["item"]
            if item["name"] == "Create E2E Asset"
        )
        raw_body = create_asset["request"]["body"]["raw"]

        self.assertIn('"name": "{{e2e_source_object_name}}"', raw_body)
        self.assertIn('"sourceObjectName": "{{e2e_source_object_name}}"', raw_body)

    def test_validation_engine_sets_default_negotiation_retry_budget(self):
        engine = ValidationEngine(
            load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak-admin.local",
                "KC_INTERNAL_URL": "http://keycloak.local",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name="demo",
        )

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_NEWMAN_NEGOTIATION_START_MAX_ATTEMPTS": "",
                "PIONERA_NEWMAN_NEGOTIATION_STATUS_MAX_ATTEMPTS": "",
            },
        ):
            env_vars = engine.build_newman_env("conn-a", "conn-b")

        self.assertEqual(env_vars["e2e_negotiation_start_max_attempts"], "30")
        self.assertEqual(env_vars["e2e_negotiation_status_max_attempts"], "10")

    def test_validation_engine_allows_negotiation_retry_budget_override(self):
        engine = ValidationEngine(
            load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak-admin.local",
                "KC_INTERNAL_URL": "http://keycloak.local",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name="demo",
        )

        with mock.patch.dict(
            os.environ,
            {
                "PIONERA_NEWMAN_NEGOTIATION_START_MAX_ATTEMPTS": "12",
                "PIONERA_NEWMAN_NEGOTIATION_STATUS_MAX_ATTEMPTS": "7",
            },
        ):
            env_vars = engine.build_newman_env("conn-a", "conn-b")

        self.assertEqual(env_vars["e2e_negotiation_start_max_attempts"], "12")
        self.assertEqual(env_vars["e2e_negotiation_status_max_attempts"], "7")

    def test_negotiation_script_defaults_allow_longer_connector_warmup(self):
        with open("validation/core/tests/negotiation_tests.js", "r", encoding="utf-8") as handle:
            script = handle.read()

        self.assertIn("const DEFAULT_NEGOTIATION_START_MAX_ATTEMPTS = 30", script)
        self.assertIn("const DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS = 10", script)

    def test_validation_engine_uses_neutral_edc_transfer_contract(self):
        engine = ValidationEngine(
            load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak-admin.local",
                "KC_INTERNAL_URL": "http://keycloak.local",
                "PIONERA_ADAPTER": "edc",
                "ENVIRONMENT": "DEV",
                "MINIO_HOSTNAME": "minio.example.local",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name="demoedc",
        )

        env_vars = engine.build_newman_env("conn-citycounciledc-demoedc", "conn-companyedc-demoedc")

        self.assertEqual(env_vars["adapter"], "edc")
        self.assertEqual(env_vars["transferStartPath"], "transferprocesses")
        self.assertEqual(env_vars["transferRequestType"], "TransferRequestDto")
        self.assertEqual(env_vars["transferType"], "AmazonS3-PUSH")
        self.assertEqual(env_vars["transferDestinationType"], "AmazonS3")
        self.assertEqual(env_vars["transferDestinationBucket"], "demoedc-conn-companyedc-demoedc")
        self.assertEqual(env_vars["transferDestinationRegion"], "eu-central-1")
        self.assertEqual(env_vars["transferDestinationEndpointOverride"], "http://minio.example.local")

    def test_validation_engine_keeps_edc_http_pull_fallback_when_configured(self):
        engine = ValidationEngine(
            load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak-admin.local",
                "KC_INTERNAL_URL": "http://keycloak.local",
                "PIONERA_ADAPTER": "edc",
                "EDC_LEVEL6_TRANSFER_MODE": "http-pull",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name="demoedc",
        )

        env_vars = engine.build_newman_env("conn-citycounciledc-demoedc", "conn-companyedc-demoedc")

        self.assertEqual(env_vars["transferType"], "HttpData-PULL")
        self.assertEqual(env_vars["transferDestinationType"], "HttpData")
        self.assertNotIn("transferDestinationBucket", env_vars)

    def test_postman_compact_collection_builds_adapter_aware_transfer_body(self):
        with open("validation/core/collections/postman/03_e2e_compact.json", "r", encoding="utf-8") as handle:
            collection = json.load(handle)

        start_transfer = next(item for item in collection["item"] if item["name"] == "Start Transfer Process")
        start_prerequest = "\n".join(
            line
            for event in start_transfer["event"]
            if event["listen"] == "prerequest"
            for line in event["script"]["exec"]
        )
        self.assertEqual(start_transfer["request"]["body"]["raw"], "{{transferRequestBody}}")
        self.assertIn('if (adapter === "edc")', start_prerequest)
        self.assertIn('getVar("transferRequestType", "TransferRequestDto")', start_prerequest)
        self.assertIn('bucketName: nonEmptyVar("transferDestinationBucket")', start_prerequest)

        resolve_destination = next(
            item for item in collection["item"] if item["name"] == "Resolve Current Transfer Destination"
        )
        resolve_tests = "\n".join(
            line
            for event in resolve_destination["event"]
            if event["listen"] == "test"
            for line in event["script"]["exec"]
        )
        self.assertIn('parseStoredJson("e2e_transfer_request_destination")', resolve_tests)
        self.assertIn('String(requestedDestinationType).toLowerCase() === "inesdatastore"', resolve_tests)

    def test_validation_engine_uses_protocol_address_resolver_when_available(self):
        engine = ValidationEngine(
            load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak-admin.local",
                "KC_INTERNAL_URL": "http://keycloak.local",
                "PIONERA_ADAPTER": "edc",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name="roleedcprove",
            protocol_address_resolver=lambda connector: (
                f"http://{connector}.roleedcprove-provider.svc.cluster.local:19194/protocol"
            ),
        )

        env_vars = engine.build_newman_env("conn-cityproof-roleedcprove", "conn-companyproof-roleedcprove")

        self.assertEqual(
            env_vars["providerProtocolAddress"],
            "http://conn-cityproof-roleedcprove.roleedcprove-provider.svc.cluster.local:19194/protocol",
        )
        self.assertEqual(
            env_vars["consumerProtocolAddress"],
            "http://conn-companyproof-roleedcprove.roleedcprove-provider.svc.cluster.local:19194/protocol",
        )

    def test_validation_engine_collects_transfer_storage_checks(self):
        fake_executor = mock.Mock()
        fake_executor.run_validation_collections.return_value = ["report.json"]
        fake_verifier = mock.Mock()
        fake_verifier.capture_consumer_bucket_snapshot.return_value = {}
        fake_verifier.verify_consumer_transfer_persistence.return_value = {
            "status": "passed",
            "bucket_name": "demo-conn-b",
        }
        engine = ValidationEngine(
            newman_executor=fake_executor,
            load_connector_credentials=lambda name: {"connector_user": {"user": name, "passwd": "secret"}},
            load_deployer_config=lambda: {
                "KC_URL": "http://keycloak-admin.local",
                "KC_INTERNAL_URL": "http://keycloak.local",
            },
            cleanup_test_entities=lambda connector: None,
            validation_test_entities_absent=lambda connector: (True, []),
            ds_domain_resolver=lambda: "example.local",
            ds_name="demo",
            transfer_storage_verifier=fake_verifier,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            reports = engine.run(["conn-a", "conn-b"], experiment_dir=tmpdir)

        self.assertEqual(reports, ["report.json", "report.json"])
        self.assertEqual(len(engine.last_storage_checks), 2)
        fake_verifier.capture_consumer_bucket_snapshot.assert_any_call("conn-b", "demo-conn-b")
        fake_verifier.capture_consumer_bucket_snapshot.assert_any_call("conn-a", "demo-conn-a")
        self.assertEqual(fake_verifier.verify_consumer_transfer_persistence.call_count, 2)

    def test_experiment_runner_bundles_newman_request_metrics(self):
        class FakeAdapter:
            def deploy_infrastructure(self):
                return None
            def deploy_dataspace(self):
                return None
            def deploy_connectors(self):
                return ["conn-a", "conn-b"]

        class FakeValidationEngine:
            def run(self, connectors, experiment_dir=None, run_index=None):
                report_dir = os.path.join(
                    ExperimentStorage.newman_reports_dir(experiment_dir),
                    f"run_{run_index:03d}",
                )
                sample_report = {
                    "collection": {"info": {"name": "01_environment_health"}},
                    "run": {"executions": []}
                }
                os.makedirs(report_dir, exist_ok=True)
                report_path = os.path.join(report_dir, "01_environment_health.json")
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump(sample_report, f)
                return [report_path]

        class FakeMetricsCollector:
            def __init__(self):
                self.collect_calls = []
            def collect(self, connectors, experiment_dir=None, run_index=None):
                self.collect_calls.append(run_index)
                return [{"source": connectors[0], "target": connectors[1], "run_index": run_index}]
            def collect_newman_request_metrics(self, report_dir, experiment_dir=None):
                return [
                    {"run_index": 1, "request_name": "Health", "collection": "01_environment_health", "status_code": 200, "response_time_ms": 11, "timestamp": None, "endpoint": "/health"},
                    {"run_index": 2, "request_name": "Health", "collection": "01_environment_health", "status_code": 200, "response_time_ms": 12, "timestamp": None, "endpoint": "/health"},
                ]

        metrics_collector = FakeMetricsCollector()
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(ExperimentStorage, "create_experiment_directory", return_value=tmpdir):
                runner = ExperimentRunner(
                    adapter=FakeAdapter(),
                    validation_engine=FakeValidationEngine(),
                    metrics_collector=metrics_collector,
                    experiment_storage=ExperimentStorage,
                    iterations=2,
                )
                result = runner.run()

        self.assertEqual(result["iterations"], 2)
        self.assertEqual(metrics_collector.collect_calls, [1, 2])
        self.assertEqual(result["newman_request_metrics"][0]["run_index"], 1)
        self.assertEqual(result["newman_request_metrics"][1]["run_index"], 2)
        self.assertEqual(len(result["validation"]), 2)


if __name__ == "__main__":
    unittest.main()

