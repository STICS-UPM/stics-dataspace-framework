import os
import unittest

import yaml


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CATALOG_PATH = os.path.join(
    PROJECT_ROOT,
    "validation",
    "components",
    "semantic_virtualization",
    "test_cases.yaml",
)


class SemanticVirtualizationTestCasesCatalogTests(unittest.TestCase):
    def _load_catalog(self):
        with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def test_catalog_declares_all_pt5_vs_cases_from_a52_scope(self):
        catalog = self._load_catalog()
        cases = catalog.get("test_cases") or []
        case_ids = {case.get("id") for case in cases}

        self.assertEqual(len(cases), 12)
        self.assertEqual(
            case_ids,
            {f"PT5-VS-{index:02d}" for index in range(1, 13)},
        )

    def test_catalog_marks_currently_automated_semantic_virtualization_cases(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        self.assertEqual(cases["PT5-VS-01"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-02"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-03"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-04"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-05"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-06"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-07"]["automation"]["status"], "automated_opt_in")
        self.assertEqual(cases["PT5-VS-08"]["automation"]["status"], "automated_opt_in")
        self.assertEqual(cases["PT5-VS-09"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-10"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-11"]["automation"]["status"], "automated_opt_in")
        self.assertEqual(cases["PT5-VS-12"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-12"]["automation"]["evidence_case"], "SV-API-04")

    def test_catalog_keeps_editor_dependent_cases_explicitly_opt_in(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        self.assertEqual(cases["PT5-VS-07"]["execution_mode"], "ui_opt_in")
        self.assertEqual(cases["PT5-VS-08"]["execution_mode"], "ui_opt_in")
        self.assertEqual(
            cases["PT5-VS-07"]["automation"]["enable_with"],
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI=1",
        )
        self.assertEqual(
            cases["PT5-VS-08"]["automation"]["enable_with"],
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI=1",
        )

    def test_catalog_declares_extended_mapping_editor_ui_demo_cases(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("ui_demo_cases") or []}

        self.assertEqual(set(cases), {"SV-UI-04", "SV-UI-05", "SV-UI-06"})
        self.assertEqual(cases["SV-UI-04"]["automation"]["status"], "automated_opt_in")
        self.assertEqual(cases["SV-UI-05"]["automation"]["status"], "automated_opt_in")
        self.assertEqual(cases["SV-UI-06"]["automation"]["status"], "automated_opt_in")
        self.assertEqual(
            cases["SV-UI-06"]["automation"]["enable_with"],
            "SEMANTIC_VIRTUALIZATION_MAPPING_EDITOR_UI=1",
        )
        self.assertIn("PT5-VS-09", cases["SV-UI-06"]["linked_pt5_cases"])


if __name__ == "__main__":
    unittest.main()
