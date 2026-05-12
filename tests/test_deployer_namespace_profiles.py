import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deployers.shared.lib.namespaces import (
    COMPACT_NAMESPACE_PROFILE,
    ROLE_ALIGNED_NAMESPACE_PROFILE,
    normalize_namespace_profile,
    resolve_namespace_profile_plan,
)


class NamespaceProfileResolutionTests(unittest.TestCase):
    def test_normalize_namespace_profile_defaults_to_compact(self):
        self.assertEqual(normalize_namespace_profile(""), COMPACT_NAMESPACE_PROFILE)
        self.assertEqual(normalize_namespace_profile(None), COMPACT_NAMESPACE_PROFILE)
        self.assertEqual(normalize_namespace_profile("unsupported"), COMPACT_NAMESPACE_PROFILE)

    def test_normalize_namespace_profile_accepts_role_aligned_aliases(self):
        self.assertEqual(normalize_namespace_profile("role-aligned"), ROLE_ALIGNED_NAMESPACE_PROFILE)
        self.assertEqual(normalize_namespace_profile("role_aligned"), ROLE_ALIGNED_NAMESPACE_PROFILE)
        self.assertEqual(normalize_namespace_profile("aligned"), ROLE_ALIGNED_NAMESPACE_PROFILE)

    def test_compact_profile_keeps_execution_and_planned_roles_equal(self):
        plan = resolve_namespace_profile_plan(
            {"DS_1_PROVIDER_NAMESPACE": "demo"},
            dataspace_name="demo",
            dataspace_namespace="demo",
        )

        self.assertEqual(plan["namespace_profile"], COMPACT_NAMESPACE_PROFILE)
        self.assertEqual(plan["namespace_roles"].registration_service_namespace, "demo")
        self.assertEqual(plan["planned_namespace_roles"].registration_service_namespace, "demo")
        self.assertEqual(plan["planned_namespace_roles"].provider_namespace, "demo")
        self.assertEqual(plan["planned_namespace_roles"].consumer_namespace, "demo")

    def test_role_aligned_profile_keeps_execution_compact_but_exposes_planned_roles(self):
        plan = resolve_namespace_profile_plan(
            {"NAMESPACE_PROFILE": "role-aligned"},
            dataspace_name="demo",
            dataspace_namespace="demo",
        )

        self.assertEqual(plan["namespace_profile"], ROLE_ALIGNED_NAMESPACE_PROFILE)
        self.assertEqual(plan["namespace_roles"].registration_service_namespace, "demo-core")
        self.assertEqual(plan["namespace_roles"].provider_namespace, "demo")
        self.assertEqual(plan["namespace_roles"].consumer_namespace, "demo")
        self.assertEqual(plan["planned_namespace_roles"].registration_service_namespace, "demo-core")
        self.assertEqual(plan["planned_namespace_roles"].provider_namespace, "demo-provider")
        self.assertEqual(plan["planned_namespace_roles"].consumer_namespace, "demo-consumer")


if __name__ == "__main__":
    unittest.main()
