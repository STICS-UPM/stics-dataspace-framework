import json
import os
import tempfile
import unittest

from deployers.shared.lib.contracts import DeploymentContext
from validation.core.test_data_cleanup import (
    build_cleanup_plan,
    ManagementApiTestDataCleaner,
)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = "" if payload is None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("empty body")
        return self._payload


class FakeCleanupSession:
    def __init__(self):
        self.entities = {
            "contractdefinitions": [
                {"@id": "contract-ui-1"},
                {"@id": "manual-contract"},
            ],
            "policydefinitions": [
                {"@id": "policy-ui-1"},
                {"@id": "manual-policy"},
            ],
            "assets": [
                {"@id": "qa-ui-asset-1"},
                {"@id": "manual-asset"},
            ],
        }
        self.deleted_urls = []

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        del headers, data, json, timeout
        if "openid-connect/token" in url:
            return FakeResponse(200, {"access_token": "jwt-token"})
        if url.endswith("/contractdefinitions/request"):
            return FakeResponse(200, list(self.entities["contractdefinitions"]))
        if url.endswith("/policydefinitions/request"):
            return FakeResponse(200, list(self.entities["policydefinitions"]))
        if url.endswith("/assets/request"):
            return FakeResponse(200, list(self.entities["assets"]))
        raise AssertionError(f"Unexpected POST URL: {url}")

    def delete(self, url, headers=None, timeout=None):
        del headers, timeout
        self.deleted_urls.append(url)
        entity_kind = url.split("/management/v3/", 1)[1].split("/", 1)[0]
        entity_id = url.rsplit("/", 1)[-1]
        self.entities[entity_kind] = [
            entity for entity in self.entities[entity_kind] if entity.get("@id") != entity_id
        ]
        return FakeResponse(204)


class ConflictCleanupSession(FakeCleanupSession):
    def __init__(self):
        super().__init__()
        self.entities = {
            "contractdefinitions": [],
            "policydefinitions": [],
            "assets": [
                {"@id": "qa-ui-transfer-1"},
            ],
            "contractnegotiations": [],
            "transferprocesses": [
                {
                    "@id": "transfer-1",
                    "@type": "TransferProcess",
                    "state": "DEPROVISIONED",
                    "assetId": "qa-ui-transfer-1",
                }
            ],
            "contractagreements": [
                {
                    "@id": "agreement-1",
                    "@type": "ContractAgreement",
                    "assetId": "qa-ui-transfer-1",
                }
            ],
        }

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        del headers, data, json, timeout
        if "openid-connect/token" in url:
            return FakeResponse(200, {"access_token": "jwt-token"})
        if url.endswith("/contractdefinitions/request"):
            return FakeResponse(200, list(self.entities["contractdefinitions"]))
        if url.endswith("/policydefinitions/request"):
            return FakeResponse(200, list(self.entities["policydefinitions"]))
        if url.endswith("/assets/request"):
            return FakeResponse(200, list(self.entities["assets"]))
        if url.endswith("/contractnegotiations/request"):
            return FakeResponse(200, list(self.entities["contractnegotiations"]))
        if url.endswith("/transferprocesses/request"):
            return FakeResponse(200, list(self.entities["transferprocesses"]))
        if url.endswith("/contractagreements/request"):
            return FakeResponse(200, list(self.entities["contractagreements"]))
        raise AssertionError(f"Unexpected POST URL: {url}")

    def delete(self, url, headers=None, timeout=None):
        del headers, timeout
        self.deleted_urls.append(url)
        if url.endswith("/assets/qa-ui-transfer-1"):
            return FakeResponse(409, {"message": "Asset is still referenced"})
        return FakeResponse(204)


class FakeConfigAdapter:
    @staticmethod
    def load_deployer_config():
        return {
            "KC_URL": "http://keycloak.local",
            "DS_1_NAME": "demo",
            "PIONERA_ADAPTER": "inesdata",
        }


class FakeConnectors:
    @staticmethod
    def load_connector_credentials(connector):
        return {
            "connector_user": {
                "user": f"{connector}-user",
                "passwd": "secret",
            },
        }


