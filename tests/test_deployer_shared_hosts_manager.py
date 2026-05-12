import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.contracts import DeploymentContext, NamespaceRoles
from deployers.shared.lib.hosts_manager import (
    HostEntry,
    apply_managed_blocks,
    blocks_as_dict,
    build_context_host_blocks,
    detect_legacy_external_hostnames,
    hostnames_by_level,
    merge_missing_managed_blocks,
    parse_hostnames,
    render_managed_block,
    upsert_managed_block,
)
from deployers.shared.lib.topology import build_topology_profile


class SharedHostsManagerTests(unittest.TestCase):
    def test_render_managed_block_uses_validation_environment_markers(self):
        block = render_managed_block(
            "dataspace demoedc",
            [
                HostEntry("127.0.0.1", "registration-service-demoedc.dev.ds.dataspaceunit.upm"),
                "127.0.0.1 conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
            ],
        )

        self.assertIn("# BEGIN Validation-Environment dataspace demoedc", block)
        self.assertIn("# END Validation-Environment dataspace demoedc", block)
        self.assertIn("127.0.0.1 registration-service-demoedc.dev.ds.dataspaceunit.upm", block)
        self.assertIn("127.0.0.1 conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm", block)

    def test_upsert_managed_block_replaces_existing_section(self):
        original = (
            "# BEGIN Validation-Environment dataspace demoedc\n"
            "127.0.0.1 old-entry.example\n"
            "# END Validation-Environment dataspace demoedc\n"
        )

        updated = upsert_managed_block(
            original,
            "dataspace demoedc",
            [HostEntry("127.0.0.1", "registration-service-demoedc.dev.ds.dataspaceunit.upm")],
        )

        self.assertNotIn("old-entry.example", updated)
        self.assertIn("registration-service-demoedc.dev.ds.dataspaceunit.upm", updated)

    def test_upsert_managed_block_appends_new_section(self):
        existing = "127.0.0.1 localhost\n"

        updated = upsert_managed_block(
            existing,
            "shared",
            [HostEntry("127.0.0.1", "auth.dev.ed.dataspaceunit.upm")],
        )

        self.assertIn("127.0.0.1 localhost", updated)
        self.assertIn("# BEGIN Validation-Environment shared", updated)
        self.assertIn("127.0.0.1 auth.dev.ed.dataspaceunit.upm", updated)

    def test_build_context_host_blocks_groups_entries_by_level(self):
        context = DeploymentContext(
            deployer="edc",
            topology="local",
            environment="DEV",
            dataspace_name="demoedc",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=[
                "conn-citycounciledc-demoedc",
                "conn-companyedc-demoedc",
            ],
            components=["ontology-hub", "ai-model-hub-demoedc"],
            namespace_roles=NamespaceRoles(
                registration_service_namespace="demoedc",
                provider_namespace="demoedc",
                consumer_namespace="demoedc",
            ),
            config={
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KEYCLOAK_HOSTNAME": "keycloak.dev.ed.dataspaceunit.upm",
                "MINIO_HOSTNAME": "minio.dev.ed.dataspaceunit.upm",
                "KC_URL": "http://keycloak-admin.dev.ed.dataspaceunit.upm",
            },
        )

        blocks = build_context_host_blocks(context)
        levels = hostnames_by_level(blocks)

        self.assertIn("auth.dev.ed.dataspaceunit.upm", levels["level_1_2"])
        self.assertIn("admin.auth.dev.ed.dataspaceunit.upm", levels["level_1_2"])
        self.assertIn("console.minio-s3.dev.ed.dataspaceunit.upm", levels["level_1_2"])
        self.assertEqual(
            levels["level_3"],
            ["registration-service-demoedc.dev.ds.dataspaceunit.upm"],
        )
        self.assertEqual(
            levels["level_4"],
            [
                "conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm",
                "conn-companyedc-demoedc.dev.ds.dataspaceunit.upm",
            ],
        )
        self.assertEqual(
            levels["level_5"],
            [
                "ontology-hub-demoedc.dev.ds.dataspaceunit.upm",
                "ai-model-hub-demoedc.dev.ds.dataspaceunit.upm",
            ],
        )

    def test_build_context_host_blocks_uses_topology_role_addresses(self):
        context = DeploymentContext(
            deployer="edc",
            topology="vm-distributed",
            environment="DEV",
            dataspace_name="demoedc",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=["conn-citycounciledc-demoedc"],
            components=["ontology-hub"],
            topology_profile=build_topology_profile(
                "vm-distributed",
                {
                    "VM_COMMON_IP": "192.0.2.10",
                    "VM_DATASPACE_IP": "192.0.2.11",
                    "VM_CONNECTORS_IP": "192.0.2.12",
                    "VM_COMPONENTS_IP": "192.0.2.13",
                },
            ),
            config={
                "DOMAIN_BASE": "dev.ed.dataspaceunit.upm",
                "KEYCLOAK_HOSTNAME": "keycloak.dev.ed.dataspaceunit.upm",
            },
        )

        rendered = blocks_as_dict(build_context_host_blocks(context))

        self.assertIn("192.0.2.10 auth.dev.ed.dataspaceunit.upm", rendered["shared common"])
        self.assertEqual(
            rendered["dataspace demoedc"],
            ["192.0.2.11 registration-service-demoedc.dev.ds.dataspaceunit.upm"],
        )
        self.assertEqual(
            rendered["connectors edc demoedc"],
            ["192.0.2.12 conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm"],
        )
        self.assertEqual(
            rendered["components demoedc"],
            ["192.0.2.13 ontology-hub-demoedc.dev.ds.dataspaceunit.upm"],
        )

    def test_apply_managed_blocks_updates_hosts_file_idempotently(self):
        context = DeploymentContext(
            deployer="edc",
            topology="local",
            environment="DEV",
            dataspace_name="demoedc",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=["conn-citycounciledc-demoedc"],
        )
        blocks = build_context_host_blocks(context)

        with self.subTest("first update"):
            import tempfile

            with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as handle:
                handle.write("127.0.0.1 localhost\n")
                handle.flush()

                first = apply_managed_blocks(handle.name, blocks)
                second = apply_managed_blocks(handle.name, blocks)
                handle.seek(0)
                content = handle.read()

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertIn("# BEGIN Validation-Environment dataspace demoedc", content)
        self.assertIn("conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm", content)

    def test_apply_managed_blocks_rewrites_managed_common_block_with_canonical_hostnames(self):
        context = DeploymentContext(
            deployer="edc",
            topology="local",
            environment="DEV",
            dataspace_name="",
            ds_domain_base="",
            config={"DOMAIN_BASE": "dev.ed.dataspaceunit.upm"},
        )
        blocks = build_context_host_blocks(context)
        existing = (
            "127.0.0.1 localhost\n"
            "# BEGIN Validation-Environment shared common\n"
            "127.0.0.1 keycloak.dev.ed.dataspaceunit.upm\n"
            "127.0.0.1 keycloak-admin.dev.ed.dataspaceunit.upm\n"
            "127.0.0.1 minio.dev.ed.dataspaceunit.upm\n"
            "# END Validation-Environment shared common\n"
        )

        with self.subTest("managed block rewritten"):
            import tempfile

            with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as handle:
                handle.write(existing)
                handle.flush()

                result = apply_managed_blocks(handle.name, blocks, config=context.config)
                handle.seek(0)
                content = handle.read()

        self.assertTrue(result["changed"])
        self.assertIn("127.0.0.1 auth.dev.ed.dataspaceunit.upm", content)
        self.assertIn("127.0.0.1 admin.auth.dev.ed.dataspaceunit.upm", content)
        self.assertNotIn("127.0.0.1 keycloak.dev.ed.dataspaceunit.upm", content)
        self.assertNotIn("127.0.0.1 keycloak-admin.dev.ed.dataspaceunit.upm", content)

    def test_apply_managed_blocks_skips_entries_already_present_outside_managed_blocks(self):
        context = DeploymentContext(
            deployer="edc",
            topology="local",
            environment="DEV",
            dataspace_name="demoedc",
            ds_domain_base="dev.ds.dataspaceunit.upm",
            connectors=[
                "conn-citycounciledc-demoedc",
                "conn-companyedc-demoedc",
            ],
            config={"DOMAIN_BASE": "dev.ed.dataspaceunit.upm"},
        )
        blocks = build_context_host_blocks(context)
        existing = (
            "127.0.0.1 localhost\n"
            "127.0.0.1 auth.dev.ed.dataspaceunit.upm\n"
            "127.0.0.1 registration-service-demoedc.dev.ds.dataspaceunit.upm\n"
            "127.0.0.1 conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm\n"
            "# BEGIN Validation-Environment dataspace demoedc\n"
            "127.0.0.1 registration-service-demoedc.dev.ds.dataspaceunit.upm\n"
            "# END Validation-Environment dataspace demoedc\n"
            "# BEGIN Validation-Environment connectors edc demoedc\n"
            "127.0.0.1 conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm\n"
            "127.0.0.1 conn-companyedc-demoedc.dev.ds.dataspaceunit.upm\n"
            "# END Validation-Environment connectors edc demoedc\n"
        )

        updated, missing_blocks, skipped = merge_missing_managed_blocks(existing, blocks)

        self.assertNotIn("# BEGIN Validation-Environment dataspace demoedc", updated)
        self.assertEqual(
            updated.count("registration-service-demoedc.dev.ds.dataspaceunit.upm"),
            1,
        )
        self.assertEqual(
            updated.count("conn-citycounciledc-demoedc.dev.ds.dataspaceunit.upm"),
            1,
        )
        self.assertEqual(
            updated.count("conn-companyedc-demoedc.dev.ds.dataspaceunit.upm"),
            1,
        )
        self.assertIn("connectors edc demoedc", {block.name for block in missing_blocks})
        self.assertIn("dataspace demoedc", skipped)
        self.assertIn("connectors edc demoedc", skipped)

    def test_detect_legacy_external_hostnames_reports_common_service_aliases(self):
        existing = (
            "127.0.0.1 localhost\n"
            "127.0.0.1 keycloak.dev.ed.dataspaceunit.upm\n"
            "127.0.0.1 keycloak-admin.dev.ed.dataspaceunit.upm\n"
        )

        warnings = detect_legacy_external_hostnames(
            existing,
            block_names=["shared common"],
            config={"DOMAIN_BASE": "dev.ed.dataspaceunit.upm"},
        )

        self.assertEqual(
            warnings,
            [
                {
                    "legacy": "keycloak.dev.ed.dataspaceunit.upm",
                    "canonical": "auth.dev.ed.dataspaceunit.upm",
                },
                {
                    "legacy": "keycloak-admin.dev.ed.dataspaceunit.upm",
                    "canonical": "admin.auth.dev.ed.dataspaceunit.upm",
                },
            ],
        )

    def test_parse_hostnames_supports_aliases_and_comments(self):
        hostnames = parse_hostnames(
            "127.0.0.1 first.local second.local # comment\n"
            "# 127.0.0.1 ignored.local\n"
        )

        self.assertEqual(hostnames, {"first.local", "second.local"})


if __name__ == "__main__":
    unittest.main()
