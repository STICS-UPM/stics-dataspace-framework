import contextlib
import io
import sys
import unittest
from unittest import mock

import main
from tests.test_main_cli import FakeMetricsCollector, FakeStorage, FakeValidationEngine


class MainMenuMigrationTests(unittest.TestCase):
    def setUp(self):
        self.adapter_registry = {"fake": "fake_adapter_module:FakeAdapter"}
        self.deployer_registry = {"fake": "fake_deployer_module:FakeDeployer"}

    def test_developer_shortcut_runs_migrated_action_without_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["B", "Q"],
        ), mock.patch.object(
            main.local_menu_tools,
            "run_framework_bootstrap_interactive",
            return_value="bootstrap-ok",
        ) as bootstrap:
            result = main.main(
                ["menu"],
                adapter_registry=self.adapter_registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        bootstrap.assert_called_once_with()

    def test_ui_shortcut_runs_migrated_action_without_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["A", "Q"],
        ), mock.patch.object(
            main.ui_interactive_menu,
            "run_ai_model_hub_ui_tests_interactive",
            return_value="ai-model-ui-ok",
        ) as ai_model_hub:
            result = main.main(
                ["menu"],
                adapter_registry=self.adapter_registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        ai_model_hub.assert_called_once_with()

    def test_vm_distributed_shortcut_switches_topology_and_runs_wizard(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["W", "Y", "Q"],
        ), mock.patch.object(
            main,
            "_run_vm_distributed_configuration_wizard",
            return_value={"status": "prepared", "adapter": "fake", "topology": "vm-distributed"},
        ) as wizard:
            result = main.main(
                ["menu"],
                adapter_registry=self.adapter_registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        wizard.assert_called_once_with(
            current_adapter="fake",
            adapter_registry=self.adapter_registry,
        )

    def test_semantic_virtualization_ui_shortcut_runs_migrated_action_without_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["V", "Q"],
        ), mock.patch.object(
            main.ui_interactive_menu,
            "run_semantic_virtualization_ui_tests_interactive",
            return_value="semantic-virtualization-ui-ok",
        ) as semantic_virtualization:
            result = main.main(
                ["menu"],
                adapter_registry=self.adapter_registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        semantic_virtualization.assert_called_once_with()

    def test_components_menu_runs_level5_with_selected_components_and_model_server(self):
        captured_env = {}

        def fake_run_levels(*args, **kwargs):
            captured_env["components"] = main.os.environ.get("PIONERA_COMPONENTS")
            captured_env["model_server"] = main.os.environ.get("PIONERA_AI_MODEL_HUB_MODEL_SERVER_ENABLED")
            captured_env["legacy_model_server"] = main.os.environ.get(
                "PIONERA_LEVEL5_AI_MODEL_HUB_MODEL_SERVER_ENABLED"
            )
            return {"status": "completed", "adapter": args[0], "topology": kwargs.get("topology"), "levels": []}

        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["CM", "2,4", "Y", "Q"],
        ), mock.patch.object(
            main,
            "run_levels",
            side_effect=fake_run_levels,
        ) as run_levels:
            result = main.main(
                ["menu"],
                adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        run_levels.assert_called_once()
        self.assertEqual(run_levels.call_args.kwargs["levels"], [5])
        self.assertEqual(captured_env["components"], "ai-model-hub")
        self.assertEqual(captured_env["model_server"], "true")
        self.assertEqual(captured_env["legacy_model_server"], "true")

    def test_components_menu_disables_model_server_when_not_selected(self):
        captured_env = {}

        def fake_run_levels(*args, **kwargs):
            captured_env["components"] = main.os.environ.get("PIONERA_COMPONENTS")
            captured_env["model_server"] = main.os.environ.get("PIONERA_AI_MODEL_HUB_MODEL_SERVER_ENABLED")
            return {"status": "completed", "adapter": args[0], "topology": kwargs.get("topology"), "levels": []}

        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["CM", "1", "Y", "Q"],
        ), mock.patch.object(
            main,
            "run_levels",
            side_effect=fake_run_levels,
        ):
            result = main.main(
                ["menu"],
                adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        self.assertEqual(captured_env["components"], "ontology-hub")
        self.assertEqual(captured_env["model_server"], "false")

    def test_ai_model_hub_steps_shortcut_opens_use_case_assistant(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["AMH", "Y", "Q"],
        ), mock.patch.object(
            main,
            "_run_ai_model_hub_use_case_demo_assistant",
            return_value={"status": "completed", "adapter": "fake", "topology": "vm-distributed"},
        ) as assistant:
            result = main.main(
                ["menu"],
                adapter_registry=self.adapter_registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        assistant.assert_called_once_with(
            current_adapter="fake",
            adapter_registry=self.adapter_registry,
        )

    def test_legacy_shortcuts_are_routed_by_main_without_inesdata_py(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["B", "I", "Q"],
        ), mock.patch.object(
            main.local_menu_tools,
            "run_framework_bootstrap_interactive",
            return_value="bootstrap-ok",
        ) as bootstrap, mock.patch.object(
            main.ui_interactive_menu,
            "run_inesdata_ui_tests_interactive",
            return_value="inesdata-ui-ok",
        ) as inesdata_ui:
            result = main.main(
                ["menu"],
                adapter_registry=self.adapter_registry,
                deployer_registry=self.deployer_registry,
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")
        bootstrap.assert_called_once_with()
        inesdata_ui.assert_called_once_with()

    def test_validation_target_menu_opens_without_running_deployment(self):
        stdout = io.StringIO()
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["G", "B", "Q"],
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry={
                    "edc": "fake_adapter_module:FakeAdapter",
                    "inesdata": "fake_adapter_module:FakeAdapter",
                },
                deployer_registry={
                    "edc": "fake_deployer_module:FakeDeployer",
                    "inesdata": "fake_deployer_module:FakeDeployer",
                },
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        output = stdout.getvalue()
        self.assertEqual(result["status"], "exited")
        self.assertIn("Project: inesdata", output)
        self.assertIn("Safety: no cleanup, no writes, no destructive actions", output)
        self.assertNotIn("INESDATA adapter selected.", output)
        self.assertNotIn("Adapter: inesdata", output)

    def test_report_viewer_menu_opens_without_adapter_selection(self):
        stdout = io.StringIO()
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch(
            "builtins.input",
            side_effect=["E", "Q"],
        ), mock.patch.object(
            main,
            "discover_report_experiments",
            return_value=[],
        ), contextlib.redirect_stdout(stdout):
            result = main.main(
                ["menu"],
                adapter_registry={
                    "edc": "fake_adapter_module:FakeAdapter",
                    "inesdata": "fake_adapter_module:FakeAdapter",
                },
                deployer_registry={
                    "edc": "fake_deployer_module:FakeDeployer",
                    "inesdata": "fake_deployer_module:FakeDeployer",
                },
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        output = stdout.getvalue()
        self.assertEqual(result["status"], "exited")
        self.assertIn("E - View experiment reports", output)
        self.assertIn("No experiments found under experiments/.", output)
        self.assertNotIn("Available adapters:", output)

    def test_validation_target_menu_does_not_change_active_deployment_adapter(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", side_effect=["B"]), contextlib.redirect_stdout(stdout):
            selected = main._run_validation_target_menu_interactive(
                current_adapter="edc",
                adapter_registry={
                    "edc": "fake_adapter_module:FakeAdapter",
                    "inesdata": "fake_adapter_module:FakeAdapter",
                },
            )

        output = stdout.getvalue()
        self.assertEqual(selected, "edc")
        self.assertIn("Project: inesdata", output)
        self.assertNotIn("Switch active adapter", output)
        self.assertNotIn("Adapter: inesdata", output)

    def test_validation_target_missing_secrets_are_prompted_for_current_run_only(self):
        plan = {
            "secrets": [
                {"env": "INESDATA_PROD_VALIDATION_USER", "status": "missing"},
                {"env": "INESDATA_PROD_VALIDATION_PASSWORD", "status": "missing"},
            ]
        }
        stdout = io.StringIO()
        with mock.patch("builtins.input", return_value="validation-user"), mock.patch.object(
            main.getpass,
            "getpass",
            return_value="credential-value-not-printed",
        ), contextlib.redirect_stdout(stdout):
            runtime_env = main._prompt_validation_target_missing_secrets(plan, environ={})

        output = stdout.getvalue()
        self.assertEqual(runtime_env["INESDATA_PROD_VALIDATION_USER"], "validation-user")
        self.assertEqual(runtime_env["INESDATA_PROD_VALIDATION_PASSWORD"], "credential-value-not-printed")
        self.assertIn("for this run only", output)
        self.assertNotIn("credential-value-not-printed", output)

    def test_report_viewer_latest_selection_marks_dashboard_open(self):
        experiments = [{"name": "experiment_1", "path": "/tmp/experiment_1"}]
        with mock.patch("builtins.input", return_value="L"):
            selected = main._select_report_experiment_interactive(experiments)

        self.assertEqual(selected["name"], "experiment_1")
        self.assertTrue(selected["_open_dashboard"])

    def test_initial_topology_prompt_uses_same_validation_target_label(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            sys,
            "argv",
            ["main.py"],
        ), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch(
            "builtins.input",
            side_effect=["G", "B", "Q"],
        ):
            result = main.main(
                None,
                adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")

    def test_initial_topology_prompt_shows_validation_target_under_other_actions(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", return_value=""), contextlib.redirect_stdout(stdout):
            selected = main._select_topology_interactive(
                "local",
                available_topologies=("local", "vm-single"),
                include_validation_target=True,
                initial_prompt=True,
            )

        output = stdout.getvalue()
        self.assertEqual(selected, "local")
        self.assertIn("Available topologies:", output)
        self.assertIn("[Other actions]", output)
        self.assertIn("G - Validate target", output)
        self.assertIn("[Navigation]", output)
        self.assertNotIn("Enter - Continue", output)
        self.assertIn("Q - Exit", output)
        self.assertNotIn("B - Back", output)

    def test_initial_topology_prompt_can_exit_without_entering_menu(self):
        with mock.patch.dict(sys.modules, {"inesdata": None}), mock.patch.object(
            sys,
            "argv",
            ["main.py"],
        ), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch(
            "builtins.input",
            side_effect=["Q"],
        ):
            result = main.main(
                None,
                adapter_registry={"inesdata": "fake_adapter_module:FakeAdapter"},
                deployer_registry={"inesdata": "fake_deployer_module:FakeDeployer"},
                validation_engine_cls=FakeValidationEngine,
                metrics_collector_cls=FakeMetricsCollector,
                experiment_storage=FakeStorage,
            )

        self.assertEqual(result["status"], "exited")

    def test_regular_topology_selector_does_not_treat_g_as_validation_target(self):
        stdout = io.StringIO()
        with mock.patch("builtins.input", return_value="G"), contextlib.redirect_stdout(stdout):
            selected = main._select_topology_interactive(
                "local",
                available_topologies=("local", "vm-single"),
            )

        output = stdout.getvalue()
        self.assertEqual(selected, "local")
        self.assertNotIn("[Other actions]", output)
        self.assertNotIn("G - Validate target", output)
        self.assertIn("Invalid selection.", output)


if __name__ == "__main__":
    unittest.main()
