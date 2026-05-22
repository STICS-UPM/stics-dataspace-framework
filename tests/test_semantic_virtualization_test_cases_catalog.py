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
        self.assertEqual(cases["PT5-VS-07"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-08"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-09"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-10"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-11"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-12"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-VS-12"]["automation"]["evidence_case"], "SV-API-04")

    def test_catalog_marks_editor_dependent_cases_as_default_level6_ui(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        self.assertEqual(cases["PT5-VS-07"]["execution_mode"], "ui")
        self.assertEqual(cases["PT5-VS-08"]["execution_mode"], "ui")
        self.assertEqual(cases["PT5-VS-07"]["automation"]["mode"], "ui")
        self.assertEqual(cases["PT5-VS-08"]["automation"]["mode"], "ui")

    def test_catalog_declares_extended_mapping_editor_ui_demo_cases(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("ui_demo_cases") or []}

        self.assertEqual(
            set(cases),
            {"SV-UI-04", "SV-UI-05", "SV-UI-06", "SV-UI-07", "SV-UI-08", "SV-UI-10"},
        )
        self.assertEqual(cases["SV-UI-04"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-UI-05"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-UI-06"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-UI-07"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-UI-08"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-UI-10"]["automation"]["status"], "automated")
        self.assertIn("PT5-VS-09", cases["SV-UI-06"]["linked_pt5_cases"])
        self.assertIn("PT5-VS-09", cases["SV-UI-07"]["linked_pt5_cases"])
        self.assertIn("PT5-VS-06", cases["SV-UI-08"]["linked_pt5_cases"])
        self.assertIn("PT5-VS-07", cases["SV-UI-10"]["linked_pt5_cases"])

    def test_catalog_declares_official_gtfs_bench_support_checks(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("support_checks") or []}

        self.assertIn("SV-GTFS-BENCH-01", cases)
        self.assertIn("SV-GTFS-BENCH-02", cases)
        self.assertIn("SV-GTFS-BENCH-03", cases)
        self.assertIn("SV-AUTOMAP-01", cases)
        self.assertIn("SV-AUTOMAP-02", cases)
        self.assertEqual(cases["SV-GTFS-BENCH-01"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-GTFS-BENCH-02"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-GTFS-BENCH-03"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-AUTOMAP-01"]["automation"]["status"], "automated")
        self.assertEqual(cases["SV-AUTOMAP-02"]["automation"]["status"], "automated")
        self.assertEqual(
            cases["SV-GTFS-BENCH-03"]["automation"]["runner"],
            "validation/components/semantic_virtualization/gtfs_bench_materialization.py",
        )
        self.assertEqual(
            cases["SV-AUTOMAP-01"]["automation"]["runner"],
            "validation/components/semantic_virtualization/automap_source.py",
        )
        self.assertEqual(
            cases["SV-AUTOMAP-02"]["automation"]["runner"],
            "validation/components/semantic_virtualization/automap_execution.py",
        )
        self.assertIn("PT5-VS-10", cases["SV-AUTOMAP-01"]["linked_pt5_cases"])
        self.assertIn("PT5-VS-10", cases["SV-AUTOMAP-02"]["linked_pt5_cases"])

    def test_catalog_declares_official_gtfs_bench_dataspace_integration(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("integration_cases") or []}

        self.assertIn("SV-GTFS-BENCH-04", cases)
        self.assertEqual(cases["SV-GTFS-BENCH-04"]["status"], "automated")
        self.assertEqual(
            cases["SV-GTFS-BENCH-04"]["runner"],
            "validation/components/semantic_virtualization/dataspace_integration.py",
        )
        self.assertIn("SV-GTFS-BENCH-03", cases["SV-GTFS-BENCH-04"]["linked_cases"])
        self.assertIn("PT5-VS-11", cases["SV-GTFS-BENCH-04"]["linked_cases"])

    def test_integration_cases_declare_closure_metadata(self):
        catalog = self._load_catalog()
        cases = catalog.get("integration_cases") or []

        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case.get("id")):
                self.assertTrue(case.get("scope"))
                self.assertTrue(case.get("case_group"))
                self.assertTrue(case.get("validation_type"))
                self.assertTrue(case.get("coverage_status"))
                self.assertTrue(case.get("mapping_status"))
                self.assertTrue(case.get("expected_result"))

    def test_catalog_declares_ontology_hub_cross_component_traceability_as_automated(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("integration_cases") or []}

        self.assertEqual(cases["INT-VS-OH-01"]["status"], "automated")
        self.assertEqual(cases["INT-VS-OH-01"]["coverage_status"], "automated")
        self.assertEqual(cases["INT-VS-OH-01"]["mapping_status"], "mapped")
        self.assertEqual(
            cases["INT-VS-OH-01"]["runner"],
            "validation/components/semantic_virtualization/mapping_validation.py",
        )
        self.assertIn("PT5-OH-07", cases["INT-VS-OH-01"]["linked_cases"])
        self.assertIn("SV-AUTOMAP-02", cases["INT-VS-OH-01"]["linked_cases"])


if __name__ == "__main__":
    unittest.main()