class FakeAdapter:
    config_adapter = FakeConfigAdapter()
    connectors = FakeConnectors()


class RecordingCleanupSession(FakeCleanupSession):
    def __init__(self):
        super().__init__()
        self.token_urls = []

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if "openid-connect/token" in url:
            self.token_urls.append(url)
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)


class TransientAuthCleanupSession(FakeCleanupSession):
    def __init__(self):
        super().__init__()
        self.token_requests = 0
        self.rejected_inventory_once = False

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if "openid-connect/token" in url:
            self.token_requests += 1
            return FakeResponse(200, {"access_token": f"jwt-token-{self.token_requests}"})
        if url.endswith("/contractdefinitions/request") and not self.rejected_inventory_once:
            self.rejected_inventory_once = True
            return FakeResponse(401, [{"type": "AuthenticationFailed"}])
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)


class TransientManagementCleanupSession(FakeCleanupSession):
    def __init__(self):
        super().__init__()
        self.contract_definition_attempts = 0

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        if url.endswith("/contractdefinitions/request"):
            self.contract_definition_attempts += 1
            if self.contract_definition_attempts == 1:
                return FakeResponse(502, {"message": "ingress settling"})
        return super().post(url, headers=headers, data=data, json=json, timeout=timeout)


class FakeMinioObject:
    def __init__(self, object_name):
        self.object_name = object_name


class FakeMinioClient:
    def __init__(self, objects_by_bucket):
        self.objects_by_bucket = objects_by_bucket
        self.deleted = []

    def list_objects(self, bucket_name, recursive=True):
        del recursive
        return [
            FakeMinioObject(object_name)
            for object_name in self.objects_by_bucket.get(bucket_name, [])
        ]

    def remove_object(self, bucket_name, object_name):
        self.deleted.append((bucket_name, object_name))
        self.objects_by_bucket[bucket_name] = [
            current
            for current in self.objects_by_bucket.get(bucket_name, [])
            if current != object_name
        ]


class FakeStorageConnectors(FakeConnectors):
    @staticmethod
    def load_connector_credentials(connector):
        credentials = FakeConnectors.load_connector_credentials(connector)
        credentials["minio"] = {
            "access_key": f"{connector}-access",
            "secret_key": f"{connector}-secret",
        }
        return credentials


class FakeStorageAdapter(FakeAdapter):
    connectors = FakeStorageConnectors()


def fake_context():
    return DeploymentContext(
        deployer="inesdata",
        topology="local",
        environment="DEV",
        dataspace_name="demo",
        ds_domain_base="example.local",
        connectors=["conn-a"],
        config={"KC_URL": "http://keycloak.local"},
    )


