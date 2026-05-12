import json
import os
import tempfile
import unittest

from framework.experiment_storage import ExperimentStorage
from validation.orchestration import state


def _aggregate_ui_results(ui_results, *, experiment_dir):
    return {
        "status": "passed" if ui_results else "not_run",
        "summary": {"total": len(ui_results)},
        "experiment_dir": experiment_dir,
    }


class Level6StateTests(unittest.TestCase):
    def test_save_level6_experiment_state_persists_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = state.save_level6_experiment_state(
                tmpdir,
                ["conn-a", "conn-b"],
                status="completed",
                experiment_storage=ExperimentStorage,
                aggregate_ui_results=_aggregate_ui_results,
                level6_readiness={"status": "passed"},
                validation_reports=["pair-report.json"],
                newman_request_metrics=[{"name": "request"}],
                kafka_metrics={"status": "completed"},
                kafka_edc_results=[{"status": "passed"}],
                storage_checks=[{"status": "passed"}],
                ui_results=[{"status": "passed"}],
                component_results=[{"component": "ontology-hub"}],
            )

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["connectors"], ["conn-a", "conn-b"])
            self.assertEqual(payload["source"], "validation.orchestration:level6")
            self.assertEqual(payload["ui_validation"]["status"], "passed")

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored["level6_readiness"]["status"], "passed")
            self.assertEqual(stored["validation_reports"], ["pair-report.json"])
            self.assertEqual(stored["component_results"][0]["component"], "ontology-hub")

    def test_save_interactive_core_ui_experiment_state_persists_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = state.save_interactive_core_ui_experiment_state(
                tmpdir,
                ["conn-a"],
                mode={"label": "Live"},
                experiment_storage=ExperimentStorage,
                aggregate_ui_results=_aggregate_ui_results,
                ui_results=[{"status": "passed"}],
            )

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["mode"], "Live")
            self.assertEqual(payload["source"], "validation.orchestration:interactive-core-ui")

            with open(os.path.join(tmpdir, "experiment_results.json"), "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored["mode"], "Live")
            self.assertEqual(stored["ui_validation"]["summary"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
