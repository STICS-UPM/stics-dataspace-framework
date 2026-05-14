from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib import parse

import requests


COMPONENT_KEY = "ai-model-hub"
SUITE_NAME = "model-observer-api"
CASE_ID = "MH-OBS-02"

OBSERVER_API_BASE_URL_ENVS = [
    "AI_MODEL_HUB_OBSERVER_API_BASE_URL",
    "AI_MODEL_OBSERVER_API_BASE_URL",
    "AI_MODEL_HUB_PUBLIC_PORTAL_BACKEND_URL",
    "INESDATA_PUBLIC_PORTAL_BACKEND_URL",
]

UNAVAILABLE_STATUS_CODES = {0, 404, 405, 501, 502, 503, 504}


def _component_dir(experiment_dir: str | None) -> str | None:
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, "components", COMPONENT_KEY, "integration")
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _default_experiment_dir() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join("experiments", f"ai-model-hub-model-observer-api-{timestamp}")


def _build_url(base_url: str, path: str) -> str:
    normalized_base = (base_url or "").rstrip("/")
    return parse.urljoin(f"{normalized_base}/", path.lstrip("/"))


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def resolve_model_observer_api_base_url(base_url: str | None = None) -> str:
    for env_name in OBSERVER_API_BASE_URL_ENVS:
        candidate = str(os.environ.get(env_name) or "").strip()
        if candidate:
            return candidate.rstrip("/")
    return str(base_url or "").strip().rstrip("/")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_observer_event_batch(run_id: str | None = None) -> dict[str, Any]:
    normalized_run_id = run_id or f"a52-observer-{uuid.uuid4().hex[:12]}"
    asset_id = f"asset-{normalized_run_id}"
    agreement_id = f"agreement-{normalized_run_id}"
    benchmark_run_id = f"benchmark-{normalized_run_id}"
    participant_id = "qa-ai-model-consumer"
    correlation_id = f"correlation-{normalized_run_id}"
    occurred_at = _utc_now()

    base_event = {
        "sourceComponent": "validation-framework",
        "participantId": participant_id,
        "actorType": "system",
        "actorId": "a52-validation",
        "correlationId": correlation_id,
        "processId": normalized_run_id,
        "assetId": asset_id,
        "agreementId": agreement_id,
        "benchmarkRunId": benchmark_run_id,
        "providerParticipantId": "qa-ai-model-provider",
        "consumerParticipantId": participant_id,
        "modelName": "A5.2 Observer Smoke Model",
        "executionMode": "local",
        "endpointKind": "local-http",
        "taskType": "observer-smoke",
        "datasetFingerprint": _sha256_short(f"dataset:{normalized_run_id}"),
        "datasetRowCount": 3,
        "payloadHash": _sha256_short(f"payload:{normalized_run_id}"),
        "responseHash": _sha256_short(f"response:{normalized_run_id}"),
        "details": {
            "scope": "A5.2 observer smoke",
            "sensitivePayloadStored": False,
            "rawDatasetStored": False,
        },
        "occurredAt": occurred_at,
    }

    events = [
        {
            **base_event,
            "eventId": f"{normalized_run_id}-detail-viewed",
            "eventType": "MODEL_DETAIL_VIEWED",
            "status": "VIEWED",
        },
        {
            **base_event,
            "eventId": f"{normalized_run_id}-benchmark-started",
            "eventType": "BENCHMARK_STARTED",
            "status": "STARTED",
            "selectedMetrics": ["accuracy", "latency"],
            "benchmarkSummary": {
                "modelsCompared": 2,
                "datasetRows": 3,
            },
        },
        {
            **base_event,
            "eventId": f"{normalized_run_id}-execution-completed",
            "eventType": "MODEL_EXECUTION_COMPLETED",
            "status": "COMPLETED",
            "httpStatus": 200,
            "latencyMs": 123,
        },
    ]

    return {
        "run_id": normalized_run_id,
        "asset_id": asset_id,
        "agreement_id": agreement_id,
        "benchmark_run_id": benchmark_run_id,
        "participant_id": participant_id,
        "correlation_id": correlation_id,
        "events": events,
    }


