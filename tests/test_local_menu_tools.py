import os
import tempfile
import unittest
from unittest import mock

from framework import local_menu_tools


class LocalMenuToolsTests(unittest.TestCase):
    def test_framework_doctor_warns_when_system_python3_is_too_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir),
                mock.patch.object(
                    local_menu_tools,
                    "FRAMEWORK_DOCTOR_SYSTEM_COMMANDS",
                    (("python3", ["python3", "--version"], "Install Python."),),
                ),
                mock.patch.object(
                    local_menu_tools.shutil,
                    "which",
                    side_effect=lambda command: f"/usr/bin/{command}" if command in {"python3", "pgrep"} else None,
                ),
                mock.patch.object(
                    local_menu_tools,
                    "_run_command_capture",
                    side_effect=lambda args, cwd=None: (0, "Python 3.9.6")
                    if args == ["python3", "--version"]
                    else (1, ""),
                ),
                mock.patch.object(local_menu_tools, "get_hosts_path", return_value=None),
                mock.patch.object(local_menu_tools.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="")),
            ):
                report = local_menu_tools.collect_framework_doctor_report()

        python_item = next(item for item in report["checks"] if item["name"] == "python3")
        self.assertEqual(python_item["status"], "warning")
        self.assertIn("Python 3.9.6", python_item["details"])
        self.assertIn("Python 3.10+", python_item["details"])
        self.assertIn("Python 3.10+", python_item["remediation"])

    def test_framework_doctor_warns_when_root_venv_python_is_too_old(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root_venv_python = os.path.join(tmpdir, ".venv", "bin", "python")
            os.makedirs(os.path.dirname(root_venv_python), exist_ok=True)
            with open(root_venv_python, "w", encoding="utf-8") as handle:
                handle.write("")

            with (
                mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir),
                mock.patch.object(local_menu_tools, "FRAMEWORK_DOCTOR_SYSTEM_COMMANDS", ()),
                mock.patch.object(local_menu_tools.shutil, "which", return_value="/usr/bin/pgrep"),
                mock.patch.object(
                    local_menu_tools,
                    "_run_command_capture",
                    side_effect=lambda args, cwd=None: (0, "Python 3.9.6")
                    if args == [root_venv_python, "--version"]
                    else (1, ""),
                ),
                mock.patch.object(local_menu_tools, "get_hosts_path", return_value=None),
                mock.patch.object(local_menu_tools.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="")),
            ):
                report = local_menu_tools.collect_framework_doctor_report()

        venv_item = next(item for item in report["checks"] if item["name"] == "root .venv")
        self.assertEqual(venv_item["status"], "warning")
        self.assertIn("Python 3.10+", venv_item["details"])
        self.assertIn("Remove .venv", venv_item["remediation"])

    def test_bootstrap_interactive_executes_framework_bootstrap_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_dir = os.path.join(tmpdir, "scripts")
            os.makedirs(script_dir, exist_ok=True)
            script_path = os.path.join(script_dir, "bootstrap_framework.sh")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\n")

            with mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir), mock.patch(
                "builtins.input",
                side_effect=["Y"],
            ), mock.patch.object(local_menu_tools.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0)

                result = local_menu_tools.run_framework_bootstrap_interactive()

        self.assertEqual(result, 0)
        run.assert_called_once_with(["bash", script_path], cwd=tmpdir)

    def test_cleanup_interactive_executes_include_results_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_dir = os.path.join(tmpdir, "scripts")
            os.makedirs(script_dir, exist_ok=True)
            script_path = os.path.join(script_dir, "clean_workspace.sh")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\n")

            with mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir), mock.patch(
                "builtins.input",
                side_effect=["2", "Y"],
            ), mock.patch.object(local_menu_tools.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0)

                local_menu_tools.run_workspace_cleanup_interactive()

        run.assert_called_once_with(
            ["bash", script_path, "--apply", "--include-results"],
            cwd=tmpdir,
        )

    def test_local_images_workflow_detects_deployers_inesdata_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapters_dir = os.path.join(tmpdir, "adapters", "edc")
            os.makedirs(adapters_dir, exist_ok=True)
            with open(os.path.join(adapters_dir, "config.py"), "w", encoding="utf-8") as handle:
                handle.write('REPO_DIR = os.path.join("deployers", "edc")\n')
            os.makedirs(os.path.join(tmpdir, "deployers", "edc"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)

            with mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir):
                detected = local_menu_tools._detect_platform_dirs_from_adapter_configs()

        self.assertEqual(detected[:2], [os.path.join("deployers", "inesdata"), os.path.join("deployers", "edc")])

    def test_collect_local_image_recipes_filters_existing_sources_by_adapter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(
                os.path.join(tmpdir, "adapters", "inesdata", "sources", "AIModelHub"),
                exist_ok=True,
            )
            os.makedirs(
                os.path.join(tmpdir, "adapters", "edc", "sources", "connector"),
                exist_ok=True,
            )

            with mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir):
                inesdata_recipes = local_menu_tools.collect_local_image_recipes(active_adapter="inesdata")
                edc_recipes = local_menu_tools.collect_local_image_recipes(active_adapter="edc")

        self.assertIn("inesdata/ai-model-hub", [recipe.key for recipe in inesdata_recipes])
        self.assertNotIn("edc/connector", [recipe.key for recipe in inesdata_recipes])
        self.assertIn("edc/connector", [recipe.key for recipe in edc_recipes])

    def test_collect_local_image_recipes_includes_script_recipe_without_synced_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = os.path.join(tmpdir, "adapters", "edc", "scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            with open(os.path.join(scripts_dir, "build_image.sh"), "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\n")

            with mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir):
                edc_recipes = local_menu_tools.collect_local_image_recipes(active_adapter="edc")

        self.assertIn("edc/connector", [recipe.key for recipe in edc_recipes])

    def test_execute_registered_local_image_recipe_builds_and_loads_generic_docker_recipe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = os.path.join(tmpdir, "sources", "demo")
            os.makedirs(source_dir, exist_ok=True)
            dockerfile = os.path.join(source_dir, "Dockerfile")
            with open(dockerfile, "w", encoding="utf-8") as handle:
                handle.write("FROM scratch\n")

            recipe = local_menu_tools.LocalImageRecipe(
                key="demo/image",
                adapter="inesdata",
                label="Demo image",
                source_rel_path=os.path.join("sources", "demo"),
                image_ref="demo/image:local",
                dockerfile_rel_path=os.path.join("sources", "demo", "Dockerfile"),
                context_rel_path=os.path.join("sources", "demo"),
                build_args=(("EXAMPLE", "1"),),
            )

            with (
                mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir),
                mock.patch.object(local_menu_tools, "_minikube_profile_for_local_images", return_value="dev"),
                mock.patch.object(local_menu_tools.subprocess, "run") as run,
            ):
                run.return_value = mock.Mock(returncode=0)

                result = local_menu_tools._execute_registered_local_image_recipe(recipe)

        self.assertTrue(result)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "docker",
                "build",
                "-t",
                "demo/image:local",
                "--build-arg",
                "EXAMPLE=1",
                "-f",
                dockerfile,
                source_dir,
            ],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["minikube", "-p", "dev", "image", "load", "demo/image:local"],
        )

    def test_execute_registered_local_image_recipe_restarts_component_deployment_when_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = os.path.join(tmpdir, "sources", "ontology")
            os.makedirs(source_dir, exist_ok=True)
            dockerfile = os.path.join(source_dir, "Dockerfile")
            with open(dockerfile, "w", encoding="utf-8") as handle:
                handle.write("FROM scratch\n")

            config_dir = os.path.join(tmpdir, "deployers", "inesdata")
            os.makedirs(config_dir, exist_ok=True)
            with open(os.path.join(config_dir, "deployer.config"), "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=demo\nDS_1_NAMESPACE=demo\n")

            recipe = local_menu_tools.LocalImageRecipe(
                key="inesdata/ontology-hub",
                adapter="inesdata",
                label="Ontology Hub",
                source_rel_path=os.path.join("sources", "ontology"),
                image_ref="ontology-hub:local",
                dockerfile_rel_path=os.path.join("sources", "ontology", "Dockerfile"),
                context_rel_path=os.path.join("sources", "ontology"),
                restart_deployment_template="{dataspace}-ontology-hub",
            )

            with (
                mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir),
                mock.patch.object(local_menu_tools, "_minikube_profile_for_local_images", return_value="dev"),
                mock.patch.object(local_menu_tools, "_run_command_capture", return_value=(0, "deployment/demo-ontology-hub")) as capture,
                mock.patch.object(local_menu_tools.subprocess, "run") as run,
            ):
                run.return_value = mock.Mock(returncode=0)

                result = local_menu_tools._execute_registered_local_image_recipe(recipe)

        self.assertTrue(result)
        capture.assert_called_once_with(["kubectl", "get", "deployment", "demo-ontology-hub", "-n", "demo"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["kubectl", "rollout", "restart", "deployment/demo-ontology-hub", "-n", "demo"], commands)
        self.assertIn(
            [
                "kubectl",
                "rollout",
                "status",
                "deployment/demo-ontology-hub",
                "-n",
                "demo",
                "--timeout=10m",
            ],
            commands,
        )

    def test_execute_registered_local_image_recipe_passes_minikube_profile_to_edc_scripts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_dir = os.path.join(tmpdir, "adapters", "edc", "scripts")
            os.makedirs(script_dir, exist_ok=True)
            script_path = os.path.join(script_dir, "build_dashboard_image.sh")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\n")

            recipe = local_menu_tools.LocalImageRecipe(
                key="edc/dashboard",
                adapter="edc",
                label="EDC dashboard",
                source_rel_path=os.path.join("adapters", "edc", "sources", "dashboard"),
                image_ref="validation-environment/edc-dashboard:latest",
                script_rel_path=os.path.join("adapters", "edc", "scripts", "build_dashboard_image.sh"),
                loads_minikube=True,
            )

            with (
                mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir),
                mock.patch.object(local_menu_tools, "_minikube_profile_for_local_images", return_value="dev"),
                mock.patch.object(local_menu_tools.subprocess, "run") as run,
            ):
                run.return_value = mock.Mock(returncode=0)

                result = local_menu_tools._execute_registered_local_image_recipe(recipe)

        self.assertTrue(result)
        self.assertEqual(
            run.call_args.args[0],
            ["bash", script_path, "--apply", "--minikube-profile", "dev"],
        )

    def test_execute_registered_workflow_recipe_preserves_values_and_namespace(self):
        recipe = local_menu_tools.LocalImageRecipe(
            key="inesdata/connector",
            adapter="inesdata",
            label="INESData connector",
            source_rel_path=os.path.join("adapters", "inesdata", "sources", "inesdata-connector"),
            image_ref="generated by INESData build manifest",
            workflow_component="connector",
        )

        with (
            mock.patch.object(
                local_menu_tools,
                "_dataspace_context_for_local_images",
                return_value={"dataspace": "demo", "namespace": "demo"},
            ),
            mock.patch.object(local_menu_tools, "_execute_local_images_workflow", return_value=True) as execute,
        ):
            result = local_menu_tools._execute_registered_local_image_recipe(
                recipe,
                platform_dir=os.path.join("deployers", "inesdata"),
                deploy=True,
                preserve_values=True,
            )

        self.assertTrue(result)
        execute.assert_called_once_with(
            [
                "--platform-dir",
                os.path.join("deployers", "inesdata"),
                "--namespace",
                "demo",
                "--component",
                "connector",
            ],
            deploy=True,
            preserve_values=True,
        )

    def test_local_images_workflow_keeps_inesdata_connector_shortcut(self):
        with (
            mock.patch.object(
                local_menu_tools,
                "_detect_platform_dirs_from_adapter_configs",
                return_value=[os.path.join("deployers", "inesdata")],
            ),
            mock.patch.object(
                local_menu_tools,
                "_dataspace_context_for_local_images",
                return_value={"dataspace": "demo", "namespace": "demo"},
            ),
            mock.patch("builtins.input", side_effect=["2", "Y"]),
            mock.patch.object(local_menu_tools, "_execute_local_images_workflow", return_value=True) as execute,
        ):
            local_menu_tools.run_local_images_workflow_interactive(active_adapter="inesdata")

        execute.assert_called_once_with(
            [
                "--platform-dir",
                os.path.join("deployers", "inesdata"),
                "--namespace",
                "demo",
                "--component",
                "connector",
            ],
            deploy=True,
            preserve_values=True,
        )

    def test_local_images_workflow_edc_quick_connector_uses_edc_recipe(self):
        recipe = local_menu_tools.LocalImageRecipe(
            key="edc/connector",
            adapter="edc",
            label="EDC connector",
            source_rel_path=os.path.join("adapters", "edc", "sources", "connector"),
            image_ref="validation-environment/edc-connector:local",
        )

        with (
            mock.patch.object(
                local_menu_tools,
                "_detect_platform_dirs_from_adapter_configs",
                return_value=[os.path.join("deployers", "inesdata")],
            ),
            mock.patch.object(local_menu_tools, "collect_local_image_recipes", return_value=[recipe]),
            mock.patch("builtins.input", side_effect=["1", "Y"]),
            mock.patch.object(local_menu_tools, "_execute_registered_local_image_recipes", return_value=True) as execute,
            mock.patch.object(local_menu_tools, "_execute_local_images_workflow", return_value=True) as legacy_execute,
        ):
            local_menu_tools.run_local_images_workflow_interactive(active_adapter="edc")

        execute.assert_called_once_with(
            [recipe],
            platform_dir=os.path.join("deployers", "inesdata"),
            deploy=True,
            preserve_values=True,
        )
        legacy_execute.assert_not_called()

    def test_local_images_workflow_edc_quick_dashboard_uses_dashboard_and_proxy_recipes(self):
        dashboard = local_menu_tools.LocalImageRecipe(
            key="edc/dashboard",
            adapter="edc",
            label="EDC dashboard",
            source_rel_path=os.path.join("adapters", "edc", "sources", "dashboard"),
            image_ref="validation-environment/edc-dashboard:latest",
        )
        proxy = local_menu_tools.LocalImageRecipe(
            key="edc/dashboard-proxy",
            adapter="edc",
            label="EDC dashboard proxy",
            source_rel_path=os.path.join("adapters", "edc", "build", "dashboard-proxy"),
            image_ref="validation-environment/edc-dashboard-proxy:latest",
        )

        with (
            mock.patch.object(
                local_menu_tools,
                "_detect_platform_dirs_from_adapter_configs",
                return_value=[os.path.join("deployers", "inesdata")],
            ),
            mock.patch.object(local_menu_tools, "collect_local_image_recipes", return_value=[dashboard, proxy]),
            mock.patch("builtins.input", side_effect=["2", "Y"]),
            mock.patch.object(local_menu_tools, "_execute_registered_local_image_recipes", return_value=True) as execute,
        ):
            local_menu_tools.run_local_images_workflow_interactive(active_adapter="edc")

        execute.assert_called_once_with(
            [dashboard, proxy],
            platform_dir=os.path.join("deployers", "inesdata"),
            deploy=True,
            preserve_values=True,
        )

    def test_local_images_workflow_can_select_registered_recipe_for_active_adapter(self):
        recipe = local_menu_tools.LocalImageRecipe(
            key="edc/connector",
            adapter="edc",
            label="EDC connector",
            source_rel_path=os.path.join("adapters", "edc", "sources", "connector"),
            image_ref="validation-environment/edc-connector:local",
        )

        with (
            mock.patch.object(
                local_menu_tools,
                "_detect_platform_dirs_from_adapter_configs",
                return_value=[os.path.join("deployers", "inesdata")],
            ),
            mock.patch.object(local_menu_tools, "collect_local_image_recipes", return_value=[recipe]),
            mock.patch.object(local_menu_tools, "_recipe_has_changes", return_value=True),
            mock.patch("builtins.input", side_effect=["6", "1", "Y"]),
            mock.patch.object(local_menu_tools, "_execute_registered_local_image_recipes", return_value=True) as execute,
        ):
            local_menu_tools.run_local_images_workflow_interactive(active_adapter="edc")

        execute.assert_called_once_with(
            [recipe],
            platform_dir=os.path.join("deployers", "inesdata"),
            deploy=True,
            preserve_values=True,
        )

    def test_local_images_workflow_can_build_load_selected_recipe_without_redeploy(self):
        recipe = local_menu_tools.LocalImageRecipe(
            key="edc/connector",
            adapter="edc",
            label="EDC connector",
            source_rel_path=os.path.join("adapters", "edc", "sources", "connector"),
            image_ref="validation-environment/edc-connector:local",
        )

        with (
            mock.patch.object(
                local_menu_tools,
                "_detect_platform_dirs_from_adapter_configs",
                return_value=[os.path.join("deployers", "inesdata")],
            ),
            mock.patch.object(local_menu_tools, "collect_local_image_recipes", return_value=[recipe]),
            mock.patch("builtins.input", side_effect=["7", "1", "Y"]),
            mock.patch.object(local_menu_tools, "_execute_registered_local_image_recipes", return_value=True) as execute,
        ):
            local_menu_tools.run_local_images_workflow_interactive(active_adapter="edc")

        execute.assert_called_once_with(
            [recipe],
            platform_dir=os.path.join("deployers", "inesdata"),
            deploy=False,
            preserve_values=True,
        )

    def test_execute_local_images_workflow_refuses_crlf_shell_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_dir = os.path.join(tmpdir, "adapters", "inesdata", "scripts")
            os.makedirs(script_dir, exist_ok=True)
            script_path = os.path.join(script_dir, "local_build_load_deploy.sh")
            with open(script_path, "wb") as handle:
                handle.write(b"#!/usr/bin/env bash\r\nset -euo pipefail\r\n")

            with (
                mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir),
                mock.patch.object(local_menu_tools.subprocess, "run") as run,
            ):
                result = local_menu_tools._execute_local_images_workflow([])

        self.assertFalse(result)
        run.assert_not_called()

    def test_execute_edc_script_recipe_restarts_matching_deployments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_dir = os.path.join(tmpdir, "adapters", "edc", "scripts")
            os.makedirs(script_dir, exist_ok=True)
            script_path = os.path.join(script_dir, "build_image.sh")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\n")

            recipe = local_menu_tools.LocalImageRecipe(
                key="edc/connector",
                adapter="edc",
                label="EDC connector",
                source_rel_path=os.path.join("adapters", "edc", "sources", "connector"),
                image_ref="validation-environment/edc-connector:local",
                script_rel_path=os.path.join("adapters", "edc", "scripts", "build_image.sh"),
            )

            with (
                mock.patch.object(local_menu_tools, "project_root", return_value=tmpdir),
                mock.patch.object(local_menu_tools, "_minikube_profile_for_local_images", return_value="dev"),
                mock.patch.object(local_menu_tools.subprocess, "run") as run,
                mock.patch.object(local_menu_tools, "_restart_edc_deployments_for_local_image_keys") as restart,
            ):
                run.return_value = mock.Mock(returncode=0)

                result = local_menu_tools._execute_registered_local_image_recipe(recipe, deploy=True)

        self.assertTrue(result)
        self.assertEqual(
            run.call_args.args[0],
            ["bash", script_path, "--apply", "--minikube-profile", "dev"],
        )
        restart.assert_called_once_with(["edc/connector"])

    def test_recover_connectors_restarts_detected_connector_deployments(self):
        adapter = _FakeRecoveryAdapter(connectors=["conn-a", "conn-b"])

        result = local_menu_tools.run_connector_recovery_after_wsl_restart(adapter=adapter)

        self.assertTrue(result)
        self.assertIn("kubectl rollout restart deployment/conn-a -n demo", adapter.commands)
        self.assertIn("kubectl rollout restart deployment/conn-b -n demo", adapter.commands)
        self.assertIn("kubectl rollout status deployment/conn-a -n demo --timeout=180s", adapter.commands)
        self.assertIn("kubectl rollout status deployment/conn-b -n demo --timeout=180s", adapter.commands)
        self.assertEqual(adapter.validated_connectors, ["conn-a", "conn-b"])

    def test_recover_connectors_falls_back_to_deployments_when_pods_are_unhealthy(self):
        adapter = _FakeRecoveryAdapter(connectors=[], deployment_output="conn-a 1/1 1 1\n")

        result = local_menu_tools.run_connector_recovery_after_wsl_restart(adapter=adapter)

        self.assertTrue(result)
        self.assertIn("kubectl rollout restart deployment/conn-a -n demo", adapter.commands)
        self.assertEqual(adapter.validated_connectors, ["conn-a"])


