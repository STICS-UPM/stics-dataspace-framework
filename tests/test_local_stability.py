import json
import subprocess
import unittest

from framework.local_stability import LocalStabilityMonitor, compare_local_stability


def _completed(payload, returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr=stderr,
    )


class LocalStabilityMonitorTests(unittest.TestCase):
    def test_wait_until_ready_retries_until_node_is_ready(self):
        node_attempts = []
        sleeps = []
        monotonic_values = iter([0, 0, 1])

        def run_command(command):
            if command[:3] == ["kubectl", "get", "nodes"]:
                node_attempts.append(command)
                ready = len(node_attempts) > 1
                return _completed(
                    {
                        "items": [
                            {
                                "metadata": {"name": "minikube"},
                                "status": {
                                    "conditions": [
                                        {"type": "Ready", "status": "True" if ready else "False"}
                                    ]
                                },
                            }
                        ]
                    }
                )
            if command[:3] == ["kubectl", "get", "pods"]:
                return _completed(
                    {
                        "items": [
                            {
                                "metadata": {"namespace": "demo", "name": "conn-a"},
                                "status": {
                                    "phase": "Running",
                                    "conditions": [{"type": "Ready", "status": "True"}],
                                    "containerStatuses": [{"name": "app", "restartCount": 0}],
                                },
                            }
                        ]
                    }
                )
            if command[:3] == ["kubectl", "get", "events"]:
                return _completed({"items": []})
            raise AssertionError(command)

        monitor = LocalStabilityMonitor(
            ["demo"],
            run_command=run_command,
            sleep=lambda seconds: sleeps.append(seconds),
            monotonic=lambda: next(monotonic_values, 1),
        )

        result = monitor.wait_until_ready(timeout_seconds=10, poll_interval_seconds=2)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["wait"]["attempts"], 2)
        self.assertEqual(sleeps, [2])

    def test_compare_local_stability_reports_restart_and_node_not_ready_deltas(self):
        before = {
            "status": "warning",
            "restart_index": {"components/demo-ontology-hub/ontology-hub": 6},
            "node_not_ready_event_count": 39,
        }
        after = {
            "status": "warning",
            "restart_index": {"components/demo-ontology-hub/ontology-hub": 7},
            "node_not_ready_event_count": 40,
        }

        result = compare_local_stability(before, after)

        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["restart_deltas"][0]["delta"], 1)
        self.assertEqual(result["node_not_ready_delta"], 1)
        self.assertEqual({item["name"] for item in result["warnings"]}, {"pod_restart_delta", "node_not_ready_delta"})


if __name__ == "__main__":
    unittest.main()