class TestDataCleanupTests(unittest.TestCase):
    def test_build_cleanup_plan_filters_to_known_test_prefixes(self):
        plan = build_cleanup_plan(
            {
                "contract_definitions": [
                    {"@id": "contract-crud-1"},
                    {"@id": "manual-contract"},
                ],
                "policies": [
                    {"@id": "qa-ui-contract-policy-1"},
                    {"@id": "manual-policy"},
                ],
                "assets": [
                    {"@id": "qa-ui-edc-transfer-1"},
                    {"@id": "qa-ui-sv-httpdata-1"},
                    {"@id": "manual-asset"},
                ],
            },
            mode="safe",
        )

        self.assertEqual(plan["contract_definitions"], ["contract-crud-1"])
        self.assertEqual(plan["policies"], ["qa-ui-contract-policy-1"])
        self.assertEqual(plan["assets"], ["qa-ui-edc-transfer-1", "qa-ui-sv-httpdata-1"])

    def test_cleaner_deletes_safe_entities_in_dependency_order_and_writes_report(self):
        session = FakeCleanupSession()

        with tempfile.TemporaryDirectory() as tmpdir:
            cleaner = ManagementApiTestDataCleaner(
                adapter=FakeAdapter(),
                context=fake_context(),
                connectors=["conn-a"],
                experiment_dir=tmpdir,
                mode="safe",
                session=session,
            )
            report = cleaner.run()
            report_path = os.path.join(tmpdir, "cleanup", "test_data_cleanup.json")

            with open(report_path, "r", encoding="utf-8") as handle:
                persisted = json.load(handle)

        self.assertEqual(report["status"], "completed")
        self.assertEqual(persisted["status"], "completed")
        self.assertEqual(
            [
                url.split("/management/v3/", 1)[1]
                for url in session.deleted_urls
            ],
            [
                "contractdefinitions/contract-ui-1",
                "policydefinitions/policy-ui-1",
                "assets/qa-ui-asset-1",
            ],
        )
        self.assertEqual(session.entities["contractdefinitions"], [{"@id": "manual-contract"}])
        self.assertEqual(session.entities["policydefinitions"], [{"@id": "manual-policy"}])
        self.assertEqual(session.entities["assets"], [{"@id": "manual-asset"}])
        self.assertEqual(report["connectors"][0]["skipped_counts"]["assets"], 0)
        self.assertEqual(report["connectors"][0]["unplanned_counts"]["assets"], 1)

    def test_token_request_uses_configured_keycloak_hostname(self):
        session = RecordingCleanupSession()
        context = fake_context()
        context.config["KC_INTERNAL_URL"] = "http://keycloak.dev.ed.dataspaceunit.upm"

        with tempfile.TemporaryDirectory() as tmpdir:
            cleaner = ManagementApiTestDataCleaner(
                adapter=FakeAdapter(),
                context=context,
                connectors=["conn-a"],
                experiment_dir=tmpdir,
                mode="safe",
                session=session,
            )
            report = cleaner.run()

        self.assertEqual(report["status"], "completed")
        self.assertTrue(session.token_urls)
        self.assertTrue(session.token_urls[0].startswith("http://keycloak.dev.ed.dataspaceunit.upm/"))

    def test_inventory_cleanup_retries_once_after_transient_401(self):
        session = TransientAuthCleanupSession()

        with tempfile.TemporaryDirectory() as tmpdir:
            cleaner = ManagementApiTestDataCleaner(
                adapter=FakeAdapter(),
                context=fake_context(),
                connectors=["conn-a"],
                experiment_dir=tmpdir,
                mode="safe",
                session=session,
                auth_retry_delay=0,
            )
            report = cleaner.run()

        self.assertEqual(report["status"], "completed")
        self.assertTrue(session.rejected_inventory_once)
        self.assertEqual(session.token_requests, 2)

    def test_inventory_cleanup_retries_transient_management_gateway_error(self):
        session = TransientManagementCleanupSession()

        cleaner = ManagementApiTestDataCleaner(
            adapter=FakeAdapter(),
            context=fake_context(),
            connectors=["conn-a"],
            experiment_dir=None,
            mode="safe",
            session=session,
            management_transient_retries=1,
            management_transient_retry_delay=0,
        )
        report = cleaner.run()

        self.assertEqual(report["status"], "completed")
        self.assertEqual(session.contract_definition_attempts, 2)

    def test_dry_run_builds_plan_without_deleting(self):
        session = FakeCleanupSession()

        with tempfile.TemporaryDirectory() as tmpdir:
            cleaner = ManagementApiTestDataCleaner(
                adapter=FakeAdapter(),
                context=fake_context(),
                connectors=["conn-a"],
                experiment_dir=tmpdir,
                mode="dry-run",
                session=session,
            )
            report = cleaner.run()

        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["connectors"][0]["planned"]["assets"], ["qa-ui-asset-1"])
        self.assertEqual(session.deleted_urls, [])
        self.assertEqual(session.entities["assets"], [{"@id": "qa-ui-asset-1"}, {"@id": "manual-asset"}])

    def test_storage_cleanup_deletes_only_safe_test_objects(self):
        session = FakeCleanupSession()
        minio_client = FakeMinioClient(
            {
                "demo-conn-a": [
                    "todos-experiment-123.json",
                    "playwright-e2e/qa-ui-transfer-1/payload.bin",
                    "playwright-edc-storage-123.json",
                    "manual-object.json",
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cleaner = ManagementApiTestDataCleaner(
                adapter=FakeStorageAdapter(),
                context=fake_context(),
                connectors=["conn-a"],
                experiment_dir=tmpdir,
                mode="safe",
                session=session,
                minio_client_factory=lambda **_kwargs: minio_client,
            )
            report = cleaner.run()

        storage = report["connectors"][0]["storage"]
        self.assertEqual(report["status"], "completed")
        self.assertEqual(
            storage["planned"],
            [
                "todos-experiment-123.json",
                "playwright-e2e/qa-ui-transfer-1/payload.bin",
                "playwright-edc-storage-123.json",
            ],
        )
        self.assertEqual(
            minio_client.deleted,
            [
                ("demo-conn-a", "todos-experiment-123.json"),
                ("demo-conn-a", "playwright-e2e/qa-ui-transfer-1/payload.bin"),
                ("demo-conn-a", "playwright-edc-storage-123.json"),
            ],
        )
        self.assertEqual(minio_client.objects_by_bucket["demo-conn-a"], ["manual-object.json"])
        self.assertEqual(report["summary"]["storage_deleted_total"], 3)

    def test_storage_cleanup_dry_run_keeps_objects(self):
        session = FakeCleanupSession()
        minio_client = FakeMinioClient(
            {
                "demo-conn-a": [
                    "todos-experiment-123.json",
                    "manual-object.json",
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cleaner = ManagementApiTestDataCleaner(
                adapter=FakeStorageAdapter(),
                context=fake_context(),
                connectors=["conn-a"],
                experiment_dir=tmpdir,
                mode="dry-run",
                session=session,
                minio_client_factory=lambda **_kwargs: minio_client,
            )
            report = cleaner.run()

        storage = report["connectors"][0]["storage"]
        self.assertEqual(storage["planned"], ["todos-experiment-123.json"])
        self.assertEqual(storage["deleted"], [])
        self.assertEqual(minio_client.deleted, [])
        self.assertEqual(
            minio_client.objects_by_bucket["demo-conn-a"],
            ["todos-experiment-123.json", "manual-object.json"],
        )

    def test_conflict_report_includes_references_that_block_asset_deletion(self):
        session = ConflictCleanupSession()

        with tempfile.TemporaryDirectory() as tmpdir:
            cleaner = ManagementApiTestDataCleaner(
                adapter=FakeAdapter(),
                context=fake_context(),
                connectors=["conn-a"],
                experiment_dir=tmpdir,
                mode="safe",
                session=session,
            )
            report = cleaner.run()

        skipped = report["connectors"][0]["skipped"]
        conflict_summary = report["connectors"][0]["conflict_summary"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["id"], "qa-ui-transfer-1")
        self.assertEqual(skipped[0]["reason"], "conflict")
        self.assertEqual(
            {(reference["kind"], reference["id"], reference["state"]) for reference in skipped[0]["references"]},
            {
                ("transfer_processes", "transfer-1", "DEPROVISIONED"),
                ("contract_agreements", "agreement-1", None),
            },
        )
        self.assertEqual(conflict_summary["total"], 1)
        self.assertEqual(conflict_summary["by_entity_kind"], {"assets": 1})
        self.assertEqual(
            conflict_summary["by_reference_kind"],
            {
                "transfer_processes": 1,
                "contract_agreements": 1,
            },
        )
        self.assertEqual(
            conflict_summary["by_reference_state"],
            {
                "transfer_processes:DEPROVISIONED": 1,
                "contract_agreements:unknown": 1,
            },
        )
        self.assertEqual(conflict_summary["sample_ids_by_entity_kind"]["assets"], ["qa-ui-transfer-1"])
        self.assertIn(
            "Assets referenced by contract agreements are preserved by safe cleanup.",
            conflict_summary["remediation"],
        )
        self.assertEqual(report["summary"]["conflict_total"], 1)
        self.assertEqual(report["connectors"][0]["skipped_counts"]["assets"], 1)
        self.assertEqual(report["connectors"][0]["unplanned_counts"]["assets"], 0)


if __name__ == "__main__":
    unittest.main()
