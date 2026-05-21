import unittest
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class INESDataProjectCatalogTests(unittest.TestCase):
    def test_external_project_scaffolds_are_not_level6_default_coverage(self):
        for relative_path in [
            "validation/projects/inesdata/linguistic/test_cases.yaml",
            "validation/projects/inesdata/mobility/test_cases.yaml",
        ]:
            with self.subTest(path=relative_path):
                catalog = yaml.safe_load((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
                cases = catalog.get("cases") or []

                self.assertGreater(len(cases), 0)
                for case in cases:
                    self.assertEqual(case["coverage_status"], "scaffold_external_target")
                    self.assertEqual(case["mapping_status"], "external_project_scaffold")
                    self.assertEqual(case["execution_mode"], "read_only_target_scaffold")
                    self.assertEqual(case["automation"]["status"], "proposed")
                    self.assertFalse(case["automation"]["enabled_by_default"])

    def test_project_suites_keep_only_integration_active_by_default(self):
        project_suites = yaml.safe_load(
            (PROJECT_ROOT / "validation/projects/inesdata/project_suites.yaml").read_text(encoding="utf-8")
        )
        suites = project_suites["suites"]

        self.assertEqual(suites["integration"]["status"], "active")
        self.assertEqual(suites["integration"]["execution"], "level6_default")
        self.assertEqual(suites["linguistic"]["status"], "scaffold")
        self.assertEqual(suites["mobility"]["status"], "scaffold")


if __name__ == "__main__":
    unittest.main()
