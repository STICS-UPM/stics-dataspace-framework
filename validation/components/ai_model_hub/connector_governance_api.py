from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Callable

import requests

from validation.components.ai_model_hub.model_execution_api import DEFAULT_MODEL_PATH, DEFAULT_PAYLOAD, default_model_url


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "connector-governance-api"
EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/"
SUCCESS_TRANSFER_STATES = {"REQUESTED", "STARTED", "COMPLETED", "FINALIZED", "ENDED", "DEPROVISIONED"}
CASE_IDS = ["PT5-MH-09", "PT5-MH-11", "PT5-MH-16", "PT5-MH-17", "PT5-MH-18"]

CASE_METADATA: dict[str, dict[str, Any]] = {
    "PT5-MH-09": {
        "description": "Request authorized model access after agreement",
        "type": "api",
        "validation_type": "integration",
        "dataspace_dimension": "execution",
        "expected_result": "An authorized access transfer is accepted for the negotiated model asset",
        "traceability": ["MH-33"],
        "required_steps": ["start_model_access_transfer", "wait_for_model_access_transfer"],
    },
    "PT5-MH-11": {
        "description": "List and use active agreements",
        "type": "api",
        "validation_type": "integration",
        "dataspace_dimension": "execution",
        "expected_result": "The negotiated agreement is listed and selected for model access",
        "traceability": ["MH-36"],
        "required_steps": ["wait_for_contract_agreement", "list_active_agreements"],
    },
    "PT5-MH-16": {
        "description": "Access connector APIs with OIDC",
        "type": "api",
        "validation_type": "integration",
        "dataspace_dimension": "identity",
        "expected_result": "Provider and consumer connector APIs accept OIDC authenticated access",
        "traceability": ["MH-45"],
        "required_steps": ["provider_oidc_login", "consumer_oidc_login"],
    },
    "PT5-MH-17": {
        "description": "Record relevant AI Model Hub connector operations",
        "type": "api",
        "validation_type": "non_functional",
        "dataspace_dimension": "governance",
        "expected_result": "The suite records a non-secret operational trace for publication, negotiation and access",
        "traceability": ["MH-46"],
        "required_steps": [
            "provider_oidc_login",
            "consumer_oidc_login",
            "create_httpdata_model_asset",
            "start_negotiation",
            "write_traceability_record",
        ],
    },
    "PT5-MH-18": {
        "description": "Consume connector APIs from the AI Model Hub integration flow",
        "type": "api",
        "validation_type": "integration",
        "dataspace_dimension": "integration",
        "expected_result": "The flow consumes provider and consumer connector APIs end to end",
        "traceability": ["MH-47"],
        "required_steps": [
            "create_httpdata_model_asset",
            "create_policy",
            "create_contract_definition",
            "request_catalog",
            "start_negotiation",
        ],
    },
}


