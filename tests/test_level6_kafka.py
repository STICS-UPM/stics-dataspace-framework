import unittest
from unittest import mock

from validation.orchestration import kafka, runner


class Level6KafkaTests(unittest.TestCase):
    def test_preflight_ignores_non_vm_distributed(self):
        result = kafka.validate_kafka_runtime_preflight(
            {"topology": "local", "cluster_bootstrap_servers": "framework-kafka.core-control.svc.cluster.local:9092"},
            env={},
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["topology"], "local")

    def test_vm_distributed_preflight_requires_connector_visible_bootstrap(self):
        result = kafka.validate_kafka_runtime_preflight(
            {"topology": "vm-distributed"},
            env={},
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("requires KAFKA_CLUSTER_BOOTSTRAP_SERVERS", result["errors"][0])

    def test_vm_distributed_preflight_rejects_cluster_dns_bootstrap(self):
        result = kafka.validate_kafka_runtime_preflight(
            {
                "topology": "vm-distributed",
                "cluster_bootstrap_servers": "framework-kafka.core-control.svc.cluster.local:9092",
            },
            env={},
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["invalid_connector_bootstrap_servers"][0]["reason"],
            "kubernetes-cluster-dns",
        )

    def test_vm_distributed_preflight_rejects_loopback_bootstrap(self):
        result = kafka.validate_kafka_runtime_preflight(
            {"topology": "vm-distributed", "cluster_bootstrap_servers": "127.0.0.1:39092"},
            env={},
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["invalid_connector_bootstrap_servers"][0]["reason"],
            "loopback-address",
        )

    def test_vm_distributed_preflight_accepts_nodeport_and_warns_without_image_override(self):
        result = kafka.validate_kafka_runtime_preflight(
            {"topology": "vm-distributed", "cluster_bootstrap_servers": "198.51.100.10:32092"},
            env={},
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["connector_bootstrap_servers"], ["198.51.100.10:32092"])
        self.assertTrue(any("data-plane-kafka" in warning for warning in result["warnings"]))

    def test_vm_distributed_preflight_accepts_explicit_connector_image_without_warning(self):
        result = kafka.validate_kafka_runtime_preflight(
            {"topology": "vm-distributed", "cluster_bootstrap_servers": "198.51.100.10:32092"},
            deployer_config={
                "INESDATA_CONNECTOR_IMAGE_NAME": "ghcr.io/example/inesdata-connector",
                "INESDATA_CONNECTOR_IMAGE_TAG": "kafka-capable",
            },
            env={},
        )

        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["warnings"])

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

    def test_level6_kafka_summary_treats_missing_messages_as_failed(self):
        results = [
            {
                "status": "passed",
                "metrics": {
                    "messages_produced": 10,
                    "messages_consumed": 9,
                    "messages_missing": 1,
                },
            },
            {"status": "skipped"},
        ]

        summary = runner._kafka_results_summary(results)

        self.assertEqual(runner._kafka_result_status(results[0]), "failed")
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["passed"], 0)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["messages_produced"], 10)
        self.assertEqual(summary["messages_consumed"], 9)
        self.assertEqual(summary["messages_missing"], 1)


if __name__ == "__main__":
    unittest.main()
