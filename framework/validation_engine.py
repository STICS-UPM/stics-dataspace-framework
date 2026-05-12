from itertools import permutations
import os
import re

from .newman_executor import NewmanExecutor
from .experiment_storage import ExperimentStorage


class ValidationEngine:
    """Runs dataspace validation tests.

    Prepares Newman environment variables, executes validation collections,
    and orchestrates interoperability tests between connector pairs.
    """

    DEFAULT_NEGOTIATION_START_MAX_ATTEMPTS = 30
    DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS = 10

    def __init__(
        self,
        newman_executor=None,
        load_connector_credentials=None,
        load_deployer_config=None,
        cleanup_test_entities=None,
        validation_test_entities_absent=None,
        ds_domain_resolver=None,
        ds_name="demo",
        transfer_storage_verifier=None,
        protocol_address_resolver=None,
    ):
        self.newman_executor = newman_executor or NewmanExecutor()
        self.load_connector_credentials = load_connector_credentials
        self.load_deployer_config = load_deployer_config
        self.cleanup_test_entities = cleanup_test_entities
        self.validation_test_entities_absent = validation_test_entities_absent
        self.ds_domain_resolver = ds_domain_resolver
        self.ds_name = ds_name
        self.transfer_storage_verifier = transfer_storage_verifier
        self.protocol_address_resolver = protocol_address_resolver
        self.last_storage_checks = []

    def _require_dependency(self, dependency, name):
        if dependency is None:
            raise RuntimeError(f"ValidationEngine requires dependency: {name}")
        return dependency

    @staticmethod
    def _positive_int_from_env(name, fallback):
        raw = str(os.environ.get(name) or "").strip()
        if not raw:
            return fallback
        try:
            value = int(raw)
        except ValueError:
            return fallback
        return value if value > 0 else fallback

    def _protocol_address(self, connector_name):
        resolver = self.protocol_address_resolver
        if callable(resolver):
            resolved = str(resolver(connector_name) or "").strip()
            if resolved:
                return resolved
        return f"http://{connector_name}:19194/protocol"

    def build_newman_env(self, provider, consumer):
        """Build Newman environment variables for dataspace validation."""
        load_connector_credentials = self._require_dependency(
            self.load_connector_credentials,
            "load_connector_credentials"
        )
        load_deployer_config = self._require_dependency(
            self.load_deployer_config,
            "load_deployer_config"
        )
        ds_domain_resolver = self._require_dependency(
            self.ds_domain_resolver,
            "ds_domain_resolver"
        )

        provider_creds = load_connector_credentials(provider)
        consumer_creds = load_connector_credentials(consumer)

        if not provider_creds or not consumer_creds:
            raise ValueError("Missing connector credentials")

        config = load_deployer_config()
        adapter_name = str(config.get("PIONERA_ADAPTER") or config.get("ADAPTER_NAME") or "").strip().lower()
        if not adapter_name:
            if "edc" in provider.lower() or "edc" in consumer.lower():
                adapter_name = "edc"
            else:
                adapter_name = "inesdata"

        ds_domain = ds_domain_resolver()
        dataspace = self.ds_name
        keycloak_url = config.get("KC_INTERNAL_URL") or config.get("KC_URL")

        if not keycloak_url.startswith("http"):
            keycloak_url = f"http://{keycloak_url}"

        return {
            "provider": provider,
            "consumer": consumer,
            "provider_user": provider_creds["connector_user"]["user"],
            "provider_password": provider_creds["connector_user"]["passwd"],
            "consumer_user": consumer_creds["connector_user"]["user"],
            "consumer_password": consumer_creds["connector_user"]["passwd"],
            "dsDomain": ds_domain,
            "dataspace": dataspace,
            "keycloakUrl": keycloak_url,
            "keycloakClientId": "dataspace-users",
            "providerParticipantId": provider,
            "providerProtocolAddress": self._protocol_address(provider),
            "consumerProtocolAddress": self._protocol_address(consumer),
            "e2e_negotiation_start_max_attempts": str(self._positive_int_from_env(
                "PIONERA_NEWMAN_NEGOTIATION_START_MAX_ATTEMPTS",
                self.DEFAULT_NEGOTIATION_START_MAX_ATTEMPTS,
            )),
            "e2e_negotiation_status_max_attempts": str(self._positive_int_from_env(
                "PIONERA_NEWMAN_NEGOTIATION_STATUS_MAX_ATTEMPTS",
                self.DEFAULT_NEGOTIATION_STATUS_MAX_ATTEMPTS,
            )),
            "e2e_expected_provider_bucket": f"{dataspace}-{provider}",
            "e2e_expected_consumer_bucket": f"{dataspace}-{consumer}",
            "adapter": adapter_name,
            "transferStartPath": (
                "transferprocesses"
                if adapter_name == "edc"
                else "inesdatatransferprocesses"
            ),
            "transferRequestType": (
                "TransferRequestDto"
                if adapter_name == "edc"
                else "TransferRequest"
            ),
            "transferType": (
                "HttpData-PULL"
                if adapter_name == "edc"
                else "AmazonS3-PUSH"
            ),
            "transferDestinationType": (
                "HttpData"
                if adapter_name == "edc"
                else "InesDataStore"
            ),
        }

    @staticmethod
    def _safe_scope_part(value):
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
        safe = re.sub(r"-{2,}", "-", safe).strip("-._")
        return safe.lower() or "unknown"

    def _build_e2e_run_scope(self, provider, consumer, experiment_dir=None, run_index=None):
        parts = []
        if experiment_dir:
            parts.append(os.path.basename(os.path.normpath(experiment_dir)))
        if run_index is not None:
            parts.append(f"run-{int(run_index):03d}")
        parts.extend([provider, consumer])
        return "-".join(self._safe_scope_part(part) for part in parts if part)

    def run_dataspace_validation(self, provider, consumer, experiment_dir=None, run_index=None):
        """Run dataspace validation tests for a provider-consumer pair."""
        cleanup_test_entities = self._require_dependency(
            self.cleanup_test_entities,
            "cleanup_test_entities"
        )
        validation_test_entities_absent = self._require_dependency(
            self.validation_test_entities_absent,
            "validation_test_entities_absent"
        )

        print(f"\n=== Testing pair ===")
        print(f"Provider : {provider}")
        print(f"Consumer : {consumer}\n")

        cleanup_test_entities(provider)
        cleanup_test_entities(consumer)

        for connector in (provider, consumer):
            is_clean, lingering_entities = validation_test_entities_absent(connector)
            if not is_clean:
                lingering = ", ".join(lingering_entities)
                print(
                    f"Warning: legacy test entities still exist after cleanup in "
                    f"{connector} ({lingering})"
                )

        report_dir = None
        if experiment_dir:
            pair_dir = f"{provider}__{consumer}"
            base_report_dir = ExperimentStorage.newman_reports_dir(experiment_dir)
            if run_index is not None:
                base_report_dir = os.path.join(base_report_dir, f"run_{int(run_index):03d}")
            report_dir = os.path.join(base_report_dir, pair_dir)
            os.makedirs(report_dir, exist_ok=True)

        env_vars = self.build_newman_env(provider, consumer)
        env_vars["e2e_run_scope"] = self._build_e2e_run_scope(
            provider,
            consumer,
            experiment_dir=experiment_dir,
            run_index=run_index,
        )
        preflight_runner = getattr(self.newman_executor, "run_management_api_preflight", None)
        preflight_runner_on_class = getattr(type(self.newman_executor), "run_management_api_preflight", None)
        if callable(preflight_runner) and callable(preflight_runner_on_class):
            preflight_runner(env_vars, report_dir=report_dir)
        baseline_snapshot = None
        baseline_reason = None
        if self.transfer_storage_verifier is not None and experiment_dir:
            try:
                baseline_snapshot = self.transfer_storage_verifier.capture_consumer_bucket_snapshot(
                    consumer,
                    env_vars["e2e_expected_consumer_bucket"],
                )
            except Exception as exc:
                baseline_reason = str(exc)

        reports = self.newman_executor.run_validation_collections(env_vars, report_dir=report_dir)

        if self.transfer_storage_verifier is not None and report_dir:
            storage_check = self.transfer_storage_verifier.verify_consumer_transfer_persistence(
                provider,
                consumer,
                report_dir,
                before_snapshot=baseline_snapshot,
                baseline_reason=baseline_reason,
                experiment_dir=experiment_dir,
            )
            self.last_storage_checks.append(storage_check)

        return reports

    def run_all_dataspace_tests(self, connectors, experiment_dir=None, run_index=None):
        """Run dataspace interoperability tests for all connector pairs."""
        print("\n========================================")
        print("DATASPACE INTEROPERABILITY TESTS")
        print("========================================\n")

        pairs = list(permutations(connectors, 2))
        exported_reports = []
        self.last_storage_checks = []

        for provider, consumer in pairs:
            reports = self.run_dataspace_validation(
                provider,
                consumer,
                experiment_dir=experiment_dir,
                run_index=run_index,
            )
            if reports:
                exported_reports.extend(reports)

        return exported_reports

    def run(self, connectors, experiment_dir=None, run_index=None):
        """Generic entry point for experiment orchestration."""
        return self.run_all_dataspace_tests(connectors, experiment_dir=experiment_dir, run_index=run_index)

    def describe(self) -> str:
        return "ValidationEngine runs dataspace validation tests."
