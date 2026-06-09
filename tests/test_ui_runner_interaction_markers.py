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

    def _edc_profile(self):
        return ValidationProfile(
            adapter="edc",
            playwright_enabled=True,
            playwright_config="validation/ui/playwright.edc.config.ts",
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

    def test_playwright_validation_enables_all_edc_component_demos_by_default(self):
        context = self._context()
        context.deployer = "edc"

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._edc_profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["PIONERA_PLAYWRIGHT_SUITE_NAME"], "EDC UI")
            self.assertEqual(env["UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO"], "1")
            self.assertEqual(env["UI_ONTOLOGY_HUB_EDC_DEMO"], "1")
            self.assertEqual(env["UI_AI_MODEL_HUB_HTTPDATA_DEMO"], "1")
            self.assertEqual(env["UI_EDC_MODEL_OBSERVER_DEMO"], "1")

    def test_playwright_validation_uses_topology_aware_edc_protocol_mode_defaults(self):
        cases = [
            ("local", "internal"),
            ("vm-single", "internal"),
            ("vm-distributed", "public"),
        ]

        for topology, expected_mode in cases:
            with self.subTest(topology=topology), tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
                ui_runner.subprocess,
                "run",
                return_value=mock.Mock(returncode=0),
            ) as subprocess_run:
                context = self._context()
                context.deployer = "edc"
                context.topology = topology

                ui_runner.run_playwright_validation(
                    profile=self._edc_profile(),
                    context=context,
                    experiment_dir=tmpdir,
                )

                env = subprocess_run.call_args.kwargs["env"]
                self.assertEqual(env["UI_CONNECTOR_PROTOCOL_ADDRESS_MODE"], expected_mode)

    def test_playwright_validation_exports_configured_ingress_proxy_port(self):
        context = self._context()
        context.deployer = "edc"
        context.config.update(
            {
                "PLAYWRIGHT_INGRESS_PROXY_HOST": "127.0.0.1",
                "PLAYWRIGHT_INGRESS_PROXY_PORT": "18088",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._edc_profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UI_INGRESS_PORT"], "18088")
            self.assertEqual(env["PLAYWRIGHT_INGRESS_PROXY_HOST"], "127.0.0.1")
            self.assertEqual(env["PLAYWRIGHT_INGRESS_PROXY_PORT"], "18088")

    def test_playwright_validation_auto_detects_local_ingress_port_forward(self):
        context = self._context()
        context.deployer = "edc"

        process_listing = mock.Mock(
            returncode=0,
            stdout="kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 18088:80\n",
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            side_effect=[process_listing, mock.Mock(returncode=0)],
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._edc_profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UI_INGRESS_PORT"], "18088")
            self.assertEqual(env["PLAYWRIGHT_INGRESS_PROXY_PORT"], "18088")

    def test_playwright_validation_respects_explicit_edc_demo_overrides(self):
        context = self._context()
        context.deployer = "edc"

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(
            os.environ,
            {
                "UI_AI_MODEL_HUB_HTTPDATA_DEMO": "0",
                "UI_EDC_MODEL_OBSERVER_DEMO": "0",
            },
        ), mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._edc_profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UI_AI_MODEL_HUB_HTTPDATA_DEMO"], "0")
            self.assertEqual(env["UI_EDC_MODEL_OBSERVER_DEMO"], "0")
            self.assertEqual(env["UI_SEMANTIC_VIRTUALIZATION_HTTPDATA_DEMO"], "1")
            self.assertEqual(env["UI_ONTOLOGY_HUB_EDC_DEMO"], "1")

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

    def test_playwright_validation_accepts_interactive_specs_args_and_env(self):
        context = self._context()
        context.deployer = "edc"

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._edc_profile(),
                context=context,
                experiment_dir=tmpdir,
                specs=["adapters/edc/specs/09-ai-model-hub-httpdata.spec.ts"],
                extra_args=["--headed"],
                extra_env={"PWDEBUG": "1"},
            )

            command = subprocess_run.call_args.args[0]
            env = subprocess_run.call_args.kwargs["env"]
            self.assertIn("adapters/edc/specs/09-ai-model-hub-httpdata.spec.ts", command)
            self.assertEqual(command[-1], "--headed")
            self.assertEqual(env["PWDEBUG"], "1")

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

    def test_playwright_validation_exports_vm_single_edc_public_connector_urls(self):
        context = self._context()
        context.deployer = "edc"
        context.topology = "vm-single"
        context.dataspace_name = "pionera-edc"
        context.connectors = [
            "conn-citycounciledc-pionera-edc",
            "conn-companyedc-pionera-edc",
        ]
        context.config.update(
            {
                "VM_SINGLE_HTTP_URL": "https://org4.pionera.oeg.fi.upm.es",
                "VM_SINGLE_CONNECTOR_PUBLIC_PATH_PREFIX": "/c",
                "KEYCLOAK_FRONTEND_URL": "https://org4.pionera.oeg.fi.upm.es/auth",
                "EDC_DASHBOARD_ENABLED": "true",
                "EDC_DASHBOARD_BASE_HREF": "/edc-dashboard/",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._edc_profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            city_prefix = "UI_CONN_CITYCOUNCILEDC_PIONERA_EDC"
            company_prefix = "UI_CONN_COMPANYEDC_PIONERA_EDC"
            self.assertEqual(
                env[f"{city_prefix}_PORTAL_URL"],
                "https://org4.pionera.oeg.fi.upm.es/c/citycounciledc/edc-dashboard/",
            )
            self.assertEqual(
                env[f"{city_prefix}_MANAGEMENT_URL"],
                "https://org4.pionera.oeg.fi.upm.es/c/citycounciledc/management/v3",
            )
            self.assertEqual(
                env[f"{company_prefix}_PORTAL_URL"],
                "https://org4.pionera.oeg.fi.upm.es/c/companyedc/edc-dashboard/",
            )
            self.assertEqual(
                env[f"{company_prefix}_MANAGEMENT_URL"],
                "https://org4.pionera.oeg.fi.upm.es/c/companyedc/management/v3",
            )
            self.assertNotIn(f"{city_prefix}_PROTOCOL_URL", env)
            self.assertEqual(env["UI_CONNECTOR_PROTOCOL_ADDRESS_MODE"], "internal")

    def test_playwright_validation_exports_vm_distributed_edc_role_public_connector_urls(self):
        context = self._context()
        context.deployer = "edc"
        context.topology = "vm-distributed"
        context.dataspace_name = "pionera-edc"
        context.connectors = [
            "conn-citycounciledc-pionera-edc",
            "conn-companyedc-pionera-edc",
        ]
        context.config.update(
            {
                "VM_COMMON_PUBLIC_URL": "https://org1.pionera.oeg.fi.upm.es",
                "VM_PROVIDER_PUBLIC_URL": "https://org2.pionera.oeg.fi.upm.es",
                "VM_CONSUMER_PUBLIC_URL": "https://org3.pionera.oeg.fi.upm.es",
                "VM_PROVIDER_CONNECTORS": "citycounciledc",
                "VM_CONSUMER_CONNECTORS": "companyedc",
                "KEYCLOAK_FRONTEND_URL": "https://org1.pionera.oeg.fi.upm.es/auth",
                "EDC_DASHBOARD_ENABLED": "true",
                "EDC_DASHBOARD_BASE_HREF": "/edc-dashboard/",
                "EDC_DASHBOARD_PROXY_AUTH_MODE": "oidc-bff",
                "EDC_VM_DISTRIBUTED_CONNECTOR_PUBLIC_PATH_PREFIX": "/edc",
                "CONNECTOR_PROTOCOL_ADDRESS_MODE": "internal",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            ui_runner.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as subprocess_run:
            ui_runner.run_playwright_validation(
                profile=self._edc_profile(),
                context=context,
                experiment_dir=tmpdir,
            )

            env = subprocess_run.call_args.kwargs["env"]
            city_prefix = "UI_CONN_CITYCOUNCILEDC_PIONERA_EDC"
            company_prefix = "UI_CONN_COMPANYEDC_PIONERA_EDC"
            self.assertEqual(env[f"{city_prefix}_PORTAL_URL"], "https://org2.pionera.oeg.fi.upm.es/edc-dashboard/")
            self.assertEqual(env[f"{city_prefix}_MANAGEMENT_URL"], "https://org2.pionera.oeg.fi.upm.es/edc/management/v3")
            self.assertEqual(env[f"{city_prefix}_PROTOCOL_URL"], "https://org2.pionera.oeg.fi.upm.es/edc/protocol")
            self.assertEqual(env[f"{company_prefix}_PORTAL_URL"], "https://org3.pionera.oeg.fi.upm.es/edc-dashboard/")
            self.assertEqual(env[f"{company_prefix}_MANAGEMENT_URL"], "https://org3.pionera.oeg.fi.upm.es/edc/management/v3")
            self.assertEqual(env[f"{company_prefix}_PROTOCOL_URL"], "https://org3.pionera.oeg.fi.upm.es/edc/protocol")
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
            self.assertEqual(env["AI_MODEL_HUB_MODEL_SERVER_BASE_URL"], "https://org1.example.test/model-server")
            self.assertEqual(
                env["AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL"],
                "https://org1.example.test/model-server",
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

    def test_playwright_validation_exports_model_server_validation_contract(self):
        context = self._context()
        context.topology = "vm-distributed"
        context.config.update(
            {
                "COMPONENTS_PUBLIC_BASE_URL": "https://org1.example.test",
                "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_ENDPOINTS": "/mobility/lightgbm_previous_delay,/mobility/randomforest_previous_delay",
                "AI_MODEL_HUB_MODEL_SERVER_VALIDATION_PAYLOAD": '[{"trip_id":"trip-1"}]',
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
            self.assertEqual(env["UI_AI_MODEL_HUB_MODEL_PATH"], "/mobility/lightgbm_previous_delay")
            self.assertEqual(env["UI_AI_MODEL_HUB_EXTERNAL_MODEL_PATH"], "/mobility/lightgbm_previous_delay")
            self.assertEqual(env["UI_AI_MODEL_HUB_MODEL_PAYLOAD"], '[{"trip_id":"trip-1"}]')
            self.assertEqual(env["UI_AI_MODEL_HUB_EXTERNAL_MODEL_PAYLOAD"], '[{"trip_id":"trip-1"}]')
            self.assertEqual(
                env["UI_AI_MODEL_HUB_BENCHMARK_MODEL_PATHS"],
                "/mobility/lightgbm_previous_delay,/mobility/randomforest_previous_delay",
            )
            self.assertEqual(env["UI_AI_MODEL_HUB_BENCHMARKING_DEMO"], "0")

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