def _response_json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw_body": response.text[:1000]}


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    payload: Any | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    try:
        response = session.request(
            method,
            url,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return {
            "method": method,
            "url": url,
            "http_status": 0,
            "payload": {"error": str(exc)},
        }

    return {
        "method": method,
        "url": url,
        "http_status": int(response.status_code),
        "content_type": response.headers.get("Content-Type", ""),
        "payload": _response_json_or_text(response),
    }


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "events", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _payload_total(payload: Any) -> int:
    if isinstance(payload, dict):
        total = payload.get("total")
        if isinstance(total, int):
            return total
    return len(_extract_items(payload))


def _contains_event_type(payload: Any, event_type: str) -> bool:
    return any(isinstance(item, dict) and item.get("eventType") == event_type for item in _extract_items(payload))


def _validate_observer_responses(responses: dict[str, dict[str, Any]]) -> list[str]:
    assertions: list[str] = []
    create_response = responses["create_bulk"]
    create_payload = create_response.get("payload")
    if create_response.get("http_status") not in {200, 201}:
        assertions.append(
            f"Expected Observer bulk ingestion HTTP 200/201, got HTTP {create_response.get('http_status')}"
        )
        return assertions

    if isinstance(create_payload, dict):
        inserted = int(create_payload.get("inserted") or 0)
        total = int(create_payload.get("total") or 0)
        if total < 3:
            assertions.append(f"Expected Observer bulk ingestion total >= 3, got {total}")
        if inserted < 1 and int(create_payload.get("ignored") or 0) < 1:
            assertions.append("Observer bulk ingestion did not insert or acknowledge any event")

    for response_name in ("timeline", "agreement", "benchmark", "participant_summary"):
        response = responses[response_name]
        if response.get("http_status") != 200:
            assertions.append(
                f"Expected {response_name} HTTP 200, got HTTP {response.get('http_status')}"
            )

    timeline_payload = responses["timeline"].get("payload")
    if _payload_total(timeline_payload) < 3:
        assertions.append("Observer timeline should contain at least the three QA smoke events")
    if not _contains_event_type(timeline_payload, "MODEL_DETAIL_VIEWED"):
        assertions.append("Observer timeline is missing MODEL_DETAIL_VIEWED")
    if not _contains_event_type(timeline_payload, "MODEL_EXECUTION_COMPLETED"):
        assertions.append("Observer timeline is missing MODEL_EXECUTION_COMPLETED")

    benchmark_payload = responses["benchmark"].get("payload")
    if _payload_total(benchmark_payload) < 1:
        assertions.append("Observer benchmark evidence should contain at least one event")
    if not _contains_event_type(benchmark_payload, "BENCHMARK_STARTED"):
        assertions.append("Observer benchmark evidence is missing BENCHMARK_STARTED")

    summary_payload = responses["participant_summary"].get("payload")
    if not isinstance(summary_payload, dict):
        assertions.append("Observer participant summary should be a JSON object")
    else:
        totals = summary_payload.get("totalsByEventType") or summary_payload.get("totals_by_event_type")
        if not isinstance(totals, dict) or not totals:
            assertions.append("Observer participant summary should expose totals by event type")

    return assertions


def _case_result(
    *,
    status: str,
    assertions: list[str],
    observer_base_url: str,
    run_context: dict[str, Any],
    responses: dict[str, dict[str, Any]],
    skip_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "test_case_id": CASE_ID,
        "description": "Model Observer journal API records and exposes controlled evidence events",
        "type": "api",
        "case_group": "observer",
        "validation_type": "non_functional",
        "dataspace_dimension": "governance",
        "mapping_status": "planned_observer",
        "automation_mode": "api",
        "execution_mode": "api",
        "coverage_status": "automated" if status != "skipped" else "blocked_by_component",
        "observer_base_url": observer_base_url,
        "observed": {
            "run_id": run_context.get("run_id"),
            "asset_id": run_context.get("asset_id"),
            "agreement_id": run_context.get("agreement_id"),
            "benchmark_run_id": run_context.get("benchmark_run_id"),
            "participant_id": run_context.get("participant_id"),
            "endpoint_statuses": {
                key: value.get("http_status") for key, value in responses.items()
            },
        },
        "evaluation": {
            "status": status,
            "assertions": assertions,
        },
        "expected_result": (
            "Observer accepts controlled QA events and returns them by timeline, agreement, benchmark and participant summary"
        ),
        "skip_reason": skip_reason,
    }


def _summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(cases), "passed": 0, "failed": 0, "skipped": 0}
    for case in cases:
        status = ((case.get("evaluation") or {}).get("status") or "").lower()
        if status in summary:
            summary[status] += 1
    return summary


