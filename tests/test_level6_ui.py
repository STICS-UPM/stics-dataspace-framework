import os
import tempfile
import unittest
from unittest import mock

from validation.orchestration import ui


class Level6UiTests(unittest.TestCase):
    def test_run_ui_smoke_builds_playwright_command_and_artifacts(self):
        subprocess_module = mock.Mock()
        subprocess_module.run.return_value = mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ui.run_ui_smoke(
                "/tmp/ui",
                "conn-a",
                "https://conn-a.example.local",
                "portal-user",
                "portal-pass",
                tmpdir,
                subprocess_module=subprocess_module,
                enrich_result=lambda payload: payload,
                environment={"BASE": "1"},
                extra_args=["--headed"],
                extra_env={"PWDEBUG": "0"},
            )

            command = subprocess_module.run.call_args.args[0]
            env = subprocess_module.run.call_args.kwargs["env"]
            self.assertEqual(command[:3], ["npx", "playwright", "test"])
            self.assertEqual(command[3:5], list(ui.LEVEL6_UI_SMOKE_SPECS))
            self.assertEqual(command[-1], "--headed")
            self.assertEqual(env["PORTAL_BASE_URL"], "https://conn-a.example.local")
            self.assertEqual(env["PORTAL_USER"], "portal-user")
            self.assertEqual(env["PORTAL_PASSWORD"], "portal-pass")
            self.assertEqual(env["PWDEBUG"], "0")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS"], "150")
            self.assertEqual(result["status"], "passed")
            self.assertTrue(os.path.isdir(os.path.join(tmpdir, "ui", "conn-a", "test-results")))
            self.assertEqual(
                result["artifacts"]["report_json"],
                os.path.join(tmpdir, "ui", "conn-a", "ui_core_validation.json"),
            )

    def test_run_ui_dataspace_defaults_upload_size_and_runs_serially(self):
        subprocess_module = mock.Mock()
        subprocess_module.run.return_value = mock.Mock(returncode=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ui.run_ui_dataspace(
                "/tmp/ui",
                "conn-a",
                "conn-b",
                tmpdir,
                subprocess_module=subprocess_module,
                enrich_result=lambda payload: payload,
                environment={},
            )

            command = subprocess_module.run.call_args.args[0]
            env = subprocess_module.run.call_args.kwargs["env"]
            self.assertEqual(command[3], "--workers=1")
            self.assertEqual(command[4:], list(ui.LEVEL6_UI_DATASPACE_SPECS))
            self.assertEqual(env["UI_PROVIDER_CONNECTOR"], "conn-a")
            self.assertEqual(env["UI_CONSUMER_CONNECTOR"], "conn-b")
            self.assertEqual(env["PORTAL_TEST_FILE_MB"], "10")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS"], "150")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["exit_code"], 1)

    def test_run_ui_dataspace_respects_disabled_interaction_markers(self):
        subprocess_module = mock.Mock()
        subprocess_module.run.return_value = mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            ui.run_ui_dataspace(
                "/tmp/ui",
                "conn-a",
                "conn-b",
                tmpdir,
                subprocess_module=subprocess_module,
                enrich_result=lambda payload: payload,
                environment={},
                extra_env={"PLAYWRIGHT_INTERACTION_MARKERS": "0"},
            )

            env = subprocess_module.run.call_args.kwargs["env"]
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "0")

    def test_run_ui_ops_marks_missing_playwright_as_skipped(self):
        subprocess_module = mock.Mock()
        subprocess_module.run.side_effect = FileNotFoundError("npx not found")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ui.run_ui_ops(
                "/tmp/ui",
                "conn-a",
                "conn-b",
                tmpdir,
                subprocess_module=subprocess_module,
                enrich_result=lambda payload: payload,
                environment={},
            )

            self.assertEqual(result["status"], "skipped")
            self.assertIsNone(result["exit_code"])
            self.assertEqual(result["error"]["type"], "FileNotFoundError")
            self.assertIn("npx not found", result["error"]["message"])
            self.assertEqual(result["specs"], [ui.LEVEL6_UI_OPS_SPEC])
            self.assertEqual(result["playwright_config"], ui.LEVEL6_UI_OPS_CONFIG)

    def test_run_core_ui_tests_orchestrates_smoke_dataspace_and_ops(self):
        mode = {
            "label": "Live",
            "args": ["--headed"],
            "env": {"PWDEBUG": "0"},
        }
        smoke_a = {"test": "ui-core-smoke-conn-a", "status": "passed"}
        smoke_b = {"test": "ui-core-smoke-conn-b", "status": "passed"}
        dataspace = {"test": "ui-core-dataspace", "status": "passed"}
        ops = {"test": "ui-ops-minio-console", "status": "passed"}
        save_interactive_state = mock.Mock(
            return_value={
                "status": "completed",
                "mode": "Live",
                "ui_results": [smoke_a, smoke_b, dataspace, ops],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            run_ui_smoke = mock.Mock(side_effect=[smoke_a, smoke_b])
            run_ui_dataspace = mock.Mock(return_value=dataspace)
            run_ui_ops = mock.Mock(return_value=ops)

            payload = ui.run_core_ui_tests(
                mode,
                ui_test_dir="/tmp/ui",
                ui_test_dir_exists=mock.Mock(return_value=True),
                get_connectors=mock.Mock(return_value=["conn-a", "conn-b"]),
                create_experiment_directory=mock.Mock(return_value=tmpdir),
                load_connector_credentials=mock.Mock(
                    return_value={"connector_user": {"user": "demo", "passwd": "demo"}}
                ),
                build_connector_url=lambda connector: f"http://{connector}.example.local",
                run_ui_smoke=run_ui_smoke,
                run_ui_dataspace=run_ui_dataspace,
                run_ui_ops=run_ui_ops,
                ui_ops_suite_available=mock.Mock(return_value=True),
                save_interactive_state=save_interactive_state,
                environment={},
            )

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(run_ui_smoke.call_count, 2)
            self.assertEqual(run_ui_dataspace.call_count, 1)
            self.assertEqual(run_ui_ops.call_count, 1)
            self.assertEqual(run_ui_smoke.call_args.kwargs["extra_args"], ["--headed"])
            self.assertEqual(run_ui_smoke.call_args.kwargs["extra_env"], {"PWDEBUG": "0"})
            self.assertEqual(run_ui_dataspace.call_args.args[1], "conn-a")
            self.assertEqual(run_ui_dataspace.call_args.args[2], "conn-b")
            self.assertEqual(run_ui_ops.call_args.args[1], "conn-a")
            self.assertEqual(run_ui_ops.call_args.args[2], "conn-b")
            save_interactive_state.assert_called_once_with(
                tmpdir,
                ["conn-a", "conn-b"],
                mode=mode,
                ui_results=[smoke_a, smoke_b, dataspace, ops],
            )

    def test_run_core_ui_tests_returns_none_when_ui_directory_is_missing(self):
        payload = ui.run_core_ui_tests(
            {"label": "Normal"},
            ui_test_dir="/tmp/missing-ui",
            ui_test_dir_exists=mock.Mock(return_value=False),
            get_connectors=mock.Mock(),
            create_experiment_directory=mock.Mock(),
            load_connector_credentials=mock.Mock(),
            build_connector_url=mock.Mock(),
            run_ui_smoke=mock.Mock(),
            run_ui_dataspace=mock.Mock(),
            run_ui_ops=mock.Mock(),
            ui_ops_suite_available=mock.Mock(),
            save_interactive_state=mock.Mock(),
            environment={},
        )

        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
