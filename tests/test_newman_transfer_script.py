import unittest
from pathlib import Path


TRANSFER_TESTS = Path("validation/core/tests/transfer_tests.js")
PROVIDER_TESTS = Path("validation/core/tests/provider_tests.js")


class NewmanTransferScriptTest(unittest.TestCase):
    def test_transfer_authentication_failures_refresh_consumer_token_before_retry(self):
        script = TRANSFER_TESTS.read_text(encoding="utf-8")

        self.assertIn("function scheduleLoginThenRetry", script)
        self.assertIn("e2e_after_consumer_login_request", script)
        self.assertIn('"Consumer Login"', script)
        self.assertIn('setNextRequestName(nextRequest)', script)
        self.assertIn('requestName === "Start Transfer Process" && isAuthenticationStatus(status)', script)
        self.assertIn('requestName === "Check Transfer Status" && isAuthenticationStatus(status)', script)
        self.assertIn(
            'requestName === "Resolve Current Transfer Destination" && isAuthenticationStatus(status)',
            script,
        )

    def test_transfer_destination_allows_fast_terminal_state_with_resolved_destination(self):
        script = TRANSFER_TESTS.read_text(encoding="utf-8")

        self.assertIn("Terminated transfer still exposes a destination for storage validation", script)
        self.assertIn("Transfer destination validation did not observe a failed terminated transfer", script)
        self.assertIn("state === \"TERMINATED\" && transferErrorDetail", script)
        self.assertNotIn("Transfer destination validation did not observe a terminated transfer", script)

    def test_provider_setup_authentication_failures_refresh_token_without_regenerating_e2e_ids(self):
        script = PROVIDER_TESTS.read_text(encoding="utf-8")

        self.assertIn("function scheduleProviderLoginThenRetry", script)
        self.assertIn("e2e_after_provider_login_request", script)
        self.assertIn('setNextRequestName("Provider Login")', script)
        self.assertIn('if (!getStoredVar("e2e_suffix"))', script)
        self.assertIn("scheduleProviderLoginThenRetry(requestName)", script)


if __name__ == "__main__":
    unittest.main()