def run_ai_model_hub_model_observer_validation(
    *,
    base_url: str | None = None,
    experiment_dir: str | None = None,
    session: requests.Session | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    started_at = datetime.now().isoformat()
    observer_base_url = resolve_model_observer_api_base_url(base_url)
    active_session = session or requests.Session()
    run_context = build_observer_event_batch(run_id)
    responses: dict[str, dict[str, Any]] = {}

    if not observer_base_url:
        skip_reason = (
            "Model Observer API base URL is not configured. Set AI_MODEL_HUB_OBSERVER_API_BASE_URL "
            "after integrating Edmundo's Observer backend."
        )
        executed_cases = [
            _case_result(
                status="skipped",
                assertions=[],
                observer_base_url="",
                run_context=run_context,
                responses=responses,
                skip_reason=skip_reason,
            )
        ]
    else:
        endpoints = {
            "create_bulk": _build_url(observer_base_url, "/api/model-observer/events/bulk"),
            "timeline": _build_url(observer_base_url, f"/api/model-observer/timeline/{parse.quote(run_context['asset_id'], safe='')}"),
            "agreement": _build_url(observer_base_url, f"/api/model-observer/agreements/{parse.quote(run_context['agreement_id'], safe='')}"),
            "benchmark": _build_url(observer_base_url, f"/api/model-observer/benchmarks/{parse.quote(run_context['benchmark_run_id'], safe='')}"),
            "participant_summary": _build_url(observer_base_url, f"/api/model-observer/participants/{parse.quote(run_context['participant_id'], safe='')}/summary"),
        }
        responses["create_bulk"] = _request_json(
            active_session,
            "POST",
            endpoints["create_bulk"],
            payload=run_context["events"],
        )

        create_status = int(responses["create_bulk"].get("http_status") or 0)
        if create_status in UNAVAILABLE_STATUS_CODES:
            skip_reason = (
                "Model Observer API is not available yet in this environment "
                f"(bulk endpoint returned HTTP {create_status})."
            )
            executed_cases = [
                _case_result(
                    status="skipped",
                    assertions=[],
                    observer_base_url=observer_base_url,
                    run_context=run_context,
                    responses=responses,
                    skip_reason=skip_reason,
                )
            ]
        else:
            for response_name in ("timeline", "agreement", "benchmark", "participant_summary"):
                responses[response_name] = _request_json(active_session, "GET", endpoints[response_name])
            assertions = _validate_observer_responses(responses)
            executed_cases = [
                _case_result(
                    status="failed" if assertions else "passed",
                    assertions=assertions,
                    observer_base_url=observer_base_url,
                    run_context=run_context,
                    responses=responses,
                )
            ]

    summary = _summary(executed_cases)
    suite_status = "failed" if summary["failed"] else "passed" if summary["passed"] else "skipped"
    result: dict[str, Any] = {
        "component": COMPONENT_KEY,
        "suite": SUITE_NAME,
        "status": suite_status,
        "timestamp": started_at,
        "observer_base_url": observer_base_url,
        "summary": summary,
        "executed_cases": executed_cases,
        "run_context": {
            key: run_context[key]
            for key in ("run_id", "asset_id", "agreement_id", "benchmark_run_id", "participant_id", "correlation_id")
        },
        "responses": responses,
        "evidence_index": [],
        "artifacts": {},
    }

    component_dir = _component_dir(experiment_dir)
    if component_dir:
        report_path = os.path.join(component_dir, "ai_model_hub_model_observer_api.json")
        responses_path = os.path.join(component_dir, "ai_model_hub_model_observer_api_responses.json")
        _write_json(responses_path, {"responses": responses})
        result["artifacts"] = {
            "report_json": report_path,
            "responses_json": responses_path,
        }
        result["evidence_index"] = [
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "report_json",
                "path": report_path,
            },
            {
                "scope": "suite",
                "suite": SUITE_NAME,
                "artifact_name": "responses_json",
                "path": responses_path,
            },
        ]
        _write_json(report_path, result)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MH-OBS-02 AI Model Hub Model Observer API validation.")
    parser.add_argument("--base-url", default=None, help="Observer API base URL, for example http://backend-demo.dev.ds.dataspaceunit.upm")
    parser.add_argument("--experiment-dir", default=None, help="Experiment directory where JSON evidence will be written.")
    args = parser.parse_args()

    experiment_dir = args.experiment_dir or _default_experiment_dir()
    result = run_ai_model_hub_model_observer_validation(
        base_url=args.base_url,
        experiment_dir=experiment_dir,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
