import os
import tempfile
import unittest
from unittest import mock

from deployers.infrastructure.lib.contracts import DeploymentContext, ValidationProfile
from validation.ui import ui_runner


class UiRunnerInteractionMarkersTests(unittest.TestCase):
    def _context(self):
        return DeploymentContext(
            deployer="inesdata",
            topology="local",
            environment="DEV",
            dataspace_name="demo",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=["conn-citycouncil-demo", "conn-company-demo"],
            config={
                "KC_URL": "http://keycloak.dev.ed.dataspaceunit.upm",
                "INESDATA_LOCAL_STORE_LABEL": "LocalStore",
            },
        )

    def _profile(self):
        return ValidationProfile(
            adapter="inesdata",
            playwright_enabled=True,
            playwright_config="validation/ui/playwright.inesdata.config.ts",
        )

    def test_playwright_validation_enables_interaction_markers_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=self._context(),
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "1")
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKER_DELAY_MS"], "150")
            self.assertEqual(env["PIONERA_PLAYWRIGHT_SUITE_NAME"], "INESData integration")
            self.assertEqual(env["UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO"], "1")
            self.assertEqual(env["UI_ONTOLOGY_HUB_INESDATA_DEMO"], "1")
            self.assertEqual(env["UI_AI_MODEL_HUB_HTTPDATA_DEMO"], "1")
            self.assertEqual(env["UI_AI_MODEL_OBSERVER_DEMO"], "1")
            self.assertEqual(env["UI_INESDATA_LOCAL_STORE_LABEL"], "LocalStore")

    def test_playwright_validation_respects_explicit_marker_override(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"PLAYWRIGHT_INTERACTION_MARKERS": "0"},
        ), mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=self._context(),
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["PLAYWRIGHT_INTERACTION_MARKERS"], "0")

    def test_playwright_validation_supports_fail_fast_max_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"PLAYWRIGHT_MAX_FAILURES": "1"},
        ), mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=self._context(),
                experiment_dir=tmpdir,
            )

            command = subprocess_run.call_args.args[0]
            self.assertIn("--max-failures", command)
            self.assertEqual(command[command.index("--max-failures") + 1], "1")

    def test_playwright_validation_prefers_public_keycloak_url(self):
        context = self._context()
        context.config.update(
            {
                "KEYCLOAK_FRONTEND_URL": "https://org1.example.test/auth",
                "KC_INTERNAL_URL": "http://auth.internal.example.test",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UI_KEYCLOAK_URL"], "https://org1.example.test/auth")

    def test_playwright_validation_exports_local_minio_console_url_from_local_hostname(self):
        context = self._context()
        context.config.update(
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "MINIO_CONSOLE_HOSTNAME": "console.minio-s3.dev.ed.dataspaceunit.upm",
                "MINIO_CONSOLE_PUBLIC_URL": "https://org1.dev.ed.dataspaceunit.upm/s3-console",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(
                env["UI_MINIO_CONSOLE_URL"],
                "http://console.minio-s3.dev.ed.dataspaceunit.upm",
            )
            self.assertNotIn("org1", env["UI_MINIO_CONSOLE_URL"])

    def test_playwright_validation_exports_vm_single_public_keycloak_and_minio_urls(self):
        context = self._context()
        context.topology = "vm-single"
        context.config.update(
            {
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KEYCLOAK_FRONTEND_URL": "https://org1.dev.ed.dataspaceunit.upm/auth",
                "MINIO_CONSOLE_PUBLIC_URL": "https://console.minio-s3.dev.ed.dataspaceunit.upm",
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UI_TOPOLOGY"], "vm-single")
            self.assertEqual(env["UI_KEYCLOAK_URL"], "https://org4.pionera.oeg.fi.upm.es/auth")
            self.assertEqual(env["UI_MINIO_CONSOLE_URL"], "https://org4.pionera.oeg.fi.upm.es/s3-console")
            self.assertEqual(env["UI_CONNECTOR_PROTOCOL_ADDRESS_MODE"], "public")

    def test_playwright_validation_exports_active_runtime_dir(self):
        context = self._context()
        context.topology = "vm-single"
        context.runtime_dir = "/tmp/deployers/inesdata/deployments/DEV/vm-single/demo"

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(
                env["UI_RUNTIME_DIR"],
                "/tmp/deployers/inesdata/deployments/DEV/vm-single/demo",
            )

    def test_playwright_validation_exports_vm_distributed_component_and_protocol_urls(self):
        context = self._context()
        context.topology = "vm-distributed"
        context.config.update(
            {
                "COMPONENTS_NAMESPACE": "components",
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
                "CONNECTOR_PROTOCOL_ADDRESS_MODE": "internal",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UI_TOPOLOGY"], "vm-distributed")
            self.assertEqual(env["UI_COMPONENTS_NAMESPACE"], "components")
            self.assertEqual(env["UI_CONNECTOR_PROTOCOL_ADDRESS_MODE"], "internal")
            self.assertEqual(env["AI_MODEL_HUB_MODEL_SERVER_BASE_URL"], "http://org1.example.test/model-server")
            self.assertEqual(
                env["AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL"],
                "http://org1.example.test/model-server",
            )

    def test_playwright_validation_respects_explicit_connector_model_server_route(self):
        context = self._context()
        context.topology = "vm-distributed"
        context.config.update(
            {
                "COMPONENTS_NAMESPACE": "components",
                "AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL": "http://components.internal/model-server",
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(
                env["AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL"],
                "http://components.internal/model-server",
            )
            self.assertEqual(
                env["AI_MODEL_HUB_MODEL_SERVER_BASE_URL"],
                "http://components.internal/model-server",
            )

    def test_playwright_validation_respects_explicit_vm_distributed_protocol_mode(self):
        context = self._context()
        context.topology = "vm-distributed"
        context.config.update(
            {
                "CONNECTOR_PROTOCOL_ADDRESS_MODE": "internal",
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {"UI_CONNECTOR_PROTOCOL_ADDRESS_MODE": "internal"},
        ), mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UI_CONNECTOR_PROTOCOL_ADDRESS_MODE"], "internal")


if __name__ == "__main__":
    unittest.main()
