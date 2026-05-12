from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Callable

import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from deployers.shared.lib.components import resolve_component_release_name
from validation.components.semantic_virtualization.runner import QUERY_PATH


COMPONENT_KEY = "semantic-virtualization"
INTEGRATION_CASE_ID = "INT-VS-DS-01"
EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/"
SUCCESS_TRANSFER_STATES = {"STARTED", "COMPLETED", "FINALIZED", "ENDED", "DEPROVISIONED"}
GTFS_MADRID_BENCH_MINI_DIR = os.path.join(
    PROJECT_ROOT,
    "validation",
    "components",
    "ai_model_hub",
    "fixtures",
    "datasets",
    "mobility",
    "gtfs-madrid-bench-mini",
)
GTFS_BENCH_OFFICIAL_MINI_DIR = os.path.join(
    PROJECT_ROOT,
    "validation",
    "components",
    "semantic_virtualization",
    "fixtures",
    "gtfs-bench-official-mini",
)


class SemanticVirtualizationDataspaceIntegrationSuite:
    """Publish a Semantic Virtualization endpoint as HttpData and consume it via the dataspace."""

    DEFAULT_NEGOTIATION_TIMEOUT_SECONDS = 60
    DEFAULT_TRANSFER_TIMEOUT_SECONDS = 60
    DEFAULT_POLL_INTERVAL_SECONDS = 3
    DEFAULT_REQUEST_ATTEMPTS = 3
    DEFAULT_REQUEST_RETRY_SECONDS = 2

    def __init__(
        self,
        *,
        load_connector_credentials: Callable[[str], dict[str, Any] | None],
        load_deployer_config: Callable[[], dict[str, Any] | None],
        ds_domain_resolver: Callable[[], str],
        ds_name_loader: Callable[[], str] | None = None,
        protocol_address_resolver: Callable[[str], str] | None = None,
        management_url_resolver: Callable[[str, str], str] | None = None,
        keycloak_url_resolver: Callable[[], str] | None = None,
        session: requests.Session | None = None,
        uuid_factory: Callable[[], str] | None = None,
        time_provider: Callable[[], float] | None = None,
    ):
        self.load_connector_credentials = load_connector_credentials
        self.load_deployer_config = load_deployer_config
        self.ds_domain_resolver = ds_domain_resolver
        self.ds_name_loader = ds_name_loader or (lambda: "demo")
        self.protocol_address_resolver = protocol_address_resolver
        self.management_url_resolver = management_url_resolver
        self.keycloak_url_resolver = keycloak_url_resolver
        self.session = session or requests.Session()
        self.uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))
        self.time_provider = time_provider or time.time

    @staticmethod
    def _component_dir(experiment_dir: str | None) -> str | None:
        if not experiment_dir:
            return None
        path = os.path.join(experiment_dir, "components", COMPONENT_KEY, "integration")
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _write_json(path: str, payload: dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

    @staticmethod
    def _safe_suffix(value: str) -> str:
        return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")[:16] or "run"

    def _runtime(self) -> dict[str, Any]:
        config = dict(self.load_deployer_config() or {})
        runtime = {
            "dataspace": str(self.ds_name_loader() or "demo").strip() or "demo",
            "ds_domain": str(self.ds_domain_resolver() or "").strip(),
            "keycloak_url": "",
            "adapter": str(config.get("PIONERA_ADAPTER") or config.get("ADAPTER_NAME") or "inesdata").strip().lower(),
            "negotiation_timeout_seconds": int(
                config.get("SEMANTIC_VIRTUALIZATION_NEGOTIATION_TIMEOUT_SECONDS")
                or self.DEFAULT_NEGOTIATION_TIMEOUT_SECONDS
            ),
            "transfer_timeout_seconds": int(
                config.get("SEMANTIC_VIRTUALIZATION_TRANSFER_TIMEOUT_SECONDS")
                or self.DEFAULT_TRANSFER_TIMEOUT_SECONDS
            ),
            "poll_interval_seconds": int(
                config.get("SEMANTIC_VIRTUALIZATION_POLL_INTERVAL_SECONDS")
                or self.DEFAULT_POLL_INTERVAL_SECONDS
            ),
        }
        if callable(self.keycloak_url_resolver):
            runtime["keycloak_url"] = str(self.keycloak_url_resolver() or "").strip()
        if not runtime["keycloak_url"]:
            runtime["keycloak_url"] = str(config.get("KC_INTERNAL_URL") or config.get("KC_URL") or "").strip()
        if runtime["keycloak_url"] and not runtime["keycloak_url"].startswith("http"):
            runtime["keycloak_url"] = f"http://{runtime['keycloak_url']}"
        if not runtime["ds_domain"]:
            raise RuntimeError("DS_DOMAIN_BASE could not be resolved")
        if not runtime["keycloak_url"]:
            raise RuntimeError("KC_INTERNAL_URL/KC_URL could not be resolved")
        runtime["transfer_start_path"] = (
            "transferprocesses" if runtime["adapter"] == "edc" else "inesdatatransferprocesses"
        )
        runtime["transfer_destination_type"] = "HttpData" if runtime["adapter"] == "edc" else "InesDataStore"
        runtime["transfer_type"] = "HttpData-PULL" if runtime["adapter"] == "edc" else "AmazonS3-PUSH"
        return runtime

    def _management_url(self, connector: str, path: str) -> str:
        if callable(self.management_url_resolver):
            resolved = str(self.management_url_resolver(connector, path) or "").strip()
            if resolved:
                return resolved
        return f"http://{connector}.{self.ds_domain_resolver()}{path}"

    def _protocol_address(self, connector: str) -> str:
        if callable(self.protocol_address_resolver):
            resolved = str(self.protocol_address_resolver(connector) or "").strip()
            if resolved:
                return resolved
        return f"http://{connector}:19194/protocol"

    def _request_with_retry(self, method: str, url: str, *, label: str, **kwargs):
        last_exc = None
        for attempt in range(1, self.DEFAULT_REQUEST_ATTEMPTS + 1):
            try:
                response = getattr(self.session, method)(url, timeout=30, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= self.DEFAULT_REQUEST_ATTEMPTS:
                    raise
                time.sleep(self.DEFAULT_REQUEST_RETRY_SECONDS)
                continue
            if response.status_code in {502, 503, 504} and attempt < self.DEFAULT_REQUEST_ATTEMPTS:
                time.sleep(self.DEFAULT_REQUEST_RETRY_SECONDS)
                continue
            return response
        raise last_exc or RuntimeError(f"{label} did not produce a response")

    @staticmethod
    def _assert_status(response, expected_codes: set[int], label: str) -> None:
        if response.status_code not in expected_codes:
            raise RuntimeError(f"{label} failed with HTTP {response.status_code}: {response.text[:500]}")

    def _get_text(self, url: str, label: str, headers: dict[str, str] | None = None) -> tuple[int, str, str]:
        response = self._request_with_retry("get", url, label=label, headers=headers or {})
        return response.status_code, response.headers.get("Content-Type", ""), response.text

    def _post_json(self, url: str, token: str, payload: dict[str, Any], label: str) -> tuple[Any, int]:
        response = self._request_with_retry(
            "post",
            url,
            label=label,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        self._assert_status(response, {200, 201}, label)
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    def _get_json(self, url: str, token: str, label: str, accepted_statuses: set[int] | None = None):
        accepted = accepted_statuses or {200}
        response = self._request_with_retry("get", url, label=label, headers={"Authorization": f"Bearer {token}"})
        self._assert_status(response, accepted, label)
        if response.status_code == 404:
            return None, response.status_code
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    def _login(self, connector: str, role_key: str, runtime: dict[str, Any]) -> str:
        credentials = self.load_connector_credentials(connector) or {}
        connector_user = credentials.get("connector_user") or {}
        username = connector_user.get("user")
        password = connector_user.get("passwd")
        if not username or not password:
            raise RuntimeError(f"Missing connector_user credentials for {connector}")

        login_url = f"{runtime['keycloak_url']}/realms/{runtime['dataspace']}/protocol/openid-connect/token"
        response = self._request_with_retry(
            "post",
            login_url,
            label=f"{role_key} login",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "password",
                "client_id": "dataspace-users",
                "username": username,
                "password": password,
                "scope": "openid profile email",
            },
        )
        self._assert_status(response, {200}, f"{role_key} login")
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError(f"{role_key} login did not return access_token")
        return token

    def _create_asset(
        self,
        provider: str,
        provider_jwt: str,
        semantic_data_url: str,
        suffix: str,
        integration_context: dict[str, Any] | None = None,
    ):
        asset_id = f"asset-e2e-sv-{suffix}"
        context_summary = (integration_context or {}).get("asset_summary") or {}
        keywords = ["validation", "semantic-virtualization", "HttpData", "A5.2"]
        keywords.extend(context_summary.get("keywords") or [])
        properties = {
            "name": context_summary.get("name") or f"Semantic Virtualization HttpData Asset {suffix}",
            "version": context_summary.get("version") or "1.0.0",
            "shortDescription": context_summary.get("short_description")
            or "Semantic Virtualization output exposed as HttpData",
            "assetType": context_summary.get("asset_type") or "semantic-virtualization-output",
            "dct:description": context_summary.get("description")
            or "SPARQL/RDF output produced by semantic-virtualization for A5.2 integration",
            "dcat:keyword": list(dict.fromkeys(keywords)),
            "sourceObjectName": context_summary.get("source_object_name") or f"semantic-virtualization-{suffix}.rdf",
        }
        if context_summary.get("dataset_name"):
            properties["daimo:sourceDataset"] = context_summary["dataset_name"]
        if context_summary.get("domain"):
            properties["daimo:domain"] = context_summary["domain"]
        if context_summary.get("task"):
            properties["daimo:task"] = context_summary["task"]
        if context_summary.get("expected_outputs_digest"):
            properties["daimo:expectedOutputsDigest"] = context_summary["expected_outputs_digest"]
        for key, value in (context_summary.get("extra_properties") or {}).items():
            if value not in (None, "", []):
                properties[key] = value
        payload = {
            "@context": {
                "@vocab": EDC_NAMESPACE,
                "dct": "http://purl.org/dc/terms/",
                "dcat": "http://www.w3.org/ns/dcat#",
                "daimo": "https://w3id.org/daimo/0.0.1/ns#",
            },
            "@id": asset_id,
            "@type": "Asset",
            "properties": properties,
            "dataAddress": {
                "type": "HttpData",
                "baseUrl": semantic_data_url,
                "name": f"semantic-virtualization-{suffix}.rdf",
            },
        }
        body, status_code = self._post_json(
            self._management_url(provider, "/management/v3/assets"),
            provider_jwt,
            payload,
            "semantic virtualization asset creation",
        )
        return asset_id, body.get("@id") or body.get("id") or asset_id, status_code, payload

    def _create_policy(self, provider: str, provider_jwt: str, suffix: str):
        policy_id = f"policy-e2e-sv-{suffix}"
        payload = {
            "@context": {"@vocab": EDC_NAMESPACE, "odrl": "http://www.w3.org/ns/odrl/2/"},
            "@id": policy_id,
            "policy": {
                "@context": "http://www.w3.org/ns/odrl.jsonld",
                "@type": "Set",
                "permission": [],
                "prohibition": [],
                "obligation": [],
            },
        }
        body, status_code = self._post_json(
            self._management_url(provider, "/management/v3/policydefinitions"),
            provider_jwt,
            payload,
            "semantic virtualization policy creation",
        )
        return policy_id, body.get("@id") or body.get("id") or policy_id, status_code

    def _create_contract_definition(self, provider: str, provider_jwt: str, asset_id: str, policy_id: str, suffix: str):
        contract_definition_id = f"contract-e2e-sv-{suffix}"
        payload = {
            "@context": {"@vocab": EDC_NAMESPACE},
            "@id": contract_definition_id,
            "accessPolicyId": policy_id,
            "contractPolicyId": policy_id,
            "assetsSelector": [
                {
                    "operandLeft": f"{EDC_NAMESPACE}id",
                    "operator": "=",
                    "operandRight": asset_id,
                }
            ],
        }
        body, status_code = self._post_json(
            self._management_url(provider, "/management/v3/contractdefinitions"),
            provider_jwt,
            payload,
            "semantic virtualization contract definition creation",
        )
        return contract_definition_id, body.get("@id") or body.get("id") or contract_definition_id, status_code

    def _request_catalog(self, provider: str, consumer: str, consumer_jwt: str):
        payload = {
            "@context": {"@vocab": EDC_NAMESPACE},
            "@type": "CatalogRequest",
            "counterPartyAddress": self._protocol_address(provider),
            "counterPartyId": provider,
            "protocol": "dataspace-protocol-http",
            "querySpec": {"offset": 0, "limit": 100, "filterExpression": []},
        }
        return self._post_json(
            self._management_url(consumer, "/management/v3/catalog/request"),
            consumer_jwt,
            payload,
            "semantic virtualization catalog request",
        )

    @staticmethod
    def _select_catalog_dataset(catalog_body: Any, expected_asset_id: str, fallback_provider: str) -> dict[str, Any]:
        catalog = catalog_body[0] if isinstance(catalog_body, list) and catalog_body else catalog_body
        if not isinstance(catalog, dict):
            raise RuntimeError("Catalog response is empty or invalid")
        datasets = catalog.get("dcat:dataset") or []
        if not isinstance(datasets, list):
            datasets = [datasets]
        dataset = next(
            (item for item in datasets if isinstance(item, dict) and expected_asset_id in json.dumps(item)),
            None,
        )
        if dataset is None:
            raise RuntimeError(f"Catalog does not contain asset {expected_asset_id}")
        policy = dataset.get("odrl:hasPolicy")
        if isinstance(policy, list):
            policy = policy[0] if policy else None
        offer_id = policy.get("@id") if isinstance(policy, dict) else None
        if not offer_id:
            raise RuntimeError("Catalog dataset does not expose offer policy id")
        return {
            "catalog_asset_id": dataset.get("@id") or expected_asset_id,
            "offer_id": offer_id,
            "provider_participant_id": catalog.get("dspace:participantId") or fallback_provider,
            "dataset": dataset,
        }

    def _start_negotiation(self, provider: str, consumer: str, consumer_jwt: str, catalog_info: dict[str, Any]):
        payload = {
            "@context": {"@vocab": EDC_NAMESPACE},
            "@type": "ContractRequest",
            "counterPartyAddress": self._protocol_address(provider),
            "protocol": "dataspace-protocol-http",
            "policy": {
                "@context": "http://www.w3.org/ns/odrl.jsonld",
                "@type": "odrl:Offer",
                "@id": catalog_info["offer_id"],
                "assigner": catalog_info["provider_participant_id"],
                "target": catalog_info["catalog_asset_id"],
                "permission": [],
                "prohibition": [],
                "obligation": [],
            },
        }
        body, status_code = self._post_json(
            self._management_url(consumer, "/management/v3/contractnegotiations"),
            consumer_jwt,
            payload,
            "semantic virtualization contract negotiation start",
        )
        negotiation_id = body.get("@id") or body.get("id")
        if not negotiation_id:
            raise RuntimeError("Negotiation creation did not return negotiation id")
        return negotiation_id, status_code

    def _query_negotiation(self, consumer: str, consumer_jwt: str, negotiation_id: str):
        body, status = self._get_json(
            self._management_url(consumer, f"/management/v3/contractnegotiations/{negotiation_id}"),
            consumer_jwt,
            "semantic virtualization contract negotiation lookup",
            accepted_statuses={200, 404},
        )
        if status == 200 and isinstance(body, dict):
            return body
        body, _ = self._post_json(
            self._management_url(consumer, "/management/v3/contractnegotiations/request"),
            consumer_jwt,
            {"@context": {"@vocab": EDC_NAMESPACE}, "offset": 0, "limit": 100},
            "semantic virtualization contract negotiation query",
        )
        if isinstance(body, list):
            return next((item for item in body if isinstance(item, dict) and item.get("@id") == negotiation_id), None)
        return body if isinstance(body, dict) else None

    def _wait_for_agreement(self, consumer: str, consumer_jwt: str, negotiation_id: str, runtime: dict[str, Any]):
        deadline = self.time_provider() + int(runtime["negotiation_timeout_seconds"])
        last_state = None
        while self.time_provider() <= deadline:
            negotiation = self._query_negotiation(consumer, consumer_jwt, negotiation_id)
            if negotiation:
                last_state = negotiation.get("state")
                agreement_id = negotiation.get("contractAgreementId")
                if agreement_id:
                    return {"state": last_state, "agreement_id": agreement_id, "raw": negotiation}
                if last_state == "TERMINATED":
                    raise RuntimeError(
                        "Negotiation reached TERMINATED state"
                        + (f": {negotiation.get('errorDetail')}" if negotiation.get("errorDetail") else "")
                    )
            time.sleep(max(1, int(runtime["poll_interval_seconds"])))
        raise RuntimeError(f"Negotiation {negotiation_id} did not produce contractAgreementId (last_state={last_state})")

    def _start_transfer(
        self,
        provider: str,
        consumer: str,
        consumer_jwt: str,
        asset_id: str,
        agreement_id: str,
        runtime: dict[str, Any],
    ):
        if runtime["adapter"] == "edc":
            payload = {
                "@context": {"@vocab": EDC_NAMESPACE},
                "@type": "TransferRequestDto",
                "connectorId": provider,
                "contractId": agreement_id,
                "counterPartyAddress": self._protocol_address(provider),
                "protocol": "dataspace-protocol-http",
                "transferType": runtime["transfer_type"],
            }
        else:
            payload = {
                "@context": {"@vocab": EDC_NAMESPACE},
                "@type": "TransferRequest",
                "assetId": asset_id,
                "contractId": agreement_id,
                "counterPartyAddress": self._protocol_address(provider),
                "protocol": "dataspace-protocol-http",
                "transferType": runtime["transfer_type"],
                "dataDestination": {"type": runtime["transfer_destination_type"]},
            }
        body, status_code = self._post_json(
            self._management_url(consumer, f"/management/v3/{runtime['transfer_start_path']}"),
            consumer_jwt,
            payload,
            "semantic virtualization transfer start",
        )
        transfer_id = body.get("@id") or body.get("id")
        if not transfer_id:
            raise RuntimeError("Transfer creation did not return transfer id")
        return transfer_id, status_code

    def _query_transfer(self, consumer: str, consumer_jwt: str, transfer_id: str):
        body, status = self._get_json(
            self._management_url(consumer, f"/management/v3/transferprocesses/{transfer_id}"),
            consumer_jwt,
            "semantic virtualization transfer lookup",
            accepted_statuses={200, 404},
        )
        if status == 200 and isinstance(body, dict):
            return body
        body, _ = self._post_json(
            self._management_url(consumer, "/management/v3/transferprocesses/request"),
            consumer_jwt,
            {"@context": {"@vocab": EDC_NAMESPACE}, "offset": 0, "limit": 100},
            "semantic virtualization transfer query",
        )
        if isinstance(body, list):
            return next((item for item in body if isinstance(item, dict) and item.get("@id") == transfer_id), None)
        return body if isinstance(body, dict) else None

    def _wait_for_transfer(self, consumer: str, consumer_jwt: str, transfer_id: str, runtime: dict[str, Any]):
        deadline = self.time_provider() + int(runtime["transfer_timeout_seconds"])
        last_state = None
        while self.time_provider() <= deadline:
            transfer = self._query_transfer(consumer, consumer_jwt, transfer_id)
            if transfer:
                last_state = transfer.get("state")
                if last_state in SUCCESS_TRANSFER_STATES:
                    return {"state": last_state, "raw": transfer}
                if last_state == "TERMINATED":
                    raise RuntimeError(
                        "Transfer reached TERMINATED state"
                        + (f": {transfer.get('errorDetail')}" if transfer.get("errorDetail") else "")
                    )
            time.sleep(max(1, int(runtime["poll_interval_seconds"])))
        raise RuntimeError(f"Transfer {transfer_id} did not reach a successful state (last_state={last_state})")

    def run(
        self,
        *,
        provider: str,
        consumer: str,
        semantic_base_url: str,
        semantic_data_url: str,
        experiment_dir: str | None = None,
        run_transfer: bool = True,
        integration_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now().isoformat()
        runtime = self._runtime()
        component_dir = self._component_dir(experiment_dir)
        suffix = self._safe_suffix(self.uuid_factory())
        steps: list[dict[str, Any]] = []
        artifacts: dict[str, str] = {}

        def step(name: str, status: str = "passed", **payload: Any) -> None:
            steps.append({"name": name, "status": status, **payload})

        try:
            probe_status, probe_content_type, probe_body = self._get_text(
                semantic_base_url.rstrip("/") + QUERY_PATH,
                "semantic virtualization public query probe",
                headers={"Accept": "application/sparql-results+json"},
            )
            if probe_status != 200:
                raise RuntimeError(f"Semantic Virtualization query probe returned HTTP {probe_status}")
            step(
                "probe_semantic_virtualization_query",
                http_status=probe_status,
                content_type=probe_content_type,
                body_excerpt=probe_body[:300],
            )

            provider_jwt = self._login(provider, "provider", runtime)
            step("provider_login", connector=provider)
            consumer_jwt = self._login(consumer, "consumer", runtime)
            step("consumer_login", connector=consumer)

            asset_id, created_asset_id, asset_status, asset_payload = self._create_asset(
                provider,
                provider_jwt,
                semantic_data_url,
                suffix,
                integration_context=integration_context,
            )
            step("create_httpdata_asset", http_status=asset_status, asset_id=created_asset_id)
            policy_id, created_policy_id, policy_status = self._create_policy(provider, provider_jwt, suffix)
            step("create_policy", http_status=policy_status, policy_id=created_policy_id)
            contract_id, created_contract_id, contract_status = self._create_contract_definition(
                provider,
                provider_jwt,
                asset_id,
                policy_id,
                suffix,
            )
            step("create_contract_definition", http_status=contract_status, contract_definition_id=created_contract_id)

            catalog_body, catalog_status = self._request_catalog(provider, consumer, consumer_jwt)
            catalog_info = self._select_catalog_dataset(catalog_body, asset_id, provider)
            step(
                "request_catalog",
                http_status=catalog_status,
                catalog_asset_id=catalog_info["catalog_asset_id"],
                offer_id=catalog_info["offer_id"],
            )

            negotiation_id, negotiation_status = self._start_negotiation(provider, consumer, consumer_jwt, catalog_info)
            step("start_negotiation", http_status=negotiation_status, negotiation_id=negotiation_id)
            agreement = self._wait_for_agreement(consumer, consumer_jwt, negotiation_id, runtime)
            step(
                "wait_for_contract_agreement",
                state=agreement["state"],
                agreement_id=agreement["agreement_id"],
            )

            transfer = None
            if run_transfer:
                transfer_id, transfer_status = self._start_transfer(
                    provider,
                    consumer,
                    consumer_jwt,
                    asset_id,
                    agreement["agreement_id"],
                    runtime,
                )
                step("start_transfer", http_status=transfer_status, transfer_id=transfer_id)
                transfer = self._wait_for_transfer(consumer, consumer_jwt, transfer_id, runtime)
                step("wait_for_transfer_state", state=transfer["state"])
            else:
                step("start_transfer", status="skipped", reason="run_transfer_disabled")

            status = "passed"
            error_payload = None
        except Exception as exc:
            status = "failed"
            error_payload = {"type": type(exc).__name__, "message": str(exc)}
            step("suite_error", status="failed", **error_payload)
            asset_payload = locals().get("asset_payload")
            agreement = locals().get("agreement")
            transfer = locals().get("transfer")

        summary = {
            "total": len(steps),
            "passed": sum(1 for item in steps if item.get("status") == "passed"),
            "failed": sum(1 for item in steps if item.get("status") == "failed"),
            "skipped": sum(1 for item in steps if item.get("status") == "skipped"),
        }
        result = {
            "component": COMPONENT_KEY,
            "suite": "dataspace-integration",
            "test_case_id": INTEGRATION_CASE_ID,
            "status": status,
            "summary": summary,
            "timestamp": started_at,
            "provider": provider,
            "consumer": consumer,
            "semantic_base_url": semantic_base_url,
            "semantic_data_url": semantic_data_url,
            "run_transfer": run_transfer,
            "integration_context": integration_context,
            "runtime": {
                "dataspace": runtime.get("dataspace"),
                "ds_domain": runtime.get("ds_domain"),
                "adapter": runtime.get("adapter"),
                "transfer_start_path": runtime.get("transfer_start_path"),
                "transfer_destination_type": runtime.get("transfer_destination_type"),
            },
            "steps": steps,
            "created_entities": {
                "asset_id": locals().get("asset_id"),
                "policy_id": locals().get("policy_id"),
                "contract_definition_id": locals().get("contract_id"),
                "negotiation_id": locals().get("negotiation_id"),
                "agreement_id": (agreement or {}).get("agreement_id") if isinstance(agreement, dict) else None,
                "transfer_id": locals().get("transfer_id"),
            },
            "asset_payload": asset_payload if isinstance(locals().get("asset_payload"), dict) else None,
            "error": error_payload,
        }

        if component_dir:
            report_path = os.path.join(component_dir, "semantic_virtualization_dataspace_integration.json")
            self._write_json(report_path, result)
            artifacts["report_json"] = report_path
            result["artifacts"] = artifacts
        else:
            result["artifacts"] = {}
        return result


def _dataspace_name_loader(adapter):
    config = getattr(adapter, "config", None)
    getter = getattr(config, "dataspace_name", None)
    if callable(getter):
        return getter
    return lambda: "demo"


def build_inesdata_semantic_virtualization_suite(topology: str = "local"):
    from adapters.inesdata.adapter import InesdataAdapter

    adapter = InesdataAdapter(topology=topology)
    return SemanticVirtualizationDataspaceIntegrationSuite(
        load_connector_credentials=adapter.load_connector_credentials,
        load_deployer_config=adapter.load_deployer_config,
        ds_domain_resolver=adapter.config.ds_domain_base,
        ds_name_loader=_dataspace_name_loader(adapter),
        protocol_address_resolver=getattr(adapter.connectors, "build_internal_protocol_address", None),
    ), adapter


def default_semantic_data_url(adapter, query_path: str = QUERY_PATH) -> str:
    config = adapter.load_deployer_config() or {}
    dataspace = str(_dataspace_name_loader(adapter)() or "demo").strip() or "demo"
    namespace = str(config.get("COMPONENTS_NAMESPACE") or "components").strip() or "components"
    release = resolve_component_release_name(COMPONENT_KEY, dataspace_name=dataspace)
    return f"http://{release}.{namespace}.svc.cluster.local:8000{query_path}"


def default_semantic_public_url(adapter) -> str:
    infer = getattr(adapter.components, "infer_component_urls", None)
    if callable(infer):
        urls = infer([COMPONENT_KEY])
        url = str((urls or {}).get(COMPONENT_KEY) or "").strip()
        if url:
            return url.rstrip("/")
    config = adapter.load_deployer_config() or {}
    dataspace = str(_dataspace_name_loader(adapter)() or "demo").strip() or "demo"
    ds_domain = str(config.get("DS_DOMAIN_BASE") or adapter.config.ds_domain_base() or "").strip()
    return f"http://{COMPONENT_KEY}-{dataspace}.{ds_domain}".rstrip("/")


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_gtfs_madrid_bench_mini_context(fixture_dir: str | None = None) -> dict[str, Any]:
    resolved_dir = os.path.abspath(fixture_dir or GTFS_MADRID_BENCH_MINI_DIR)
    expected_files = {
        "metadata": "metadata.json",
        "schema": "schema.json",
        "sample": "benchmark_sample.json",
        "expected_outputs": "expected_outputs.json",
    }
    missing = [name for name in expected_files.values() if not os.path.exists(os.path.join(resolved_dir, name))]
    if missing:
        raise RuntimeError(f"GTFS-Madrid-Bench-mini fixture is missing required files: {', '.join(missing)}")

    metadata = _read_json(os.path.join(resolved_dir, expected_files["metadata"]))
    sample = _read_json(os.path.join(resolved_dir, expected_files["sample"]))
    expected_outputs_path = os.path.join(resolved_dir, expected_files["expected_outputs"])
    expected_outputs = _read_json(expected_outputs_path)
    record_counts = expected_outputs.get("benchmark_sample", {}).get("recordCounts") or {}
    transfer_cases = expected_outputs.get("benchmark_sample", {}).get("transferCases") or []

    return {
        "case_id": "MH-MOB-01",
        "fixture_name": metadata.get("datasetName") or "GTFS-Madrid-Bench-mini",
        "fixture_dir": resolved_dir,
        "metadata_source": os.path.join(resolved_dir, expected_files["metadata"]),
        "schema_source": os.path.join(resolved_dir, expected_files["schema"]),
        "sample_source": os.path.join(resolved_dir, expected_files["sample"]),
        "expected_outputs_source": expected_outputs_path,
        "record_counts": record_counts,
        "transfer_case_count": len(transfer_cases),
        "join_keys": expected_outputs.get("integrationExpectations", {}).get("joinKeys") or [],
        "semantic_virtualization_ready": bool(
            expected_outputs.get("integrationExpectations", {}).get("semanticVirtualizationReady")
        ),
        "mobility_model_ready": bool(expected_outputs.get("integrationExpectations", {}).get("mobilityModelReady")),
        "asset_summary": {
            "name": f"{metadata.get('datasetName') or 'GTFS-Madrid-Bench-mini'} via Semantic Virtualization",
            "version": metadata.get("version") or "mini-v1",
            "short_description": "Semantic Virtualization HttpData asset linked to GTFS-Madrid-Bench-mini",
            "description": (
                "Semantic Virtualization output exposed as HttpData and traced to the "
                "GTFS-Madrid-Bench-mini mobility fixture for MH-MOB-01."
            ),
            "asset_type": "semantic-virtualization-mobility-output",
            "dataset_name": metadata.get("datasetName") or "GTFS-Madrid-Bench-mini",
            "domain": metadata.get("domain") or "mobility",
            "task": metadata.get("task"),
            "keywords": ["GTFS-Madrid-Bench-mini", "mobility", "gtfs", "MH-MOB-01"],
            "source_object_name": metadata.get("assetPublication", {}).get("fileName")
            or "gtfs-madrid-bench-mini.json",
            "expected_outputs_digest": _sha256_file(expected_outputs_path),
        },
        "notes": [
            "This context only adds traceability between INT-VS-DS-01 and the mobility fixture.",
            "It does not imply that a mobility inference model has been executed.",
            "The HttpData resource remains the Semantic Virtualization endpoint selected for the run.",
        ],
        "sample_summary": {
            "stops": len(sample.get("stops") or []),
            "routes": len(sample.get("routes") or []),
            "trips": len(sample.get("trips") or []),
            "stop_times": len(sample.get("stop_times") or []),
            "transfer_benchmark_cases": len(sample.get("transfer_benchmark_cases") or []),
        },
    }


def _resolve_materialization_report_path(report_path: str, experiment_dir: str | None) -> str:
    if report_path:
        resolved = os.path.abspath(report_path)
        if not os.path.exists(resolved):
            raise RuntimeError(f"GTFS-Bench materialization report does not exist: {resolved}")
        return resolved

    materialization_experiment_dir = experiment_dir or os.path.join(
        "experiments",
        f"semantic-virtualization-gtfs-bench-official-materialization-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )
    from validation.components.semantic_virtualization.gtfs_bench_materialization import (
        run_gtfs_bench_official_materialization_validation,
    )

    report = run_gtfs_bench_official_materialization_validation(experiment_dir=materialization_experiment_dir)
    generated = (report.get("artifacts") or {}).get("report_json")
    if not generated:
        raise RuntimeError("GTFS-Bench materialization runner did not produce a report_json artifact")
    return os.path.abspath(generated)


def load_gtfs_bench_official_materialization_context(
    *,
    report_path: str = "",
    experiment_dir: str | None = None,
) -> dict[str, Any]:
    """Build INESData asset metadata for the official-derived GTFS-Bench RDF output."""

    materialization_report_path = _resolve_materialization_report_path(report_path, experiment_dir)
    materialization_report = _read_json(materialization_report_path)
    if materialization_report.get("status") != "passed":
        raise RuntimeError(
            "GTFS-Bench materialization report must be passed before it can be exposed as HttpData"
        )

    artifacts = materialization_report.get("artifacts") or {}
    evidence = ((materialization_report.get("test_cases") or [{}])[0] or {}).get("evidence") or {}
    fixture_dir = evidence.get("fixture_dir") or GTFS_BENCH_OFFICIAL_MINI_DIR
    manifest_path = os.path.join(fixture_dir, "manifest.json")
    manifest = _read_json(manifest_path)
    materialization = evidence.get("materialization") or {}
    mapping_validation = evidence.get("mapping_validation") or {}
    queries = evidence.get("queries") or {}
    source = manifest.get("source") or {}
    record_counts = ((manifest.get("selection") or {}).get("recordCounts")) or {}
    graph_path = artifacts.get("materialized_graph") or materialization.get("graph_path") or ""
    graph_sha256 = materialization.get("graph_sha256") or (_sha256_file(graph_path) if graph_path else "")

    return {
        "case_id": "SV-GTFS-BENCH-04",
        "fixture_name": manifest.get("datasetName") or "GTFS-Bench-official-mini",
        "fixture_dir": os.path.abspath(fixture_dir),
        "manifest_source": manifest_path,
        "materialization_report": materialization_report_path,
        "materialized_graph_path": graph_path,
        "record_counts": record_counts,
        "source_repository": source.get("repository") or "https://github.com/oeg-upm/gtfs-bench",
        "source_commit": source.get("commit"),
        "source_license": source.get("license"),
        "triple_count": materialization.get("triple_count"),
        "query_summary": {
            "simple_q1_rows": (queries.get("simple_q1") or {}).get("row_count"),
            "full_q1_rows": (queries.get("full_q1") or {}).get("row_count"),
            "route_trip_stop_join_rows": (queries.get("route_trip_stop_join_probe") or {}).get("row_count"),
        },
        "asset_summary": {
            "name": "GTFS-Bench official mini RDF via Semantic Virtualization",
            "version": manifest.get("version") or "official-mini-v1",
            "short_description": "Official-derived GTFS-Bench RDF output exposed as HttpData",
            "description": (
                "RDF/Turtle output generated from the official-derived GTFS-Bench mini fixture, "
                "linked to the adapted official CSV mapping and exposed through INESData as HttpData."
            ),
            "asset_type": "semantic-virtualization-gtfs-bench-rdf-output",
            "dataset_name": manifest.get("datasetName") or "GTFS-Bench-official-mini",
            "domain": manifest.get("domain") or "mobility",
            "task": "semantic-virtualization-gtfs-bench-official-materialization",
            "keywords": [
                "GTFS-Madrid-Bench",
                "gtfs-bench",
                "official-derived",
                "semantic-virtualization",
                "rdf",
                "mobility",
                "SV-GTFS-BENCH-04",
            ],
            "source_object_name": os.path.basename(graph_path) or "gtfs_bench_official_mini_materialized.ttl",
            "expected_outputs_digest": graph_sha256,
            "extra_properties": {
                "daimo:sourceRepository": source.get("repository"),
                "daimo:sourceCommit": source.get("commit"),
                "daimo:sourceLicense": source.get("license"),
                "daimo:tripleCount": materialization.get("triple_count"),
                "daimo:shapePointCount": materialization.get("shape_point_count"),
                "daimo:stopTimeCount": materialization.get("stop_time_count"),
                "daimo:mappingTriplesMapCount": mapping_validation.get("triples_map_count"),
                "daimo:mappingSha256": mapping_validation.get("adapted_mapping_sha256"),
                "daimo:simpleQ1Rows": (queries.get("simple_q1") or {}).get("row_count"),
                "daimo:fullQ1Rows": (queries.get("full_q1") or {}).get("row_count"),
                "daimo:joinProbeRows": (queries.get("route_trip_stop_join_probe") or {}).get("row_count"),
            },
        },
        "notes": [
            "This context exposes the official-derived RDF artifact as INESData HttpData metadata.",
            "The default dataAddress still points to the deployed Semantic Virtualization endpoint unless overridden.",
            "The complete official benchmark/generator remains opt-in to avoid destabilizing Level 6.",
        ],
    }


def _default_experiment_dir() -> str:
    return os.path.join("experiments", f"semantic-virtualization-dataspace-{datetime.now().strftime('%Y%m%d-%H%M%S')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run INT-VS-DS-01 Semantic Virtualization + HttpData integration.")
    parser.add_argument("--topology", default="local", choices=["local", "vm-single"])
    parser.add_argument("--provider", default="")
    parser.add_argument("--consumer", default="")
    parser.add_argument("--semantic-base-url", default="")
    parser.add_argument("--semantic-data-url", default="")
    parser.add_argument("--experiment-dir", default="")
    parser.add_argument("--skip-transfer", action="store_true")
    parser.add_argument(
        "--gtfs-madrid-bench-mini",
        action="store_true",
        help="Attach GTFS-Madrid-Bench-mini traceability metadata to the HttpData asset/report.",
    )
    parser.add_argument("--gtfs-fixture-dir", default="")
    parser.add_argument(
        "--gtfs-bench-official-materialization",
        action="store_true",
        help="Attach official-derived GTFS-Bench RDF materialization metadata to the HttpData asset/report.",
    )
    parser.add_argument(
        "--gtfs-materialization-report",
        default="",
        help="Existing SV-GTFS-BENCH-03 report to reuse when attaching official GTFS-Bench metadata.",
    )
    args = parser.parse_args(argv)

    if args.gtfs_madrid_bench_mini and args.gtfs_bench_official_materialization:
        raise RuntimeError("Use only one GTFS context flag per run")

    suite, adapter = build_inesdata_semantic_virtualization_suite(topology=args.topology)
    connectors = list(adapter.get_cluster_connectors() or [])
    provider = args.provider or (connectors[0] if connectors else "")
    consumer = args.consumer or (connectors[1] if len(connectors) > 1 else "")
    if not provider or not consumer:
        raise RuntimeError("Provider and consumer connectors must be provided or discoverable from the cluster")

    semantic_base_url = args.semantic_base_url or default_semantic_public_url(adapter)
    semantic_data_url = args.semantic_data_url or default_semantic_data_url(adapter)
    experiment_dir = args.experiment_dir or _default_experiment_dir()
    integration_context = None
    if args.gtfs_madrid_bench_mini:
        integration_context = load_gtfs_madrid_bench_mini_context(args.gtfs_fixture_dir or None)
    if args.gtfs_bench_official_materialization:
        integration_context = load_gtfs_bench_official_materialization_context(
            report_path=args.gtfs_materialization_report,
            experiment_dir=experiment_dir,
        )
    result = suite.run(
        provider=provider,
        consumer=consumer,
        semantic_base_url=semantic_base_url,
        semantic_data_url=semantic_data_url,
        experiment_dir=experiment_dir,
        run_transfer=not args.skip_transfer,
        integration_context=integration_context,
    )
    print(json.dumps({
        "status": result.get("status"),
        "summary": result.get("summary"),
        "artifact": (result.get("artifacts") or {}).get("report_json"),
    }, indent=2))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
