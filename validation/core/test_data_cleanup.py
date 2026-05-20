from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests


EDC_VOCAB = "https://w3id.org/edc/v0.0.1/ns/"
DEFAULT_QUERY_LIMIT = 100
DEFAULT_MAX_PAGES = 50
DEFAULT_MANAGEMENT_TRANSIENT_RETRIES = 6
DEFAULT_MANAGEMENT_TRANSIENT_RETRY_DELAY = 5.0
TRANSIENT_MANAGEMENT_STATUS_CODES = {502, 503, 504}
AUTHENTICATION_STATUS_CODES = {401, 403}
SUPPORTED_MODES = {"safe", "dry-run", "aggressive"}
SAFE_TEST_OBJECT_PREFIXES = (
    "todos-",
    "playwright-e2e/",
    "playwright-edc-",
    "playwright-edc-storage-",
)

ENTITY_DEFINITIONS = {
    "contract_definitions": {
        "request_path": "/contractdefinitions/request",
        "delete_path": "/contractdefinitions/{entity_id}",
    },
    "policies": {
        "request_path": "/policydefinitions/request",
        "delete_path": "/policydefinitions/{entity_id}",
    },
    "assets": {
        "request_path": "/assets/request",
        "delete_path": "/assets/{entity_id}",
    },
}
ENTITY_ORDER = ("contract_definitions", "policies", "assets")
REFERENCE_ENTITY_DEFINITIONS = {
    "contract_definitions": {
        "request_path": "/contractdefinitions/request",
    },
    "contract_negotiations": {
        "request_path": "/contractnegotiations/request",
    },
    "transfer_processes": {
        "request_path": "/transferprocesses/request",
    },
    "contract_agreements": {
        "request_path": "/contractagreements/request",
    },
}

