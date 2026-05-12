"""Readiness probes used by Level 6 validation."""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from itertools import permutations
from typing import Any, Callable


def build_management_health_payload() -> dict[str, Any]:
    return {
        "@context": {
            "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
        },
        "offset": 0,
        "limit": 1,
        "filterExpression": [],
    }


def _decode_jwt_payload(headers: dict[str, str] | None) -> dict[str, Any]:
    if not isinstance(headers, dict):
        return {}

    authorization = ""
    for key, value in headers.items():
        if str(key).lower() == "authorization":
            authorization = str(value or "")
            break

    if not authorization.startswith("Bearer "):
        return {}

    token = authorization.split(" ", 1)[1].strip()
    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        parsed = json.loads(decoded)
    except Exception:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _response_body_summary(response: Any) -> Any:
    try:
        body = response.json()
    except (AttributeError, ValueError):
        text = getattr(response, "text", "") or ""
        return text[:300]

    if isinstance(body, list):
        summarized = []
        for item in body[:3]:
            if isinstance(item, dict):
                summarized.append({
                    key: item.get(key)
                    for key in ("message", "type", "path", "invalidValue")
                    if key in item
                })
            else:
                summarized.append(str(item)[:120])
        return summarized

    if isinstance(body, dict):
        return {
            key: body.get(key)
            for key in ("message", "type", "path", "invalidValue", "error")
            if key in body
        } or str(body)[:300]

    return str(body)[:300]


def _auth_diagnostic(
    *,
    connector: str,
    url: str,
    headers: dict[str, str] | None,
    response: Any,
) -> dict[str, Any]:
    payload = _decode_jwt_payload(headers)
    realm_access = payload.get("realm_access") if isinstance(payload, dict) else {}
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else []

    return {
        "http_status": getattr(response, "status_code", None),
        "connector": connector,
        "url": url,
        "auth_header_present": bool(headers and any(str(k).lower() == "authorization" for k in headers)),
        "token_present": bool(payload),
        "issuer": payload.get("iss"),
        "audience": payload.get("aud"),
        "preferred_username": payload.get("preferred_username"),
        "realm_roles": roles if isinstance(roles, list) else [],
        "response": _response_body_summary(response),
    }


def _invalidate_management_token(connectors_adapter: Any, connector: str) -> None:
    invalidate = getattr(connectors_adapter, "invalidate_management_api_token", None)
    if callable(invalidate):
        invalidate(connector)


def _brief_gate_error(detail: Any) -> str:
    if isinstance(detail, dict):
        status = detail.get("http_status")
        connector = detail.get("connector")
        response = detail.get("response")
        response_type = None
        response_message = None
        if isinstance(response, list) and response:
            first = response[0]
            if isinstance(first, dict):
                response_type = first.get("type")
                response_message = first.get("message")
        elif isinstance(response, dict):
            response_type = response.get("type")
            response_message = response.get("message") or response.get("error")

        pieces = []
        if connector:
            pieces.append(str(connector))
        if status:
            pieces.append(f"HTTP {status}")
        if response_type:
            pieces.append(str(response_type))
        if response_message:
            pieces.append(str(response_message))
        return " - ".join(pieces) if pieces else str(detail)
    return str(detail)


def build_catalog_payload(provider: str, consumer: str, validation_engine: Any) -> dict[str, Any]:
    env_vars = validation_engine.build_newman_env(provider, consumer)
    return {
        "@context": {
            "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
        },
        "@type": "CatalogRequest",
        "counterPartyAddress": env_vars["providerProtocolAddress"],
        "counterPartyId": provider,
        "protocol": "dataspace-protocol-http",
        "querySpec": {
            "offset": 0,
            "limit": 1,
            "filterExpression": [],
        },
    }


def probe_management_api(connector: str, *, connectors_adapter: Any, requests_module: Any) -> tuple[bool, Any]:
    headers = connectors_adapter.get_management_api_headers(connector)
    if not headers:
        return False, "could not obtain management API token"

    base_url = connectors_adapter.connector_base_url(connector)
    url = f"{base_url}/management/v3/assets/request"
    response = requests_module.post(
        url,
        headers=headers,
        json=build_management_health_payload(),
        timeout=5,
    )
    if response.status_code != 200:
        if response.status_code == 401:
            _invalidate_management_token(connectors_adapter, connector)
        return False, _auth_diagnostic(
            connector=connector,
            url=url,
            headers=headers,
            response=response,
        )

    try:
        body = response.json()
    except ValueError:
        return False, "response body is not valid JSON"

    if not isinstance(body, list):
        return False, "management response is not a JSON array"

    return True, {"items": len(body)}


