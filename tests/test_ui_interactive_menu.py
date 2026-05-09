import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from validation.ui import interactive_menu


class FakeInteractiveAdapter:
    def get_cluster_connectors(self):
        return ["conn-a", "conn-b"]

    def load_connector_credentials(self, connector):
        return {
            "connector_user": {
                "user": f"{connector}-user",
                "passwd": "secret",
            }
        }

    def build_connector_url(self, connector):
        return f"http://{connector}.example.test/interface"

    def load_deployer_config(self):
        return {
            "DS_1_NAME": "demo",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
        }


class UiInteractiveMenuTests(unittest.TestCase):
    def test_resolve_ui_mode_rejects_live_without_display_on_linux(self):
        output = io.StringIO()
        with mock.patch.object(interactive_menu.sys, "platform", "linux"), mock.patch.dict(
            interactive_menu.os.environ,
            {
                "SSH_CONNECTION": "198.51.100.10 51000 192.0.2.134 22",
                "USER": "pionera",
            },
            clear=True,
        ), mock.patch("builtins.input", side_effect=["2", "1"]), mock.patch("sys.stdout", output):
            mode = interactive_menu._resolve_ui_mode()

        self.assertEqual(mode, {"label": "normal", "args": [], "env": {}})
        self.assertIn("From Windows, use WSL", output.getvalue())
        self.assertIn("On macOS, install and start XQuartz", output.getvalue())
        self.assertIn("ssh -Y pionera@192.0.2.134", output.getvalue())
        self.assertIn("ssh -Y -J <jump-user>@<jump-host>:<jump-port> pionera@192.0.2.134", output.getvalue())
        self.assertIn("echo $DISPLAY", output.getvalue())
        self.assertIn("cd ~/Validation-Environment", output.getvalue())
        self.assertIn("source .venv/bin/activate", output.getvalue())
        self.assertIn("python3 main.py", output.getvalue())

    def test_resolve_ui_mode_allows_live_when_display_is_available(self):
        with mock.patch.object(interactive_menu.sys, "platform", "linux"), mock.patch.dict(
            interactive_menu.os.environ,
            {"DISPLAY": ":0"},
            clear=True,
        ), mock.patch("builtins.input", side_effect=["2"]):
            mode = interactive_menu._resolve_ui_mode()

        self.assertEqual(mode["label"], "live")
        self.assertEqual(mode["args"], ["--headed"])
        self.assertEqual(mode["env"]["PLAYWRIGHT_HEADED_GPU_FIX"], "1")

    @mock.patch.object(interactive_menu, "_run_ai_model_hub_ui_functional")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_ai_model_hub_ui_tests_interactive_routes_functional(
        self,
        _mock_resolve_mode,
        mock_run_functional,
    ):
        interactive_menu.run_ai_model_hub_ui_tests_interactive()

        mock_run_functional.assert_called_once_with({"label": "Normal", "args": [], "env": {}})

    @mock.patch.object(interactive_menu, "_run_ontology_hub_ui_integration_with_inesdata")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_inesdata_ui_tests_interactive_routes_ontology_hub_integration(
        self,
        _mock_resolve_mode,
        mock_run_ontology_hub_integration,
    ):
        with mock.patch("builtins.input", side_effect=["2"]):
            interactive_menu.run_inesdata_ui_tests_interactive()

        mock_run_ontology_hub_integration.assert_called_once_with({"label": "Normal", "args": [], "env": {}})

    @mock.patch.object(interactive_menu, "_run_ai_model_hub_ui_integration")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_inesdata_ui_tests_interactive_routes_ai_model_hub_integration(
        self,
        _mock_resolve_mode,
        mock_run_ai_model_hub_integration,
    ):
        with mock.patch("builtins.input", side_effect=["3"]):
            interactive_menu.run_inesdata_ui_tests_interactive()

        mock_run_ai_model_hub_integration.assert_called_once_with({"label": "Normal", "args": [], "env": {}})

    @mock.patch.object(interactive_menu, "_run_ai_model_observer_ui_integration")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_inesdata_ui_tests_interactive_routes_ai_model_observer_integration(
        self,
        _mock_resolve_mode,
        mock_run_ai_model_observer_integration,
    ):
        with mock.patch("builtins.input", side_effect=["5"]):
            interactive_menu.run_inesdata_ui_tests_interactive()

        mock_run_ai_model_observer_integration.assert_called_once_with({"label": "Normal", "args": [], "env": {}})

    @mock.patch.object(interactive_menu, "_run_semantic_virtualization_ui_tests")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_semantic_virtualization_ui_tests_interactive_routes_runner(
        self,
        _mock_resolve_mode,
        mock_run_semantic_virtualization_ui,
    ):
        interactive_menu.run_semantic_virtualization_ui_tests_interactive()

        mock_run_semantic_virtualization_ui.assert_called_once_with({"label": "Normal", "args": [], "env": {}})

    @mock.patch.object(interactive_menu, "_run_semantic_virtualization_ui_integration_with_inesdata")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_inesdata_ui_tests_interactive_routes_semantic_virtualization_integration(
        self,
        _mock_resolve_mode,
        mock_run_semantic_virtualization_integration,
    ):
        with mock.patch("builtins.input", side_effect=["4"]):
            interactive_menu.run_inesdata_ui_tests_interactive()

        mock_run_semantic_virtualization_integration.assert_called_once_with({"label": "Normal", "args": [], "env": {}})

    @mock.patch.object(interactive_menu, "_cleanup_playwright_processes")
    @mock.patch.object(interactive_menu.subprocess, "run")
    @mock.patch.object(interactive_menu, "project_root")
    @mock.patch.object(interactive_menu, "_resolve_ai_model_hub_base_url", return_value="http://example.test")
    def test_run_ai_model_hub_ui_functional_uses_absolute_artifact_paths(
        self,
        _mock_resolve_base_url,
        mock_project_root,
        mock_subprocess_run,
        _mock_cleanup,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project_root.return_value = Path(tmpdir)
            mock_subprocess_run.return_value = mock.Mock(returncode=0)

            interactive_menu._run_ai_model_hub_ui_functional({"label": "Normal", "args": [], "env": {}})

            mock_subprocess_run.assert_called_once()
            env = mock_subprocess_run.call_args.kwargs["env"]
            cwd = mock_subprocess_run.call_args.kwargs["cwd"]
            base_experiments_dir = os.path.join(tmpdir, "experiments")

            self.assertEqual(cwd, os.path.join(tmpdir, "validation", "ui"))
            self.assertTrue(env["PLAYWRIGHT_OUTPUT_DIR"].startswith(base_experiments_dir))
            self.assertTrue(env["PLAYWRIGHT_HTML_REPORT_DIR"].startswith(base_experiments_dir))
            self.assertTrue(env["PLAYWRIGHT_BLOB_REPORT_DIR"].startswith(base_experiments_dir))
            self.assertTrue(env["PLAYWRIGHT_JSON_REPORT_FILE"].startswith(base_experiments_dir))
            self.assertTrue(os.path.isdir(env["PLAYWRIGHT_OUTPUT_DIR"]))
            self.assertTrue(os.path.isdir(env["PLAYWRIGHT_HTML_REPORT_DIR"]))
            self.assertTrue(os.path.isdir(env["PLAYWRIGHT_BLOB_REPORT_DIR"]))

    @mock.patch.object(interactive_menu, "_cleanup_playwright_processes")
    @mock.patch.object(interactive_menu.subprocess, "run")
    @mock.patch.object(interactive_menu, "project_root")
    @mock.patch.object(interactive_menu, "_resolve_semantic_virtualization_base_url", return_value="http://semantic.example.test")
    def test_run_semantic_virtualization_ui_tests_uses_absolute_artifact_paths(
        self,
        _mock_resolve_base_url,
        mock_project_root,
        mock_subprocess_run,
        _mock_cleanup,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project_root.return_value = Path(tmpdir)
            mock_subprocess_run.return_value = mock.Mock(returncode=0)

            interactive_menu._run_semantic_virtualization_ui_tests({"label": "Normal", "args": [], "env": {}})

            mock_subprocess_run.assert_called_once()
            env = mock_subprocess_run.call_args.kwargs["env"]
            cwd = mock_subprocess_run.call_args.kwargs["cwd"]
            base_experiments_dir = os.path.join(tmpdir, "experiments")

            self.assertEqual(cwd, os.path.join(tmpdir, "validation", "ui"))
            self.assertEqual(env["SEMANTIC_VIRTUALIZATION_BASE_URL"], "http://semantic.example.test")
            self.assertTrue(env["PLAYWRIGHT_OUTPUT_DIR"].startswith(base_experiments_dir))
            self.assertTrue(env["PLAYWRIGHT_HTML_REPORT_DIR"].startswith(base_experiments_dir))
            self.assertTrue(env["PLAYWRIGHT_BLOB_REPORT_DIR"].startswith(base_experiments_dir))
            self.assertTrue(env["PLAYWRIGHT_JSON_REPORT_FILE"].startswith(base_experiments_dir))
            self.assertTrue(os.path.isdir(env["PLAYWRIGHT_OUTPUT_DIR"]))
            self.assertTrue(os.path.isdir(env["PLAYWRIGHT_HTML_REPORT_DIR"]))
            self.assertTrue(os.path.isdir(env["PLAYWRIGHT_BLOB_REPORT_DIR"]))

    @mock.patch.object(interactive_menu, "_cleanup_playwright_processes")
    @mock.patch.object(interactive_menu.subprocess, "run")
    @mock.patch.object(interactive_menu, "project_root")
    @mock.patch.object(interactive_menu, "_default_inesdata_adapter", return_value=FakeInteractiveAdapter())
    def test_run_ontology_hub_ui_integration_with_inesdata_uses_expected_spec_and_markers(
        self,
        _mock_default_adapter,
        mock_project_root,
        mock_subprocess_run,
        _mock_cleanup,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project_root.return_value = Path(tmpdir)
            mock_subprocess_run.return_value = mock.Mock(returncode=0)

            interactive_menu._run_ontology_hub_ui_integration_with_inesdata(
                {"label": "Normal", "args": [], "env": {}}
            )

            mock_subprocess_run.assert_called_once()
            command = mock_subprocess_run.call_args.args[0]
            env = mock_subprocess_run.call_args.kwargs["env"]

            self.assertIn("core/08-ontology-hub-inesdata-readonly.spec.ts", command)
            self.assertEqual(env["UI_ONTOLOGY_HUB_INESDATA_DEMO"], "1")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
            self.assertTrue(env["PLAYWRIGHT_OUTPUT_DIR"].startswith(os.path.join(tmpdir, "experiments")))
            self.assertIn(os.path.join("components", "ontology-hub", "inesdata-ui"), env["PLAYWRIGHT_OUTPUT_DIR"])

    @mock.patch.object(interactive_menu, "_cleanup_playwright_processes")
    @mock.patch.object(interactive_menu.subprocess, "run")
    @mock.patch.object(interactive_menu, "project_root")
    @mock.patch.object(interactive_menu, "_default_inesdata_adapter", return_value=FakeInteractiveAdapter())
    def test_run_semantic_virtualization_ui_integration_with_inesdata_uses_expected_spec_and_markers(
        self,
        _mock_default_adapter,
        mock_project_root,
        mock_subprocess_run,
        _mock_cleanup,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project_root.return_value = Path(tmpdir)
            mock_subprocess_run.return_value = mock.Mock(returncode=0)

            interactive_menu._run_semantic_virtualization_ui_integration_with_inesdata(
                {"label": "Normal", "args": [], "env": {}}
            )

            mock_subprocess_run.assert_called_once()
            command = mock_subprocess_run.call_args.args[0]
            env = mock_subprocess_run.call_args.kwargs["env"]

            self.assertIn("core/07-semantic-virtualization-httpdata.spec.ts", command)
            self.assertEqual(env["UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO"], "1")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
            self.assertTrue(env["PLAYWRIGHT_OUTPUT_DIR"].startswith(os.path.join(tmpdir, "experiments")))
            self.assertIn(
                os.path.join("components", "semantic-virtualization", "inesdata-ui"),
                env["PLAYWRIGHT_OUTPUT_DIR"],
            )

    @mock.patch.object(interactive_menu, "_cleanup_playwright_processes")
    @mock.patch.object(interactive_menu.subprocess, "run")
    @mock.patch.object(interactive_menu, "project_root")
    @mock.patch.object(interactive_menu, "_default_inesdata_adapter", return_value=FakeInteractiveAdapter())
    def test_run_ai_model_observer_ui_integration_uses_expected_spec_and_markers(
        self,
        _mock_default_adapter,
        mock_project_root,
        mock_subprocess_run,
        _mock_cleanup,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project_root.return_value = Path(tmpdir)
            mock_subprocess_run.return_value = mock.Mock(returncode=0)

            interactive_menu._run_ai_model_observer_ui_integration(
                {"label": "Normal", "args": [], "env": {}}
            )

            mock_subprocess_run.assert_called_once()
            command = mock_subprocess_run.call_args.args[0]
            env = mock_subprocess_run.call_args.kwargs["env"]

            self.assertIn("core/10-ai-model-observer.spec.ts", command)
            self.assertEqual(env["UI_AI_MODEL_OBSERVER_DEMO"], "1")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
            self.assertTrue(env["PLAYWRIGHT_OUTPUT_DIR"].startswith(os.path.join(tmpdir, "experiments")))
            self.assertIn(
                os.path.join("components", "ai-model-hub", "observer-ui"),
                env["PLAYWRIGHT_OUTPUT_DIR"],
            )

    def test_run_core_ui_tests_routes_smoke_dataspace_and_ops_suites(self):
        mode = {"label": "Live", "args": ["--headed"], "env": {"PWDEBUG": "0"}}
        smoke_result_a = {"test": "ui-core-smoke", "status": "passed"}
        smoke_result_b = {"test": "ui-core-smoke", "status": "passed"}
        dataspace_result = {"test": "ui-core-dataspace", "status": "passed"}
        ops_result = {"test": "ui-ops-minio-console", "status": "passed"}

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            interactive_menu.ExperimentStorage,
            "create_experiment_directory",
            return_value=tmpdir,
        ), mock.patch.object(
            interactive_menu.ExperimentStorage,
            "save",
            return_value=None,
        ), mock.patch.object(
            interactive_menu,
            "_level6_ui_ops_suite_available",
            return_value=True,
        ), mock.patch.object(
            interactive_menu,
            "_aggregate_level6_ui_results",
            return_value={"summary": {"passed": 4}},
        ) as mock_aggregate, mock.patch.object(
            interactive_menu,
            "_run_level6_ui_smoke",
            side_effect=[smoke_result_a, smoke_result_b],
        ) as mock_smoke, mock.patch.object(
            interactive_menu,
            "_run_level6_ui_dataspace",
            return_value=dataspace_result,
        ) as mock_dataspace, mock.patch.object(
            interactive_menu,
            "_run_level6_ui_ops",
            return_value=ops_result,
        ) as mock_ops:
            payload = interactive_menu._run_core_ui_tests(mode, adapter=FakeInteractiveAdapter())

        self.assertEqual(mock_smoke.call_count, 2)
        self.assertEqual(mock_dataspace.call_count, 1)
        self.assertEqual(mock_ops.call_count, 1)
        self.assertEqual(mock_smoke.call_args.kwargs["extra_args"], ["--headed"])
        self.assertEqual(
            mock_smoke.call_args.kwargs["extra_env"],
            {
                "UI_KEYCLOAK_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "PWDEBUG": "0",
            },
        )
        self.assertEqual(mock_dataspace.call_args.kwargs["extra_args"], ["--headed"])
        self.assertEqual(
            mock_dataspace.call_args.kwargs["extra_env"],
            {
                "UI_KEYCLOAK_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "PWDEBUG": "0",
            },
        )
        self.assertEqual(mock_ops.call_args.kwargs["extra_args"], ["--headed"])
        self.assertEqual(
            mock_ops.call_args.kwargs["extra_env"],
            {
                "UI_KEYCLOAK_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "PWDEBUG": "0",
            },
        )
        mock_aggregate.assert_called_once()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["mode"], "Live")
        self.assertEqual(len(payload["ui_results"]), 4)
        self.assertEqual(payload["ui_results"][3]["test"], "ui-ops-minio-console")


if __name__ == "__main__":
    unittest.main()
