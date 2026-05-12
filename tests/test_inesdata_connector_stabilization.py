import contextlib
import io
import unittest
from unittest import mock

from adapters.inesdata.connectors import INESDataConnectorsAdapter


class ConnectorStabilizationTests(unittest.TestCase):
    def test_validate_connectors_with_stabilization_uses_backoff_and_recovers(self):
        adapter = _FakeConnectorsAdapter(validation_results=[False, False, True])
        output = io.StringIO()

        with (
            mock.patch.object(
                adapter,
                "validate_connectors_deployment",
                wraps=adapter.validate_connectors_deployment,
            ) as mock_validate,
            mock.patch("adapters.inesdata.connectors.time.sleep") as mock_sleep,
            contextlib.redirect_stdout(output),
        ):
            result = adapter.validate_connectors_with_stabilization(["conn-a"])

        self.assertTrue(result)
        self.assertEqual(mock_validate.call_count, 3)
        self.assertEqual(mock_sleep.call_args_list, [mock.call(20), mock.call(40)])
        rendered = output.getvalue()
        self.assertIn("attempt 1/3", rendered)
        self.assertIn("attempt 2/3", rendered)
        self.assertIn("Connector validation recovered after stabilization retry.", rendered)

    def test_validate_connectors_with_stabilization_returns_false_after_exhausting_retries(self):
        adapter = _FakeConnectorsAdapter(validation_results=[False, False, False])
        output = io.StringIO()

        with (
            mock.patch.object(
                adapter,
                "validate_connectors_deployment",
                wraps=adapter.validate_connectors_deployment,
            ) as mock_validate,
            mock.patch("adapters.inesdata.connectors.time.sleep") as mock_sleep,
            contextlib.redirect_stdout(output),
        ):
            result = adapter.validate_connectors_with_stabilization(
                ["conn-a"],
                retries=2,
                wait_seconds=5,
                backoff_factor=3,
            )

        self.assertFalse(result)
        self.assertEqual(mock_validate.call_count, 3)
        self.assertEqual(mock_sleep.call_args_list, [mock.call(5), mock.call(15)])
        rendered = output.getvalue()
        self.assertIn("attempt 1/3", rendered)
        self.assertIn("attempt 2/3", rendered)


class _FakeConnectorsAdapter(INESDataConnectorsAdapter):
    def __init__(self, validation_results):
        self.validation_results = list(validation_results)

    def validate_connectors_deployment(self, connectors):
        if not self.validation_results:
            return False
        return self.validation_results.pop(0)


if __name__ == "__main__":
    unittest.main()
