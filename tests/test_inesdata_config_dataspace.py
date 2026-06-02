import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from adapters.inesdata.config import INESDataConfigAdapter, InesdataConfig


class DataspaceAwareConfig:
    DS_NAME = "demo"

    def __init__(self, root):
        self.root = root

    def deployer_config_path(self):
        return os.path.join(self.root, "deployer.config")


class InesdataConfigDataspaceTests(unittest.TestCase):
    def test_default_deployer_config_paths_are_adapter_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            InesdataConfig,
            "script_dir",
            return_value=tmpdir,
        ):
            self.assertEqual(
                InesdataConfig.deployer_config_path(),
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
            )
            self.assertEqual(
                InesdataConfig.deployer_config_example_path(),
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config.example"),
            )
            self.assertEqual(
                InesdataConfig.infrastructure_deployer_config_path(),
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
            )

    def test_infrastructure_deployer_config_example_uses_shared_auth_hostnames(self):
        example_path = os.path.join(
            InesdataConfig.script_dir(),
            "deployers",
            "infrastructure",
            "deployer.config.example",
        )

        with open(example_path, "r", encoding="utf-8") as handle:
            config_text = handle.read()

        self.assertIn("KC_URL=http://admin.auth.dev.ed.dataspaceunit.upm\n", config_text)
        self.assertIn("KC_INTERNAL_URL=http://auth.dev.ed.dataspaceunit.upm\n", config_text)
        self.assertIn("KEYCLOAK_HOSTNAME=auth.dev.ed.dataspaceunit.upm\n", config_text)
        self.assertIn("KEYCLOAK_ADMIN_HOSTNAME=admin.auth.dev.ed.dataspaceunit.upm\n", config_text)

    def test_load_deployer_config_uses_infrastructure_base_and_adapter_overlay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("KC_URL=http://shared-keycloak\nDS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n")
            with open(
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("DS_1_NAME=demo\nDS_1_NAMESPACE=demo\n")

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            config = INESDataConfigAdapter(TempConfig).load_deployer_config()

        self.assertEqual(config["KC_URL"], "http://shared-keycloak")
        self.assertEqual(config["DS_DOMAIN_BASE"], "dev.ds.dataspaceunit.upm")
        self.assertEqual(config["DS_1_NAME"], "demo")

    def test_load_deployer_config_includes_identity_branding_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "identity"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("KC_URL=http://shared-keycloak\n")
            with open(
                os.path.join(tmpdir, "identity", "branding.config.example"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("INESDATA_BRAND_LOGO_FILES=pionera-logo.svg\n")
            with open(
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("DS_1_NAME=demo\n")

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            config = INESDataConfigAdapter(TempConfig).load_deployer_config()

        self.assertEqual(config["INESDATA_BRAND_LOGO_FILES"], "pionera-logo.svg")

    def test_load_deployer_config_identity_branding_overrides_example(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "identity"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("")
            with open(
                os.path.join(tmpdir, "identity", "branding.config.example"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("INESDATA_BRAND_NAME=PIONERA\n")
            with open(
                os.path.join(tmpdir, "identity", "branding.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("INESDATA_BRAND_NAME=CustomBrand\n")
            with open(
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("DS_1_NAME=demo\n")

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            config = INESDataConfigAdapter(TempConfig).load_deployer_config()

        self.assertEqual(config["INESDATA_BRAND_NAME"], "CustomBrand")

    def test_dataspace_database_names_match_bootstrap_normalization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("DS_1_NAME=pionera-edc\nDS_1_NAMESPACE=edc-control\n")

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            self.assertEqual(TempConfig.sql_dataspace_name(), "pionera_edc")
            self.assertEqual(TempConfig.registration_db_name(), "pionera_edc_rs")
            self.assertEqual(TempConfig.registration_db_user(), "pionera_edc_rsusr")
            self.assertEqual(TempConfig.webportal_db_name(), "pionera_edc_wp")
            self.assertEqual(TempConfig.webportal_db_user(), "pionera_edc_wpusr")

    def test_load_deployer_config_includes_topology_overlays_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure", "topologies"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata", "topologies"), exist_ok=True)
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
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("DS_1_NAME=demo\nDS_1_NAMESPACE=demo\n")
            with open(
                os.path.join(tmpdir, "deployers", "inesdata", "topologies", "vm-single.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("COMPONENTS=ontology-hub\n")

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            config = INESDataConfigAdapter(TempConfig, topology="vm-single").load_deployer_config()

        self.assertEqual(config["KC_URL"], "http://shared-keycloak")
        self.assertEqual(config["VM_EXTERNAL_IP"], "192.0.2.10")
        self.assertEqual(config["DS_1_NAME"], "demo")
        self.assertEqual(config["COMPONENTS"], "ontology-hub")

    def test_load_deployer_config_keeps_infrastructure_credentials_over_adapter_placeholders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("VT_TOKEN=real-vault-token\nPG_PASSWORD=real-db-password\n")
            with open(
                os.path.join(tmpdir, "deployers", "inesdata", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("VT_TOKEN=X\nPG_PASSWORD=CHANGE_ME\nDS_1_NAME=demo\n")

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            config = INESDataConfigAdapter(TempConfig).load_deployer_config()

        self.assertEqual(config["VT_TOKEN"], "real-vault-token")
        self.assertEqual(config["PG_PASSWORD"], "real-db-password")
        self.assertEqual(config["DS_1_NAME"], "demo")

    def test_foundation_minikube_runtime_prefers_shared_infrastructure_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "MINIKUBE_DRIVER=kvm2\n"
                    "MINIKUBE_CPUS=4\n"
                    "MINIKUBE_MEMORY=8192\n"
                    "MINIKUBE_PROFILE=ubuntu-vm\n"
                )

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            runtime = INESDataConfigAdapter(TempConfig).foundation_minikube_runtime()

        self.assertEqual(
            runtime,
            {
                "driver": "kvm2",
                "cpus": "4",
                "memory": "8192",
                "profile": "ubuntu-vm",
                "local_resource_profile": "",
            },
        )

    def test_foundation_minikube_runtime_allows_pionera_environment_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "MINIKUBE_DRIVER=docker\n"
                    "MINIKUBE_CPUS=4\n"
                    "MINIKUBE_MEMORY=8192\n"
                    "MINIKUBE_PROFILE=minikube\n"
                )

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            with mock.patch.dict(
                os.environ,
                {
                    "PIONERA_MINIKUBE_CPUS": "6",
                    "PIONERA_MINIKUBE_MEMORY": "16384",
                    "PIONERA_MINIKUBE_PROFILE": "vm-override",
                },
                clear=False,
            ):
                runtime = INESDataConfigAdapter(TempConfig).foundation_minikube_runtime()

        self.assertEqual(runtime["driver"], "docker")
        self.assertEqual(runtime["cpus"], "6")
        self.assertEqual(runtime["memory"], "16384")
        self.assertEqual(runtime["profile"], "vm-override")

    def test_cluster_runtime_preserves_vm_single_minikube_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            runtime = INESDataConfigAdapter(TempConfig, topology="vm-single").cluster_runtime()

        self.assertEqual(runtime["cluster_type"], "minikube")
        self.assertEqual(runtime["k3s_kubeconfig"], "/etc/rancher/k3s/k3s.yaml")

    def test_cluster_runtime_reads_vm_single_k3s_overlay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "deployers", "infrastructure", "topologies"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "deployers", "inesdata"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "deployer.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("ENVIRONMENT=DEV\n")
            with open(
                os.path.join(tmpdir, "deployers", "infrastructure", "topologies", "vm-single.config"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("CLUSTER_TYPE=k3s\nK3S_KUBECONFIG=/tmp/k3s.yaml\n")

            class TempConfig(InesdataConfig):
                @classmethod
                def script_dir(cls):
                    return tmpdir

            runtime = INESDataConfigAdapter(TempConfig, topology="vm-single").cluster_runtime()

        self.assertEqual(runtime["cluster_type"], "k3s")
        self.assertEqual(runtime["k3s_kubeconfig"], "/tmp/k3s.yaml")

    def test_primary_dataspace_name_prefers_deployer_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pilot\n")

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(adapter.primary_dataspace_name(), "pilot")

    def test_primary_dataspace_namespace_prefers_deployer_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pilot\nDS_1_NAMESPACE=pilot-ns\n")

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(adapter.primary_dataspace_namespace(), "pilot-ns")

    def test_primary_dataspace_namespace_falls_back_to_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pilot\n")

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(adapter.primary_dataspace_namespace(), "pilot")

    def test_primary_registration_service_namespace_prefers_deployer_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pilot\nDS_1_REGISTRATION_NAMESPACE=pilot-core\n")

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(adapter.primary_registration_service_namespace(), "pilot-core")

    def test_primary_registration_service_namespace_derives_role_aligned_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pilot\nNAMESPACE_PROFILE=role-aligned\n")

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(adapter.primary_registration_service_namespace(), "pilot-core")

    def test_primary_provider_and_consumer_namespaces_follow_active_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=pilot\n"
                    "DS_1_NAMESPACE=pilot\n"
                    "NAMESPACE_PROFILE=role-aligned\n"
                )

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(adapter.primary_provider_namespace(), "pilot")
            self.assertEqual(adapter.primary_consumer_namespace(), "pilot")

    def test_namespace_plan_for_dataspace_preserves_role_aligned_preview_for_level4(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=pilot\n"
                    "DS_1_NAMESPACE=pilot\n"
                    "NAMESPACE_PROFILE=role-aligned\n"
                )

            adapter = INESDataConfigAdapter(config)
            plan = adapter.namespace_plan_for_dataspace(ds_name="pilot", ds_namespace="pilot", ds_index=1)

            self.assertEqual(plan["namespace_profile"], "role-aligned")
            self.assertEqual(plan["namespace_roles"].registration_service_namespace, "pilot-core")
            self.assertEqual(plan["namespace_roles"].provider_namespace, "pilot")
            self.assertEqual(plan["namespace_roles"].consumer_namespace, "pilot")
            self.assertEqual(plan["planned_namespace_roles"].provider_namespace, "pilot-provider")
            self.assertEqual(plan["planned_namespace_roles"].consumer_namespace, "pilot-consumer")

    def test_registration_service_internal_hostname_uses_short_name_in_compact_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write("DS_1_NAME=pilot\nDS_1_NAMESPACE=pilot\n")

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(
                adapter.registration_service_internal_hostname(ds_name="pilot", connector_namespace="pilot"),
                "pilot-registration-service:8080",
            )

    def test_host_alias_domains_use_requested_dataspace_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=demo\n"
                    "DS_1_NAMESPACE=demo\n"
                    "DS_2_NAME=pilot\n"
                    "DS_2_NAMESPACE=pilot\n"
                    "DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n"
                )

            adapter = INESDataConfigAdapter(config)

            self.assertIn(
                "registration-service-pilot.dev.ds.dataspaceunit.upm",
                adapter.host_alias_domains(ds_name="pilot"),
            )

    def test_registration_service_internal_hostname_uses_fqdn_when_registration_namespace_differs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=pilot\n"
                    "DS_1_NAMESPACE=pilot\n"
                    "NAMESPACE_PROFILE=role-aligned\n"
                )

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(
                adapter.registration_service_internal_hostname(ds_name="pilot", connector_namespace="pilot"),
                "pilot-registration-service.pilot-core.svc.cluster.local:8080",
            )

    def test_host_alias_domains_use_synced_common_service_hostnames(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=pilot\n"
                    "DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n"
                    "KEYCLOAK_HOSTNAME=auth.dev.ed.dataspaceunit.upm\n"
                    "KEYCLOAK_ADMIN_HOSTNAME=admin.auth.dev.ed.dataspaceunit.upm\n"
                    "MINIO_HOSTNAME=minio.dev.ed.dataspaceunit.upm\n"
                    "MINIO_CONSOLE_HOSTNAME=console.minio-s3.dev.ed.dataspaceunit.upm\n"
                )

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(
                adapter.host_alias_domains(ds_name="pilot"),
                [
                    "auth.dev.ed.dataspaceunit.upm",
                    "admin.auth.dev.ed.dataspaceunit.upm",
                    "minio.dev.ed.dataspaceunit.upm",
                    "console.minio-s3.dev.ed.dataspaceunit.upm",
                    "pilot.dev.ds.dataspaceunit.upm",
                    "backend-pilot.dev.ds.dataspaceunit.upm",
                    "registration-service-pilot.dev.ds.dataspaceunit.upm",
                ],
            )

    def test_generate_hosts_uses_synced_common_service_hostnames(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=pilot\n"
                    "DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n"
                    "KEYCLOAK_HOSTNAME=auth.dev.ed.dataspaceunit.upm\n"
                    "KEYCLOAK_ADMIN_HOSTNAME=admin.auth.dev.ed.dataspaceunit.upm\n"
                    "MINIO_HOSTNAME=minio.dev.ed.dataspaceunit.upm\n"
                    "MINIO_CONSOLE_HOSTNAME=console.minio-s3.dev.ed.dataspaceunit.upm\n"
                )

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(
                adapter.generate_hosts(ds_name="pilot"),
                [
                    "127.0.0.1 auth.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 admin.auth.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 minio.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 console.minio-s3.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 pilot.dev.ds.dataspaceunit.upm",
                    "127.0.0.1 backend-pilot.dev.ds.dataspaceunit.upm",
                    "127.0.0.1 registration-service-pilot.dev.ds.dataspaceunit.upm",
                ],
            )

    def test_generate_hosts_promote_legacy_keycloak_hostnames_to_canonical_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=pilot\n"
                    "DS_DOMAIN_BASE=dev.ds.dataspaceunit.upm\n"
                    "DOMAIN_BASE=dev.ed.dataspaceunit.upm\n"
                    "KEYCLOAK_HOSTNAME=keycloak.dev.ed.dataspaceunit.upm\n"
                    "KEYCLOAK_ADMIN_HOSTNAME=keycloak-admin.dev.ed.dataspaceunit.upm\n"
                )

            adapter = INESDataConfigAdapter(config)

            self.assertEqual(
                adapter.generate_hosts(ds_name="pilot"),
                [
                    "127.0.0.1 auth.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 admin.auth.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 minio.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 console.minio-s3.dev.ed.dataspaceunit.upm",
                    "127.0.0.1 pilot.dev.ds.dataspaceunit.upm",
                    "127.0.0.1 backend-pilot.dev.ds.dataspaceunit.upm",
                    "127.0.0.1 registration-service-pilot.dev.ds.dataspaceunit.upm",
                ],
            )

    def test_prefixed_environment_overrides_can_isolate_the_active_dataspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DataspaceAwareConfig(tmpdir)
            with open(config.deployer_config_path(), "w", encoding="utf-8") as handle:
                handle.write(
                    "DS_1_NAME=demo\n"
                    "DS_1_NAMESPACE=demo\n"
                    "DS_1_CONNECTORS=citycouncil,company\n"
                )

            with mock.patch.dict(
                os.environ,
                {
                    "PIONERA_DS_1_NAME": "demoedc",
                    "PIONERA_DS_1_NAMESPACE": "demoedc",
                    "PIONERA_DS_1_CONNECTORS": "citycounciledc,companyedc",
                },
                clear=False,
            ):
                adapter = INESDataConfigAdapter(config)

                self.assertEqual(adapter.primary_dataspace_name(), "demoedc")
                self.assertEqual(adapter.primary_dataspace_namespace(), "demoedc")
                self.assertEqual(
                    adapter.load_deployer_config()["DS_1_CONNECTORS"],
                    "citycounciledc,companyedc",
                )


if __name__ == "__main__":
    unittest.main()