class _FakeRecoveryConfig:
    NS_COMMON = "common"
    TIMEOUT_NAMESPACE = 90

    @staticmethod
    def namespace_demo():
        return "demo"


class _FakeRecoveryInfrastructure:
    def __init__(self):
        self.host_entries = []

    def wait_for_vault_pod(self, namespace, timeout=None):
        self.vault_namespace = namespace
        self.vault_timeout = timeout
        return True

    def ensure_vault_unsealed(self):
        return True

    def manage_hosts_entries(self, entries, header_comment=None):
        self.host_entries.append((entries, header_comment))


class _FakeRecoveryConfigAdapter:
    def generate_connector_hosts(self, connectors):
        return []

    def ds_domain_base(self):
        return ""


class _FakeRecoveryConnectors:
    def __init__(self, adapter):
        self.adapter = adapter

    def validate_connectors_deployment(self, connectors):
        self.adapter.validated_connectors = list(connectors)
        return True


class _FakeRecoveryAdapter:
    config = _FakeRecoveryConfig()

    def __init__(self, connectors, deployment_output=""):
        self._connectors = connectors
        self.deployment_output = deployment_output
        self.infrastructure = _FakeRecoveryInfrastructure()
        self.config_adapter = _FakeRecoveryConfigAdapter()
        self.connectors = _FakeRecoveryConnectors(self)
        self.commands = []
        self.validated_connectors = []

    def get_cluster_connectors(self):
        return list(self._connectors)

    def run(self, command, capture=False, check=True, cwd=None):
        self.commands.append(command)
        if capture and "kubectl get deployments" in command:
            return self.deployment_output
        return mock.Mock(returncode=0)


if __name__ == "__main__":
    unittest.main()
