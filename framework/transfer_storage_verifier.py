import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse


class TransferStorageVerifier:
    """Validate that a successful transfer produces observable objects in MinIO."""

    SENSITIVE_DESTINATION_KEYWORDS = (
        "accesskey",
        "secret",
        "password",
        "passwd",
        "token",
        "privatekey",
    )

    def __init__(
        self,
        load_connector_credentials=None,
        load_deployer_config=None,
        experiment_storage=None,
        poll_attempts=60,
        poll_interval_seconds=2.0,
    ):
        self.load_connector_credentials = load_connector_credentials
        self.load_deployer_config = load_deployer_config
        self.experiment_storage = experiment_storage
        self.poll_attempts = max(1, int(poll_attempts or 1))
        self.poll_interval_seconds = max(0.0, float(poll_interval_seconds or 0.0))

    @staticmethod
    def _parse_iso_datetime(value):
        if not value or not isinstance(value, str):
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    @staticmethod
    def _parse_epoch_millis(value):
        if value in (None, ""):
            return None
        try:
            millis = float(value)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc)

    @staticmethod
    def _read_field(obj, field_name):
        if not isinstance(obj, dict):
            return None
        namespaced = f"https://w3id.org/edc/v0.0.1/ns/{field_name}"
        if field_name in obj:
            return obj[field_name]
        if namespaced in obj:
            return obj[namespaced]
        properties = obj.get("properties")
        if isinstance(properties, dict):
            if field_name in properties:
                return properties[field_name]
            if namespaced in properties:
                return properties[namespaced]
        return None

    @classmethod
    def _redact_sensitive_fields(cls, value):
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                normalized = str(key or "").replace("_", "").replace("-", "").lower()
                if any(marker in normalized for marker in cls.SENSITIVE_DESTINATION_KEYWORDS):
                    redacted[key] = "***REDACTED***"
                else:
                    redacted[key] = cls._redact_sensitive_fields(item)
            return redacted
        if isinstance(value, list):
            return [cls._redact_sensitive_fields(item) for item in value]
        return value

    @staticmethod
    def _decode_response_json(execution):
        response = execution.get("response", {}) or {}
        stream = response.get("stream")
        if isinstance(stream, dict) and stream.get("type") == "Buffer":
            data = stream.get("data") or []
        elif isinstance(stream, list):
            data = stream
        else:
            return None

        try:
            text = bytes(data).decode("utf-8", errors="replace")
            return json.loads(text)
        except (ValueError, TypeError):
            return None

    def _resolve_minio_runtime(self):
        if not callable(self.load_deployer_config):
            raise RuntimeError("Missing load_deployer_config dependency")

        config = self.load_deployer_config() or {}
        endpoint = config.get("MINIO_ENDPOINT")
        hostname = config.get("MINIO_HOSTNAME")

        if endpoint:
            if "://" not in endpoint:
                endpoint = f"http://{endpoint}"
            parsed = urlparse(endpoint)
            return {
                "host": parsed.hostname,
                "port": parsed.port or (443 if parsed.scheme == "https" else 80),
                "secure": parsed.scheme == "https",
            }

        if hostname:
            if "://" in hostname:
                parsed = urlparse(hostname)
                return {
                    "host": parsed.hostname,
                    "port": parsed.port or (443 if parsed.scheme == "https" else 80),
                    "secure": parsed.scheme == "https",
                }
            return {"host": hostname, "port": 80, "secure": False}

        domain_base = config.get("DOMAIN_BASE")
        if domain_base:
            return {"host": f"minio.{domain_base}", "port": 80, "secure": False}

        raise RuntimeError("Cannot resolve MinIO endpoint from deployer.config")

    def _build_minio_client(self, connector_name):
        if not callable(self.load_connector_credentials):
            raise RuntimeError("Missing load_connector_credentials dependency")

        credentials = self.load_connector_credentials(connector_name) or {}
        minio_credentials = credentials.get("minio") or {}
        access_key = minio_credentials.get("access_key")
        secret_key = minio_credentials.get("secret_key")

        if not access_key or not secret_key:
            raise RuntimeError(f"Missing MinIO access credentials for connector {connector_name}")

        runtime = self._resolve_minio_runtime()
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

    def capture_consumer_bucket_snapshot(self, consumer_connector, bucket_name):
        client = self._build_minio_client(consumer_connector)
        snapshot = {}
        for obj in client.list_objects(bucket_name, recursive=True):
            snapshot[obj.object_name] = {
                "etag": obj.etag,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
            }
        return snapshot

    def _parse_transfer_report(self, report_path):
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)

        start_execution = None
        destination_execution = None
        for execution in report.get("run", {}).get("executions", []) or []:
            request_name = ((execution.get("item") or {}).get("name")) or ""
            if request_name == "Start Transfer Process":
                start_execution = execution
            elif request_name == "Resolve Current Transfer Destination":
                destination_execution = execution

        if start_execution is None:
            raise RuntimeError("Start Transfer Process execution not found in 06_consumer_transfer report")

        start_body = self._decode_response_json(start_execution) or {}
        transfer_id = start_body.get("@id") or start_body.get("id")
        started_at = self._parse_iso_datetime(((start_execution.get("cursor") or {}).get("started")))
        if started_at is None:
            started_at = self._parse_epoch_millis(start_body.get("createdAt"))

        resolved_transfer = None
        if destination_execution is not None:
            destination_body = self._decode_response_json(destination_execution)
            if isinstance(destination_body, list):
                resolved_transfer = next(
                    (
                        item for item in destination_body
                        if isinstance(item, dict) and (item.get("@id") == transfer_id or item.get("id") == transfer_id)
                    ),
                    None,
                )
            elif isinstance(destination_body, dict):
                resolved_transfer = destination_body

        data_destination = None
        if resolved_transfer:
            data_destination = (
                self._read_field(resolved_transfer, "dataDestination")
                or resolved_transfer.get("dataDestination")
            )

        return {
            "transfer_id": transfer_id,
            "started_at": started_at,
            "resolved_transfer": resolved_transfer,
            "data_destination": data_destination,
            "failures": report.get("run", {}).get("failures", []) or [],
        }

    def _parse_expected_object_name(self, report_dir):
        report_path = os.path.join(report_dir, "03_provider_setup.json")
        if not os.path.exists(report_path):
            return None

        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError):
            return None

        for execution in report.get("run", {}).get("executions", []) or []:
            request_name = ((execution.get("item") or {}).get("name")) or ""
            if request_name != "Create E2E Asset":
                continue

            body = ((execution.get("request") or {}).get("body") or {}).get("raw")
            if not body:
                return None
            try:
                asset_payload = json.loads(body)
            except ValueError:
                return None

            data_address = self._read_field(asset_payload, "dataAddress") or asset_payload.get("dataAddress")
            object_name = self._read_field(data_address, "name")
            return object_name.strip() if isinstance(object_name, str) and object_name.strip() else None

        return None

    @staticmethod
    def _matches_expected_object(object_name, expected_object_name):
        if not expected_object_name:
            return True
        if object_name == expected_object_name:
            return True
        return str(object_name or "").endswith(f"/{expected_object_name}")

    def _detect_new_or_updated_objects(self, before_snapshot, after_snapshot, started_at, expected_object_name=None):
        matches = []
        started_at = started_at.astimezone(timezone.utc) if started_at else None

        for object_name, current in (after_snapshot or {}).items():
            if not self._matches_expected_object(object_name, expected_object_name):
                continue

            previous = (before_snapshot or {}).get(object_name)
            current_modified = self._parse_iso_datetime(current.get("last_modified"))
            if current_modified and current_modified.tzinfo is None:
                current_modified = current_modified.replace(tzinfo=timezone.utc)

            reason = None
            if previous is None:
                reason = "new_object"
            elif current.get("etag") != previous.get("etag") or current.get("size") != previous.get("size"):
                reason = "updated_object"
            elif started_at and current_modified and current_modified >= started_at:
                reason = "modified_after_transfer_start"

            if reason and (current.get("size") or 0) > 0:
                matches.append(
                    {
                        "object_name": object_name,
                        "size": current.get("size"),
                        "etag": current.get("etag"),
                        "last_modified": current.get("last_modified"),
                        "reason": reason,
                    }
                )

        return matches

    def _artifact_path(self, experiment_dir, provider, consumer):
        artifact_dir = os.path.join(experiment_dir, "storage_checks")
        os.makedirs(artifact_dir, exist_ok=True)
        return os.path.join(artifact_dir, f"{provider}__{consumer}.json")

    def _save_payload(self, payload, experiment_dir, provider, consumer):
        if not experiment_dir:
            return None
        path = self._artifact_path(experiment_dir, provider, consumer)
        payload_to_save = dict(payload)
        payload_to_save["artifact_path"] = path
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload_to_save, handle, indent=2, ensure_ascii=False)
        return path

    @staticmethod
    def _failure_summary(failures):
        summary = []
        for failure in failures or []:
            source = ((failure.get("source") or {}).get("name")) or "unknown"
            error = failure.get("error") or {}
            summary.append(
                {
                    "source": source,
                    "test": error.get("test"),
                    "message": error.get("message"),
                }
            )
        return summary

    def verify_consumer_transfer_persistence(
        self,
        provider,
        consumer,
        report_dir,
        before_snapshot=None,
        baseline_reason=None,
        experiment_dir=None,
    ):
        payload = {
            "provider": provider,
            "consumer": consumer,
            "status": "skipped",
            "reason": None,
            "artifact_path": None,
        }

        report_path = os.path.join(report_dir, "06_consumer_transfer.json")
        if not os.path.exists(report_path):
            payload["reason"] = "06_consumer_transfer report not found"
            self._save_payload(payload, experiment_dir, provider, consumer)
            return payload

        try:
            report_data = self._parse_transfer_report(report_path)
        except Exception as exc:
            payload["reason"] = f"Unable to parse transfer report: {exc}"
            payload["artifact_path"] = self._save_payload(payload, experiment_dir, provider, consumer)
            return payload
        expected_object_name = self._parse_expected_object_name(report_dir)

        if baseline_reason:
            payload["status"] = "failed"
            payload["reason"] = f"Unable to capture consumer bucket baseline before validation: {baseline_reason}"
            payload["transfer_id"] = report_data.get("transfer_id")
            payload["expected_object_name"] = expected_object_name
            payload["artifact_path"] = self._save_payload(payload, experiment_dir, provider, consumer)
            return payload

        if before_snapshot is None:
            payload["reason"] = "Consumer bucket baseline was not captured before validation"
            payload["transfer_id"] = report_data.get("transfer_id")
            payload["expected_object_name"] = expected_object_name
            payload["artifact_path"] = self._save_payload(payload, experiment_dir, provider, consumer)
            return payload

        failures = self._failure_summary(report_data.get("failures"))
        if failures:
            payload["status"] = "failed"
            payload["reason"] = "06_consumer_transfer reported Newman assertion failures before storage verification"
            payload["transfer_id"] = report_data.get("transfer_id")
            payload["expected_object_name"] = expected_object_name
            payload["report_failures"] = failures
            payload["artifact_path"] = self._save_payload(payload, experiment_dir, provider, consumer)
            return payload

        data_destination = report_data.get("data_destination") or {}
        bucket_name = self._read_field(data_destination, "bucketName")
        if not bucket_name:
            payload["reason"] = "Transfer report does not expose a destination bucket"
            payload["transfer_id"] = report_data.get("transfer_id")
            payload["expected_object_name"] = expected_object_name
            payload["artifact_path"] = self._save_payload(payload, experiment_dir, provider, consumer)
            return payload

        after_snapshot = {}
        changed_objects = []
        attempts = self.poll_attempts
        for attempt in range(1, attempts + 1):
            try:
                after_snapshot = self.capture_consumer_bucket_snapshot(consumer, bucket_name)
            except Exception as exc:
                payload["status"] = "failed"
                payload["reason"] = f"Unable to inspect consumer bucket: {exc}"
                payload["bucket_name"] = bucket_name
                payload["transfer_id"] = report_data.get("transfer_id")
                payload["attempts"] = attempt
                payload["artifact_path"] = self._save_payload(payload, experiment_dir, provider, consumer)
                return payload

            changed_objects = self._detect_new_or_updated_objects(
                before_snapshot,
                after_snapshot,
                report_data.get("started_at"),
                expected_object_name=expected_object_name,
            )
            if changed_objects:
                break
            if attempt < attempts and self.poll_interval_seconds > 0:
                time.sleep(self.poll_interval_seconds)

        payload.update(
            {
                "bucket_name": bucket_name,
                "transfer_id": report_data.get("transfer_id"),
                "expected_object_name": expected_object_name,
                "transfer_started_at": report_data.get("started_at").isoformat() if report_data.get("started_at") else None,
                "objects_before": len(before_snapshot),
                "objects_after": len(after_snapshot),
                "matched_objects": changed_objects,
                "data_destination": self._redact_sensitive_fields(data_destination),
                "attempts": attempts,
            }
        )

        if changed_objects:
            payload["status"] = "passed"
            if expected_object_name:
                payload["reason"] = "Expected transfer object was observed in the consumer bucket after transfer start"
            else:
                payload["reason"] = "New or updated objects were observed in the consumer bucket after transfer start"
        else:
            payload["status"] = "failed"
            if expected_object_name:
                payload["reason"] = (
                    "Expected transfer object was not observed as new or updated in the consumer bucket "
                    f"after transfer start: {expected_object_name}"
                )
            else:
                payload["reason"] = "No new or updated objects were observed in the consumer bucket after transfer start"

        payload["artifact_path"] = self._save_payload(payload, experiment_dir, provider, consumer)
        return payload
