import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.edc.config import EDCConfigAdapter, EdcConfig


class EdcConfigPathTests(unittest.TestCase):
    def _clear_pionera_overrides(self):
        keys = [key for key in os.environ if key.startswith("PIONERA_")]
        previous = {key: os.environ.get(key) for key in keys}
        for key in keys:
            os.environ.pop(key, None)
        return previous

    @staticmethod
    def _restore_environment(previous):
        for key in [key for key in os.environ if key.startswith("PIONERA_")]:
            os.environ.pop(key, None)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_edc_adapter_paths_are_resolved_from_the_repository_root(self):
        adapter = EDCConfigAdapter(EdcConfig)

        self.assertTrue(adapter.edc_adapter_dir().endswith("Validation-Environment/adapters/edc"))
        self.assertTrue(adapter.edc_scripts_dir().endswith("Validation-Environment/adapters/edc/scripts"))
        self.assertTrue(adapter.edc_sources_dir().endswith("Validation-Environment/adapters/edc/sources"))
        self.assertEqual(
            adapter.edc_reference_repo_url(),
            "https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard",
        )
        self.assertEqual(adapter.edc_reference_repo_subdir(), "asset-filter-template")
        self.assertTrue(
            adapter.edc_connector_source_dir().endswith(
                "Validation-Environment/adapters/edc/sources/connector"
            )
        )
        self.assertTrue(adapter.edc_dashboard_source_dir().endswith("Validation-Environment/adapters/edc/sources/dashboard"))
        self.assertTrue(adapter.edc_build_dir().endswith("Validation-Environment/adapters/edc/build"))
        self.assertTrue(adapter.edc_build_docker_dir().endswith("Validation-Environment/adapters/edc/build/docker"))
        self.assertTrue(
            adapter.edc_connector_dockerfile().endswith(
                "Validation-Environment/adapters/edc/build/docker/connector.Dockerfile"
            )
        )
        self.assertTrue(
            adapter.edc_dashboard_dockerfile().endswith(
                "Validation-Environment/adapters/edc/build/docker/dashboard.Dockerfile"
            )
        )
        self.assertTrue(
            adapter.edc_dashboard_proxy_dockerfile().endswith(
                "Validation-Environment/adapters/edc/build/docker/dashboard-proxy.Dockerfile"
            )
        )
        self.assertTrue(
            adapter.edc_connector_local_override_file().endswith(
                "Validation-Environment/adapters/edc/build/local-overrides/connector-local-overrides.yaml"
            )
        )
        self.assertTrue(
            adapter.edc_dashboard_local_override_file().endswith(
                "Validation-Environment/adapters/edc/build/local-overrides/dashboard-local-overrides.yaml"
            )
        )
        self.assertTrue(
            adapter.edc_dashboard_proxy_local_override_file().endswith(
                "Validation-Environment/adapters/edc/build/local-overrides/dashboard-proxy-local-overrides.yaml"
            )
        )
        self.assertTrue(
            adapter.edc_deployments_dir().endswith(
                "Validation-Environment/deployers/edc/deployments"
            )
        )
        self.assertTrue(
            adapter.edc_dataspace_runtime_dir("pionera-edc").endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc"
            )
        )
        self.assertTrue(
            adapter.config.deployer_config_path().endswith(
                "Validation-Environment/deployers/edc/deployer.config"
            )
        )
        self.assertTrue(
            adapter.config.deployer_config_example_path().endswith(
                "Validation-Environment/deployers/edc/deployer.config.example"
            )
        )
        self.assertTrue(
            adapter.edc_connector_values_file("conn-pionera-edc", ds_name="pionera-edc").endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc/values-conn-pionera-edc.yaml"
            )
        )
        self.assertTrue(
            adapter.edc_connector_certs_dir("pionera-edc").endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc/certs"
            )
        )
        self.assertTrue(
            adapter.edc_dashboard_runtime_dir("conn-pionera-edc", ds_name="pionera-edc").endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc/dashboard/conn-pionera-edc"
            )
        )
        self.assertTrue(adapter.edc_dashboard_enabled())
        self.assertEqual(adapter.edc_dashboard_base_href(), "/edc-dashboard/")
        self.assertEqual(adapter.edc_dashboard_proxy_client_id(), "dataspace-users")
        self.assertEqual(adapter.edc_dashboard_proxy_scope(), "openid profile email")
        self.assertEqual(adapter.edc_dashboard_proxy_cookie_name(), "edc_dashboard_session")
        self.assertTrue(adapter.edc_sql_schema_autocreate())

    def test_edc_connector_credentials_path_uses_edc_deployment_runtime_dir(self):
        previous = self._clear_pionera_overrides()
        try:
            path = EdcConfig.connector_credentials_path("conn-companyedc-pionera-edc")
        finally:
            self._restore_environment(previous)

        self.assertTrue(
            path.endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc/"
                "credentials-connector-conn-companyedc-pionera-edc.json"
            )
        )

    def test_edc_connector_certificates_dir_uses_edc_runtime_dir(self):
        previous = self._clear_pionera_overrides()
        try:
            path = EdcConfig.connector_certificates_dir()
        finally:
            self._restore_environment(previous)

        self.assertTrue(
            path.endswith(
                "Validation-Environment/deployers/edc/deployments/DEV/pionera-edc/certs"
            )
        )

    def test_edc_level3_database_names_use_bootstrap_sql_normalization(self):
        previous = self._clear_pionera_overrides()
        try:
            self.assertEqual(EdcConfig.sql_dataspace_name(), "pionera_edc")
            self.assertEqual(EdcConfig.registration_db_name(), "pionera_edc_rs")
            self.assertEqual(EdcConfig.registration_db_user(), "pionera_edc_rsusr")
            self.assertEqual(EdcConfig.webportal_db_name(), "pionera_edc_wp")
            self.assertEqual(EdcConfig.webportal_db_user(), "pionera_edc_wpusr")
        finally:
            self._restore_environment(previous)

    def test_edc_bootstrap_uses_edc_deployment_and_current_python_by_default(self):
        previous = self._clear_pionera_overrides()
        try:
            self.assertTrue(
                EdcConfig.repo_dir().endswith("Validation-Environment/deployers/edc")
            )
            self.assertEqual(EdcConfig.python_exec(), sys.executable)

            os.environ["PIONERA_EDC_BOOTSTRAP_PYTHON"] = "/custom/edc/python"
            self.assertEqual(EdcConfig.python_exec(), "/custom/edc/python")
        finally:
            self._restore_environment(previous)

    def test_edc_dashboard_base_href_is_normalized_from_overrides(self):
        previous = os.environ.get("PIONERA_EDC_DASHBOARD_BASE_HREF")
        os.environ["PIONERA_EDC_DASHBOARD_BASE_HREF"] = "dashboard"
        try:
            adapter = EDCConfigAdapter(EdcConfig)
            base_href = adapter.edc_dashboard_base_href()
        finally:
            if previous is None:
                os.environ.pop("PIONERA_EDC_DASHBOARD_BASE_HREF", None)
            else:
                os.environ["PIONERA_EDC_DASHBOARD_BASE_HREF"] = previous

        self.assertEqual(base_href, "/dashboard/")

    def test_edc_defaults_isolate_dataspace_when_only_shared_legacy_config_exists(self):
        previous = self._clear_pionera_overrides()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
                with open(
                    os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(
                        "KC_URL=http://keycloak.local\n"
                        "DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n"
                        "DS_1_NAME=demo\n"
                        "DS_1_NAMESPACE=demo\n"
                        "DS_1_CONNECTORS=citycouncil,company\n"
                        "COMPONENTS=ontology-hub,ai-model-hub\n"
                    )

                class TempEdcConfig(EdcConfig):
                    @classmethod
                    def script_dir(cls):
                        return tmpdir

                config = EDCConfigAdapter(TempEdcConfig).load_deployer_config()
        finally:
            self._restore_environment(previous)

        self.assertEqual(config["KC_URL"], "http://keycloak.local")
        self.assertEqual(config["DS_DOMAIN_BASE"], "dev.ds.dataspaceunit.upm")
        self.assertEqual(config["DS_1_NAME"], "pionera-edc")
        self.assertEqual(config["DS_1_NAMESPACE"], "edc-control")
        self.assertEqual(config["NAMESPACE_PROFILE"], "role-aligned")
        self.assertEqual(config["DS_1_REGISTRATION_NAMESPACE"], "edc-control")
        self.assertEqual(config["DS_1_PROVIDER_NAMESPACE"], "edc-provider")
        self.assertEqual(config["DS_1_CONSUMER_NAMESPACE"], "edc-consumer")
        self.assertEqual(config["DS_1_CONNECTORS"], "citycounciledc,companyedc")
        self.assertEqual(config["COMPONENTS"], "")
        self.assertEqual(config["EDC_DASHBOARD_ENABLED"], "true")
        self.assertEqual(config["EDC_DASHBOARD_PROXY_AUTH_MODE"], "oidc-bff")

    def test_edc_local_deployer_config_overrides_edc_defaults(self):
        previous = self._clear_pionera_overrides()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.makedirs(os.path.join(tmpdir, "deployers", "edc"), exist_ok=True)
                with open(
                    os.path.join(tmpdir, "deployers", "edc", "deployer.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(
                        "DS_1_NAME=customedc\n"
                        "DS_1_NAMESPACE=customns\n"
                        "DS_1_CONNECTORS=alpha,beta\n"
                        "EDC_DASHBOARD_ENABLED=false\n"
                    )

                class TempEdcConfig(EdcConfig):
                    @classmethod
                    def script_dir(cls):
                        return tmpdir

                adapter = EDCConfigAdapter(TempEdcConfig)
                config = adapter.load_deployer_config()
                dashboard_enabled = adapter.edc_dashboard_enabled()
        finally:
            self._restore_environment(previous)

        self.assertEqual(config["DS_1_NAME"], "customedc")
        self.assertEqual(config["DS_1_NAMESPACE"], "customns")
        self.assertEqual(config["DS_1_CONNECTORS"], "alpha,beta")
        self.assertFalse(dashboard_enabled)

    def test_edc_load_deployer_config_includes_topology_overlays_when_present(self):
        previous = self._clear_pionera_overrides()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure", "topologies"), exist_ok=True)
                os.makedirs(os.path.join(tmpdir, "deployers", "edc", "topologies"), exist_ok=True)
                with open(
                    os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write("KC_URL=http://shared-keycloak\n")
                with open(
                    os.path.join(tmpdir, "deployers", "infrastructure", "topologies", "vm-single.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write("VM_EXTERNAL_IP=192.0.2.10\n")
                with open(
                    os.path.join(tmpdir, "deployers", "edc", "topologies", "vm-single.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write("EDC_DASHBOARD_ENABLED=false\n")

                class TempEdcConfig(EdcConfig):
                    @classmethod
                    def script_dir(cls):
                        return tmpdir

                adapter = EDCConfigAdapter(TempEdcConfig, topology="vm-single")
                config = adapter.load_deployer_config()
        finally:
            self._restore_environment(previous)

        self.assertEqual(config["KC_URL"], "http://shared-keycloak")
        self.assertEqual(config["VM_EXTERNAL_IP"], "192.0.2.10")
        self.assertEqual(config["DS_1_NAME"], "pionera-edc")
        self.assertEqual(config["EDC_DASHBOARD_ENABLED"], "false")

    def test_edc_load_deployer_config_applies_topology_runtime_defaults(self):
        previous = self._clear_pionera_overrides()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure", "topologies"), exist_ok=True)
                os.makedirs(os.path.join(tmpdir, "deployers", "edc"), exist_ok=True)
                with open(
                    os.path.join(tmpdir, "deployers", "infrastructure", "topologies", "local.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(
                        "DOMAIN_BASE=dev.ed.dataspaceunit.upm\n"
                        "DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n"
                        "KEYCLOAK_HOSTNAME=auth.dev.ed.dataspaceunit.upm\n"
                        "MINIO_HOSTNAME=minio.dev.ed.dataspaceunit.upm\n"
                    )
                with open(
                    os.path.join(tmpdir, "deployers", "edc", "deployer.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write("DS_1_NAME=pionera-edc\n")

                class TempEdcConfig(EdcConfig):
                    @classmethod
                    def script_dir(cls):
                        return tmpdir

                config = EDCConfigAdapter(TempEdcConfig, topology="local").load_deployer_config()
        finally:
            self._restore_environment(previous)

        self.assertEqual(config["DATABASE_HOSTNAME"], "common-srvs-postgresql.common-srvs.svc")
        self.assertEqual(config["KEYCLOAK_HOSTNAME"], "auth.dev.ed.dataspaceunit.upm")
        self.assertEqual(config["MINIO_HOSTNAME"], "minio.dev.ed.dataspaceunit.upm")

    def test_edc_infrastructure_config_overrides_legacy_shared_config(self):
        previous = self._clear_pionera_overrides()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
                os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
                with open(
                    os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write("KC_URL=http://legacy-keycloak\nKC_PASSWORD=legacy-secret\n")
                with open(
                    os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write("KC_URL=http://shared-keycloak\nKC_PASSWORD=shared-secret\n")

                class TempEdcConfig(EdcConfig):
                    @classmethod
                    def script_dir(cls):
                        return tmpdir

                config = EDCConfigAdapter(TempEdcConfig).load_deployer_config()
        finally:
            self._restore_environment(previous)

        self.assertEqual(config["KC_URL"], "http://shared-keycloak")
        self.assertEqual(config["KC_PASSWORD"], "shared-secret")
        self.assertEqual(config["DS_1_NAME"], "pionera-edc")

    def test_edc_environment_overrides_remain_highest_priority(self):
        previous = self._clear_pionera_overrides()
        os.environ["PIONERA_DS_1_NAME"] = "overrideedc"
        os.environ["PIONERA_DS_1_NAMESPACE"] = "overridens"
        os.environ["PIONERA_DS_1_CONNECTORS"] = "overridea,overrideb"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                class TempEdcConfig(EdcConfig):
                    @classmethod
                    def script_dir(cls):
                        return tmpdir

                config = EDCConfigAdapter(TempEdcConfig).load_deployer_config()
        finally:
            self._restore_environment(previous)

        self.assertEqual(config["DS_1_NAME"], "overrideedc")
        self.assertEqual(config["DS_1_NAMESPACE"], "overridens")
        self.assertEqual(config["DS_1_CONNECTORS"], "overridea,overrideb")


if __name__ == "__main__":
    unittest.main()
