import json
import os
import tempfile
import unittest
import base64
from unittest import mock

from framework.experiment_storage import ExperimentStorage
from validation.orchestration import readiness


def _fake_jwt(payload):
    def encode(part):
        raw = json.dumps(part, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode(payload)}.signature"


class Level6ReadinessTests(unittest.TestCase):
    def test_wait_for_validation_ready_persists_passed_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = readiness.wait_for_validation_ready(
                ["conn-a", "conn-b"],
                timeout_seconds=1.0,
                poll_interval_seconds=0.01,
                probe_management_api_fn=mock.Mock(return_value=(True, {"items": 1})),
                probe_catalog_fn=mock.Mock(return_value=(True, {"datasets": 0})),
                experiment_storage=ExperimentStorage,
                experiment_dir=tmpdir,
            )

            readiness_path = os.path.join(tmpdir, "level6_readiness.json")
            self.assertEqual(result["status"], "passed")
            self.assertTrue(os.path.exists(readiness_path))
            with open(readiness_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertEqual(stored["status"], "passed")
            self.assertEqual(len(stored["gates"]), 4)

    def test_wait_for_validation_ready_reports_failed_gates(self):
        result = readiness.wait_for_validation_ready(
            ["conn-a"],
            timeout_seconds=0.01,
            poll_interval_seconds=0.01,
            probe_management_api_fn=mock.Mock(return_value=(False, "HTTP 401")),
            probe_catalog_fn=mock.Mock(return_value=(True, {"datasets": 0})),
            experiment_storage=ExperimentStorage,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["gates"][0]["gate"], "management_api_smoke:conn-a")
        self.assertEqual(result["gates"][0]["status"], "failed")
        self.assertEqual(result["gates"][0]["error"], "HTTP 401")

    def test_probe_management_api_requires_token(self):
        connectors_adapter = mock.Mock()
        connectors_adapter.get_management_api_headers.return_value = None

        passed, detail = readiness.probe_management_api(
            "conn-a",
            connectors_adapter=connectors_adapter,
            requests_module=mock.Mock(),
        )

        self.assertFalse(passed)
        self.assertEqual(detail, "could not obtain management API token")

    def test_probe_management_api_invalidates_token_and_returns_sanitized_401_detail(self):
        token = _fake_jwt({
            "iss": "http://keycloak.dev.ed.dataspaceunit.upm/realms/demo",
            "aud": ["account"],
            "preferred_username": "user-conn-a",
            "realm_access": {
                "roles": ["conn-a", "connector-user"],
            },
        })
        connectors_adapter = mock.Mock()
        connectors_adapter.get_management_api_headers.return_value = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        connectors_adapter.connector_base_url.return_value = "http://conn-a.example.local"

        response = mock.Mock(status_code=401)
        response.json.return_value = [
            {
                "message": "Request could not be authenticated",
                "type": "AuthenticationFailed",
                "path": None,
                "invalidValue": None,
            }
        ]
        requests_module = mock.Mock()
        requests_module.post.return_value = response

        passed, detail = readiness.probe_management_api(
            "conn-a",
            connectors_adapter=connectors_adapter,
            requests_module=requests_module,
        )

        self.assertFalse(passed)
        connectors_adapter.invalidate_management_api_token.assert_called_once_with("conn-a")
        self.assertEqual(detail["http_status"], 401)
        self.assertEqual(detail["connector"], "conn-a")
        self.assertEqual(detail["preferred_username"], "user-conn-a")
        self.assertEqual(detail["realm_roles"], ["conn-a", "connector-user"])
        self.assertEqual(detail["response"][0]["type"], "AuthenticationFailed")
        self.assertNotIn(token, json.dumps(detail))

    def test_wait_for_validation_ready_keeps_previous_error_when_gate_recovers(self):
        recovered_probe = mock.Mock(side_effect=[
            (
                False,
                {
                    "http_status": 401,
                    "connector": "conn-a",
                    "response": [
                        {
                            "message": "Request could not be authenticated",
                            "type": "AuthenticationFailed",
                        }
                    ],
                },
            ),
            (True, {"items": 1}),
        ])

        result = readiness.wait_for_validation_ready(
            ["conn-a"],
            timeout_seconds=1.0,
            poll_interval_seconds=0.01,
            probe_management_api_fn=recovered_probe,
            probe_catalog_fn=mock.Mock(return_value=(True, {"datasets": 0})),
            experiment_storage=ExperimentStorage,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["gates"][0]["attempts"], 2)
        self.assertEqual(result["gates"][0]["previous_error"]["http_status"], 401)


if __name__ == "__main__":
    unittest.main()
