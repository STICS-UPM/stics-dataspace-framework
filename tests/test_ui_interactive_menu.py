import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
            "INESDATA_LOCAL_STORE_LABEL": "LocalStore",
        }


class FakeVmSingleInteractiveAdapter(FakeInteractiveAdapter):
    def load_deployer_config(self):
        return {
            "TOPOLOGY": "vm-single",
            "DS_1_NAME": "pionera",
            "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            "DS_1_CONNECTORS": "org2,org3",
            "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
            "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
            "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX": "/c",
        }


class FakeVmDistributedInteractiveAdapter(FakeInteractiveAdapter):
    def load_deployer_config(self):
        return {
            "TOPOLOGY": "vm-distributed",
            "DS_1_NAME": "pionera",
            "DS_DOMAIN_BASE": "pionera.oeg.fi.upm.es",
            "DS_1_CONNECTORS": "org2,org3",
            "KC_INTERNAL_URL": "http://auth.dev.ed.dataspaceunit.upm",
            "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
        }


class FakeEdcInteractiveAdapter(FakeInteractiveAdapter):
    def load_deployer_config(self):
        return {
            "TOPOLOGY": "local",
            "DS_1_NAME": "pionera-edc",
            "DS_DOMAIN_BASE": "dev.ds.dataspaceunit.upm",
            "DS_1_CONNECTORS": "citycounciledc,companyedc",
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

    def test_resolve_validation_ui_test_route_maps_component_id(self):
        route = interactive_menu._resolve_validation_ui_test_route("oh-app-10")

        self.assertIs(route["runner"], interactive_menu._run_ontology_hub_ui_functional)
        self.assertEqual(route["grep"], r"OH\-APP\-10\b")

    def test_resolve_validation_ui_test_route_maps_inesdata_id(self):
        route = interactive_menu._resolve_validation_ui_test_route("DS-UI-AMH-BENCH-01")

        self.assertIs(route["runner"], interactive_menu._run_inesdata_ui_specs_by_id)
        self.assertEqual(route["specs"], ["adapters/inesdata/specs/13-ai-model-benchmarking.spec.ts"])
        self.assertEqual(route["grep"], r"13 AI Model Benchmarking\b")
        self.assertEqual(route["env"], {"UI_AI_MODEL_HUB_HTTPDATA_DEMO": "1"})

    def test_finalize_playwright_run_reports_empty_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_report = Path(tmpdir) / "results.json"
            html_report = Path(tmpdir) / "playwright-report"
            html_report.mkdir()
            (html_report / "index.html").write_text("<html></html>", encoding="utf-8")
            json_report.write_text(
                """
                {
                  "stats": {"expected": 0, "unexpected": 0, "flaky": 0, "skipped": 0},
                  "errors": [{"message": "Error: No tests found"}]
                }
                """,
                encoding="utf-8",
            )

            output = io.StringIO()
            completed = mock.Mock(returncode=1)
            with mock.patch("sys.stdout", output):
                result = interactive_menu._finalize_playwright_run(
                    "Ontology Hub Functional",
                    completed,
                    str(json_report),
                    str(html_report),
                    test_grep=r"OH\-APP\-00\b",
                )

        self.assertEqual(result["summary"]["total"], 0)
        self.assertIn("Playwright did not find tests", output.getvalue())
        self.assertIn(r"OH\-APP\-00\b", output.getvalue())
        self.assertIn("Error: No tests found", output.getvalue())

    def test_resolve_validation_api_test_route_maps_component_id(self):
        route = interactive_menu._resolve_validation_api_test_route("pt5-oh-13")

        self.assertIs(route["runner"], interactive_menu._run_ontology_hub_api_case)
        self.assertEqual(route["component"], "ontology-hub")
        self.assertTrue(route["requires_base_url"])

    @mock.patch.object(interactive_menu, "_write_api_test_by_id_result", return_value="/tmp/api-result.json")
    @mock.patch.object(interactive_menu, "_api_test_experiment_dir", return_value="/tmp/api-test")
    @mock.patch.object(interactive_menu, "_resolve_component_api_base_url", return_value="http://ontology.example.test")
    @mock.patch.object(interactive_menu, "_run_ontology_hub_api_case")
    def test_run_validation_api_test_by_id_interactive_routes_component_api_test(
        self,
        mock_runner,
        mock_resolve_base_url,
        _mock_experiment_dir,
        _mock_write_result,
    ):
        mock_runner.return_value = {
            "executed_cases": [
                {
                    "test_case_id": "PT5-OH-13",
                    "description": "SPARQL access",
                    "evaluation": {"status": "passed", "assertions": []},
                }
            ]
        }

        with mock.patch("builtins.input", side_effect=["PT5-OH-13"]):
            result = interactive_menu.run_validation_api_test_by_id_interactive(
                adapter_name="inesdata",
                topology="local",
            )

        mock_resolve_base_url.assert_called_once_with(
            "ontology-hub",
            adapter_name="inesdata",
            topology="local",
        )
        mock_runner.assert_called_once_with("http://ontology.example.test", "/tmp/api-test", "PT5-OH-13")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["test_case_id"], "PT5-OH-13")

    @mock.patch.object(interactive_menu, "_write_api_test_by_id_result", return_value="/tmp/api-result.json")
    @mock.patch.object(interactive_menu, "_api_test_experiment_dir", return_value="/tmp/api-test")
    @mock.patch.object(interactive_menu, "_resolve_component_api_base_url")
    @mock.patch.object(interactive_menu, "_run_ai_model_hub_model_benchmarking_api_case")
    def test_run_validation_api_test_by_id_interactive_skips_base_url_when_not_required(
        self,
        mock_runner,
        mock_resolve_base_url,
        _mock_experiment_dir,
        _mock_write_result,
    ):
        mock_runner.return_value = {
            "executed_cases": [
                {
                    "test_case_id": "PT5-MH-14",
                    "description": "Benchmark metrics",
                    "evaluation": {"status": "passed", "assertions": []},
                }
            ]
        }

        with mock.patch("builtins.input", side_effect=["PT5-MH-14"]):
            result = interactive_menu.run_validation_api_test_by_id_interactive(
                adapter_name="inesdata",
                topology="local",
            )

        mock_resolve_base_url.assert_not_called()
        mock_runner.assert_called_once_with("", "/tmp/api-test", "PT5-MH-14")
        self.assertEqual(result["status"], "passed")

    @mock.patch.object(interactive_menu, "_run_ontology_hub_ui_functional")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_validation_test_by_id_interactive_routes_component_test(
        self,
        _mock_resolve_mode,
        mock_runner,
    ):
        with mock.patch("builtins.input", side_effect=["OH-APP-10"]):
            interactive_menu.run_validation_test_by_id_interactive()

        mock_runner.assert_called_once_with(
            {"label": "Normal", "args": [], "env": {}},
            test_grep=r"OH\-APP\-10\b",
            adapter_name=None,
            topology=None,
        )

    @mock.patch.object(interactive_menu, "_run_inesdata_ui_specs_by_id")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_validation_test_by_id_interactive_routes_inesdata_test(
        self,
        _mock_resolve_mode,
        mock_runner,
    ):
        with mock.patch("builtins.input", side_effect=["DS-UI-OH-01"]):
            interactive_menu.run_validation_test_by_id_interactive(
                adapter_name="inesdata",
                topology="vm-single",
            )

        route = mock_runner.call_args.args[1]
        self.assertEqual(route["id"], "DS-UI-OH-01")
        self.assertEqual(route["specs"], ["adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts"])
        self.assertEqual(mock_runner.call_args.kwargs["adapter_name"], "inesdata")
        self.assertEqual(mock_runner.call_args.kwargs["topology"], "vm-single")

    @mock.patch.object(interactive_menu, "_run_ai_model_hub_ui_functional")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_validation_test_by_id_interactive_routes_ai_model_hub_with_topology(
        self,
        _mock_resolve_mode,
        mock_runner,
    ):
        with mock.patch("builtins.input", side_effect=["PT5-MH-01"]):
            interactive_menu.run_validation_test_by_id_interactive(
                adapter_name="inesdata",
                topology="vm-single",
            )

        mock_runner.assert_called_once_with(
            {"label": "Normal", "args": [], "env": {}},
            test_grep=r"PT5\-MH\-01\b",
            adapter_name="inesdata",
            topology="vm-single",
        )

    @mock.patch.object(interactive_menu, "_run_validation_api_route_by_id")
    def test_run_validation_test_by_id_interactive_routes_api_test(self, mock_api_runner):
        with mock.patch("builtins.input", side_effect=["PT5-OH-13"]):
            interactive_menu.run_validation_test_by_id_interactive(
                adapter_name="edc",
                topology="vm-single",
            )

        route = mock_api_runner.call_args.args[0]
        self.assertEqual(route["id"], "PT5-OH-13")
        self.assertEqual(mock_api_runner.call_args.kwargs["adapter_name"], "edc")
        self.assertEqual(mock_api_runner.call_args.kwargs["topology"], "vm-single")

    @mock.patch.object(interactive_menu, "_run_validation_ui_route_by_id")
    @mock.patch.object(interactive_menu, "_run_validation_api_route_by_id")
    def test_run_validation_test_by_id_interactive_handles_ambiguous_api_choice(
        self,
        mock_api_runner,
        mock_ui_runner,
    ):
        with mock.patch("builtins.input", side_effect=["PT5-MH-14", "3"]):
            interactive_menu.run_validation_test_by_id_interactive(
                adapter_name="inesdata",
                topology="local",
            )

        route = mock_api_runner.call_args.args[0]
        self.assertEqual(route["id"], "PT5-MH-14")
        mock_ui_runner.assert_not_called()

    def test_run_validation_test_by_id_interactive_reports_unmapped_case(self):
        output = io.StringIO()
        with mock.patch("builtins.input", side_effect=["UNKNOWN-01"]), mock.patch("sys.stdout", output):
            interactive_menu.run_validation_test_by_id_interactive()

        self.assertIn("No automated test route is mapped", output.getvalue())

    @mock.patch.object(interactive_menu, "_run_semantic_virtualization_ui_tests")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_validation_test_by_id_interactive_prepares_vm_single_semantic_editor_test(
        self,
        _mock_resolve_mode,
        mock_runner,
    ):
        with mock.patch("builtins.input", side_effect=["SV-UI-10"]):
            interactive_menu.run_validation_test_by_id_interactive(
                adapter_name="inesdata",
                topology="vm-single",
            )

        mock_runner.assert_called_once_with(
            {"label": "Normal", "args": [], "env": {}},
            test_grep=r"SV\-UI\-10\b",
            adapter_name="inesdata",
            topology="vm-single",
            needs_mapping_editor=True,
        )

    @mock.patch.object(interactive_menu, "_run_ai_model_hub_ui_functional")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_ai_model_hub_ui_tests_interactive_routes_functional(
        self,
        _mock_resolve_mode,
        mock_run_functional,
    ):
        interactive_menu.run_ai_model_hub_ui_tests_interactive()

        mock_run_functional.assert_called_once_with({"label": "Normal", "args": [], "env": {}})

    @mock.patch.object(interactive_menu, "_run_ontology_hub_ui_functional")
    @mock.patch.object(interactive_menu, "_resolve_ui_mode", return_value={"label": "Normal", "args": [], "env": {}})
    def test_run_ontology_hub_ui_tests_interactive_routes_functional(
        self,
        _mock_resolve_mode,
        mock_run_functional,
    ):
        interactive_menu.run_ontology_hub_ui_tests_interactive()

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

    def test_ai_model_hub_functional_runtime_env_uses_vm_single_public_routes(self):
        env = interactive_menu._ai_model_hub_functional_runtime_env(FakeVmSingleInteractiveAdapter())

        self.assertEqual(env["UI_TOPOLOGY"], "vm-single")
        self.assertEqual(env["AI_MODEL_HUB_KEYCLOAK_URL"], "https://org4.pionera.oeg.fi.upm.es/auth")
        self.assertEqual(env["AI_MODEL_HUB_PROVIDER_CONNECTOR_ID"], "conn-org2-pionera")
        self.assertEqual(
            env["AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL"],
            "https://org4.pionera.oeg.fi.upm.es/c/org2/management",
        )
        self.assertEqual(
            env["AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL"],
            "https://org4.pionera.oeg.fi.upm.es/c/org3/management",
        )
        self.assertEqual(
            env["AI_MODEL_HUB_PROVIDER_PROTOCOL_URL"],
            "https://org4.pionera.oeg.fi.upm.es/c/org2/protocol",
        )

    def test_ai_model_hub_functional_runtime_env_uses_active_edc_adapter(self):
        env = interactive_menu._ai_model_hub_functional_runtime_env(
            FakeEdcInteractiveAdapter(),
            adapter_name="edc",
        )

        self.assertEqual(env["PIONERA_ADAPTER"], "edc")
        self.assertEqual(env["UI_ADAPTER"], "edc")
        self.assertEqual(env["AI_MODEL_HUB_COMPONENT_ADAPTER"], "edc")
        self.assertEqual(env["UI_DATASPACE"], "pionera-edc")
        self.assertEqual(env["AI_MODEL_HUB_PROVIDER_CONNECTOR_ID"], "conn-citycounciledc-pionera-edc")

    def test_ai_model_hub_base_url_uses_vm_single_public_route(self):
        base_url = interactive_menu._resolve_ai_model_hub_base_url(FakeVmSingleInteractiveAdapter())

        self.assertEqual(base_url, "https://org4.pionera.oeg.fi.upm.es/ai-model-hub")

    @mock.patch.object(interactive_menu, "_infrastructure_runtime_config", return_value={})
    def test_ontology_hub_runtime_env_uses_local_component_host(self, _mock_infra_config):
        with mock.patch.dict(interactive_menu.os.environ, {}, clear=True):
            env = interactive_menu._ontology_hub_functional_runtime_env(
                adapter=FakeInteractiveAdapter(),
                topology="local",
            )

        self.assertEqual(env["UI_TOPOLOGY"], "local")
        self.assertEqual(env["ONTOLOGY_HUB_BASE_URL"], "http://ontology-hub-demo.dev.ds.dataspaceunit.upm")

    @mock.patch.object(interactive_menu, "_infrastructure_runtime_config", return_value={})
    def test_ontology_hub_runtime_env_uses_vm_single_public_path(self, _mock_infra_config):
        with mock.patch.dict(interactive_menu.os.environ, {}, clear=True):
            env = interactive_menu._ontology_hub_functional_runtime_env(
                adapter=FakeVmSingleInteractiveAdapter(),
                topology="vm-single",
            )

        self.assertEqual(env["UI_TOPOLOGY"], "vm-single")
        self.assertEqual(env["ONTOLOGY_HUB_BASE_URL"], "https://org4.pionera.oeg.fi.upm.es/ontology-hub")

    @mock.patch.object(interactive_menu, "_infrastructure_runtime_config", return_value={})
    def test_ontology_hub_runtime_env_uses_vm_distributed_common_public_path(self, _mock_infra_config):
        with mock.patch.dict(interactive_menu.os.environ, {}, clear=True):
            env = interactive_menu._ontology_hub_functional_runtime_env(
                adapter=FakeVmDistributedInteractiveAdapter(),
                topology="vm-distributed",
            )

        self.assertEqual(env["UI_TOPOLOGY"], "vm-distributed")
        self.assertEqual(env["ONTOLOGY_HUB_BASE_URL"], "https://org1.pionera.oeg.fi.upm.es/ontology-hub")

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

    @mock.patch.object(interactive_menu, "_main_validation_runtime_module")
    def test_semantic_virtualization_menu_tunnel_environment_is_vm_single_only(self, mock_main_runtime):
        env = interactive_menu._semantic_virtualization_vm_single_menu_environment(
            topology="local",
            test_grep=r"SV\-UI\-10\b",
        )

        self.assertEqual(env, {})
        mock_main_runtime.assert_not_called()

    @mock.patch.object(interactive_menu, "_main_validation_runtime_module")
    def test_semantic_virtualization_menu_tunnel_environment_uses_vm_single_helper(self, mock_main_runtime):
        fake_runtime = mock.Mock()
        fake_runtime._load_effective_infrastructure_deployer_config.return_value = {"TOPOLOGY": "vm-single"}
        fake_runtime._vm_single_component_validation_tunnel_environment.return_value = {
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL": "http://127.0.0.1:5678",
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_PUBLIC_URL": "http://127.0.0.1:5678",
            "MAPPING_EDITOR_BASE_URL": "http://127.0.0.1:5678",
        }
        mock_main_runtime.return_value = fake_runtime

        env = interactive_menu._semantic_virtualization_vm_single_menu_environment(
            topology="vm-single",
            test_grep=r"SV\-UI\-10\b",
        )

        fake_runtime._load_effective_infrastructure_deployer_config.assert_called_once_with(topology="vm-single")
        fake_runtime._vm_single_component_validation_tunnel_environment.assert_called_once_with(
            {"TOPOLOGY": "vm-single"}
        )
        self.assertEqual(env["SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL"], "http://127.0.0.1:5678")

    @mock.patch.object(
        interactive_menu,
        "_semantic_virtualization_vm_single_menu_environment",
        return_value={
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL": "http://127.0.0.1:5678",
            "MAPPING_EDITOR_BASE_URL": "http://127.0.0.1:5678",
        },
    )
    @mock.patch.object(interactive_menu, "_build_validation_adapter", return_value=FakeVmSingleInteractiveAdapter())
    @mock.patch.object(interactive_menu, "_cleanup_playwright_processes")
    @mock.patch.object(interactive_menu.subprocess, "run")
    @mock.patch.object(interactive_menu, "project_root")
    @mock.patch.object(interactive_menu, "_resolve_semantic_virtualization_base_url", return_value="https://org4.example.test/semantic-virtualization")
    def test_run_semantic_virtualization_ui_tests_injects_vm_single_editor_tunnel_env(
        self,
        _mock_resolve_base_url,
        mock_project_root,
        mock_subprocess_run,
        _mock_cleanup,
        _mock_build_adapter,
        mock_tunnel_env,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project_root.return_value = Path(tmpdir)
            mock_subprocess_run.return_value = mock.Mock(returncode=0)

            interactive_menu._run_semantic_virtualization_ui_tests(
                {"label": "Normal", "args": [], "env": {}},
                test_grep=r"SV\-UI\-10\b",
                adapter_name="inesdata",
                topology="vm-single",
                needs_mapping_editor=True,
            )

            env = mock_subprocess_run.call_args.kwargs["env"]
            mock_tunnel_env.assert_called_once_with(
                topology="vm-single",
                test_grep=r"SV\-UI\-10\b",
                needs_mapping_editor=True,
            )
            self.assertEqual(env["PIONERA_TOPOLOGY"], "vm-single")
            self.assertEqual(env["UI_TOPOLOGY"], "vm-single")
            self.assertEqual(env["SEMANTIC_VIRTUALIZATION_ENABLE_UI_VALIDATION"], "1")
            self.assertEqual(env["SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI"], "1")
            self.assertEqual(env["SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_BASE_URL"], "http://127.0.0.1:5678")
            self.assertEqual(env["MAPPING_EDITOR_BASE_URL"], "http://127.0.0.1:5678")

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

            self.assertIn("adapters/inesdata/specs/08-ontology-hub-inesdata-readonly.spec.ts", command)
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

            self.assertIn("adapters/inesdata/specs/07-semantic-virtualization-httpdata.spec.ts", command)
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

            self.assertIn("adapters/inesdata/specs/10-ai-model-observer.spec.ts", command)
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
                "UI_INESDATA_LOCAL_STORE_LABEL": "LocalStore",
                "PWDEBUG": "0",
            },
        )
        self.assertEqual(mock_dataspace.call_args.kwargs["extra_args"], ["--headed"])
        self.assertEqual(
            mock_dataspace.call_args.kwargs["extra_env"],
            {
                "UI_KEYCLOAK_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "UI_INESDATA_LOCAL_STORE_LABEL": "LocalStore",
                "PWDEBUG": "0",
            },
        )
        self.assertEqual(mock_ops.call_args.kwargs["extra_args"], ["--headed"])
        self.assertEqual(
            mock_ops.call_args.kwargs["extra_env"],
            {
                "UI_KEYCLOAK_URL": "http://auth.dev.ed.dataspaceunit.upm",
                "UI_INESDATA_LOCAL_STORE_LABEL": "LocalStore",
                "PWDEBUG": "0",
            },
        )
        mock_aggregate.assert_called_once()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["mode"], "Live")
        self.assertEqual(len(payload["ui_results"]), 4)
        self.assertEqual(payload["ui_results"][3]["test"], "ui-ops-minio-console")

    def test_edc_ui_menu_runs_ai_model_hub_subset(self):
        mode = {"label": "normal", "args": [], "env": {}}

        with mock.patch("builtins.input", side_effect=["3"]), mock.patch.object(
            interactive_menu,
            "_resolve_ui_mode",
            return_value=mode,
        ), mock.patch.object(
            interactive_menu,
            "_run_edc_ui_specs",
            return_value={"status": "passed"},
        ) as runner:
            result = interactive_menu.run_edc_ui_tests_interactive()

        self.assertIsNone(result)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], mode)
        self.assertEqual(runner.call_args.args[1], "AI Model Hub Integration with EDC")
        self.assertIn(
            os.path.join("adapters", "edc", "specs", "09-ai-model-hub-httpdata.spec.ts"),
            runner.call_args.args[2],
        )
        self.assertIn(
            os.path.join("adapters", "edc", "specs", "15-ai-model-external-execution.spec.ts"),
            runner.call_args.args[2],
        )

    def test_edc_ui_specs_metadata_records_vm_single_k3s_runtime(self):
        class FakeEdcDeployer:
            def __init__(self, adapter=None, topology=None):
                self.adapter = adapter
                self.topology = topology

            def resolve_context(self, topology=None):
                return SimpleNamespace(
                    connectors=["conn-companyedc-demo"],
                    environment="DEV",
                    config={"CLUSTER_TYPE": "k3s"},
                    topology=topology or self.topology,
                )

            def get_validation_profile(self, context):
                return SimpleNamespace(adapter="edc")

        metadata_calls = []

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "deployers.edc.deployer.EdcDeployer",
            FakeEdcDeployer,
        ), mock.patch.object(
            interactive_menu,
            "_build_validation_adapter",
            return_value=FakeVmSingleInteractiveAdapter(),
        ), mock.patch.object(
            interactive_menu.ExperimentStorage,
            "create_experiment_directory",
            return_value=tmpdir,
        ), mock.patch.object(
            interactive_menu.ExperimentStorage,
            "save_experiment_metadata",
            side_effect=lambda *args, **kwargs: metadata_calls.append((args, kwargs)),
        ), mock.patch(
            "validation.ui.ui_runner.run_playwright_validation",
            return_value={"summary": {"status_counts": {"passed": 1}, "total_specs": 1}},
        ):
            interactive_menu._run_edc_ui_specs(
                {"label": "normal", "args": [], "env": {}},
                "Core",
                specs=["adapters/edc/specs/01-login-readiness.spec.ts"],
                topology="vm-single",
            )

        self.assertEqual(metadata_calls[0][1]["topology"], "vm-single")
        self.assertEqual(metadata_calls[0][1]["cluster_runtime"], "k3s")


if __name__ == "__main__":
    unittest.main()
