import os
import unittest

import yaml


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CATALOG_PATH = os.path.join(
    PROJECT_ROOT,
    "validation",
    "components",
    "ai_model_hub",
    "test_cases.yaml",
)


class AIModelHubTestCasesCatalogTests(unittest.TestCase):
    def _load_catalog(self):
        with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def test_catalog_declares_all_pt5_mh_cases_from_a52_scope(self):
        catalog = self._load_catalog()
        cases = catalog.get("test_cases") or []
        case_ids = {case.get("id") for case in cases}

        self.assertEqual(len(cases), 18)
        self.assertEqual(
            case_ids,
            {f"PT5-MH-{index:02d}" for index in range(1, 19)},
        )

    def test_connector_governance_cases_are_automated_for_level6(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        for case_id in ["PT5-MH-09", "PT5-MH-11", "PT5-MH-16", "PT5-MH-17", "PT5-MH-18"]:
            with self.subTest(case_id=case_id):
                self.assertEqual(cases[case_id]["automation"]["status"], "automated")
                self.assertEqual(cases[case_id]["automation"]["mode"], "api")
                self.assertEqual(
                    cases[case_id]["automation"]["runner"],
                    "validation/components/ai_model_hub/connector_governance_api.py",
                )

    def test_model_execution_case_is_automated_for_level6(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        self.assertEqual(cases["PT5-MH-10"]["automation"]["status"], "automated")
        self.assertEqual(cases["PT5-MH-10"]["automation"]["mode"], "api")
        self.assertEqual(
            cases["PT5-MH-10"]["automation"]["runner"],
            "validation/components/ai_model_hub/model_execution_api.py",
        )

    def test_model_benchmarking_cases_are_automated_for_level6(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        for case_id in ["PT5-MH-12", "PT5-MH-13", "PT5-MH-14", "PT5-MH-15"]:
            with self.subTest(case_id=case_id):
                self.assertEqual(cases[case_id]["automation"]["status"], "automated")
                self.assertEqual(
                    cases[case_id]["automation"]["runner"],
                    "validation/components/ai_model_hub/model_benchmarking_api.py",
                )
                self.assertEqual(
                    cases[case_id]["automation"]["ui_spec"],
                    "validation/components/ai_model_hub/ui/specs/pt5_mh_12_15_model_benchmarking_demo.spec.js",
                )

    def test_mobility_functional_case_is_automated_for_level6(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("functional_use_cases") or []}
        mobility_case = cases["MH-MOB-01"]

        self.assertEqual(mobility_case["coverage_status"], "automated_source")
        self.assertEqual(mobility_case["automation"]["status"], "automated")
        self.assertEqual(mobility_case["automation"]["mode"], "api_source")
        self.assertEqual(
            mobility_case["automation"]["dataset_source"],
            "validation/datasets/sources/gtfs-bench",
        )
        self.assertEqual(
            mobility_case["automation"]["runner"],
            "validation/components/ai_model_hub/mobility_benchmarking_api.py",
        )
        self.assertEqual(
            mobility_case["automation"]["suite_test"],
            "tests/test_ai_model_hub_mobility_benchmarking_api.py",
        )

    def test_model_observer_cases_are_registered_for_a52_closure(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("observer_cases") or []}

        self.assertEqual(
            set(cases),
            {f"MH-OBS-{index:02d}" for index in range(1, 7)},
        )

        observer_ui_case = cases["MH-OBS-01"]
        self.assertEqual(observer_ui_case["coverage_status"], "automated")
        self.assertEqual(observer_ui_case["automation"]["status"], "automated")
        self.assertEqual(observer_ui_case["automation"]["mode"], "ui")
        self.assertEqual(
            observer_ui_case["automation"]["ui_spec"],
            "validation/ui/adapters/inesdata/specs/10-ai-model-observer.spec.ts",
        )
        self.assertEqual(
            observer_ui_case["automation"]["visual_markers"],
            "PLAYWRIGHT_INTERACTION_MARKERS=1",
        )

        observer_api_case = cases["MH-OBS-02"]
        self.assertEqual(observer_api_case["coverage_status"], "automated")
        self.assertEqual(observer_api_case["automation"]["status"], "automated")
        self.assertEqual(observer_api_case["automation"]["mode"], "api")
        self.assertEqual(
            observer_api_case["automation"]["runner"],
            "validation/components/ai_model_hub/model_observer_api.py",
        )
        self.assertEqual(
            observer_api_case["automation"]["suite_test"],
            "tests/test_ai_model_hub_model_observer_api.py",
        )


if __name__ == "__main__":
    unittest.main()
