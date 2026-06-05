import unittest

from deployers.shared.lib import local_images
from deployers.shared.lib.topology import LOCAL_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY, VM_SINGLE_TOPOLOGY


class LocalImagePolicyTests(unittest.TestCase):
    def test_level4_default_mode_is_auto_only_for_local(self):
        self.assertEqual(local_images.default_level4_mode(LOCAL_TOPOLOGY), "auto")
        self.assertEqual(local_images.default_level4_mode(VM_SINGLE_TOPOLOGY), "disabled")
        self.assertEqual(local_images.default_level4_mode(VM_DISTRIBUTED_TOPOLOGY), "disabled")

    def test_level4_mode_normalization_keeps_existing_aliases(self):
        self.assertEqual(local_images.normalize_level4_mode("false"), "disabled")
        self.assertEqual(local_images.normalize_level4_mode("disable"), "disabled")
        self.assertEqual(local_images.normalize_level4_mode("true"), "auto")
        self.assertEqual(local_images.normalize_level4_mode("auto"), "auto")
        self.assertEqual(local_images.normalize_level4_mode("strict"), "required")
        self.assertEqual(local_images.normalize_level4_mode("unexpected"), "auto")

    def test_level4_policy_allows_supported_topologies(self):
        for topology in (LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY):
            policy = local_images.resolve_level4_policy(
                topology=topology,
                mode="auto",
                label="INESData",
                supported_topologies={LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY},
                vm_distributed_remote_import_configured=False,
            )

            self.assertTrue(policy["prepare_local_images"])
            self.assertTrue(policy["allow_local_image_overrides"])
            self.assertEqual(policy["error"], "")

    def test_level4_policy_allows_vm_distributed_only_when_remote_import_is_configured(self):
        policy = local_images.resolve_level4_policy(
            topology=VM_DISTRIBUTED_TOPOLOGY,
            mode="auto",
            label="INESData",
            supported_topologies={LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY},
            vm_distributed_remote_import_configured=True,
        )

        self.assertTrue(policy["prepare_local_images"])
        self.assertIn("remote k3s image import", policy["message"])

    def test_level4_required_policy_reports_unsupported_topology_error(self):
        policy = local_images.resolve_level4_policy(
            topology=VM_DISTRIBUTED_TOPOLOGY,
            mode="required",
            label="INESData",
            supported_topologies={LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY},
            vm_distributed_remote_import_configured=False,
        )

        self.assertFalse(policy["prepare_local_images"])
        self.assertIn("mode 'required' is only supported", policy["error"])

    def test_level5_auto_build_defaults_to_false_for_vm_topologies(self):
        self.assertTrue(local_images.level5_auto_build_enabled({}, topology=LOCAL_TOPOLOGY, environ={}))
        self.assertFalse(local_images.level5_auto_build_enabled({}, topology=VM_SINGLE_TOPOLOGY, environ={}))
        self.assertFalse(local_images.level5_auto_build_enabled({}, topology=VM_DISTRIBUTED_TOPOLOGY, environ={}))

    def test_level5_auto_build_can_be_overridden_by_config_or_environment(self):
        self.assertTrue(
            local_images.level5_auto_build_enabled(
                {"LEVEL5_AUTO_BUILD_LOCAL_IMAGES": "true"},
                topology=VM_SINGLE_TOPOLOGY,
                environ={},
            )
        )
        self.assertTrue(
            local_images.level5_auto_build_enabled(
                {},
                topology=VM_DISTRIBUTED_TOPOLOGY,
                environ={"LEVEL6_AUTO_BUILD_LOCAL_IMAGES": "true"},
            )
        )

    def test_level5_assume_local_images_available_reads_config_before_environment(self):
        self.assertTrue(
            local_images.assume_level5_local_images_available(
                {"LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE": "true"},
                {"LEVEL5_ASSUME_LOCAL_IMAGES_AVAILABLE": "false"},
            )
        )
        self.assertTrue(
            local_images.assume_level5_local_images_available(
                {},
                {"LEVEL6_ASSUME_LOCAL_IMAGES_AVAILABLE": "true"},
            )
        )


if __name__ == "__main__":
    unittest.main()
