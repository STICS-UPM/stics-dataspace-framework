from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Callable

import requests


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "model-execution-api"
TEST_CASE_ID = "PT5-MH-10"
FUNCTIONAL_CASE_ID = "MH-LING-01"
EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/"
DEFAULT_MODEL_PATH = "/api/v1/nlp/ecommerce-sentiment"
DEFAULT_PAYLOAD = {"text": "This product is excellent and very useful"}
DEFAULT_EXPECTED_MODEL = "E-commerce Sentiment Analyzer"
FLARES_FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "datasets",
    "linguistic",
    "flares-mini",
)


class AIModelHubModelExecutionApiSuite:
    """Exercise Edmundo's connector-side model execution API with a temporary HttpData asset."""

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
        keycloak_url_resolver: Callable[[], str] | None = None,
        session: requests.Session | None = None,
        uuid_factory: Callable[[], str] | None = None,
    ):
        self.load_connector_credentials = load_connector_credentials
        self.load_deployer_config = load_deployer_config
        self.ds_domain_resolver = ds_domain_resolver
        self.ds_name_loader = ds_name_loader or (lambda: "demo")
        self.management_url_resolver = management_url_resolver
        self.keycloak_url_resolver = keycloak_url_resolver
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

    def _create_asset(self, provider: str, provider_jwt: str, model_url: str, suffix: str):
        asset_id = f"a52-model-exec-{suffix}"
        payload = {
            "@context": {
                "@vocab": EDC_NAMESPACE,
                "dct": "http://purl.org/dc/terms/",
                "dcat": "http://www.w3.org/ns/dcat#",
            },
            "@id": asset_id,
            "@type": "Asset",
            "properties": {
                "name": f"AI Model Hub executable model {suffix}",
                "version": "1.0.0",
                "shortDescription": "Temporary model endpoint for A5.2 execution API smoke",
                "assetType": "ai-model-execution-endpoint",
                "dct:description": "HttpData endpoint consumed through the connector-side model execution API",
                "dcat:keyword": ["validation", "ai-model-hub", "model-execution", "A5.2"],
            },
            "dataAddress": {
                "type": "HttpData",
                "baseUrl": model_url,
                "method": "POST",
                "name": f"ai-model-hub-model-execution-{suffix}",
            },
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
        payload: dict[str, Any],
    ) -> tuple[int, Any, str]:
        url = self._management_url(provider, "/management/v3/modelexecutions/execute")
        status_code, body = self._post_json(
            url,
            provider_jwt,
            {
                "assetId": asset_id,
                "payload": payload,
            },
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
        if not isinstance(body, dict):
            assertions.append("Model execution response must be a JSON object")
        elif expected_model and body.get("model") != expected_model:
            assertions.append(f"Expected model '{expected_model}', got '{body.get('model')}'")

        return {
            "status": "failed" if assertions else "passed",
            "assertions": assertions,
            "http_status": status_code,
            "response_keys": sorted(body.keys()) if isinstance(body, dict) else [],
        }

    @staticmethod
    def _case_result(
        *,
        status: str,
        assertions: list[str],
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "test_case_id": TEST_CASE_ID,
            "description": "Execute inference through the connector-side model execution API",
            "type": "api",
            "case_group": "pt5",
            "validation_type": "integration",
            "dataspace_dimension": "execution",
            "mapping_status": "phase_3",
            "automation_mode": "api",
            "execution_mode": "api",
            "coverage_status": "api_smoke",
            "request": request_payload,
            "response": response_payload,
            "evaluation": {
                "status": status,
                "assertions": assertions,
            },
            "expected_result": "The model execution API resolves the HttpData asset and returns a model response",
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
    ) -> dict[str, Any]:
        expected_output = dict(functional_context.get("expected_output") or {})
        return {
            "test_case_id": FUNCTIONAL_CASE_ID,
            "description": "Execute a FLARES-mini linguistic sample through the connector-side model execution API",
            "type": "api",
            "case_group": "functional",
            "validation_type": "functional",
            "dataspace_dimension": "linguistic",
            "mapping_status": "phase_3",
            "automation_mode": "api",
            "execution_mode": "api",
            "coverage_status": "partial_api_execution",
            "request": request_payload,
            "response": response_payload,
            "evaluation": {
                "status": status,
                "assertions": assertions,
                "comparison_scope": "transport_and_fixture_alignment",
                "semantic_comparison_status": "pending_flares_model_endpoint",
            },
            "expected_result": (
                "A FLARES-mini record is executable through the connector API and linked to "
                "expected_outputs.json for the future reliability-label assertion"
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
            "limitation": (
                "The current model-server endpoint is a controlled execution fixture. It confirms "
                "connector-side execution with a FLARES payload, but it does not yet emit the "
                "FLARES reliability label required for the final semantic comparison."
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
        payload: dict[str, Any] | None = None,
        expected_model: str | None = DEFAULT_EXPECTED_MODEL,
        functional_context: dict[str, Any] | None = None,
        experiment_dir: str | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now().isoformat()
        runtime = self._runtime()
        component_dir = self._component_dir(experiment_dir)
        suffix = self._safe_suffix(self.uuid_factory())
        inference_payload = dict(payload or DEFAULT_PAYLOAD)
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
            )
            step("create_httpdata_asset", http_status=asset_status, asset_id=created_asset_id)

            execution_status, execution_body, execution_url = self._execute_model(
                provider,
                provider_jwt,
                asset_id,
                inference_payload,
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
                )
            )
            if functional_context:
                functional_status = "passed" if evaluation["status"] == "passed" else "failed"
                functional_assertions = [] if functional_status == "passed" else list(evaluation["assertions"])
                executed_cases.append(
                    self._functional_case_result(
                        status=functional_status,
                        assertions=functional_assertions,
                        request_payload=execution_request,
                        response_payload=execution_response,
                        functional_context=functional_context,
                    )
                )
        except Exception as exc:
            message = str(exc)
            step("suite_error", status="failed", error_type=type(exc).__name__, message=message)
            failed_request = {
                "method": "POST",
                "url": self._management_url(provider, "/management/v3/modelexecutions/execute"),
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
            },
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


def build_inesdata_ai_model_hub_model_execution_suite(topology: str = "local"):
    from adapters.inesdata.adapter import InesdataAdapter

    adapter = InesdataAdapter(topology=topology)
    return AIModelHubModelExecutionApiSuite(
        load_connector_credentials=adapter.load_connector_credentials,
        load_deployer_config=adapter.load_deployer_config,
        ds_domain_resolver=adapter.config.ds_domain_base,
        ds_name_loader=_dataspace_name_loader(adapter),
    ), adapter


def default_model_url(adapter, model_path: str = DEFAULT_MODEL_PATH) -> str:
    dataspace = str(_dataspace_name_loader(adapter)() or "demo").strip() or "demo"
    normalized_path = f"/{str(model_path or DEFAULT_MODEL_PATH).lstrip('/')}"
    return f"http://model-server.{dataspace}.svc.cluster.local:8080{normalized_path}"


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_flares_mini_fixture(fixture_dir: str | None = None) -> dict[str, Any]:
    resolved_dir = os.path.abspath(fixture_dir or FLARES_FIXTURE_DIR)
    expected_files = {
        "metadata": "metadata.json",
        "schema": "schema.json",
        "trial_sample": "subtask2_trial_sample.json",
        "test_sample": "subtask2_test_sample.json",
        "expected_outputs": "expected_outputs.json",
    }
    missing = [
        file_name for file_name in expected_files.values() if not os.path.exists(os.path.join(resolved_dir, file_name))
    ]
    if missing:
        raise RuntimeError(f"FLARES-mini fixture is missing required files: {', '.join(missing)}")
    return {
        "fixture_dir": resolved_dir,
        "metadata": _read_json(os.path.join(resolved_dir, expected_files["metadata"])),
        "schema": _read_json(os.path.join(resolved_dir, expected_files["schema"])),
        "trial_sample": _read_json(os.path.join(resolved_dir, expected_files["trial_sample"])),
        "test_sample": _read_json(os.path.join(resolved_dir, expected_files["test_sample"])),
        "expected_outputs": _read_json(os.path.join(resolved_dir, expected_files["expected_outputs"])),
        "expected_outputs_source": os.path.join(resolved_dir, expected_files["expected_outputs"]),
    }


def _select_flares_trial_record(fixture: dict[str, Any], record_id: int | None = None) -> dict[str, Any]:
    records = list(fixture.get("trial_sample") or [])
    if not records:
        raise RuntimeError("FLARES-mini trial sample is empty")
    if record_id is None:
        return dict(records[0])
    for record in records:
        if int(record.get("Id")) == int(record_id):
            return dict(record)
    raise RuntimeError(f"FLARES-mini trial record {record_id} was not found")


def _expected_flares_output(fixture: dict[str, Any], record_id: int) -> dict[str, Any]:
    outputs = ((fixture.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get("records") or []
    for output in outputs:
        if int(output.get("Id")) == int(record_id):
            return dict(output)
    raise RuntimeError(f"FLARES-mini expected output for record {record_id} was not found")


def build_flares_mini_execution_context(
    *,
    fixture_dir: str | None = None,
    record_id: int | None = None,
) -> dict[str, Any]:
    fixture = load_flares_mini_fixture(fixture_dir)
    metadata = dict(fixture.get("metadata") or {})
    record = _select_flares_trial_record(fixture, record_id)
    resolved_record_id = int(record["Id"])
    expected_output = _expected_flares_output(fixture, resolved_record_id)
    payload = {
        "text": record.get("Text"),
        "w1h_label": record.get("5W1H_Label"),
        "tag_text": record.get("Tag_Text"),
        "tag_start": record.get("Tag_Start"),
        "tag_end": record.get("Tag_End"),
        "dataset": metadata.get("datasetName") or "FLARES-mini",
        "record_id": resolved_record_id,
    }
    return {
        "use_case_id": FUNCTIONAL_CASE_ID,
        "dataset_name": metadata.get("datasetName") or "FLARES-mini",
        "domain": metadata.get("domain") or "linguistic",
        "record_id": resolved_record_id,
        "w1h_label": record.get("5W1H_Label"),
        "expected_output": expected_output,
        "expected_outputs_source": fixture.get("expected_outputs_source"),
        "payload": payload,
        "sample": {
            "text_excerpt": str(record.get("Text") or "")[:240],
            "tag_text": record.get("Tag_Text"),
            "original_reliability_label": record.get("Reliability_Label"),
        },
        "expected_outputs_summary": {
            "record_count": ((fixture.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get(
                "recordCount"
            ),
            "class_distribution": ((fixture.get("expected_outputs") or {}).get("subtask2_trial_sample") or {}).get(
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
    parser = argparse.ArgumentParser(description="Run PT5-MH-10 AI Model Hub model execution API smoke.")
    parser.add_argument("--topology", default="local", choices=["local", "vm-single"])
    parser.add_argument("--provider", default="")
    parser.add_argument("--model-url", default="")
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--payload-json", default=json.dumps(DEFAULT_PAYLOAD))
    parser.add_argument("--expected-model", default=DEFAULT_EXPECTED_MODEL)
    parser.add_argument("--flares-mini", action="store_true")
    parser.add_argument("--flares-fixture-dir", default="")
    parser.add_argument("--flares-record-id", type=int, default=0)
    parser.add_argument("--experiment-dir", default="")
    args = parser.parse_args(argv)

    functional_context = None
    if args.flares_mini:
        functional_context = build_flares_mini_execution_context(
            fixture_dir=args.flares_fixture_dir or None,
            record_id=args.flares_record_id or None,
        )
        payload = dict(functional_context["payload"])
    else:
        payload = _parse_json_object(args.payload_json, "--payload-json")

    suite, adapter = build_inesdata_ai_model_hub_model_execution_suite(topology=args.topology)
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
