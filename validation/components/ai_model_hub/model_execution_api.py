from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import requests

from validation.components.ai_model_hub.model_server_policy import (
    model_server_execution_labels,
    model_server_validation_state,
)
from validation.components.ai_model_hub.daimo_metadata import model_asset_data
from validation.datasets.manager import dataset_source_dir


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "model-execution-api"
TEST_CASE_ID = "PT5-MH-10"
FUNCTIONAL_CASE_ID = "MH-LING-01"
EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/"
DAIMO_NAMESPACE = "https://w3id.org/daimo/0.0.1/ns#"
LEGACY_DAIMO_NAMESPACE = "https://pionera.ai/edc/daimo#"
DEFAULT_MODEL_PATH = "/api/v1/nlp/ecommerce-sentiment"
DEFAULT_PAYLOAD = {"text": "This product is excellent and very useful"}
DEFAULT_EXPECTED_MODEL = "E-commerce Sentiment Analyzer"
FLARES_MODEL_PATH = "/flares/dccuchile-distilbert-base-spanish-uncased-reliability"
FLARES_EXPECTED_MODEL = ""
FLARES_DATASET_DIR = str(dataset_source_dir("flares-dataset"))
FLARES_TRIAL_FILE = "5w1h_subtask_2_trial.json"
FLARES_TEST_FILE = "5w1h_subtarea_2_test.json"
FLARES_DATASET_NAME = "FLARES"