def probe_catalog(
    provider: str,
    consumer: str,
    *,
    connectors_adapter: Any,
    validation_engine: Any,
    requests_module: Any,
) -> tuple[bool, Any]:
    headers = connectors_adapter.get_management_api_headers(consumer)
    if not headers:
        return False, "could not obtain consumer management API token"

    consumer_base_url = connectors_adapter.connector_base_url(consumer)
    url = f"{consumer_base_url}/management/v3/catalog/request"
    response = requests_module.post(
        url,
        headers=headers,
        json=build_catalog_payload(provider, consumer, validation_engine),
        timeout=10,
    )
    if response.status_code != 200:
        if response.status_code == 401:
            _invalidate_management_token(connectors_adapter, consumer)
        return False, _auth_diagnostic(
            connector=consumer,
            url=url,
            headers=headers,
            response=response,
        )

    try:
        body = response.json()
    except ValueError:
        return False, "catalog response is not valid JSON"

    if not isinstance(body, dict):
        return False, "catalog response is not a JSON object"

    datasets = body.get("dcat:dataset")
    if datasets is None:
        datasets = body.get("dataset")
    if datasets is None:
        return False, "catalog response missing dataset field"

    if isinstance(datasets, list):
        dataset_count = len(datasets)
    elif isinstance(datasets, dict):
        dataset_count = 1
    else:
        dataset_count = 0

    return True, {"datasets": dataset_count}


def wait_for_validation_ready(
    connectors: list[str],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    probe_management_api_fn: Callable[[str], tuple[bool, Any]],
    probe_catalog_fn: Callable[[str, str], tuple[bool, Any]],
    experiment_storage: Any,
    experiment_dir: str | None = None,
) -> dict[str, Any]:
    started_at = time.time()
    deadline = started_at + timeout_seconds
    gates: list[dict[str, Any]] = []

    pending_checks = []
    for connector in connectors or []:
        pending_checks.append({
            "name": f"management_api_smoke:{connector}",
            "probe": lambda connector_name=connector: probe_management_api_fn(connector_name),
            "attempts": 0,
        })

    for provider, consumer in permutations(connectors or [], 2):
        pending_checks.append({
            "name": f"catalog_smoke:{provider}->{consumer}",
            "probe": lambda provider_name=provider, consumer_name=consumer: probe_catalog_fn(provider_name, consumer_name),
            "attempts": 0,
        })

    while pending_checks and time.time() <= deadline:
        remaining_checks = []
        for check in pending_checks:
            check["attempts"] += 1
            gate_started_at = time.time()
            try:
                passed, detail = check["probe"]()
            except Exception as exc:
                passed = False
                detail = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }

            if passed:
                gate = {
                    "gate": check["name"],
                    "status": "passed",
                    "attempts": check["attempts"],
                    "duration_seconds": round(time.time() - started_at, 3),
                    "probe_duration_seconds": round(time.time() - gate_started_at, 3),
                    "detail": detail,
                }
                if check.get("last_error") is not None:
                    gate["previous_error"] = check.get("last_error")
                gates.append(gate)
                continue

            check["last_error"] = detail
            remaining_checks.append(check)

        pending_checks = remaining_checks
        if pending_checks and time.time() <= deadline:
            time.sleep(poll_interval_seconds)

    for check in pending_checks:
        gates.append({
            "gate": check["name"],
            "status": "failed",
            "attempts": check["attempts"],
            "duration_seconds": round(time.time() - started_at, 3),
            "error": check.get("last_error"),
        })

    readiness = {
        "status": "passed" if not pending_checks else "failed",
        "timestamp": datetime.now().isoformat(),
        "connectors": list(connectors or []),
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "total_duration_seconds": round(time.time() - started_at, 3),
        "gates": gates,
    }

    if experiment_dir:
        experiment_storage.save(
            readiness,
            experiment_dir=experiment_dir,
            file_name="level6_readiness.json",
        )

    if readiness["status"] == "passed":
        print(
            "Level 6 validation readiness confirmed in "
            f"{readiness['total_duration_seconds']}s"
        )
    else:
        print(
            "Level 6 validation readiness did not converge within "
            f"{timeout_seconds}s"
        )
        for gate in gates:
            if gate.get("status") == "failed":
                print(f"  FAIL {gate.get('gate')}: {_brief_gate_error(gate.get('error'))}")

    return readiness
