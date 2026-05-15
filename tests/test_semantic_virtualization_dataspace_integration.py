import json
import os
import tempfile
import unittest

from tests.dataset_test_helpers import create_gtfs_source
from validation.components.semantic_virtualization.dataspace_integration import (
    COMPONENT_KEY,
    SemanticVirtualizationDataspaceIntegrationSuite,
    default_semantic_data_url,
    load_gtfs_bench_official_materialization_context,
    load_gtfs_madrid_bench_context,
)
from validation.components.semantic_virtualization.gtfs_bench_materialization import (
    run_gtfs_bench_official_materialization_validation,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        if self._payload is None:
            return json.loads(self.text)
        return self._payload


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def get(self, url, timeout=30, headers=None):
        self.gets.append({"url": url, "headers": headers or {}})
        if url.startswith("http://semantic.example.local"):
            return FakeResponse(
                200,
                text=json.dumps({"head": {}, "results": {"bindings": []}}),
                headers={"Content-Type": "application/sparql-results+json"},
            )
        if url.endswith("/management/v3/contractnegotiations/neg-1"):
            return FakeResponse(200, {"@id": "neg-1", "state": "FINALIZED", "contractAgreementId": "agreement-1"})
        if url.endswith("/management/v3/transferprocesses/transfer-1"):
            return FakeResponse(200, {"@id": "transfer-1", "state": "STARTED"})
        return FakeResponse(404, {"error": "not found"})

    def post(self, url, timeout=30, headers=None, json=None, data=None):
        self.posts.append({"url": url, "headers": headers or {}, "json": json, "data": data})
        if "/protocol/openid-connect/token" in url:
            return FakeResponse(200, {"access_token": f"token-{data['username']}"})
        if url.endswith("/management/v3/assets"):
            return FakeResponse(200, {"@id": json["@id"]})
        if url.endswith("/management/v3/policydefinitions"):
            return FakeResponse(200, {"@id": json["@id"]})
        if url.endswith("/management/v3/contractdefinitions"):
            return FakeResponse(200, {"@id": json["@id"]})
        if url.endswith("/management/v3/catalog/request"):
            return FakeResponse(
                200,
                {
                    "dspace:participantId": "conn-provider",
                    "dcat:dataset": [
                        {
                            "@id": "asset-e2e-sv-fixed-uuid",
                            "odrl:hasPolicy": {"@id": "offer-1"},
                        }
                    ],
                },
            )
        if url.endswith("/management/v3/contractnegotiations"):
            return FakeResponse(200, {"@id": "neg-1"})
        if url.endswith("/management/v3/inesdatatransferprocesses"):
            return FakeResponse(200, {"@id": "transfer-1"})
        return FakeResponse(404, {"error": "not found"})


class SemanticVirtualizationDataspaceIntegrationTests(unittest.TestCase):
    def _suite(self, session):
        credentials = {
            "conn-provider": {"connector_user": {"user": "provider-user", "passwd": "provider-pass"}},
            "conn-consumer": {"connector_user": {"user": "consumer-user", "passwd": "consumer-pass"}},
        }
        return SemanticVirtualizationDataspaceIntegrationSuite(
            load_connector_credentials=lambda connector: credentials[connector],
            load_deployer_config=lambda: {
                "KC_URL": "auth.example.local",
                "PIONERA_ADAPTER": "inesdata",
            },
            ds_domain_resolver=lambda: "example.local",
            ds_name_loader=lambda: "demo",
            protocol_address_resolver=lambda connector: f"http://{connector}:19194/protocol",
            session=session,
            uuid_factory=lambda: "fixed-uuid",
        )

    def test_run_publishes_semantic_virtualization_as_httpdata_and_starts_transfer(self):
        session = FakeSession()
        suite = self._suite(session)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = suite.run(
                provider="conn-provider",
                consumer="conn-consumer",
                semantic_base_url="http://semantic.example.local",
                semantic_data_url="http://demo-semantic-virtualization.components.svc.cluster.local:8000/?query=ASK%20%7B%7D",
                experiment_dir=tmpdir,
            )
            self.assertTrue(os.path.exists(result["artifacts"]["report_json"]))

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["created_entities"]["asset_id"], "asset-e2e-sv-fixed-uuid")
        self.assertEqual(result["created_entities"]["agreement_id"], "agreement-1")
        self.assertEqual(result["created_entities"]["transfer_id"], "transfer-1")

        asset_requests = [entry for entry in session.posts if entry["url"].endswith("/management/v3/assets")]
        self.assertEqual(len(asset_requests), 1)
        self.assertEqual(
            asset_requests[0]["json"]["dataAddress"]["baseUrl"],
            "http://demo-semantic-virtualization.components.svc.cluster.local:8000/?query=ASK%20%7B%7D",
        )

        transfer_requests = [
            entry for entry in session.posts if entry["url"].endswith("/management/v3/inesdatatransferprocesses")
        ]
        self.assertEqual(len(transfer_requests), 1)
        self.assertEqual(transfer_requests[0]["json"]["transferType"], "AmazonS3-PUSH")
        self.assertEqual(transfer_requests[0]["json"]["@type"], "TransferRequest")
        self.assertEqual(transfer_requests[0]["json"]["dataDestination"]["type"], "InesDataStore")

    def test_default_semantic_data_url_uses_internal_cluster_service(self):
        class Adapter:
            def load_deployer_config(self):
                return {"COMPONENTS_NAMESPACE": "components"}

            class config:
                @staticmethod
                def dataspace_name():
                    return "demo"

        self.assertEqual(
            default_semantic_data_url(Adapter()),
            "http://demo-semantic-virtualization.components.svc.cluster.local:8000"
            "/?query=SELECT%20*%20WHERE%20%7B%20%3Fs%20%3Fp%20%3Fo%20.%20%7D%20LIMIT%201",
        )

    def test_component_key_is_stable(self):
        self.assertEqual(COMPONENT_KEY, "semantic-virtualization")

    def test_gtfs_madrid_bench_context_loads_dataset_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            context = load_gtfs_madrid_bench_context(str(source_dir))

        self.assertEqual(context["case_id"], "MH-MOB-01")
        self.assertEqual(context["dataset_name"], "GTFS-Madrid-Bench")
        self.assertEqual(context["record_counts"]["STOPS"], 12)
        self.assertEqual(context["sample_summary"]["transfer_benchmark_cases"], 2)
        self.assertEqual(context["join_keys"], ["route_id", "trip_id", "stop_id"])
        self.assertTrue(context["semantic_virtualization_ready"])
        self.assertFalse(context["mobility_model_ready"])
        self.assertEqual(len(context["asset_summary"]["expected_outputs_digest"]), 64)

    def test_run_can_attach_gtfs_mobility_context_without_changing_default_flow(self):
        session = FakeSession()
        suite = self._suite(session)
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            context = load_gtfs_madrid_bench_context(str(source_dir))

        result = suite.run(
            provider="conn-provider",
            consumer="conn-consumer",
            semantic_base_url="http://semantic.example.local",
            semantic_data_url="http://demo-semantic-virtualization.components.svc.cluster.local:8000/?query=ASK%20%7B%7D",
            run_transfer=False,
            integration_context=context,
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["integration_context"]["case_id"], "MH-MOB-01")
        asset_requests = [entry for entry in session.posts if entry["url"].endswith("/management/v3/assets")]
        self.assertEqual(len(asset_requests), 1)
        asset_properties = asset_requests[0]["json"]["properties"]
        self.assertEqual(asset_properties["assetType"], "semantic-virtualization-mobility-output")
        self.assertEqual(asset_properties["daimo:sourceDataset"], "GTFS-Madrid-Bench")
        self.assertIn("GTFS-Madrid-Bench", asset_properties["dcat:keyword"])
        self.assertEqual(asset_properties["sourceObjectName"], "gtfs-bench-source.json")

        transfer_requests = [
            entry for entry in session.posts if entry["url"].endswith("/management/v3/inesdatatransferprocesses")
        ]
        self.assertEqual(transfer_requests, [])

    def test_gtfs_bench_official_materialization_context_loads_asset_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            materialization = run_gtfs_bench_official_materialization_validation(
                source_dir=source_dir,
                experiment_dir=tmpdir,
            )
            context = load_gtfs_bench_official_materialization_context(
                report_path=materialization["artifacts"]["report_json"],
            )

        self.assertEqual(context["case_id"], "SV-GTFS-BENCH-04")
        self.assertEqual(context["dataset_name"], "GTFS-Madrid-Bench")
        self.assertEqual(context["source_repository"], "https://github.com/oeg-upm/gtfs-bench")
        self.assertGreater(context["triple_count"], 300)
        self.assertEqual(context["query_summary"]["simple_q1_rows"], 16)
        self.assertEqual(context["query_summary"]["full_q1_rows"], 16)
        self.assertEqual(context["query_summary"]["route_trip_stop_join_rows"], 12)
        self.assertEqual(len(context["asset_summary"]["expected_outputs_digest"]), 64)
        self.assertEqual(
            context["asset_summary"]["asset_type"],
            "semantic-virtualization-gtfs-bench-rdf-output",
        )

    def test_run_can_attach_gtfs_bench_official_materialization_context(self):
        session = FakeSession()
        suite = self._suite(session)
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = create_gtfs_source(tmpdir)
            materialization = run_gtfs_bench_official_materialization_validation(
                source_dir=source_dir,
                experiment_dir=tmpdir,
            )
            context = load_gtfs_bench_official_materialization_context(
                report_path=materialization["artifacts"]["report_json"],
            )

            result = suite.run(
                provider="conn-provider",
                consumer="conn-consumer",
                semantic_base_url="http://semantic.example.local",
                semantic_data_url=(
                    "http://demo-semantic-virtualization.components.svc.cluster.local:8000"
                    "/?query=ASK%20%7B%7D"
                ),
                run_transfer=False,
                integration_context=context,
            )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["integration_context"]["case_id"], "SV-GTFS-BENCH-04")
        asset_requests = [entry for entry in session.posts if entry["url"].endswith("/management/v3/assets")]
        self.assertEqual(len(asset_requests), 1)
        asset_properties = asset_requests[0]["json"]["properties"]
        self.assertEqual(
            asset_properties["assetType"],
            "semantic-virtualization-gtfs-bench-rdf-output",
        )
        self.assertEqual(asset_properties["daimo:sourceDataset"], "GTFS-Madrid-Bench")
        self.assertEqual(asset_properties["daimo:sourceRepository"], "https://github.com/oeg-upm/gtfs-bench")
        self.assertGreater(asset_properties["daimo:tripleCount"], 300)
        self.assertEqual(asset_properties["daimo:simpleQ1Rows"], 16)
        self.assertIn("SV-GTFS-BENCH-04", asset_properties["dcat:keyword"])
        self.assertEqual(asset_properties["sourceObjectName"], "gtfs_bench_official_materialized.ttl")

        transfer_requests = [
            entry for entry in session.posts if entry["url"].endswith("/management/v3/inesdatatransferprocesses")
        ]
        self.assertEqual(transfer_requests, [])


if __name__ == "__main__":
    unittest.main()
