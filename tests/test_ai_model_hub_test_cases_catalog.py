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

    def test_connector_governance_cases_are_automated_opt_in(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        for case_id in ["PT5-MH-09", "PT5-MH-11", "PT5-MH-16", "PT5-MH-17", "PT5-MH-18"]:
            with self.subTest(case_id=case_id):
                self.assertEqual(cases[case_id]["automation"]["status"], "automated_opt_in")
                self.assertEqual(
                    cases[case_id]["automation"]["runner"],
                    "validation/components/ai_model_hub/connector_governance_api.py",
                )
                self.assertEqual(
                    cases[case_id]["automation"]["enable_with"],
                    "AI_MODEL_HUB_ENABLE_CONNECTOR_GOVERNANCE=1",
                )

    def test_model_benchmarking_cases_are_automated_opt_in(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("test_cases") or []}

        for case_id in ["PT5-MH-12", "PT5-MH-13", "PT5-MH-14", "PT5-MH-15"]:
            with self.subTest(case_id=case_id):
                self.assertEqual(cases[case_id]["automation"]["status"], "automated_opt_in")
                self.assertEqual(
                    cases[case_id]["automation"]["runner"],
                    "validation/components/ai_model_hub/model_benchmarking_api.py",
                )
                self.assertEqual(
                    cases[case_id]["automation"]["enable_with"],
                    "AI_MODEL_HUB_ENABLE_MODEL_BENCHMARKING=1",
                )
                self.assertEqual(
                    cases[case_id]["automation"]["ui_spec"],
                    "validation/components/ai_model_hub/ui/specs/pt5_mh_12_15_model_benchmarking_demo.spec.js",
                )
                self.assertEqual(
                    cases[case_id]["automation"]["ui_demo_enable_with"],
                    "AI_MODEL_HUB_ENABLE_BENCHMARKING_UI_DEMO=1",
                )

    def test_mobility_functional_case_is_automated_opt_in(self):
        catalog = self._load_catalog()
        cases = {case.get("id"): case for case in catalog.get("functional_use_cases") or []}
        mobility_case = cases["MH-MOB-01"]

        self.assertEqual(mobility_case["coverage_status"], "automated_fixture")
        self.assertEqual(mobility_case["automation"]["status"], "automated_opt_in")
        self.assertEqual(mobility_case["automation"]["mode"], "api_fixture")
        self.assertEqual(
            mobility_case["automation"]["runner"],
            "validation/components/ai_model_hub/mobility_benchmarking_api.py",
        )
        self.assertEqual(
            mobility_case["automation"]["enable_with"],
            "AI_MODEL_HUB_ENABLE_MOBILITY_BENCHMARKING=1",
        )
        self.assertEqual(
            mobility_case["automation"]["suite_test"],
            "tests/test_ai_model_hub_mobility_benchmarking_api.py",
        )


if __name__ == "__main__":
    unittest.main()