def _env_first(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _connector_matches(connector: str, *env_names: str) -> bool:
    normalized = str(connector or "").strip()
    return bool(normalized) and any(str(os.environ.get(name) or "").strip() == normalized for name in env_names)


def _join_management_url(base_url: str, path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    suffix = str(path or "").strip()
    if not base:
        return ""
    if base.endswith("/management/v3") and suffix.startswith("/management/v3/"):
        suffix = suffix[len("/management/v3") :]
    elif base.endswith("/management") and suffix.startswith("/management/"):
        suffix = suffix[len("/management"):]
    if not suffix.startswith("/"):
        suffix = f"/{suffix}"
    return f"{base}{suffix}"


def _join_default_api_url(base_url: str, path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    suffix = str(path or "").strip()
    if not base:
        return ""
    if not suffix:
        return base
    if not suffix.startswith("/"):
        suffix = f"/{suffix}"
    if base.endswith("/api") and suffix == "/api":
        suffix = ""
    elif base.endswith("/api") and suffix.startswith("/api/"):
        suffix = suffix[len("/api"):]
    return f"{base}{suffix.rstrip('/')}"


class AIModelHubModelExecutionApiSuite:
    """Exercise the connector-side model execution API with a temporary HttpData asset."""

    DEFAULT_REQUEST_ATTEMPTS = 3
    DEFAULT_REQUEST_RETRY_SECONDS = 2

    def __init__(
        self,
        *,
        load_connector_credentials: Callable[[str], dict[str, Any] | None],
        load_deployer_config: Callable[[], dict[str, Any] | None],
        ds_domain_resolver: Callable[[], str],
        ds_name_loader: Callable[[], str] | None = None,
        management_url_resolver: Callable[[str, str], str] | None = None,
        default_api_url_resolver: Callable[[str, str], str] | None = None,
        keycloak_url_resolver: Callable[[], str] | None = None,
        adapter_name: str | None = None,
        session: requests.Session | None = None,
        uuid_factory: Callable[[], str] | None = None,
    ):
        self.load_connector_credentials = load_connector_credentials
        self.load_deployer_config = load_deployer_config
        self.ds_domain_resolver = ds_domain_resolver
        self.ds_name_loader = ds_name_loader or (lambda: "demo")
        self.management_url_resolver = management_url_resolver
        self.default_api_url_resolver = default_api_url_resolver
        self.keycloak_url_resolver = keycloak_url_resolver
        self.adapter_name = str(adapter_name or "").strip().lower()
        self.session = session or requests.Session()
        self.uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))

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

    def _runtime(self) -> dict[str, Any]:
        config = dict(self.load_deployer_config() or {})
        runtime = {
            "dataspace": str(self.ds_name_loader() or "demo").strip() or "demo",
            "ds_domain": str(self.ds_domain_resolver() or "").strip(),
            "keycloak_url": "",
            "adapter": str(
                self.adapter_name
                or os.environ.get("AI_MODEL_HUB_COMPONENT_ADAPTER")
                or os.environ.get("PIONERA_ADAPTER")
                or config.get("PIONERA_ADAPTER")
                or config.get("ADAPTER_NAME")
                or "inesdata"
            ).strip().lower(),
            "topology": str(
                _env_first(
                    "AI_MODEL_HUB_MODEL_EXECUTION_TOPOLOGY",
                    "PIONERA_TOPOLOGY",
                    "INESDATA_TOPOLOGY",
                    "TOPOLOGY",
                )
                or config.get("TOPOLOGY")
                or "local"
            ).strip().lower(),
            "inference_api_path": str(config.get("AI_MODEL_HUB_INFERENCE_API_PATH") or "/api/infer"),
        }
        runtime["model_server"] = model_server_validation_state(config, topology=runtime["topology"])
        runtime["inference_api_path"] = (
            _env_first("AI_MODEL_HUB_INFERENCE_API_PATH", "AI_MODEL_HUB_EDC_INFERENCE_API_PATH")
            or runtime["inference_api_path"]
        )
        if callable(self.keycloak_url_resolver):
            runtime["keycloak_url"] = str(self.keycloak_url_resolver() or "").strip()
        if not runtime["keycloak_url"]:
            runtime["keycloak_url"] = _env_first(
                "AI_MODEL_HUB_KEYCLOAK_URL",
                "KEYCLOAK_FRONTEND_URL",
                "KEYCLOAK_PUBLIC_URL",
                "UI_KEYCLOAK_URL",
            )
        if not runtime["keycloak_url"]:
            runtime["keycloak_url"] = str(
                config.get("KEYCLOAK_FRONTEND_URL")
                or config.get("KEYCLOAK_PUBLIC_URL")
                or config.get("KC_INTERNAL_URL")
                or config.get("KC_URL")
                or ""
            ).strip()
        if runtime["keycloak_url"] and not runtime["keycloak_url"].startswith("http"):
            runtime["keycloak_url"] = f"http://{runtime['keycloak_url']}"
        if not runtime["ds_domain"]:
            raise RuntimeError("DS_DOMAIN_BASE could not be resolved")
        if not runtime["keycloak_url"]:
            raise RuntimeError("KC_INTERNAL_URL/KC_URL could not be resolved")
        return runtime

    def _management_url(self, connector: str, path: str) -> str:
        if _connector_matches(
            connector,
            "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID",
            "AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER",
            "AI_MODEL_HUB_CONNECTOR_GOVERNANCE_PROVIDER",
        ):
            resolved = _join_management_url(_env_first("AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL"), path)
            if resolved:
                return resolved
        if _connector_matches(
            connector,
            "AI_MODEL_HUB_CONSUMER_CONNECTOR_ID",
            "AI_MODEL_HUB_CONNECTOR_GOVERNANCE_CONSUMER",
        ):
            resolved = _join_management_url(_env_first("AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL"), path)
            if resolved:
                return resolved
        if callable(self.management_url_resolver):
            resolved = str(self.management_url_resolver(connector, path) or "").strip()
            if resolved:
                return resolved
        return f"http://{connector}.{self.ds_domain_resolver()}{path}"

    def _default_api_url(self, connector: str, path: str) -> str:
        if _connector_matches(
            connector,
            "AI_MODEL_HUB_PROVIDER_CONNECTOR_ID",
            "AI_MODEL_HUB_MODEL_EXECUTION_PROVIDER",
            "AI_MODEL_HUB_CONNECTOR_GOVERNANCE_PROVIDER",
        ):
            resolved = _join_default_api_url(_env_first("AI_MODEL_HUB_PROVIDER_DEFAULT_URL"), path)
            if resolved:
                return resolved
            management_url = _env_first("AI_MODEL_HUB_PROVIDER_MANAGEMENT_URL")
            if management_url:
                return _join_default_api_url(management_url.rstrip("/").removesuffix("/management") + "/api", path)
        if _connector_matches(
            connector,
            "AI_MODEL_HUB_CONSUMER_CONNECTOR_ID",
            "AI_MODEL_HUB_CONNECTOR_GOVERNANCE_CONSUMER",
        ):
            resolved = _join_default_api_url(_env_first("AI_MODEL_HUB_CONSUMER_DEFAULT_URL"), path)
            if resolved:
                return resolved
            management_url = _env_first("AI_MODEL_HUB_CONSUMER_MANAGEMENT_URL")
            if management_url:
                return _join_default_api_url(management_url.rstrip("/").removesuffix("/management") + "/api", path)
        if callable(self.default_api_url_resolver):
            resolved = str(self.default_api_url_resolver(connector, path) or "").strip()
            if resolved:
                return resolved
        return _join_default_api_url(f"http://{connector}.{self.ds_domain_resolver()}/api", path)

    def _execution_url(self, provider: str, runtime: dict[str, Any]) -> str:
        if runtime.get("adapter") == "edc":
            return self._default_api_url(provider, str(runtime.get("inference_api_path") or "/api/infer"))
        return self._management_url(provider, "/management/v3/modelexecutions/execute")

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
    def _response_json_or_text(response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw_body": response.text[:1000]}

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

    def _post_json(self, url: str, token: str, payload: dict[str, Any], label: str):
        response = self._request_with_retry(
            "post",
            url,
            label=label,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        return response.status_code, self._response_json_or_text(response)

    def _delete(self, url: str, token: str, label: str):
        response = self._request_with_retry(
            "delete",
            url,
            label=label,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 204:
            return response.status_code, None
        return response.status_code, self._response_json_or_text(response)

    def _create_asset(
        self,
        provider: str,
        provider_jwt: str,
        model_url: str,
        suffix: str,
        runtime: dict[str, Any],
    ):
        asset_id = f"a52-model-exec-{suffix}"
        keywords = ["validation", "ai-model-hub", "model-execution", "A5.2"]
        data_address = {
            "type": "HttpData",
            "baseUrl": model_url,
            "method": "POST",
            "name": f"ai-model-hub-model-execution-{suffix}",
        }
        if runtime.get("adapter") == "edc":
            data_address["proxyPath"] = "true"
        payload = {
            "@context": {
                "@vocab": EDC_NAMESPACE,
                "edc": EDC_NAMESPACE,
                "dct": "http://purl.org/dc/terms/",
                "dcat": "http://www.w3.org/ns/dcat#",
                "daimo": DAIMO_NAMESPACE,
            },
            "@id": asset_id,
            "@type": "Asset",
            "properties": {
                "name": f"AI Model Hub executable model {suffix}",
                "version": "1.0.0",
                "shortDescription": "Temporary model endpoint for the A5.2 controlled execution baseline",
                "assetType": "machineLearning",
                "assetData": model_asset_data(
                    task="text-classification",
                    subtask="text-classification",
                    subtask_description="Controlled sentiment-analysis execution endpoint",
                    description="HttpData endpoint consumed through the connector-side model execution API",
                    library_name="Custom",
                    language=["English", "Spanish"],
                    input_features=[
                        {
                            "name": "text",
                            "type": "string",
                            "description": "Text to analyze",
                        }
                    ],
                    input_schema={
                        "type": "object",
                        "required": ["text"],
                        "properties": {"text": {"type": "string", "description": "Text to analyze"}},
                    },
                    input_example=DEFAULT_PAYLOAD,
                ),
                "asset:prop:type": "machineLearning",
                "storageType": "HttpData",
                "edc:dataAddressType": "HttpData",
                f"{EDC_NAMESPACE}dataAddressType": "HttpData",
                "dct:description": "HttpData endpoint consumed through the connector-side model execution API",
                "dcat:keyword": keywords,
                "daimo:asset_kind": "model",
                f"{DAIMO_NAMESPACE}asset_kind": "model",
                f"{LEGACY_DAIMO_NAMESPACE}asset_kind": "model",
                "daimo:task": "text-classification",
                f"{DAIMO_NAMESPACE}task": "text-classification",
                f"{LEGACY_DAIMO_NAMESPACE}task": "text-classification",
                "daimo:subtask": "sentiment-analysis",
                f"{DAIMO_NAMESPACE}subtask": "sentiment-analysis",
                f"{LEGACY_DAIMO_NAMESPACE}subtask": "sentiment-analysis",
                "daimo:algorithm": "deterministic-rule-engine",
                f"{DAIMO_NAMESPACE}algorithm": "deterministic-rule-engine",
                f"{LEGACY_DAIMO_NAMESPACE}algorithm": "deterministic-rule-engine",
                "daimo:library": "flask",
                "daimo:library_name": "flask",
                f"{DAIMO_NAMESPACE}library": "flask",
                f"{LEGACY_DAIMO_NAMESPACE}library": "flask",
                f"{LEGACY_DAIMO_NAMESPACE}library_name": "flask",
                "daimo:framework": "model-server",
                f"{DAIMO_NAMESPACE}framework": "model-server",
                f"{LEGACY_DAIMO_NAMESPACE}framework": "model-server",
                "daimo:software": "pionera-validation-framework",
                f"{DAIMO_NAMESPACE}software": "pionera-validation-framework",
                f"{LEGACY_DAIMO_NAMESPACE}software": "pionera-validation-framework",
                "daimo:inference_path": DEFAULT_MODEL_PATH,
                f"{DAIMO_NAMESPACE}inference_path": DEFAULT_MODEL_PATH,
                f"{LEGACY_DAIMO_NAMESPACE}inference_path": DEFAULT_MODEL_PATH,
                "daimo:tags": keywords,
                f"{LEGACY_DAIMO_NAMESPACE}tags": keywords,
                "task": "text-classification",
                "subtask": "sentiment-analysis",
                "algorithm": "deterministic-rule-engine",
                "library": "flask",
                "framework": "model-server",
                "software": "pionera-validation-framework",
                "contenttype": "application/json",
                "inputFeatures": [
                    {
                        "name": "text",
                        "type": "string",
                        "required": True,
                        "description": "Text to analyze",
                    }
                ],
                "inputExample": DEFAULT_PAYLOAD,
                "format": "json",
            },
            "dataAddress": data_address,
        }
        status_code, body = self._post_json(
            self._management_url(provider, "/management/v3/assets"),
            provider_jwt,
            payload,
            "AI Model Hub model execution asset creation",
        )
        if status_code not in {200, 201}:
            raise RuntimeError(f"Asset creation failed with HTTP {status_code}: {str(body)[:500]}")
        return asset_id, body.get("@id") or body.get("id") or asset_id, status_code, payload

    def _execute_model(
        self,
        provider: str,
        provider_jwt: str,
        asset_id: str,
        payload: Any,
        runtime: dict[str, Any],
    ) -> tuple[int, Any, str]:
        if runtime.get("adapter") == "edc":
            url = self._execution_url(provider, runtime)
            request_payload = {
                "assetId": asset_id,
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "payload": payload,
            }
        else:
            url = self._management_url(provider, "/management/v3/modelexecutions/execute")
            request_payload = {
                "assetId": asset_id,
                "payload": payload,
            }
        status_code, body = self._post_json(
            url,
            provider_jwt,
            request_payload,
            "AI Model Hub model execution",
        )
        return status_code, body, url

    def _delete_asset(self, provider: str, provider_jwt: str, asset_id: str):
        return self._delete(
            self._management_url(provider, f"/management/v3/assets/{asset_id}"),
            provider_jwt,
            "AI Model Hub model execution asset cleanup",
        )

    @staticmethod
    def evaluate_execution_response(
        status_code: int,
        body: Any,
        *,
        expected_model: str | None = DEFAULT_EXPECTED_MODEL,
    ) -> dict[str, Any]:
        assertions: list[str] = []
        if status_code < 200 or status_code >= 300:
            assertions.append(f"Expected HTTP 2xx, got HTTP {status_code}")
        if not isinstance(body, (dict, list)):
            assertions.append("Model execution response must be a JSON object or array")
        elif expected_model and isinstance(body, dict) and body.get("model") != expected_model:
            assertions.append(f"Expected model '{expected_model}', got '{body.get('model')}'")

        return {
            "status": "failed" if assertions else "passed",
            "assertions": assertions,
            "http_status": status_code,
            "response_keys": sorted(body.keys()) if isinstance(body, dict) else (["<array>"] if isinstance(body, list) else []),
        }

    @staticmethod
    def evaluate_flares_semantic_response(body: Any, functional_context: dict[str, Any]) -> dict[str, Any]:
        expected_output = dict(functional_context.get("expected_output") or {})
        expected_label = str(expected_output.get("expectedReliability") or "").strip()
        actual_label = ""
        if isinstance(body, list) and body:
            first_prediction = body[0]
            if isinstance(first_prediction, dict):
                actual_label = str(first_prediction.get("Reliability_Label") or "").strip()
        elif isinstance(body, dict):
            result = body.get("result")
            actual_label = str((result or {}).get("label") or "").strip() if isinstance(result, dict) else ""
        if not actual_label:
            return {
                "coverage_status": "partial_api_execution",
                "comparison_scope": "transport_and_dataset_alignment",
                "semantic_comparison_status": "pending_flares_model_endpoint",
                "assertions": [],
                "expected_label": expected_label,
                "actual_label": None,
            }
        assertions = []
        if actual_label != expected_label:
            assertions.append(f"Expected FLARES reliability label '{expected_label}', got '{actual_label}'")
        return {
            "coverage_status": "automated",
            "comparison_scope": "transport_dataset_and_semantic_label",
            "semantic_comparison_status": "failed" if assertions else "passed",
            "assertions": assertions,
            "expected_label": expected_label,
            "actual_label": actual_label,
        }

    @staticmethod
    def _case_result(
        *,
        status: str,
        assertions: list[str],
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        execution_mode: str = "api",
        coverage_status: str = "automated",
        model_server_mode: str = "",
    ) -> dict[str, Any]:
        return {
            "test_case_id": TEST_CASE_ID,
            "description": "Execute inference through the connector-side model execution API with a controlled baseline",
            "type": "api",
            "case_group": "pt5",
            "validation_type": "integration",
            "dataspace_dimension": "execution",
            "mapping_status": "mapped",
            "automation_mode": "api",
            "execution_mode": execution_mode,
            "coverage_status": coverage_status,
            "model_server_mode": model_server_mode,
            "request": request_payload,
            "response": response_payload,
            "evaluation": {
                "status": status,
                "assertions": assertions,
            },
            "expected_result": (
                "The model execution API resolves the controlled HttpData asset and returns "
                "a deterministic model response"
            ),
            "traceability": ["MH-34", "MH-35"],
        }

    @staticmethod
    def _functional_case_result(
        *,
        status: str,
        assertions: list[str],
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        functional_context: dict[str, Any],
        semantic_evaluation: dict[str, Any] | None = None,
        model_server_mode: str = "",
    ) -> dict[str, Any]:
        expected_output = dict(functional_context.get("expected_output") or {})
        semantic_evaluation = semantic_evaluation or {
            "coverage_status": "partial_api_execution",
            "comparison_scope": "transport_and_dataset_alignment",
            "semantic_comparison_status": "pending_flares_model_endpoint",
            "expected_label": expected_output.get("expectedReliability"),
            "actual_label": None,
        }
        pending_semantic_comparison = (
            semantic_evaluation.get("semantic_comparison_status") == "pending_flares_model_endpoint"
        )
        coverage_status = semantic_evaluation.get("coverage_status") or "partial_api_execution"
        if model_server_mode == "mock" and coverage_status == "automated":
            coverage_status = "automated_mock_model_server"
        return {
            "test_case_id": FUNCTIONAL_CASE_ID,
            "description": "Execute a FLARES linguistic record through the connector-side model execution API",
            "type": "api",
            "case_group": "functional",
            "validation_type": "functional",
            "dataspace_dimension": "linguistic",
            "mapping_status": "phase_3",
            "automation_mode": "api",
            "execution_mode": "api",
            "coverage_status": coverage_status,
            "model_server_mode": model_server_mode,
            "request": request_payload,
            "response": response_payload,
            "evaluation": {
                "status": status,
                "assertions": assertions,
                "comparison_scope": semantic_evaluation.get("comparison_scope"),
                "semantic_comparison_status": semantic_evaluation.get("semantic_comparison_status"),
                "expected_label": semantic_evaluation.get("expected_label"),
                "actual_label": semantic_evaluation.get("actual_label"),
            },
            "expected_result": (
                "A FLARES source record is executable through the connector API and linked to "
                "dataset-derived expected labels for the reliability assertion"
            ),
            "traceability": [FUNCTIONAL_CASE_ID],
            "fixture": {
                "dataset": functional_context.get("dataset_name"),
                "domain": functional_context.get("domain"),
                "record_id": functional_context.get("record_id"),
                "w1h_label": functional_context.get("w1h_label"),
                "expected_reliability": expected_output.get("expectedReliability"),
                "expected_outputs_source": functional_context.get("expected_outputs_source"),
            },
            **(
                {
                    "limitation": (
                        "The current model endpoint confirms connector-side execution with a FLARES payload, "
                        "but it does not emit the FLARES reliability label required for the semantic comparison."
                    )
                }
                if pending_semantic_comparison
                else {
                    "baseline_note": (
                        "The FLARES reliability label is validated through the real AIModelHub-Use-Cases "
                        "model-server endpoint. Model quality is reported as observed validation evidence."
                    )
                }
            ),
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

    def run(
        self,
        *,
        provider: str,
        model_url: str,
        payload: Any | None = None,
        expected_model: str | None = DEFAULT_EXPECTED_MODEL,
        functional_context: dict[str, Any] | None = None,
        experiment_dir: str | None = None,
        model_server_mode: str | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now().isoformat()
        runtime = self._runtime()
        resolved_model_server_mode = str(model_server_mode or (runtime.get("model_server") or {}).get("mode") or "")
        if model_url and resolved_model_server_mode in {"", "disabled"}:
            resolved_model_server_mode = "external"
        execution_mode, coverage_status = model_server_execution_labels(resolved_model_server_mode)
        model_server_metadata = dict(runtime.get("model_server") or {})
        if model_url and not model_server_metadata.get("enabled"):
            model_server_metadata["enabled"] = True
            model_server_metadata["has_explicit_url"] = True
            model_server_metadata["skip_reason"] = ""
        model_server_metadata.update(
            {
                "mode": resolved_model_server_mode,
                "execution_mode": execution_mode,
                "coverage_status": coverage_status,
            }
        )
        component_dir = self._component_dir(experiment_dir)
        suffix = self._safe_suffix(self.uuid_factory())
        if payload is None:
            inference_payload: Any = dict(DEFAULT_PAYLOAD)
        elif isinstance(payload, dict):
            inference_payload = dict(payload)
        else:
            inference_payload = payload
        steps: list[dict[str, Any]] = []
        artifacts: dict[str, str] = {}
        executed_cases: list[dict[str, Any]] = []
        asset_payload = None
        asset_id = None
        provider_jwt = None

        def step(name: str, status: str = "passed", **fields: Any) -> None:
            steps.append({"name": name, "status": status, **fields})

        try:
            provider_jwt = self._login(provider, "provider", runtime)
            step("provider_login", connector=provider)

            asset_id, created_asset_id, asset_status, asset_payload = self._create_asset(
                provider,
                provider_jwt,
                model_url,
                suffix,
                runtime,
            )
            step("create_httpdata_asset", http_status=asset_status, asset_id=created_asset_id)

            execution_status, execution_body, execution_url = self._execute_model(
                provider,
                provider_jwt,
                asset_id,
                inference_payload,
                runtime,
            )
            evaluation = self.evaluate_execution_response(
                execution_status,
                execution_body,
                expected_model=expected_model,
            )
            step(
                "execute_model",
                status=evaluation["status"],
                http_status=execution_status,
                response_keys=evaluation["response_keys"],
            )
            execution_request = {
                "method": "POST",
                "url": execution_url,
                "asset_id": asset_id,
                "payload": inference_payload,
            }
            execution_response = {
                "http_status": execution_status,
                "body": execution_body,
            }
            executed_cases.append(
                self._case_result(
                    status=evaluation["status"],
                    assertions=list(evaluation["assertions"]),
                    request_payload=execution_request,
                    response_payload=execution_response,
                    execution_mode=execution_mode,
                    coverage_status=coverage_status,
                    model_server_mode=resolved_model_server_mode,
                )
            )
            if functional_context:
                semantic_evaluation = self.evaluate_flares_semantic_response(execution_body, functional_context)
                functional_assertions = list(evaluation["assertions"]) + list(semantic_evaluation["assertions"])
                functional_status = "failed" if functional_assertions else "passed"
                executed_cases.append(
                    self._functional_case_result(
                        status=functional_status,
                        assertions=functional_assertions,
                        request_payload=execution_request,
                        response_payload=execution_response,
                        functional_context=functional_context,
                        semantic_evaluation=semantic_evaluation,
                        model_server_mode=resolved_model_server_mode,
                    )
                )
        except Exception as exc:
            message = str(exc)
            step("suite_error", status="failed", error_type=type(exc).__name__, message=message)
            failed_request = {
                "method": "POST",
                "url": self._execution_url(provider, runtime),
                "asset_id": asset_id,
                "payload": inference_payload,
            }
            failed_response = {"http_status": None, "body": None}
            executed_cases.append(
                self._case_result(
                    status="failed",
                    assertions=[message],
                    request_payload=failed_request,
                    response_payload=failed_response,
                    execution_mode=execution_mode,
                    coverage_status=coverage_status,
                    model_server_mode=resolved_model_server_mode,
                )
            )
            if functional_context:
                executed_cases.append(
                    self._functional_case_result(
                        status="failed",
                        assertions=[message],
                        request_payload=failed_request,
                        response_payload=failed_response,
                        functional_context=functional_context,
                        model_server_mode=resolved_model_server_mode,
                    )
                )

        cleanup_error = None
        if provider_jwt and asset_id:
            try:
                cleanup_status, cleanup_body = self._delete_asset(provider, provider_jwt, asset_id)
                cleanup_ok = cleanup_status in {200, 204, 404}
                step(
                    "cleanup_delete_asset",
                    status="passed" if cleanup_ok else "failed",
                    http_status=cleanup_status,
                    body=cleanup_body,
                )
                if not cleanup_ok:
                    cleanup_error = f"Asset cleanup returned HTTP {cleanup_status}"
            except Exception as exc:
                cleanup_error = str(exc)
                step("cleanup_delete_asset", status="failed", error_type=type(exc).__name__, message=cleanup_error)

        if cleanup_error:
            for case in executed_cases:
                case["evaluation"]["status"] = "failed"
                case["evaluation"]["assertions"].append(cleanup_error)

        summary = self._summary(executed_cases, steps)
        status = "failed" if summary["failed"] else "passed"
        result = {
            "component": COMPONENT_KEY,
            "suite": SUITE_NAME,
            "status": status,
            "summary": summary,
            "timestamp": started_at,
            "provider": provider,
            "model_url": model_url,
            "runtime": {
                "dataspace": runtime.get("dataspace"),
                "ds_domain": runtime.get("ds_domain"),
                "adapter": runtime.get("adapter"),
                "topology": runtime.get("topology"),
            },
            "model_server": model_server_metadata,
            "created_entities": {
                "asset_id": asset_id,
            },
            "steps": steps,
            "executed_cases": executed_cases,
            "functional_context": functional_context,
            "asset_payload": asset_payload,
            "evidence_index": [],
        }

        if component_dir:
            report_path = os.path.join(component_dir, "ai_model_hub_model_execution_api.json")
            response_path = os.path.join(component_dir, "pt5-mh-10-execute-response.json")
            artifacts = {
                "report_json": report_path,
                "pt5-mh-10-execute-response.json": response_path,
            }
            functional_case = next(
                (case for case in executed_cases if case.get("test_case_id") == FUNCTIONAL_CASE_ID),
                None,
            )
            functional_response_path = os.path.join(component_dir, "mh-ling-01-flares-execution.json")
            self._write_json(
                response_path,
                {
                    "request": executed_cases[0]["request"] if executed_cases else {},
                    "response": executed_cases[0]["response"] if executed_cases else {},
                    "evaluation": executed_cases[0]["evaluation"] if executed_cases else {},
                },
            )
            if functional_case:
                artifacts["mh-ling-01-flares-execution.json"] = functional_response_path
                self._write_json(
                    functional_response_path,
                    {
                        "request": functional_case["request"],
                        "response": functional_case["response"],
                        "evaluation": functional_case["evaluation"],
                        "fixture": functional_case.get("fixture"),
                        "limitation": functional_case.get("limitation"),
                    },
                )
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
                    "test_case_id": TEST_CASE_ID,
                    "artifact_name": "pt5-mh-10-execute-response.json",
                    "path": response_path,
                },
            ]
            if functional_case:
                result["evidence_index"].append(
                    {
                        "scope": "case",
                        "suite": SUITE_NAME,
                        "test_case_id": FUNCTIONAL_CASE_ID,
                        "artifact_name": "mh-ling-01-flares-execution.json",
                        "path": functional_response_path,
                    }
                )
            self._write_json(report_path, result)
        else:
            result["artifacts"] = {}

        return result


def _dataspace_name_loader(adapter):
    config = getattr(adapter, "config", None)
    getter = getattr(config, "dataspace_name", None)
    if callable(getter):
        return getter
    return lambda: "demo"


def _build_adapter(adapter_name: str, topology: str):
    normalized = str(adapter_name or "inesdata").strip().lower()
    if normalized == "edc":
        from adapters.edc.adapter import EdcAdapter

        return EdcAdapter(topology=topology)
    from adapters.inesdata.adapter import InesdataAdapter

    return InesdataAdapter(topology=topology)


def _adapter_management_url_resolver(adapter):
    connectors = getattr(adapter, "connectors", None)
    credentials_loader = getattr(adapter, "load_connector_credentials", None)
    base_builder = getattr(connectors, "connector_base_url", None)
    interface_builder = getattr(connectors, "build_connector_url", None)
    if not any(callable(candidate) for candidate in (credentials_loader, base_builder, interface_builder)):
        return None

    def management_base_url(connector: str) -> str:
        if callable(credentials_loader):
            credentials = credentials_loader(connector) or {}
            public_urls = credentials.get("public_access_urls") if isinstance(credentials, dict) else {}
            if isinstance(public_urls, dict):
                management_v3 = str(public_urls.get("connector_management_api_v3") or "").strip().rstrip("/")
                if management_v3:
                    return management_v3
                management = str(public_urls.get("connector_management_api") or "").strip().rstrip("/")
                if management:
                    return _join_management_url(management, "/management/v3")

        if callable(base_builder):
            base = str(base_builder(connector) or "").strip().rstrip("/")
            if base:
                return _join_management_url(base, "/management/v3")

        if callable(interface_builder):
            base = str(interface_builder(connector) or "").strip().rstrip("/")
            if not base:
                return ""
            if base.endswith("/management/v3") or base.endswith("/management"):
                return _join_management_url(base, "/management/v3")
            for suffix in ("/inesdata-connector-interface", "/inesdata-connector-interface/"):
                if base.endswith(suffix):
                    base = base[: -len(suffix)].rstrip("/")
                    break
            if base:
                return _join_management_url(base, "/management/v3")
        return ""

    def resolver(connector: str, path: str) -> str:
        base = management_base_url(connector)
        suffix = str(path or "").strip()
        if not base:
            return ""
        if not suffix:
            return base
        if not suffix.startswith("/"):
            suffix = f"/{suffix}"
        if base.endswith("/management/v3") and suffix.startswith("/management/v3/"):
            suffix = suffix[len("/management/v3") :]
        elif base.endswith("/management") and suffix.startswith("/management/"):
            suffix = suffix[len("/management") :]
        return f"{base}{suffix}"

    return resolver


def _adapter_default_api_url_resolver(adapter):
    connectors = getattr(adapter, "connectors", None)
    public_api_builder = getattr(connectors, "_edc_connector_public_api_base_url", None)
    management_builder = getattr(connectors, "build_connector_url", None)

    def resolver(connector: str, path: str) -> str:
        base = ""
        if callable(public_api_builder):
            base = str(public_api_builder(connector) or "").strip().rstrip("/")
        if not base and callable(management_builder):
            management_base = str(management_builder(connector) or "").strip().rstrip("/")
            for suffix in ("/management/v3", "/management"):
                if management_base.endswith(suffix):
                    management_base = management_base[: -len(suffix)]
                    break
            base = management_base
        if not base:
            return ""
        return _join_default_api_url(f"{base}/api", path)

    return resolver


def build_ai_model_hub_model_execution_suite(adapter_name: str = "inesdata", topology: str = "local"):
    adapter = _build_adapter(adapter_name, topology)
    return AIModelHubModelExecutionApiSuite(
        load_connector_credentials=adapter.load_connector_credentials,
        load_deployer_config=adapter.load_deployer_config,
        ds_domain_resolver=adapter.config.ds_domain_base,
        ds_name_loader=_dataspace_name_loader(adapter),
        management_url_resolver=_adapter_management_url_resolver(adapter),
        default_api_url_resolver=_adapter_default_api_url_resolver(adapter),
        adapter_name=str(adapter_name or "inesdata").strip().lower(),
    ), adapter


def build_inesdata_ai_model_hub_model_execution_suite(topology: str = "local"):
    return build_ai_model_hub_model_execution_suite("inesdata", topology=topology)


def _join_url_path(base_url: str | None, path_value: str | None) -> str:
    base = str(base_url or "").strip().rstrip("/")
    path = str(path_value or "").strip()
    if not base:
        return ""
    if not path:
        return base
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path.rstrip('/')}"


def _force_url_scheme(base_url: str | None, scheme: str) -> str:
    raw_value = str(base_url or "").strip().rstrip("/")
    if not raw_value:
        return ""
    parsed = urlsplit(raw_value if "://" in raw_value else f"{scheme}://{raw_value}")
    if not parsed.netloc:
        return ""
    return urlunsplit((scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _configured_connector_model_server_base_url(config: dict[str, Any], topology: str | None = None) -> str:
    explicit = str(
        os.environ.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL")
        or os.environ.get("MODEL_SERVER_CONNECTOR_BASE_URL")
        or config.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_BASE_URL")
        or config.get("MODEL_SERVER_CONNECTOR_BASE_URL")
        or config.get("AI_MODEL_HUB_MODEL_SERVER_CONNECTOR_URL")
        or config.get("MODEL_SERVER_CONNECTOR_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")

    if str(topology or "").strip().lower() != "vm-distributed":
        return ""

    public_path = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH")
        or config.get("MODEL_SERVER_PUBLIC_PATH")
        or "/model-server"
    ).strip()
    for base_candidate in (
        config.get("VM_COMMON_HTTP_URL"),
        config.get("VM_COMMON_PUBLIC_URL"),
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL"),
        config.get("COMPONENTS_PUBLIC_BASE_URL"),
    ):
        base_url = _force_url_scheme(base_candidate, "http")
        if base_url:
            return _join_url_path(base_url, public_path)
    return ""


def _configured_model_server_base_url(config: dict[str, Any]) -> str:
    explicit = str(
        os.environ.get("AI_MODEL_HUB_MODEL_SERVER_BASE_URL")
        or config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_URL")
        or config.get("MODEL_SERVER_PUBLIC_URL")
        or config.get("AI_MODEL_HUB_MODEL_SERVER_BASE_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")

    public_base = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_BASE_URL")
        or config.get("COMPONENTS_PUBLIC_BASE_URL")
        or ""
    ).strip()
    public_path = str(
        config.get("AI_MODEL_HUB_MODEL_SERVER_PUBLIC_PATH")
        or config.get("MODEL_SERVER_PUBLIC_PATH")
        or "/model-server"
    ).strip()
    return _join_url_path(public_base, public_path)


def default_model_url(adapter, model_path: str = DEFAULT_MODEL_PATH) -> str:
    config_loader = getattr(adapter, "load_deployer_config", None)
    config = config_loader() if callable(config_loader) else {}
    if not isinstance(config, dict):
        config = {}
    normalized_path = f"/{str(model_path or DEFAULT_MODEL_PATH).lstrip('/')}"
    topology = (
        getattr(adapter, "topology", "")
        or config.get("TOPOLOGY")
        or os.environ.get("PIONERA_TOPOLOGY")
        or os.environ.get("TOPOLOGY")
        or ""
    )
    connector_base = _configured_connector_model_server_base_url(config, topology=topology)
    if connector_base:
        return _join_url_path(connector_base, normalized_path)
    public_base = _configured_model_server_base_url(config)
    if public_base:
        return _join_url_path(public_base, normalized_path)
    namespace = (
        os.environ.get("AI_MODEL_HUB_MODEL_SERVER_NAMESPACE")
        or os.environ.get("UI_AI_MODEL_HUB_MODEL_NAMESPACE")
        or os.environ.get("UI_COMPONENTS_NAMESPACE")
        or config.get("COMPONENTS_NAMESPACE")
        or _dataspace_name_loader(adapter)()
        or "components"
    )
    namespace = str(namespace or "components").strip() or "components"
    return f"http://model-server.{namespace}.svc.cluster.local:8080{normalized_path}"


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        raw = handle.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as original_error:
        records = []
        for index, line in enumerate(raw.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as line_error:
                raise RuntimeError(
                    f"Invalid JSON or JSON Lines content in {path} at line {index}: {line_error}"
                ) from line_error
        if records:
            return records
        raise original_error


def _ensure_flares_records(value: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    raise RuntimeError(f"FLARES {label} file must contain a JSON array or JSON Lines objects")


def _build_flares_metadata(source_dir: str) -> dict[str, Any]:
    return {
        "datasetName": FLARES_DATASET_NAME,
        "domain": "linguistic",
        "language": "es",
        "task": "5w1h-reliability-classification",
        "version": "source-runtime",
        "keywords": ["flares", "5w1h", "reliability", "linguistic", "mh-ling-01"],
        "source": {
            "name": "FLARES",
            "repository": "https://github.com/rsepulveda911112/Flares-dataset",
            "localPath": source_dir,
            "license": "Review upstream dataset terms before external publication.",
        },
        "assetPublication": {
            "assetId": "dataset-flares-subtask2",
            "policyId": "policy-flares-subtask2",
            "contractDefinitionId": "contractdef-flares-subtask2",
            "storeFolder": "linguistic-flares",
            "publicationMode": "on_demand",
            "uploadFile": FLARES_TRIAL_FILE,
            "fileName": "flares-subtask2-trial.json",
            "uploadMediaType": "application/json",
            "description": "FLARES source records used by the MH-LING-01 linguistic validation flow.",
        },
    }


def _build_flares_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "FLARES records",
        "type": "array",
        "items": {
            "type": "object",
            "required": ["Id", "Text", "5W1H_Label", "Tag_Text", "Tag_Start", "Tag_End"],
            "properties": {
                "Id": {"type": "integer"},
                "Text": {"type": "string"},
                "Reliability_Label": {"type": "string"},
                "5W1H_Label": {"type": "string"},
                "Tag_Text": {"type": "string"},
                "Tag_Start": {"type": "integer"},
                "Tag_End": {"type": "integer"},
            },
        },
    }


def _flares_expected_outputs(trial_sample: list[dict[str, Any]], test_sample: list[dict[str, Any]]) -> dict[str, Any]:
    records = [
        {
            "Id": int(record["Id"]),
            "5W1H_Label": record.get("5W1H_Label"),
            "expectedReliability": record.get("Reliability_Label"),
        }
        for record in trial_sample
        if "Id" in record and record.get("Reliability_Label") is not None
    ]
    distribution: dict[str, int] = {}
    for record in records:
        label = str(record.get("expectedReliability") or "")
        distribution[label] = distribution.get(label, 0) + 1
    return {
        "subtask2_trial_sample": {
            "recordCount": len(records),
            "classDistribution": distribution,
            "records": records,
        },
        "subtask2_test_sample": {
            "recordCount": len(test_sample),
            "unlabeled": not any("Reliability_Label" in record for record in test_sample),
            "requiredFields": ["Id", "Text", "5W1H_Label", "Tag_Text", "Tag_Start", "Tag_End"],
            "records": [
                {
                    "Id": int(record["Id"]),
                    "5W1H_Label": record.get("5W1H_Label"),
                }
                for record in test_sample
                if "Id" in record
            ],
        },
    }


def load_flares_dataset(source_dir: str | None = None) -> dict[str, Any]:
    resolved_dir = os.path.abspath(source_dir or FLARES_DATASET_DIR)
    expected_files = {
        "trial_sample": FLARES_TRIAL_FILE,
        "test_sample": FLARES_TEST_FILE,
    }
    missing = [
        file_name for file_name in expected_files.values() if not os.path.exists(os.path.join(resolved_dir, file_name))
    ]
    if missing:
        raise RuntimeError(
            "FLARES source dataset is missing required files. "
            f"Expected Level 5 clone at {resolved_dir}; missing: {', '.join(missing)}"
        )
    trial_sample = _ensure_flares_records(
        _read_json(os.path.join(resolved_dir, expected_files["trial_sample"])),
        "trial",
    )
    test_sample = _ensure_flares_records(
        _read_json(os.path.join(resolved_dir, expected_files["test_sample"])),
        "test",
    )
    return {
        "source_dir": resolved_dir,
        "metadata": _build_flares_metadata(resolved_dir),
        "schema": _build_flares_schema(),
        "trial_sample": trial_sample,
        "test_sample": test_sample,
        "expected_outputs": _flares_expected_outputs(trial_sample, test_sample),
        "expected_outputs_source": os.path.join(resolved_dir, expected_files["trial_sample"]),
        "upload_file_path": os.path.join(resolved_dir, expected_files["trial_sample"]),
    }


def _select_flares_trial_record(dataset: dict[str, Any], record_id: int | None = None) -> dict[str, Any]:
    records = list(dataset.get("trial_sample") or [])
    if not records:
        raise RuntimeError("FLARES trial sample is empty")
    if record_id is None:
        return dict(records[0])
    for record in records:
        if int(record.get("Id")) == int(record_id):
            return dict(record)
    raise RuntimeError(f"FLARES trial record {record_id} was not found")


def _expected_flares_output(dataset: dict[str, Any], record_id: int) -> dict[str, Any]:
    outputs = ((dataset.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get("records") or []
    for output in outputs:
        if int(output.get("Id")) == int(record_id):
            return dict(output)
    raise RuntimeError(f"FLARES expected output for record {record_id} was not found")


def build_flares_execution_context(
    *,
    source_dir: str | None = None,
    record_id: int | None = None,
) -> dict[str, Any]:
    dataset = load_flares_dataset(source_dir)
    metadata = dict(dataset.get("metadata") or {})
    record = _select_flares_trial_record(dataset, record_id)
    resolved_record_id = int(record["Id"])
    expected_output = _expected_flares_output(dataset, resolved_record_id)
    payload = [
        {
            "Id": resolved_record_id,
            "Text": record.get("Text"),
            "5W1H_Label": record.get("5W1H_Label"),
            "Tag_Text": record.get("Tag_Text"),
            "Tag_Start": record.get("Tag_Start"),
            "Tag_End": record.get("Tag_End"),
        }
    ]
    return {
        "use_case_id": FUNCTIONAL_CASE_ID,
        "dataset_name": metadata.get("datasetName") or FLARES_DATASET_NAME,
        "domain": metadata.get("domain") or "linguistic",
        "record_id": resolved_record_id,
        "w1h_label": record.get("5W1H_Label"),
        "expected_output": expected_output,
        "expected_outputs_source": dataset.get("expected_outputs_source"),
        "payload": payload,
        "sample": {
            "text_excerpt": str(record.get("Text") or "")[:240],
            "tag_text": record.get("Tag_Text"),
            "original_reliability_label": record.get("Reliability_Label"),
        },
        "expected_outputs_summary": {
            "record_count": ((dataset.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get(
                "recordCount"
            ),
            "class_distribution": ((dataset.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get(
                "classDistribution"
            ),
        },
    }


def _default_experiment_dir() -> str:
    return os.path.join("experiments", f"ai-model-hub-model-execution-api-{datetime.now().strftime('%Y%m%d-%H%M%S')}")


def _parse_json_object(value: str, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError(f"{label} must be a JSON object")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PT5-MH-10 AI Model Hub controlled execution baseline.")
    parser.add_argument(
        "--adapter",
        default=str(os.environ.get("PIONERA_ADAPTER") or os.environ.get("AI_MODEL_HUB_COMPONENT_ADAPTER") or "inesdata"),
        choices=["inesdata", "edc"],
    )
    parser.add_argument("--topology", default="local", choices=["local", "vm-single", "vm-distributed"])
    parser.add_argument("--provider", default="")
    parser.add_argument("--model-url", default="")
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--payload-json", default=json.dumps(DEFAULT_PAYLOAD))
    parser.add_argument("--expected-model", default=DEFAULT_EXPECTED_MODEL)
    parser.add_argument("--flares-dataset", action="store_true")
    parser.add_argument("--flares-source-dir", default="")
    parser.add_argument("--flares-record-id", type=int, default=0)
    parser.add_argument("--experiment-dir", default="")
    args = parser.parse_args(argv)

    functional_context = None
    if args.flares_dataset:
        functional_context = build_flares_execution_context(
            source_dir=args.flares_source_dir or None,
            record_id=args.flares_record_id or None,
        )
        payload = functional_context["payload"]
        if args.model_path == DEFAULT_MODEL_PATH and not args.model_url:
            args.model_path = FLARES_MODEL_PATH
        if args.expected_model == DEFAULT_EXPECTED_MODEL:
            args.expected_model = FLARES_EXPECTED_MODEL
    else:
        payload = _parse_json_object(args.payload_json, "--payload-json")

    suite, adapter = build_ai_model_hub_model_execution_suite(args.adapter, topology=args.topology)
    connectors = list(adapter.get_cluster_connectors() or []) if not args.provider else []
    provider = args.provider or (connectors[0] if connectors else "")
    if not provider:
        raise RuntimeError("Provider connector must be provided or discoverable from the cluster")

    result = suite.run(
        provider=provider,
        model_url=args.model_url or default_model_url(adapter, args.model_path),
        payload=payload,
        expected_model=args.expected_model or None,
        functional_context=functional_context,
        experiment_dir=args.experiment_dir or _default_experiment_dir(),
    )
    print(json.dumps({
        "status": result.get("status"),
        "summary": result.get("summary"),
        "artifact": (result.get("artifacts") or {}).get("report_json"),
    }, indent=2))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
