import os
import tempfile
import unittest

from adapters.inesdata.deployment import INESDataDeploymentAdapter


class RecreateConfig:
    ADAPTER_NAME = "edc"
    DS_NAME = "demoedc"
    NS_COMMON = "common-srvs"

    root = ""

    @classmethod
    def script_dir(cls):
        return cls.root

    @classmethod
    def repo_dir(cls):
        return os.path.join(cls.root, "deployers", "inesdata")

    @classmethod
    def python_exec(cls):
        return "/usr/bin/python3"

    @classmethod
    def dataspace_name(cls):
        return "demoedc"

    @classmethod
    def namespace_demo(cls):
        return "demoedc"

    @classmethod
    def adapter_name(cls):
        return "edc"

    @classmethod
    def helm_release_rs(cls):
        return "demoedc-dataspace-rs"

    @classmethod
    def deployment_runtime_dir(cls):
        return os.path.join(cls.root, "deployers", "edc", "deployments", "DEV", "demoedc")


class RecreateConfigProtectedNamespace(RecreateConfig):
    @classmethod
    def namespace_demo(cls):
        return "common-srvs"


class RecreateConfigRoleAligned(RecreateConfig):
    @classmethod
    def registration_service_namespace(cls):
        return "demoedc-core"


class RecreateDataspaceTests(unittest.TestCase):
    def test_recreate_cleanup_targets_only_selected_dataspace_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            RecreateConfig.root = tmpdir
            repo_dir = RecreateConfig.repo_dir()
            runtime_dir = RecreateConfig.deployment_runtime_dir()
            os.makedirs(repo_dir, exist_ok=True)
            os.makedirs(runtime_dir, exist_ok=True)
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("# test bootstrap\n")
            with open(os.path.join(runtime_dir, "generated.txt"), "w", encoding="utf-8") as handle:
                handle.write("runtime\n")

            commands = []

            def run(cmd, **kwargs):
                commands.append((cmd, kwargs))
                return object()

            deployment = INESDataDeploymentAdapter(
                run=run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_cls=RecreateConfig,
            )

            plan = deployment.build_recreate_dataspace_plan()
            deployment._cleanup_dataspace_before_recreate()

            self.assertEqual(plan["dataspace"], "demoedc")
            self.assertEqual(plan["namespace"], "demoedc")
            self.assertTrue(plan["preserves_shared_services"])
            self.assertFalse(os.path.exists(runtime_dir))
            self.assertEqual(commands[0][0], "helm uninstall demoedc-dataspace-rs -n demoedc")
            self.assertEqual(commands[1][0], "kubectl delete namespace demoedc --ignore-not-found=true")
            self.assertIn("PIONERA_TOPOLOGY=local", commands[2][0])
            self.assertIn("bootstrap.py dataspace delete demoedc", commands[2][0])
            self.assertEqual(commands[2][1]["cwd"], repo_dir)

    def test_recreate_cleanup_rejects_common_services_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            RecreateConfigProtectedNamespace.root = tmpdir
            deployment = INESDataDeploymentAdapter(
                run=lambda *_args, **_kwargs: object(),
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_cls=RecreateConfigProtectedNamespace,
            )

            with self.assertRaises(RuntimeError) as exc:
                deployment._cleanup_dataspace_before_recreate()

            self.assertIn("protected namespace", str(exc.exception))

    def test_recreate_cleanup_uses_registration_service_namespace_when_defined(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            RecreateConfigRoleAligned.root = tmpdir
            repo_dir = RecreateConfigRoleAligned.repo_dir()
            runtime_dir = RecreateConfigRoleAligned.deployment_runtime_dir()
            os.makedirs(repo_dir, exist_ok=True)
            os.makedirs(runtime_dir, exist_ok=True)
            with open(os.path.join(repo_dir, "bootstrap.py"), "w", encoding="utf-8") as handle:
                handle.write("# test bootstrap\n")

            commands = []

            def run(cmd, **kwargs):
                commands.append((cmd, kwargs))
                return object()

            deployment = INESDataDeploymentAdapter(
                run=run,
                run_silent=lambda *_args, **_kwargs: "",
                auto_mode_getter=lambda: True,
                infrastructure_adapter=object(),
                config_cls=RecreateConfigRoleAligned,
            )

            plan = deployment.build_recreate_dataspace_plan()
            deployment._cleanup_dataspace_before_recreate()

            self.assertEqual(plan["namespace"], "demoedc-core")
            self.assertEqual(commands[0][0], "helm uninstall demoedc-dataspace-rs -n demoedc-core")
            self.assertEqual(commands[1][0], "kubectl delete namespace demoedc-core --ignore-not-found=true")


if __name__ == "__main__":
    unittest.main()
