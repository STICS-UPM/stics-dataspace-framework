import unittest
from unittest import mock

from validation.orchestration import kafka


class Level6KafkaTests(unittest.TestCase):
    def test_should_run_kafka_edc_validation_is_disabled_by_default(self):
        def flag_enabled(name, default):
            return default

        self.assertFalse(kafka.should_run_kafka_edc_validation(flag_enabled=flag_enabled))

    def test_should_run_kafka_edc_validation_can_be_temporarily_skipped(self):
        def flag_enabled(name, default):
            return name == "PIONERA_LEVEL6_SKIP_KAFKA" or default

        self.assertFalse(kafka.should_run_kafka_edc_validation(flag_enabled=flag_enabled))

    def test_should_run_kafka_edc_validation_can_be_reenabled_with_run_flag(self):
        def flag_enabled(name, default):
            values = {
                "PIONERA_LEVEL6_SKIP_KAFKA": False,
                "PIONERA_LEVEL6_RUN_KAFKA": True,
            }
            return values.get(name, default)

        self.assertTrue(kafka.should_run_kafka_edc_validation(flag_enabled=flag_enabled))

    def test_run_kafka_edc_validation_skips_when_not_enough_connectors(self):
        experiment_storage = mock.Mock()

        results = kafka.run_kafka_edc_validation(
            ["conn-a"],
            "/tmp/experiment",
            validator=mock.Mock(),
            experiment_storage=experiment_storage,
        )

        self.assertEqual(results[0]["status"], "skipped")
        self.assertEqual(results[0]["reason"], "not_enough_connectors")
        experiment_storage.save_kafka_edc_results_json.assert_called_once_with(
            results,
            "/tmp/experiment",
        )

    def test_run_kafka_edc_validation_persists_results(self):
        validator = mock.Mock()
        validator.run_all.return_value = [{"status": "passed"}]
        experiment_storage = mock.Mock()

        results = kafka.run_kafka_edc_validation(
            ["conn-a", "conn-b"],
            "/tmp/experiment",
            validator=validator,
            experiment_storage=experiment_storage,
        )

        self.assertEqual(results, [{"status": "passed"}])
        validator.run_all.assert_called_once_with(
            ["conn-a", "conn-b"],
            experiment_dir="/tmp/experiment",
        )
        experiment_storage.save_kafka_edc_results_json.assert_called_once_with(
            [{"status": "passed"}],
            "/tmp/experiment",
        )

    def test_run_kafka_edc_validation_forwards_progress_callback(self):
        validator = mock.Mock()
        validator.run_all.return_value = [{"status": "passed"}]
        experiment_storage = mock.Mock()
        progress_callback = mock.Mock()

        kafka.run_kafka_edc_validation(
            ["conn-a", "conn-b"],
            "/tmp/experiment",
            validator=validator,
            experiment_storage=experiment_storage,
            progress_callback=progress_callback,
        )

        validator.run_all.assert_called_once_with(
            ["conn-a", "conn-b"],
            experiment_dir="/tmp/experiment",
            progress_callback=progress_callback,
        )

    def test_run_kafka_edc_validation_persists_execution_errors(self):
        validator = mock.Mock()
        validator.run_all.side_effect = RuntimeError("broker unavailable")
        experiment_storage = mock.Mock()

        results = kafka.run_kafka_edc_validation(
            ["conn-a", "conn-b"],
            "/tmp/experiment",
            validator=validator,
            experiment_storage=experiment_storage,
        )

        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(results[0]["reason"], "execution_error")
        self.assertIn("broker unavailable", results[0]["error"]["message"])
        experiment_storage.save_kafka_edc_results_json.assert_called_once_with(
            results,
            "/tmp/experiment",
        )


if __name__ == "__main__":
    unittest.main()