class AIModelHubConnectorGovernanceApiSuite:
    """Validate AI Model Hub connector-side access, agreements, OIDC and traceability."""

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
        return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")[:18] or "run"

    @staticmethod
    def _extract_items(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("results", "items", "contractAgreements", "@graph", "dcat:dataset", "datasets"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return [value]
        return [payload]

    @staticmethod
    def _body_json_or_text(response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw_body": response.text[:1000]}

    def _runtime(self) -> dict[str, Any]:
        config = dict(self.load_deployer_config() or {})
        runtime = {
            "dataspace": str(self.ds_name_loader() or "demo").strip() or "demo",
            "ds_domain": str(self.ds_domain_resolver() or "").strip(),
            "keycloak_url": "",
            "adapter": str(config.get("PIONERA_ADAPTER") or config.get("ADAPTER_NAME") or "inesdata").strip().lower(),
            "negotiation_timeout_seconds": int(
                config.get("AI_MODEL_HUB_NEGOTIATION_TIMEOUT_SECONDS")
                or self.DEFAULT_NEGOTIATION_TIMEOUT_SECONDS
            ),
            "transfer_timeout_seconds": int(
                config.get("AI_MODEL_HUB_TRANSFER_TIMEOUT_SECONDS") or self.DEFAULT_TRANSFER_TIMEOUT_SECONDS
            ),
            "poll_interval_seconds": int(
                config.get("AI_MODEL_HUB_POLL_INTERVAL_SECONDS") or self.DEFAULT_POLL_INTERVAL_SECONDS
            ),
            "access_transfer_path": str(config.get("AI_MODEL_HUB_ACCESS_TRANSFER_PATH") or "transferprocesses"),
            "access_transfer_type": str(config.get("AI_MODEL_HUB_ACCESS_TRANSFER_TYPE") or "HttpData-PULL"),
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
            label=f"{role_key} OIDC login",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "password",
                "client_id": "dataspace-users",
                "username": username,
                "password": password,
                "scope": "openid profile email",
            },
        )
        self._assert_status(response, {200}, f"{role_key} OIDC login")
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError(f"{role_key} OIDC login did not return access_token")
        return token

    def _post_json(
        self,
        url: str,
        token: str,
        payload: dict[str, Any],
        label: str,
        accepted_statuses: set[int] | None = None,
    ) -> tuple[Any, int]:
        response = self._request_with_retry(
            "post",
            url,
            label=label,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        self._assert_status(response, accepted_statuses or {200, 201}, label)
        return self._body_json_or_text(response), response.status_code

    def _get_json(
        self,
        url: str,
        token: str,
        label: str,
        accepted_statuses: set[int] | None = None,
    ) -> tuple[Any, int]:
        response = self._request_with_retry(
            "get",
            url,
            label=label,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        self._assert_status(response, accepted_statuses or {200}, label)
        return self._body_json_or_text(response), response.status_code

    def _delete_optional(self, url: str, token: str, label: str) -> tuple[int, Any]:
        response = self._request_with_retry("delete", url, label=label, headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 204:
            return response.status_code, None
        return response.status_code, self._body_json_or_text(response)

    def _create_model_asset(self, provider: str, provider_jwt: str, model_url: str, model_path: str, suffix: str):
        asset_id = f"a52-amh-access-{suffix}"
        payload = {
            "@context": {
                "@vocab": EDC_NAMESPACE,
                "dct": "http://purl.org/dc/terms/",
                "dcat": "http://www.w3.org/ns/dcat#",
                "daimo": "https://w3id.org/daimo/0.0.1/ns#",
            },
            "@id": asset_id,
            "@type": "Asset",
            "properties": {
                "name": f"AI Model Hub access model {suffix}",
                "version": "1.0.0",
                "shortDescription": "Temporary executable model endpoint for A5.2 connector governance validation",
                "assetType": "ai-model-execution-endpoint",
                "dct:description": "HttpData model endpoint negotiated and accessed through connector APIs",
                "dcat:keyword": ["validation", "ai-model-hub", "model-access", "A5.2"],
                "daimo:inference_path": model_path,
            },
            "dataAddress": {
                "type": "HttpData",
                "baseUrl": model_url,
                "method": "POST",
                "name": f"ai-model-hub-access-{suffix}",
            },
        }
        body, status_code = self._post_json(
            self._management_url(provider, "/management/v3/assets"),
            provider_jwt,
            payload,
            "AI Model Hub access asset creation",
        )
        return asset_id, body.get("@id") or body.get("id") or asset_id, status_code, payload

    def _create_policy(self, provider: str, provider_jwt: str, suffix: str):
        policy_id = f"policy-a52-amh-{suffix}"
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
            "AI Model Hub access policy creation",
        )
        return policy_id, body.get("@id") or body.get("id") or policy_id, status_code

    def _create_contract_definition(self, provider: str, provider_jwt: str, asset_id: str, policy_id: str, suffix: str):
        contract_definition_id = f"contract-a52-amh-{suffix}"
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
            "AI Model Hub access contract definition creation",
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
            "AI Model Hub access catalog request",
        )

    @staticmethod
    def _select_catalog_dataset(catalog_body: Any, expected_asset_id: str, fallback_provider: str) -> dict[str, Any]:
        catalog = catalog_body[0] if isinstance(catalog_body, list) and catalog_body else catalog_body
        if not isinstance(catalog, dict):
            raise RuntimeError("Catalog response is empty or invalid")
        dataset = next(
            (
                item
                for item in AIModelHubConnectorGovernanceApiSuite._extract_items(catalog)
                if isinstance(item, dict) and expected_asset_id in json.dumps(item)
            ),
            None,
        )
        if dataset is None:
            raise RuntimeError(f"Catalog does not contain AI Model Hub asset {expected_asset_id}")
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
            "AI Model Hub access contract negotiation start",
        )
        negotiation_id = body.get("@id") or body.get("id")
        if not negotiation_id:
            raise RuntimeError("Negotiation creation did not return negotiation id")
        return negotiation_id, status_code

    def _query_negotiation(self, consumer: str, consumer_jwt: str, negotiation_id: str):
        body, status = self._get_json(
            self._management_url(consumer, f"/management/v3/contractnegotiations/{negotiation_id}"),
            consumer_jwt,
            "AI Model Hub access contract negotiation lookup",
            accepted_statuses={200, 404},
        )
        if status == 200 and isinstance(body, dict):
            return body
        body, _ = self._post_json(
            self._management_url(consumer, "/management/v3/contractnegotiations/request"),
            consumer_jwt,
            {"@context": {"@vocab": EDC_NAMESPACE}, "offset": 0, "limit": 100},
            "AI Model Hub access contract negotiation query",
        )
        return next(
            (item for item in self._extract_items(body) if isinstance(item, dict) and item.get("@id") == negotiation_id),
            None,
        )

    def _wait_for_agreement(self, consumer: str, consumer_jwt: str, negotiation_id: str, runtime: dict[str, Any]):
        deadline = self.time_provider() + int(runtime["negotiation_timeout_seconds"])
        last_state = None
        while self.time_provider() <= deadline:
            negotiation = self._query_negotiation(consumer, consumer_jwt, negotiation_id)
            if negotiation:
                last_state = negotiation.get("state")
                agreement_id = negotiation.get("contractAgreementId") or negotiation.get("agreementId")
                if agreement_id:
                    return {"state": last_state, "agreement_id": agreement_id, "raw": negotiation}
                if str(last_state or "").upper() in {"TERMINATED", "ERROR", "DECLINED"}:
                    raise RuntimeError(
                        "Negotiation reached terminal state"
                        + (f": {negotiation.get('errorDetail')}" if negotiation.get("errorDetail") else "")
                    )
            time.sleep(max(1, int(runtime["poll_interval_seconds"])))
        raise RuntimeError(f"Negotiation {negotiation_id} did not produce contractAgreementId (last_state={last_state})")

    def _list_agreements(self, consumer: str, consumer_jwt: str):
        body, status_code = self._post_json(
            self._management_url(consumer, "/management/v3/contractagreements/request"),
            consumer_jwt,
            {"@context": {"@vocab": EDC_NAMESPACE}, "offset": 0, "limit": 100},
            "AI Model Hub access contract agreements query",
        )
        return self._extract_items(body), status_code

    @staticmethod
    def _agreement_matches(agreement: Any, agreement_id: str, asset_id: str) -> bool:
        if not isinstance(agreement, dict):
            return False
        serialized = json.dumps(agreement)
        return agreement_id in serialized and asset_id in serialized

    def _start_model_access_transfer(
        self,
        provider: str,
        consumer: str,
        consumer_jwt: str,
        asset_id: str,
        agreement_id: str,
        runtime: dict[str, Any],
    ):
        payload = {
            "@context": {"@vocab": EDC_NAMESPACE},
            "@type": "TransferRequestDto",
            "connectorId": provider,
            "counterPartyAddress": self._protocol_address(provider),
            "contractId": agreement_id,
            "assetId": asset_id,
            "protocol": "dataspace-protocol-http",
            "transferType": runtime["access_transfer_type"],
        }
        body, status_code = self._post_json(
            self._management_url(consumer, f"/management/v3/{runtime['access_transfer_path']}"),
            consumer_jwt,
            payload,
            "AI Model Hub authorized model access transfer",
        )
        transfer_id = body.get("@id") or body.get("id")
        if not transfer_id:
            raise RuntimeError("Model access transfer did not return transfer id")
        return transfer_id, status_code

    def _query_transfer(self, consumer: str, consumer_jwt: str, transfer_id: str):
        body, status = self._get_json(
            self._management_url(consumer, f"/management/v3/transferprocesses/{transfer_id}"),
            consumer_jwt,
            "AI Model Hub access transfer lookup",
            accepted_statuses={200, 404},
        )
        if status == 200 and isinstance(body, dict):
            return body
        body, _ = self._post_json(
            self._management_url(consumer, "/management/v3/transferprocesses/request"),
            consumer_jwt,
            {"@context": {"@vocab": EDC_NAMESPACE}, "offset": 0, "limit": 100},
            "AI Model Hub access transfer query",
        )
        return next(
            (item for item in self._extract_items(body) if isinstance(item, dict) and item.get("@id") == transfer_id),
            None,
        )

    def _wait_for_transfer(self, consumer: str, consumer_jwt: str, transfer_id: str, runtime: dict[str, Any]):
        deadline = self.time_provider() + int(runtime["transfer_timeout_seconds"])
        last_state = None
        while self.time_provider() <= deadline:
            transfer = self._query_transfer(consumer, consumer_jwt, transfer_id)
            if transfer:
                last_state = str(transfer.get("state") or "").upper()
                if last_state in SUCCESS_TRANSFER_STATES:
                    return {"state": last_state, "raw": transfer}
                if last_state == "TERMINATED":
                    raise RuntimeError(
                        "Model access transfer reached TERMINATED state"
                        + (f": {transfer.get('errorDetail')}" if transfer.get("errorDetail") else "")
                    )
            time.sleep(max(1, int(runtime["poll_interval_seconds"])))
        raise RuntimeError(f"Transfer {transfer_id} did not reach a successful state (last_state={last_state})")

    def _lookup_edr(self, consumer: str, consumer_jwt: str, transfer_id: str):
        body, status_code = self._get_json(
            self._management_url(consumer, f"/management/v3/edrs/{transfer_id}/dataaddress"),
            consumer_jwt,
            "AI Model Hub access EDR lookup",
            accepted_statuses={200, 404},
        )
        if status_code == 404:
            return {"available": False, "http_status": status_code}
        endpoint = body.get("endpoint") or body.get("edc:endpoint") or body.get("endpointUrl")
        auth = body.get("authorization") or body.get("edc:authorization") or body.get("authCode")
        return {
            "available": bool(endpoint),
            "http_status": status_code,
            "endpoint_present": bool(endpoint),
            "authorization_present": bool(auth),
            "payload_keys": sorted(body.keys()) if isinstance(body, dict) else [],
        }

    def _case_result(
        self,
        case_id: str,
        *,
        status: str,
        assertions: list[str],
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = CASE_METADATA[case_id]
        return {
            "test_case_id": case_id,
            "description": metadata["description"],
            "type": metadata["type"],
            "case_group": "pt5",
            "validation_type": metadata["validation_type"],
            "dataspace_dimension": metadata["dataspace_dimension"],
            "mapping_status": "phase_3",
            "automation_mode": "api_opt_in",
            "execution_mode": "api_opt_in",
            "coverage_status": "automated_opt_in",
            "request": request_payload,
            "response": response_payload,
            "evaluation": {"status": status, "assertions": assertions},
            "expected_result": metadata["expected_result"],
            "traceability": list(metadata["traceability"]),
        }

    @staticmethod
    def _summary(cases: list[dict[str, Any]], steps: list[dict[str, Any]]) -> dict[str, Any]:
        case_summary = {"total": len(cases), "passed": 0, "failed": 0, "skipped": 0}
        for case in cases:
            status = ((case.get("evaluation") or {}).get("status") or "").lower()
            if status in case_summary:
                case_summary[status] += 1
        return {
            **case_summary,
            "steps": {
                "total": len(steps),
                "passed": sum(1 for step in steps if step.get("status") == "passed"),
                "failed": sum(1 for step in steps if step.get("status") == "failed"),
                "skipped": sum(1 for step in steps if step.get("status") == "skipped"),
            },
        }

    @staticmethod
    def _step_passed(steps: list[dict[str, Any]], name: str) -> bool:
        return any(step.get("name") == name and step.get("status") == "passed" for step in steps)

    @staticmethod
    def _case_assertions(steps: list[dict[str, Any]], required_steps: list[str], error_payload: dict[str, Any] | None):
        missing = [name for name in required_steps if not AIModelHubConnectorGovernanceApiSuite._step_passed(steps, name)]
        assertions = [f"Required step did not pass: {name}" for name in missing]
        if assertions and error_payload:
            assertions.append(error_payload["message"])
        return assertions

    def _build_executed_cases(
        self,
        *,
        provider: str,
        consumer: str,
        steps: list[dict[str, Any]],
        created_entities: dict[str, Any],
        runtime: dict[str, Any],
        traceability_record_path: str | None,
        error_payload: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        common_request = {
            "provider": provider,
            "consumer": consumer,
            "runner": "validation/components/ai_model_hub/connector_governance_api.py",
            "secret_policy": "Authorization headers and OIDC tokens are not persisted",
        }
        common_response = {
            "created_entities": {key: value for key, value in created_entities.items() if value},
            "passed_steps": [step.get("name") for step in steps if step.get("status") == "passed"],
            "failed_steps": [step.get("name") for step in steps if step.get("status") == "failed"],
        }
        case_requests = {
            "PT5-MH-09": {
                **common_request,
                "api_paths": [f"/management/v3/{runtime['access_transfer_path']}", "/management/v3/transferprocesses/{id}"],
            },
            "PT5-MH-11": {
                **common_request,
                "api_paths": ["/management/v3/contractagreements/request"],
            },
            "PT5-MH-16": {
                **common_request,
                "api_paths": ["/realms/{dataspace}/protocol/openid-connect/token"],
            },
            "PT5-MH-17": {
                **common_request,
                "traceability_record": traceability_record_path,
            },
            "PT5-MH-18": {
                **common_request,
                "api_paths": [
                    "/management/v3/assets",
                    "/management/v3/policydefinitions",
                    "/management/v3/contractdefinitions",
                    "/management/v3/catalog/request",
                    "/management/v3/contractnegotiations",
                ],
            },
        }
        case_responses = {
            "PT5-MH-09": {
                **common_response,
                "transfer_id": created_entities.get("transfer_id"),
                "transfer_state": created_entities.get("transfer_state"),
                "edr": created_entities.get("edr_summary"),
            },
            "PT5-MH-11": {
                **common_response,
                "agreement_id": created_entities.get("agreement_id"),
                "agreements_listed": created_entities.get("agreements_listed"),
            },
            "PT5-MH-16": {
                **common_response,
                "provider_oidc_authenticated": self._step_passed(steps, "provider_oidc_login"),
                "consumer_oidc_authenticated": self._step_passed(steps, "consumer_oidc_login"),
            },
            "PT5-MH-17": {
                **common_response,
                "traceability_record": traceability_record_path,
                "operation_count": len(steps),
            },
            "PT5-MH-18": {
                **common_response,
                "connector_api_operations": [
                    "create_asset",
                    "create_policy",
                    "create_contract_definition",
                    "request_catalog",
                    "start_negotiation",
                ],
            },
        }
        executed_cases = []
        for case_id in CASE_IDS:
            required_steps = list(CASE_METADATA[case_id]["required_steps"])
            assertions = self._case_assertions(steps, required_steps, error_payload)
            executed_cases.append(
                self._case_result(
                    case_id,
                    status="failed" if assertions else "passed",
                    assertions=assertions,
                    request_payload=case_requests[case_id],
                    response_payload=case_responses[case_id],
                )
            )
        return executed_cases

    def run(
        self,
        *,
        provider: str,
        consumer: str,
        model_url: str,
        model_path: str = DEFAULT_MODEL_PATH,
        experiment_dir: str | None = None,
        run_access_transfer: bool = True,
    ) -> dict[str, Any]:
        started_at = datetime.now().isoformat()
        runtime = self._runtime()
        component_dir = self._component_dir(experiment_dir)
        suffix = self._safe_suffix(self.uuid_factory())
        steps: list[dict[str, Any]] = []
        artifacts: dict[str, str] = {}
        created_entities: dict[str, Any] = {}
        provider_jwt = None
        traceability_record_path = None

        def step(name: str, status: str = "passed", **payload: Any) -> None:
            steps.append({"name": name, "status": status, **payload})

        try:
            provider_jwt = self._login(provider, "provider", runtime)
            step("provider_oidc_login", connector=provider)
            consumer_jwt = self._login(consumer, "consumer", runtime)
            step("consumer_oidc_login", connector=consumer)

            asset_id, created_asset_id, asset_status, asset_payload = self._create_model_asset(
                provider,
                provider_jwt,
                model_url,
                model_path,
                suffix,
            )
            created_entities["asset_id"] = created_asset_id
            step("create_httpdata_model_asset", http_status=asset_status, asset_id=created_asset_id)

            policy_id, created_policy_id, policy_status = self._create_policy(provider, provider_jwt, suffix)
            created_entities["policy_id"] = created_policy_id
            step("create_policy", http_status=policy_status, policy_id=created_policy_id)

            contract_id, created_contract_id, contract_status = self._create_contract_definition(
                provider,
                provider_jwt,
                asset_id,
                policy_id,
                suffix,
            )
            created_entities["contract_definition_id"] = created_contract_id
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
            created_entities["negotiation_id"] = negotiation_id
            step("start_negotiation", http_status=negotiation_status, negotiation_id=negotiation_id)

            agreement = self._wait_for_agreement(consumer, consumer_jwt, negotiation_id, runtime)
            created_entities["agreement_id"] = agreement["agreement_id"]
            step("wait_for_contract_agreement", state=agreement["state"], agreement_id=agreement["agreement_id"])

            agreements, agreements_status = self._list_agreements(consumer, consumer_jwt)
            matching_agreement = next(
                (
                    item
                    for item in agreements
                    if self._agreement_matches(item, agreement["agreement_id"], asset_id)
                    or agreement["agreement_id"] in json.dumps(item)
                ),
                None,
            )
            if matching_agreement is None:
                raise RuntimeError(f"Agreement {agreement['agreement_id']} was not found in contractagreements/request")
            created_entities["agreements_listed"] = len(agreements)
            step("list_active_agreements", http_status=agreements_status, agreements_listed=len(agreements))

            if run_access_transfer:
                transfer_id, transfer_status = self._start_model_access_transfer(
                    provider,
                    consumer,
                    consumer_jwt,
                    asset_id,
                    agreement["agreement_id"],
                    runtime,
                )
                created_entities["transfer_id"] = transfer_id
                step("start_model_access_transfer", http_status=transfer_status, transfer_id=transfer_id)
                transfer = self._wait_for_transfer(consumer, consumer_jwt, transfer_id, runtime)
                created_entities["transfer_state"] = transfer["state"]
                step("wait_for_model_access_transfer", state=transfer["state"])
                edr_summary = self._lookup_edr(consumer, consumer_jwt, transfer_id)
                created_entities["edr_summary"] = edr_summary
                step("lookup_model_access_edr", **edr_summary)
            else:
                step("start_model_access_transfer", status="skipped", reason="run_access_transfer_disabled")
                step("wait_for_model_access_transfer", status="skipped", reason="run_access_transfer_disabled")

            error_payload = None
        except Exception as exc:
            error_payload = {"type": type(exc).__name__, "message": str(exc)}
            step("suite_error", status="failed", **error_payload)
            asset_payload = locals().get("asset_payload")

        traceability_record = {
            "component": COMPONENT_KEY,
            "suite": SUITE_NAME,
            "timestamp": started_at,
            "provider": provider,
            "consumer": consumer,
            "created_entities": {key: value for key, value in created_entities.items() if key != "edr_summary"},
            "steps": steps,
            "secret_policy": "No OIDC tokens, Bearer headers or connector passwords are stored in this record.",
        }
        if component_dir:
            traceability_record_path = os.path.join(component_dir, "pt5-mh-17-traceability-record.json")
            self._write_json(traceability_record_path, traceability_record)
            artifacts["pt5-mh-17-traceability-record.json"] = traceability_record_path
            step("write_traceability_record", path=traceability_record_path)
        else:
            step("write_traceability_record")

        executed_cases = self._build_executed_cases(
            provider=provider,
            consumer=consumer,
            steps=steps,
            created_entities=created_entities,
            runtime=runtime,
            traceability_record_path=traceability_record_path,
            error_payload=error_payload,
        )

        cleanup_steps = []
        if provider_jwt:
            cleanup_targets = [
                ("contract_definition_id", "/management/v3/contractdefinitions/{id}", "cleanup_contract_definition"),
                ("policy_id", "/management/v3/policydefinitions/{id}", "cleanup_policy"),
            ]
            if created_entities.get("agreement_id") and created_entities.get("asset_id"):
                cleanup_steps.append(
                    {
                        "name": "cleanup_asset",
                        "status": "skipped",
                        "entity_id": created_entities.get("asset_id"),
                        "reason": "asset retained because it is referenced by an active contract agreement",
                    }
                )
            else:
                cleanup_targets.append(("asset_id", "/management/v3/assets/{id}", "cleanup_asset"))

            for entity_key, path_template, label in cleanup_targets:
                entity_id = created_entities.get(entity_key)
                if not entity_id:
                    continue
                try:
                    cleanup_status, cleanup_body = self._delete_optional(
                        self._management_url(provider, path_template.format(id=entity_id)),
                        provider_jwt,
                        label,
                    )
                    cleanup_steps.append(
                        {
                            "name": label,
                            "status": "passed" if cleanup_status in {200, 204, 404} else "warning",
                            "http_status": cleanup_status,
                            "entity_id": entity_id,
                            "body": cleanup_body,
                        }
                    )
                except Exception as exc:
                    cleanup_steps.append(
                        {
                            "name": label,
                            "status": "warning",
                            "entity_id": entity_id,
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )

        all_steps = steps + cleanup_steps
        summary = self._summary(executed_cases, all_steps)
        result = {
            "component": COMPONENT_KEY,
            "suite": SUITE_NAME,
            "status": "failed" if summary["failed"] else "passed",
            "summary": summary,
            "timestamp": started_at,
            "provider": provider,
            "consumer": consumer,
            "model_url": model_url,
            "model_path": model_path,
            "run_access_transfer": run_access_transfer,
            "runtime": {
                "dataspace": runtime.get("dataspace"),
                "ds_domain": runtime.get("ds_domain"),
                "adapter": runtime.get("adapter"),
                "access_transfer_path": runtime.get("access_transfer_path"),
                "access_transfer_type": runtime.get("access_transfer_type"),
            },
            "created_entities": created_entities,
            "steps": all_steps,
            "executed_cases": executed_cases,
            "asset_payload": asset_payload if isinstance(locals().get("asset_payload"), dict) else None,
            "error": error_payload,
            "artifacts": artifacts,
            "evidence_index": [],
        }

        if component_dir:
            report_path = os.path.join(component_dir, "ai_model_hub_connector_governance_api.json")
            artifacts["report_json"] = report_path
            result["artifacts"] = artifacts
            result["evidence_index"] = [
                {
                    "scope": "suite",
                    "suite": SUITE_NAME,
                    "artifact_name": "report_json",
                    "path": report_path,
                },
                {
                    "scope": "case",
                    "suite": SUITE_NAME,
                    "test_case_id": "PT5-MH-17",
                    "artifact_name": "pt5-mh-17-traceability-record.json",
                    "path": traceability_record_path,
                },
            ]
            for case in executed_cases:
                case_path = os.path.join(component_dir, f"{case['test_case_id'].lower()}-connector-governance.json")
                self._write_json(case_path, case)
                artifacts[f"{case['test_case_id'].lower()}-connector-governance.json"] = case_path
                result["evidence_index"].append(
                    {
                        "scope": "case",
                        "suite": SUITE_NAME,
                        "test_case_id": case["test_case_id"],
                        "artifact_name": f"{case['test_case_id'].lower()}-connector-governance.json",
                        "path": case_path,
                    }
                )
            self._write_json(report_path, result)

        return result


def _dataspace_name_loader(adapter):
    config = getattr(adapter, "config", None)
    getter = getattr(config, "dataspace_name", None)
    if callable(getter):
        return getter
    return lambda: "demo"


def build_inesdata_ai_model_hub_connector_governance_suite(topology: str = "local"):
    from adapters.inesdata.adapter import InesdataAdapter

    adapter = InesdataAdapter(topology=topology)
    return AIModelHubConnectorGovernanceApiSuite(
        load_connector_credentials=adapter.load_connector_credentials,
        load_deployer_config=adapter.load_deployer_config,
        ds_domain_resolver=adapter.config.ds_domain_base,
        ds_name_loader=_dataspace_name_loader(adapter),
        protocol_address_resolver=getattr(adapter.connectors, "build_internal_protocol_address", None),
    ), adapter


def _default_experiment_dir() -> str:
    return os.path.join("experiments", f"ai-model-hub-connector-governance-api-{datetime.now().strftime('%Y%m%d-%H%M%S')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run AI Model Hub connector governance API validation for PT5-MH-09/11/16/17/18."
    )
    parser.add_argument("--topology", default="local", choices=["local", "vm-single"])
    parser.add_argument("--provider", default="")
    parser.add_argument("--consumer", default="")
    parser.add_argument("--model-url", default="")
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--skip-access-transfer", action="store_true")
    parser.add_argument("--experiment-dir", default="")
    args = parser.parse_args(argv)

    suite, adapter = build_inesdata_ai_model_hub_connector_governance_suite(topology=args.topology)
    connectors = list(adapter.get_cluster_connectors() or []) if not (args.provider and args.consumer) else []
    provider = args.provider or (connectors[0] if connectors else "")
    consumer = args.consumer or (connectors[1] if len(connectors) > 1 else "")
    if not provider or not consumer:
        raise RuntimeError("Provider and consumer connectors must be provided or discoverable from the cluster")

    result = suite.run(
        provider=provider,
        consumer=consumer,
        model_url=args.model_url or default_model_url(adapter, args.model_path),
        model_path=args.model_path,
        run_access_transfer=not args.skip_access_transfer,
        experiment_dir=args.experiment_dir or _default_experiment_dir(),
    )
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "summary": result.get("summary"),
                "artifact": (result.get("artifacts") or {}).get("report_json"),
            },
            indent=2,
        )
    )
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
