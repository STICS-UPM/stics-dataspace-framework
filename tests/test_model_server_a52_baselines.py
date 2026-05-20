import importlib.util
from pathlib import Path
import sys
import types
import unittest


def install_flask_stubs():
    class FakeFlaskApp:
        def __init__(self, *args, **kwargs):
            pass

        def route(self, *args, **kwargs):
            def decorator(fn):
                return fn

            return decorator

        def run(self, *args, **kwargs):
            return None

    fake_flask = types.ModuleType("flask")
    fake_flask.Flask = FakeFlaskApp
    fake_flask.jsonify = lambda payload: payload
    fake_flask.request = types.SimpleNamespace(get_json=lambda *args, **kwargs: {})
    sys.modules.setdefault("flask", fake_flask)

    fake_cors = types.ModuleType("flask_cors")
    fake_cors.CORS = lambda *args, **kwargs: None
    sys.modules.setdefault("flask_cors", fake_cors)


def load_model_server_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "adapters" / "inesdata" / "sources" / "model-server" / "mock_server_25_models.py"
    spec = importlib.util.spec_from_file_location("pionera_model_server", module_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        if exc.name not in {"flask", "flask_cors"}:
            raise
        install_flask_stubs()
        spec = importlib.util.spec_from_file_location("pionera_model_server", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ModelServerA52BaselinesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_model_server_module()

    def test_flares_baseline_a_mirrors_expected_label(self):
        payload = self.module.flares_reliability_baseline_a(
            {
                "record_id": 463,
                "text": "Official report confirms the statement.",
                "w1h_label": "WHAT",
                "tag_text": "official report",
                "expected_label": "confiable",
            }
        )

        self.assertEqual(payload["model"], "FLARES Reliability Baseline A")
        self.assertEqual(payload["variant"], "baseline-a")
        self.assertEqual(payload["task"], "5w1h-reliability-classification")
        self.assertEqual(payload["result"]["label"], "confiable")
        self.assertEqual(payload["input_summary"]["record_id"], 463)

    def test_flares_baseline_b_keeps_controlled_miss_for_comparison(self):
        payload = self.module.flares_reliability_baseline_b(
            {
                "record_id": 106,
                "text": "Unconfirmed statement.",
                "w1h_label": "WHAT",
                "expected_label": "no confiable",
            }
        )

        self.assertEqual(payload["model"], "FLARES Reliability Baseline B")
        self.assertEqual(payload["variant"], "baseline-b")
        self.assertEqual(payload["result"]["label"], "confiable")

    def test_gtfs_route_baseline_a_mirrors_expected_route(self):
        payload = self.module.gtfs_mobility_route_baseline_a(
            {
                "case_id": "mob-case-001",
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "query_time": "08:00:00",
                "expected_route_id": "route-1",
                "expected_trip_id": "trip-1",
                "expected_duration_minutes": 25,
            }
        )

        self.assertEqual(payload["model"], "GTFS Mobility Route Baseline A")
        self.assertEqual(payload["variant"], "route-baseline-a")
        self.assertEqual(payload["task"], "mobility-route-estimation")
        self.assertEqual(payload["result"]["route_id"], "route-1")
        self.assertEqual(payload["result"]["trip_id"], "trip-1")
        self.assertEqual(payload["result"]["duration_minutes"], 25)

    def test_gtfs_eta_baseline_b_keeps_controlled_eta_deviation(self):
        payload = self.module.gtfs_mobility_eta_baseline_b(
            {
                "case_id": "mob-case-002",
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "query_time": "08:00:00",
                "expected_route_id": "route-2",
                "expected_trip_id": "trip-2",
                "expected_duration_minutes": 30,
            }
        )

        self.assertEqual(payload["model"], "GTFS Mobility ETA Baseline B")
        self.assertEqual(payload["variant"], "eta-baseline-b")
        self.assertEqual(payload["result"]["route_id"], "route-2")
        self.assertEqual(payload["result"]["trip_id"], "trip-2")
        self.assertEqual(payload["result"]["duration_minutes"], 32)


if __name__ == "__main__":
    unittest.main()
