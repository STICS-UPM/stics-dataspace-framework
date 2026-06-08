import tempfile
import unittest
from pathlib import Path

from validation.components.ai_model_hub.upstream_bridge import (
    analyze_seed_script,
    build_demo_adoption_plan,
    classify_porting_need,
    inspect_use_case_datasets,
)


class AIModelHubUpstreamBridgeTests(unittest.TestCase):
    def test_seed_script_analysis_detects_upstream_step_9_and_10_capabilities(self):
        script = """
        SEED_SCOPE="${SEED_SCOPE:-models}"
        MOBILITY_SEGMENTS_DATASET_FILE=/tmp/segments.csv
        FLARES_5W1H_DATASET_FILE=/tmp/flares.json
        create_company_dataset_policies_and_contracts() { true; }
        FLARES_METRIC_MODEL_SLUGS=(flares-5w1h-bert-metrics)
        "daimo:benchmark_model_type": "metric"
        USE_CASE_MODEL_SERVER_BASE_URL=http://host.docker.internal:8000
        --skip-inesdata-models --skip-use-case-models --seed-scope
        COMBINED_HTTP_COUNT=10
        combined
        Mobility
        FLARES
        """

        features = analyze_seed_script(script)

        self.assertTrue(features["supports_seed_scope"])
        self.assertTrue(features["supports_dataset_assets"])
        self.assertTrue(features["supports_flares_metric_models"])
        self.assertTrue(features["supports_skip_flags"])
        self.assertTrue(features["supports_combined_mode"])
        self.assertTrue(features["supports_use_case_models"])

    def test_classify_porting_need_reports_missing_dataset_and_metric_seed_features(self):
        local = {
            "supports_seed_scope": False,
            "supports_dataset_assets": False,
            "supports_flares_metric_models": False,
            "supports_skip_flags": False,
        }
        upstream = {
            "supports_seed_scope": True,
            "supports_dataset_assets": True,
            "supports_flares_metric_models": True,
            "supports_skip_flags": True,
        }

        result = classify_porting_need(local, upstream)

        self.assertEqual(result["status"], "port_required")
        self.assertEqual(
            {gap["feature"] for gap in result["gaps"]},
            {
                "supports_seed_scope",
                "supports_dataset_assets",
                "supports_flares_metric_models",
                "supports_skip_flags",
            },
        )

    def test_demo_adoption_plan_marks_step_9_and_10_as_port_required_for_current_local_gap(self):
        local = {
            "supports_seed_scope": False,
            "supports_dataset_assets": False,
            "supports_use_case_models": True,
            "supports_flares_metric_models": False,
            "supports_skip_flags": False,
        }
        upstream = {
            "supports_seed_scope": True,
            "supports_dataset_assets": True,
            "supports_use_case_models": True,
            "supports_flares_metric_models": True,
            "supports_skip_flags": True,
        }

        plan = build_demo_adoption_plan(local, upstream)

        self.assertEqual(plan[0]["upstream_step"], 7)
        self.assertEqual(plan[0]["local_status"], "available")
        self.assertEqual(plan[1]["upstream_step"], 9)
        self.assertEqual(plan[1]["local_status"], "port_required")
        self.assertEqual(plan[2]["upstream_step"], 10)
        self.assertEqual(plan[2]["local_status"], "port_required")

    def test_demo_adoption_plan_marks_new_seed_steps_available_when_features_are_ported(self):
        local = {
            "supports_seed_scope": True,
            "supports_dataset_assets": True,
            "supports_use_case_models": True,
            "supports_flares_metric_models": True,
            "supports_skip_flags": True,
        }

        plan = build_demo_adoption_plan(local, local)

        self.assertEqual([item["local_status"] for item in plan], ["available", "available", "available"])

    def test_inspect_use_case_datasets_requires_all_step_9_dataset_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "adapters" / "inesdata" / "sources" / "AIModelHub-Use-Cases"
            (source / "data" / "mobility-datasets").mkdir(parents=True)
            (source / "data" / "flares-datasets").mkdir(parents=True)
            (source / "data" / "mobility-datasets" / "segments_test.csv").write_text("a,b\n1,2\n")
            (source / "data" / "flares-datasets" / "5w1h_subtarea_1_test.json").write_text("{}\n")

            result = inspect_use_case_datasets(root)

            self.assertTrue(result["available"])
            self.assertFalse(result["datasets_available"])
            self.assertEqual(
                [
                    item["relative_path"]
                    for item in result["datasets"]
                    if not item["available"]
                ],
                ["data/flares-datasets/5w1h_subtarea_2_test.json"],
            )

            (source / "data" / "flares-datasets" / "5w1h_subtarea_2_test.json").write_text("{}\n")

            self.assertTrue(inspect_use_case_datasets(root)["datasets_available"])


if __name__ == "__main__":
    unittest.main()