SAFE_TEST_ID_PREFIXES = {
    "contract_definitions": (
        "contract-crud-",
        "contract-e2e-",
        "contract-ui-",
        "qa-ui-contract-definition-",
        "qa-edc-contract-",
        "playwright-edc-contract-",
    ),
    "policies": (
        "policy-crud-",
        "policy-e2e-",
        "policy-ui-",
        "qa-ui-policy-",
        "qa-ui-contract-policy-",
        "qa-edc-policy-",
        "playwright-edc-policy-",
    ),
    "assets": (
        "asset-crud-",
        "asset-e2e-",
        "qa-ui-asset-",
        "qa-ui-contract-asset-",
        "qa-ui-negotiation-",
        "qa-ui-sv-httpdata-",
        "qa-ui-transfer-",
        "qa-ui-edc-",
        "qa-edc-",
        "playwright-e2e",
        "playwright-edc-",
        "playwright-edc-storage-",
    ),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_cleanup_mode(mode: str | None) -> str:
    normalized = str(mode or "safe").strip().lower() or "safe"
    if normalized not in SUPPORTED_MODES:
        supported = ", ".join(sorted(SUPPORTED_MODES))
        raise ValueError(f"Unsupported test data cleanup mode '{mode}'. Supported modes: {supported}")
    return normalized


def normalize_base_url(value: str | None) -> str:
    normalized = str(value or "").strip().rstrip("/")
    if not normalized:
        return ""
    if not normalized.startswith(("http://", "https://")):
        normalized = f"http://{normalized}"
    return normalized


def extract_entity_id(entity: Any) -> str | None:
    if not isinstance(entity, dict):
        return None

    candidate_keys = (
        "@id",
        "id",
        "assetId",
        "policyId",
        "contractDefinitionId",
        f"{EDC_VOCAB}id",
    )
    for key in candidate_keys:
        value = entity.get(key)
        if value not in (None, ""):
            return str(value)

    properties = entity.get("properties")
    if isinstance(properties, dict):
        for key in ("id", f"{EDC_VOCAB}id"):
            value = properties.get(key)
            if value not in (None, ""):
                return str(value)

    return None


def iter_entities(payload: Any):
    if isinstance(payload, list):
        yield from payload
        return

    if not isinstance(payload, dict):
        return

    for key in ("@graph", "items", "results", "data", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            yield from value
            return

    if extract_entity_id(payload):
        yield payload


def is_safe_test_entity_id(entity_id: str, entity_kind: str, prefixes: dict[str, tuple[str, ...]] | None = None) -> bool:
    configured_prefixes = prefixes or SAFE_TEST_ID_PREFIXES
    return str(entity_id or "").startswith(tuple(configured_prefixes.get(entity_kind, ())))


def build_cleanup_plan(
    inventory: dict[str, list[Any]],
    mode: str = "safe",
    prefixes: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, list[str]]:
    normalized_mode = normalize_cleanup_mode(mode)
    plan: dict[str, list[str]] = {entity_kind: [] for entity_kind in ENTITY_ORDER}

    for entity_kind in ENTITY_ORDER:
        seen = set()
        for entity in inventory.get(entity_kind, []) or []:
            entity_id = extract_entity_id(entity)
            if not entity_id or entity_id in seen:
                continue
            seen.add(entity_id)
            if normalized_mode == "aggressive" or is_safe_test_entity_id(entity_id, entity_kind, prefixes=prefixes):
                plan[entity_kind].append(entity_id)

    return plan


class ManagementApiTestDataCleaner:
    def __init__(
        self,
        *,
        adapter: Any,
        context: Any,
        connectors: list[str],
        experiment_dir: str | None = None,
        mode: str = "safe",
        session: Any = None,
        minio_client_factory: Any = None,
        report_enabled: bool = True,
        query_limit: int = DEFAULT_QUERY_LIMIT,
        max_pages: int = DEFAULT_MAX_PAGES,
        auth_retries: int = 2,
        auth_retry_delay: float = 2.0,
        management_transient_retries: int = DEFAULT_MANAGEMENT_TRANSIENT_RETRIES,
        management_transient_retry_delay: float = DEFAULT_MANAGEMENT_TRANSIENT_RETRY_DELAY,
    ):
        self.adapter = adapter
        self.context = context
        self.connectors = list(connectors or [])
        self.experiment_dir = experiment_dir
        self.mode = normalize_cleanup_mode(mode)
        self.session = session or requests.Session()
        self.minio_client_factory = minio_client_factory
        self.report_enabled = report_enabled
        self.query_limit = max(int(query_limit or DEFAULT_QUERY_LIMIT), 1)
        self.max_pages = max(int(max_pages or DEFAULT_MAX_PAGES), 1)
        self.auth_retries = max(int(auth_retries or 0), 0)
        self.auth_retry_delay = max(float(auth_retry_delay or 0), 0.0)
        self.management_transient_retries = max(int(management_transient_retries or 0), 0)
        self.management_transient_retry_delay = max(float(management_transient_retry_delay or 0), 0.0)
        self.config = self._load_config()
        self.dataspace = str(getattr(context, "dataspace_name", "") or self.config.get("DS_1_NAME") or "").strip()
        self.ds_domain_base = str(getattr(context, "ds_domain_base", "") or self._resolve_adapter_domain() or "").strip()
        self.adapter_name = str(getattr(context, "deployer", "") or self.config.get("PIONERA_ADAPTER") or "").strip()

        if self.mode == "aggressive" and not self._allow_aggressive_cleanup():
            raise RuntimeError(
                "PIONERA_TEST_DATA_CLEANUP_MODE=aggressive requires "
                "PIONERA_TEST_DATA_CLEANUP_ALLOW_AGGRESSIVE=true."
            )

    def run(self) -> dict[str, Any]:
        report = {
            "status": "running",
            "adapter": self.adapter_name or type(self.adapter).__name__,
            "dataspace": self.dataspace,
            "mode": self.mode,
            "started_at": utc_now_iso(),
            "finished_at": None,
            "connectors": [],
            "summary": {
                "planned_total": 0,
                "deleted_total": 0,
                "skipped_total": 0,
                "error_total": 0,
                "storage_planned_total": 0,
                "storage_deleted_total": 0,
                "storage_skipped_total": 0,
                "storage_error_total": 0,
                "conflict_total": 0,
            },
        }

        for connector in self.connectors:
            connector_report = self._run_connector(connector)
            report["connectors"].append(connector_report)
            self._add_summary(report["summary"], connector_report)

        report["finished_at"] = utc_now_iso()
        report["status"] = "failed" if report["summary"]["error_total"] else "completed"
        self._persist_report(report)
        return report

    def _run_connector(self, connector: str) -> dict[str, Any]:
        connector_report = {
            "name": connector,
            "management_base_url": "",
            "planned": {entity_kind: [] for entity_kind in ENTITY_ORDER},
            "deleted": {entity_kind: [] for entity_kind in ENTITY_ORDER},
            "skipped": [],
            "skipped_counts": {entity_kind: 0 for entity_kind in ENTITY_ORDER},
            "unplanned_counts": {entity_kind: 0 for entity_kind in ENTITY_ORDER},
            "conflict_summary": {
                "total": 0,
                "by_entity_kind": {},
                "by_reference_kind": {},
                "by_reference_state": {},
                "sample_ids_by_entity_kind": {},
                "remediation": [],
            },
            "storage": {
                "bucket_name": self._bucket_name(connector),
                "planned": [],
                "deleted": [],
                "skipped": [],
                "errors": [],
            },
            "errors": [],
        }

        try:
            connector_report["management_base_url"] = self._management_base_url(connector)
            token, inventory = self._load_inventory_with_auth_retry(
                connector,
                connector_report["management_base_url"],
            )
            plan = build_cleanup_plan(inventory, mode=self.mode)
            connector_report["planned"] = plan
            self._record_unsafe_counts(connector_report, inventory, plan)
            self._execute_plan(connector_report, connector, token, plan)
            self._cleanup_storage_objects(connector, connector_report["storage"])
        except Exception as exc:
            connector_report["errors"].append(
                {
                    "action": "connector-cleanup",
                    "message": str(exc),
                }
            )
            try:
                self._cleanup_storage_objects(connector, connector_report["storage"])
            except Exception as storage_exc:
                connector_report["storage"]["errors"].append(
                    {
                        "action": "storage-cleanup",
                        "message": str(storage_exc),
                    }
                )

        self._record_skipped_counts(connector_report)
        self._record_conflict_summary(connector_report)
        return connector_report

    def _load_inventory_with_auth_retry(
        self,
        connector: str,
        management_base_url: str,
    ) -> tuple[str, dict[str, list[Any]]]:
        last_error = None
        for attempt in range(self.auth_retries + 1):
            token = self._issue_token(connector)
            try:
                return token, self._load_inventory(management_base_url, token)
            except RuntimeError as exc:
                last_error = exc
                if not self._is_authentication_error(exc) or attempt >= self.auth_retries:
                    raise
                if self.auth_retry_delay:
                    time.sleep(self.auth_retry_delay)

        raise last_error or RuntimeError(f"Could not load cleanup inventory for {connector}")

    def _load_inventory(self, management_base_url: str, token: str) -> dict[str, list[Any]]:
        inventory: dict[str, list[Any]] = {entity_kind: [] for entity_kind in ENTITY_ORDER}
        for entity_kind in ENTITY_ORDER:
            inventory[entity_kind] = self._list_entities(management_base_url, token, entity_kind)
        return inventory

    def _list_entities(self, management_base_url: str, token: str, entity_kind: str) -> list[Any]:
        definition = ENTITY_DEFINITIONS[entity_kind]
        return self._list_entities_by_path(management_base_url, token, entity_kind, definition["request_path"])

    def _list_entities_by_path(
        self,
        management_base_url: str,
        token: str,
        entity_kind: str,
        request_path: str,
    ) -> list[Any]:
        entities = []
        seen_ids = set()

        for page_index in range(self.max_pages):
            offset = page_index * self.query_limit
            payload = {
                "@context": {
                    "@vocab": EDC_VOCAB,
                },
                "offset": offset,
                "limit": self.query_limit,
                "filterExpression": [],
            }
            label = f"List {entity_kind}"
            response = self._post_management_with_transient_retry(
                f"{management_base_url}{request_path}",
                label=label,
                headers=self._json_headers(token),
                json=payload,
                timeout=30,
            )
            self._assert_status(response, {200}, label)
            page_entities = list(iter_entities(self._json_body(response, label)))
            if not page_entities:
                break

            new_entities = []
            for entity in page_entities:
                entity_id = extract_entity_id(entity)
                if entity_id and entity_id in seen_ids:
                    continue
                if entity_id:
                    seen_ids.add(entity_id)
                new_entities.append(entity)

            if not new_entities:
                break
            entities.extend(new_entities)
            if len(page_entities) < self.query_limit:
                break

        return entities

    def _execute_plan(
        self,
        connector_report: dict[str, Any],
        connector: str,
        token: str,
        plan: dict[str, list[str]],
    ) -> None:
        if self.mode == "dry-run":
            return

        management_base_url = connector_report["management_base_url"]
        current_token = token
        reference_inventory = None
        reference_errors = None
        for entity_kind in ENTITY_ORDER:
            definition = ENTITY_DEFINITIONS[entity_kind]
            for entity_id in plan.get(entity_kind, []) or []:
                delete_path = definition["delete_path"].format(entity_id=quote(entity_id, safe=""))
                response, current_token = self._delete_management_with_auth_retry(
                    connector,
                    f"{management_base_url}{delete_path}",
                    current_token,
                )
                if response.status_code in {200, 204}:
                    connector_report["deleted"][entity_kind].append(entity_id)
                    continue
                if response.status_code == 404:
                    connector_report["skipped"].append(
                        {
                            "entity_kind": entity_kind,
                            "id": entity_id,
                            "reason": "not-found",
                            "status_code": response.status_code,
                        }
                    )
                    continue
                if response.status_code == 409:
                    if reference_inventory is None:
                        reference_inventory, reference_errors, current_token = self._load_reference_inventory(
                            connector,
                            management_base_url,
                            current_token,
                        )
                    skipped_entry = {
                        "entity_kind": entity_kind,
                        "id": entity_id,
                        "reason": "conflict",
                        "status_code": response.status_code,
                        "message": self._response_text(response),
                        "references": self._find_entity_references(entity_id, reference_inventory),
                    }
                    if reference_errors:
                        skipped_entry["reference_errors"] = reference_errors
                    connector_report["skipped"].append(
                        skipped_entry
                    )
                    continue
                connector_report["errors"].append(
                    {
                        "action": "delete",
                        "entity_kind": entity_kind,
                        "id": entity_id,
                        "status_code": response.status_code,
                        "message": self._response_text(response),
                    }
                )

    def _load_reference_inventory(
        self,
        connector: str,
        management_base_url: str,
        token: str,
    ) -> tuple[dict[str, list[Any]], dict[str, str], str]:
        inventory: dict[str, list[Any]] = {}
        errors: dict[str, str] = {}
        current_token = token
        for entity_kind, definition in REFERENCE_ENTITY_DEFINITIONS.items():
            try:
                current_token, inventory[entity_kind] = self._list_entities_by_path_with_auth_retry(
                    connector,
                    management_base_url,
                    current_token,
                    entity_kind,
                    definition["request_path"],
                )
            except Exception as exc:
                inventory[entity_kind] = []
                errors[entity_kind] = str(exc)
        return inventory, errors, current_token

    def _list_entities_by_path_with_auth_retry(
        self,
        connector: str,
        management_base_url: str,
        token: str,
        entity_kind: str,
        request_path: str,
    ) -> tuple[str, list[Any]]:
        current_token = token
        last_error = None
        for attempt in range(self.auth_retries + 1):
            try:
                return current_token, self._list_entities_by_path(
                    management_base_url,
                    current_token,
                    entity_kind,
                    request_path,
                )
            except RuntimeError as exc:
                last_error = exc
                if not self._is_authentication_error(exc) or attempt >= self.auth_retries:
                    raise
                current_token = self._issue_token(connector)
                if self.auth_retry_delay:
                    time.sleep(self.auth_retry_delay)

        raise last_error or RuntimeError(f"Could not list cleanup references for {connector}")

    def _delete_management_with_auth_retry(self, connector: str, url: str, token: str) -> tuple[Any, str]:
        current_token = token
        response = None
        for attempt in range(self.auth_retries + 1):
            response = self.session.delete(
                url,
                headers=self._json_headers(current_token),
                timeout=30,
            )
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code not in AUTHENTICATION_STATUS_CODES:
                return response, current_token
            if attempt >= self.auth_retries:
                return response, current_token
            current_token = self._issue_token(connector)
            if self.auth_retry_delay:
                time.sleep(self.auth_retry_delay)

        return response, current_token

    @staticmethod
    def _find_entity_references(entity_id: str, reference_inventory: dict[str, list[Any]]) -> list[dict[str, Any]]:
        references = []
        for entity_kind, entities in (reference_inventory or {}).items():
            for entity in entities or []:
                if not isinstance(entity, dict):
                    continue
                if str(entity_id) not in json.dumps(entity, sort_keys=True):
                    continue
                references.append(
                    {
                        "kind": entity_kind,
                        "id": extract_entity_id(entity),
                        "state": entity.get("state"),
                        "type": entity.get("@type"),
                    }
                )
        return references[:20]

    def _record_unsafe_counts(
        self,
        connector_report: dict[str, Any],
        inventory: dict[str, list[Any]],
        plan: dict[str, list[str]],
    ) -> None:
        for entity_kind in ENTITY_ORDER:
            planned = set(plan.get(entity_kind, []) or [])
            unsafe_count = 0
            for entity in inventory.get(entity_kind, []) or []:
                entity_id = extract_entity_id(entity)
                if entity_id and entity_id not in planned:
                    unsafe_count += 1
            connector_report["unplanned_counts"][entity_kind] = unsafe_count

    @staticmethod
    def _record_skipped_counts(connector_report: dict[str, Any]) -> None:
        counts = {entity_kind: 0 for entity_kind in ENTITY_ORDER}
        for skipped in connector_report.get("skipped", []) or []:
            entity_kind = skipped.get("entity_kind")
            if entity_kind in counts:
                counts[entity_kind] += 1
        connector_report["skipped_counts"] = counts

    @staticmethod
    def _record_conflict_summary(connector_report: dict[str, Any]) -> None:
        summary = {
            "total": 0,
            "by_entity_kind": {},
            "by_reference_kind": {},
            "by_reference_state": {},
            "sample_ids_by_entity_kind": {},
            "remediation": [],
        }

        for skipped in connector_report.get("skipped", []) or []:
            if skipped.get("reason") != "conflict":
                continue

            entity_kind = str(skipped.get("entity_kind") or "unknown")
            entity_id = str(skipped.get("id") or "")
            summary["total"] += 1
            summary["by_entity_kind"][entity_kind] = summary["by_entity_kind"].get(entity_kind, 0) + 1

            samples = summary["sample_ids_by_entity_kind"].setdefault(entity_kind, [])
            if entity_id and len(samples) < 10:
                samples.append(entity_id)

            for reference in skipped.get("references", []) or []:
                reference_kind = str(reference.get("kind") or "unknown")
                reference_state = str(reference.get("state") or "unknown")
                summary["by_reference_kind"][reference_kind] = (
                    summary["by_reference_kind"].get(reference_kind, 0) + 1
                )
                state_key = f"{reference_kind}:{reference_state}"
                summary["by_reference_state"][state_key] = (
                    summary["by_reference_state"].get(state_key, 0) + 1
                )

        if summary["total"]:
            if summary["by_reference_kind"].get("contract_agreements"):
                summary["remediation"].append(
                    "Assets referenced by contract agreements are preserved by safe cleanup."
                )
            if summary["by_reference_kind"].get("contract_negotiations"):
                summary["remediation"].append(
                    "Review finalized negotiations before considering deeper cleanup."
                )
            if summary["by_reference_kind"].get("transfer_processes"):
                summary["remediation"].append(
                    "Transfer process references should be handled by connector-supported lifecycle actions."
                )

        connector_report["conflict_summary"] = summary

    def _issue_token(self, connector: str) -> str:
        credentials = self._load_connector_credentials(connector)
        connector_user = credentials.get("connector_user") if isinstance(credentials, dict) else {}
        username = (connector_user or {}).get("user")
        password = (connector_user or {}).get("passwd")
        if not username or not password:
            raise RuntimeError(f"Missing connector_user credentials for {connector}")

        keycloak_urls = self._keycloak_token_base_urls()
        if not keycloak_urls:
            raise RuntimeError("Missing KC_INTERNAL_URL/KC_URL/KEYCLOAK_HOSTNAME in deployer config")
        if not self.dataspace:
            raise RuntimeError("Missing dataspace name for test data cleanup")

        last_error = None
        for keycloak_url in keycloak_urls:
            token_url = f"{keycloak_url}/realms/{self.dataspace}/protocol/openid-connect/token"
            try:
                response = self.session.post(
                    token_url,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "password",
                        "client_id": self.config.get("EDC_DASHBOARD_PROXY_CLIENT_ID") or "dataspace-users",
                        "username": username,
                        "password": password,
                        "scope": self.config.get("EDC_DASHBOARD_PROXY_SCOPE") or "openid profile email",
                    },
                    timeout=30,
                )
                self._assert_status(response, {200}, f"Token request for {connector}")
                body = self._json_body(response, f"Token request for {connector}")
                token = body.get("access_token") if isinstance(body, dict) else None
                if token:
                    return str(token)
                last_error = f"Token request for {connector} did not return access_token"
            except Exception as exc:
                last_error = str(exc)
                continue

        raise RuntimeError(f"Token request for {connector} failed: {last_error}")

    def _keycloak_token_base_urls(self) -> list[str]:
        candidates = []
        for key in ("KC_INTERNAL_URL", "KC_URL", "KEYCLOAK_HOSTNAME"):
            value = self.config.get(key)
            if value:
                candidates.append(value)

        urls = []
        seen = set()
        for candidate in candidates:
            normalized = normalize_base_url(candidate)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)
        return urls

    def _load_connector_credentials(self, connector: str) -> dict[str, Any]:
        credentials_loader = self._resolve_callable(
            "connectors.load_connector_credentials",
            "load_connector_credentials",
        )
        if not callable(credentials_loader):
            raise RuntimeError("Selected adapter does not expose load_connector_credentials")

        credentials = credentials_loader(connector) or {}
        return credentials if isinstance(credentials, dict) else {}

    def _bucket_name(self, connector: str) -> str:
        if not self.dataspace:
            return ""
        return f"{self.dataspace}-{connector}"

    def _cleanup_storage_objects(self, connector: str, storage_report: dict[str, Any]) -> None:
        bucket_name = storage_report.get("bucket_name") or self._bucket_name(connector)
        storage_report["bucket_name"] = bucket_name
        if not bucket_name:
            storage_report["skipped"].append({"reason": "missing-bucket-name"})
            return

        try:
            client = self._build_minio_client(connector)
        except RuntimeError as exc:
            storage_report["skipped"].append({"reason": str(exc)})
            return
        except Exception as exc:
            storage_report["errors"].append(
                {
                    "action": "build-minio-client",
                    "bucket_name": bucket_name,
                    "message": str(exc),
                }
            )
            return

        try:
            objects = self._list_storage_objects(client, bucket_name)
        except Exception as exc:
            storage_report["errors"].append(
                {
                    "action": "list-objects",
                    "bucket_name": bucket_name,
                    "message": str(exc),
                }
            )
            return
        planned = [
            object_name
            for object_name in objects
            if self.mode == "aggressive" or self._is_safe_test_object(object_name)
        ]
        storage_report["planned"] = planned

        if self.mode == "dry-run":
            return

        for object_name in planned:
            try:
                client.remove_object(bucket_name, object_name)
            except Exception as exc:
                storage_report["errors"].append(
                    {
                        "action": "delete-object",
                        "bucket_name": bucket_name,
                        "object_name": object_name,
                        "message": str(exc),
                    }
                )
                continue
            storage_report["deleted"].append(object_name)

    def _build_minio_client(self, connector: str):
        credentials = self._load_connector_credentials(connector)
        minio_credentials = credentials.get("minio") if isinstance(credentials, dict) else {}
        access_key = (minio_credentials or {}).get("access_key")
        secret_key = (minio_credentials or {}).get("secret_key")
        if not access_key or not secret_key:
            raise RuntimeError(f"missing-minio-credentials:{connector}")

        runtime = self._resolve_minio_runtime()
        if self.minio_client_factory is not None:
            return self.minio_client_factory(
                connector=connector,
                access_key=access_key,
                secret_key=secret_key,
                runtime=runtime,
            )

        endpoint = runtime["host"]
        if runtime["port"] not in (80, 443):
            endpoint = f"{endpoint}:{runtime['port']}"

        from minio import Minio

        return Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=runtime["secure"],
        )

    def _resolve_minio_runtime(self) -> dict[str, Any]:
        endpoint = self.config.get("MINIO_ENDPOINT")
        hostname = self.config.get("MINIO_HOSTNAME")

        if endpoint:
            parsed_endpoint = normalize_base_url(str(endpoint))
            from urllib.parse import urlparse

            parsed = urlparse(parsed_endpoint)
            return {
                "host": parsed.hostname,
                "port": parsed.port or (443 if parsed.scheme == "https" else 80),
                "secure": parsed.scheme == "https",
            }

        if hostname:
            parsed_hostname = str(hostname)
            from urllib.parse import urlparse

            if "://" in parsed_hostname:
                parsed = urlparse(parsed_hostname)
                return {
                    "host": parsed.hostname,
                    "port": parsed.port or (443 if parsed.scheme == "https" else 80),
                    "secure": parsed.scheme == "https",
                }
            return {"host": parsed_hostname, "port": 80, "secure": False}

        if self.ds_domain_base:
            return {"host": f"minio.{self.ds_domain_base}", "port": 80, "secure": False}

        raise RuntimeError("missing-minio-endpoint")

    @staticmethod
    def _list_storage_objects(client: Any, bucket_name: str) -> list[str]:
        return [
            str(getattr(item, "object_name", "") or "")
            for item in client.list_objects(bucket_name, recursive=True)
            if getattr(item, "object_name", None)
        ]

    @staticmethod
    def _is_safe_test_object(object_name: str) -> bool:
        return str(object_name or "").startswith(SAFE_TEST_OBJECT_PREFIXES)

    def _management_base_url(self, connector: str) -> str:
        if not self.ds_domain_base:
            raise RuntimeError("Missing ds_domain_base for test data cleanup")
        return f"http://{connector}.{self.ds_domain_base}/management/v3"

    def _load_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {}
        loader = self._resolve_callable(
            "config_adapter.load_deployer_config",
            "load_deployer_config",
        )
        if callable(loader):
            loaded = loader() or {}
            if isinstance(loaded, dict):
                config.update(loaded)

        context_config = getattr(self.context, "config", None)
        if isinstance(context_config, dict):
            config.update(context_config)
        return config

    def _resolve_adapter_domain(self) -> str:
        resolver = self._resolve_callable(
            "config_adapter.ds_domain_base",
            "config.ds_domain_base",
            "ds_domain_base",
        )
        if callable(resolver):
            return str(resolver() or "")
        return ""

    def _resolve_callable(self, *paths: str):
        for path in paths:
            current = self.adapter
            try:
                for attribute in path.split("."):
                    current = getattr(current, attribute)
            except AttributeError:
                continue
            if callable(current):
                return current
        return None

    @staticmethod
    def _json_headers(token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _json_body(response: Any, label: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"{label} did not return valid JSON") from exc

    @staticmethod
    def _response_text(response: Any) -> str:
        return str(getattr(response, "text", "") or "")[:500]

    def _post_management_with_transient_retry(self, url: str, *, label: str, **kwargs: Any) -> Any:
        last_error = None
        attempts = self.management_transient_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.post(url, **kwargs)
            except requests.RequestException as exc:
                last_error = str(exc)
                should_retry = attempt < attempts
            else:
                status_code = int(getattr(response, "status_code", 0) or 0)
                if status_code not in TRANSIENT_MANAGEMENT_STATUS_CODES:
                    return response
                last_error = f"HTTP {status_code}: {self._response_text(response)}"
                should_retry = attempt < attempts

            if not should_retry:
                break
            if self.management_transient_retry_delay:
                time.sleep(self.management_transient_retry_delay)

        raise RuntimeError(f"{label} failed after transient management retries: {last_error}")

    def _assert_status(self, response: Any, expected_codes: set[int], label: str) -> None:
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code not in expected_codes:
            raise RuntimeError(f"{label} failed with HTTP {status_code}: {self._response_text(response)}")

    @staticmethod
    def _is_authentication_error(exc: Exception) -> bool:
        message = str(exc)
        return any(f"HTTP {status_code}" in message for status_code in AUTHENTICATION_STATUS_CODES)

    @staticmethod
    def _allow_aggressive_cleanup() -> bool:
        return str(os.getenv("PIONERA_TEST_DATA_CLEANUP_ALLOW_AGGRESSIVE", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _add_summary(summary: dict[str, int], connector_report: dict[str, Any]) -> None:
        summary["planned_total"] += sum(len(values) for values in connector_report.get("planned", {}).values())
        summary["deleted_total"] += sum(len(values) for values in connector_report.get("deleted", {}).values())
        summary["skipped_total"] += len(connector_report.get("skipped", []) or [])
        summary["error_total"] += len(connector_report.get("errors", []) or [])
        storage_report = connector_report.get("storage", {}) or {}
        storage_errors = len(storage_report.get("errors", []) or [])
        conflict_summary = connector_report.get("conflict_summary", {}) or {}
        summary["storage_planned_total"] += len(storage_report.get("planned", []) or [])
        summary["storage_deleted_total"] += len(storage_report.get("deleted", []) or [])
        summary["storage_skipped_total"] += len(storage_report.get("skipped", []) or [])
        summary["storage_error_total"] += storage_errors
        summary["error_total"] += storage_errors
        summary["conflict_total"] += int(conflict_summary.get("total", 0) or 0)

    def _persist_report(self, report: dict[str, Any]) -> None:
        if not self.report_enabled or not self.experiment_dir:
            return
        cleanup_dir = os.path.join(self.experiment_dir, "cleanup")
        os.makedirs(cleanup_dir, exist_ok=True)
        report_path = os.path.join(cleanup_dir, "test_data_cleanup.json")
        report["report_path"] = report_path
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)


def run_pre_validation_cleanup(
    *,
    adapter: Any,
    context: Any,
    connectors: list[str],
    experiment_dir: str | None,
    mode: str = "safe",
    session: Any = None,
    minio_client_factory: Any = None,
    report_enabled: bool = True,
    management_transient_retries: int = DEFAULT_MANAGEMENT_TRANSIENT_RETRIES,
    management_transient_retry_delay: float = DEFAULT_MANAGEMENT_TRANSIENT_RETRY_DELAY,
) -> dict[str, Any]:
    cleaner = ManagementApiTestDataCleaner(
        adapter=adapter,
        context=context,
        connectors=connectors,
        experiment_dir=experiment_dir,
        mode=mode,
        session=session,
        minio_client_factory=minio_client_factory,
        report_enabled=report_enabled,
        management_transient_retries=management_transient_retries,
        management_transient_retry_delay=management_transient_retry_delay,
    )
    return cleaner.run()
