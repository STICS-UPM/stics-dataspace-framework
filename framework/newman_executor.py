import json
import os
import shutil
import subprocess
import tempfile
import time

import requests


class ManagementAuthenticationError(RuntimeError):
    """Management API rejected a connector token that can be safely refreshed."""


class NewmanExecutor:
    """Runs Postman collections through Newman.

    Encapsulates Newman command execution, environment variable injection,
    and dynamic test script loading for validation collections.
    """

    CONTRACT_AGREEMENT_TIMEOUT_SECONDS = 60
    CONTRACT_AGREEMENT_POLL_INTERVAL_SECONDS = 3
    CONTRACT_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS = 30
    ASYNC_COLLECTION_DELAY_REQUEST_MS = 2000
    TRANSIENT_AUTH_ATTEMPTS = 5
    TRANSIENT_AUTH_RETRY_DELAY_SECONDS = 5
    MANAGEMENT_PREFLIGHT_ATTEMPTS = 20
    MANAGEMENT_PREFLIGHT_RETRY_DELAY_SECONDS = 3
    MANAGEMENT_PREFLIGHT_TIMEOUT_SECONDS = 15
    MANAGEMENT_PREFLIGHT_CATALOG_TIMEOUT_SECONDS = 15
    DSP_NEGOTIATION_RECOVERY_ATTEMPTS = 2
    DSP_NEGOTIATION_RECOVERY_DELAY_SECONDS = 10
    AUTH_LOGIN_REQUESTS = {"Provider Login", "Consumer Login"}
    AUTH_HEALTH_REQUESTS = {"Provider Management API Health", "Consumer Management API Health"}
    TRANSIENT_AUTH_STATUS_CODES = {502, 503, 504}
    MANAGEMENT_AUTH_REFRESH_STATUS_CODES = {401, 403}
    MANAGEMENT_AUTH_FAILURE_HINTS = (
        "authenticationfailed",
        "could not be authenticated",
    )
    DSP_NEGOTIATION_RECOVERY_HINTS = (
        "terminating",
        "terminated",
        "401",
        "unauthorized",
        "invalid_client",
        "token is not active",
        "contractnegotiationerror",
        "contract negotiation error",
        "dsp",
        "oauth",
    )
    E2E_NEGOTIATION_STATE_KEYS = (
        "e2e_catalog_attempt",
        "e2e_offer_policy_id",
        "e2e_catalog_asset_id",
        "e2e_negotiation_id",
        "e2e_negotiation_start_attempt",
        "e2e_negotiation_status_attempt",
        "e2e_agreement_id",
        "e2e_transfer_id",
        "e2e_transfer_process_id",
        "e2e_transfer_status_attempt",
        "e2e_endpoint_data_reference",
    )
    TRANSIENT_AUTH_ERROR_HINTS = (
        "ECONNRESET",
        "ECONNREFUSED",
        "ETIMEDOUT",
        "ESOCKETTIMEDOUT",
        "socket hang up",
    )

    def ensure_available(self):
        newman_cmd = self.resolve_newman_command()
        if newman_cmd is not None:
            return newman_cmd

        package_json = "package.json"
        if os.path.exists(package_json):
            print("[INFO] Newman not found. Installing local Node.js tooling with npm...")
            result = subprocess.run(
                ["npm", "install"],
                check=False,
                capture_output=False,
                text=True,
            )
            if result.returncode == 0:
                newman_cmd = self.resolve_newman_command()
                if newman_cmd is not None:
                    return newman_cmd

        return None

    def resolve_newman_command(self):
        local_newman = os.path.join("node_modules", ".bin", "newman")
        if os.path.exists(local_newman):
            return [local_newman]

        global_newman = shutil.which("newman")
        if global_newman:
            return [global_newman]

        return None

    def is_available(self):
        return self.ensure_available() is not None

    def _load_file(self, path):
        """Read a file and return its content as string."""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def load_test_scripts(self, collection_name):
        scripts = []

        scripts.append(self._load_file("validation/shared/api/common_tests.js"))

        if "environment_health" in collection_name:
            scripts.append(self._load_file("validation/core/tests/health_tests.js"))

        if "management" in collection_name:
            scripts.append(self._load_file("validation/core/tests/management_tests.js"))

        if "provider" in collection_name:
            scripts.append(self._load_file("validation/core/tests/provider_tests.js"))

        if "catalog" in collection_name:
            scripts.append(self._load_file("validation/core/tests/catalog_tests.js"))

        if "negotiation" in collection_name:
            scripts.append(self._load_file("validation/core/tests/negotiation_tests.js"))

        if "transfer" in collection_name:
            scripts.append(self._load_file("validation/core/tests/transfer_tests.js"))

        return "\n".join(scripts)

    def _write_environment_file(self, env_vars, environment_path):
        payload = {
            "id": "validation-environment",
            "name": "Validation Environment",
            "values": [
                {
                    "key": key,
                    "value": value,
                    "type": "text",
                    "enabled": True,
                }
                for key, value in env_vars.items()
            ],
            "_postman_variable_scope": "environment",
        }
        with open(environment_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _read_environment_payload(self, environment_path):
        with open(environment_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _read_environment_values(self, environment_path):
        payload = self._read_environment_payload(environment_path)
        values = {}
        for entry in payload.get("values", []):
            key = entry.get("key")
            if key:
                values[key] = entry.get("value")
        return payload, values

    def _write_environment_values(self, environment_path, updates):
        payload = self._read_environment_payload(environment_path)
        entries = payload.setdefault("values", [])
        indexed_entries = {
            entry.get("key"): entry
            for entry in entries
            if entry.get("key")
        }

        for key, value in updates.items():
            if key in indexed_entries:
                indexed_entries[key]["value"] = value
                indexed_entries[key]["enabled"] = True
                indexed_entries[key]["type"] = indexed_entries[key].get("type") or "text"
                continue

            entries.append({
                "key": key,
                "value": value,
                "type": "text",
                "enabled": True,
            })

        with open(environment_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _clear_environment_values(self, environment_path, keys):
        self._write_environment_values(
            environment_path,
            {key: "" for key in keys},
        )

    @staticmethod
    def _is_missing_or_unresolved(value):
        text = str(value or "").strip()
        return not text or "{{" in text or "}}" in text

    @staticmethod
    def _runtime_base_url_replacements(env_vars):
        replacements = {}
        provider_base_url = str(env_vars.get("providerBaseUrl") or "").strip().rstrip("/")
        consumer_base_url = str(env_vars.get("consumerBaseUrl") or "").strip().rstrip("/")
        if provider_base_url:
            replacements["http://{{provider}}.{{dsDomain}}"] = "{{providerBaseUrl}}"
        if consumer_base_url:
            replacements["http://{{consumer}}.{{dsDomain}}"] = "{{consumerBaseUrl}}"
        return replacements

    @classmethod
    def _replace_runtime_collection_urls(cls, value, replacements):
        if isinstance(value, dict):
            if "raw" in value and isinstance(value.get("raw"), str):
                raw = value["raw"]
                replaced = raw
                for source, target in replacements.items():
                    replaced = replaced.replace(source, target)
                if replaced != raw:
                    return replaced
            return {
                key: cls._replace_runtime_collection_urls(item, replacements)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._replace_runtime_collection_urls(item, replacements) for item in value]
        if isinstance(value, str):
            replaced = value
            for source, target in replacements.items():
                replaced = replaced.replace(source, target)
            return replaced
        return value

    def _runtime_collection_path(self, collection_path, env_vars):
        replacements = self._runtime_base_url_replacements(env_vars)
        if not replacements:
            return collection_path, None

        with open(collection_path, "r", encoding="utf-8") as f:
            collection = json.load(f)

        rewritten = self._replace_runtime_collection_urls(collection, replacements)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=f"-{os.path.basename(collection_path)}",
            prefix="validation-newman-collection-",
            delete=False,
        )
        with handle:
            json.dump(rewritten, handle, indent=2)
        return handle.name, handle.name

    def _require_environment_values(self, environment_path, required_keys, context):
        _, env_vars = self._read_environment_values(environment_path)
        missing = [
            key
            for key in required_keys
            if self._is_missing_or_unresolved(env_vars.get(key))
        ]
        if missing:
            raise RuntimeError(
                f"Cannot continue to {context} because required Newman variables are missing "
                f"or unresolved: {', '.join(missing)}"
            )
        return env_vars

    @staticmethod
    def _positive_int_from_env(name, default):
        value = os.getenv(name)
        if value in (None, ""):
            return default
        try:
            return max(1, int(value))
        except ValueError:
            print(f"[WARNING] Ignoring invalid {name}={value!r}; using {default}")
            return default

    @staticmethod
    def _positive_int_from_mapping(mapping, names, default):
        for name in names:
            value = mapping.get(name) if isinstance(mapping, dict) else None
            if value in (None, ""):
                continue
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                continue
        return default

    @staticmethod
    def _positive_float_from_env(name, default):
        value = os.getenv(name)
        if value in (None, ""):
            return default
        try:
            return max(0.0, float(value))
        except ValueError:
            print(f"[WARNING] Ignoring invalid {name}={value!r}; using {default}")
            return default

    @staticmethod
    def _response_header(response, header_name):
        expected = header_name.lower()
        for header in response.get("header", []) or []:
            key = str(header.get("key") or "").lower()
            if key == expected:
                return header.get("value")
        return None

    @staticmethod
    def _response_body_text(response):
        stream = response.get("stream")
        if isinstance(stream, dict) and stream.get("type") == "Buffer":
            try:
                return bytes(stream.get("data") or []).decode("utf-8", errors="replace")
            except (TypeError, ValueError):
                return ""
        if isinstance(stream, str):
            return stream
        body = response.get("body")
        return body if isinstance(body, str) else ""

    def _newman_auth_execution(self, report, request_name):
        for execution in report.get("run", {}).get("executions", []) or []:
            item_name = (execution.get("item") or {}).get("name")
            if item_name == request_name:
                return execution
        return None

    def _newman_auth_failure_detail(self, report_path):
        """Return a retry reason when Newman hit a transient auth endpoint failure."""
        if not report_path or not os.path.exists(report_path):
            return None

        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

        failures = report.get("run", {}).get("failures", []) or []
        for failure in failures:
            request_name = (failure.get("source") or {}).get("name")
            error = failure.get("error") or {}
            error_text = " ".join(
                str(error.get(key) or "")
                for key in ("name", "test", "message")
            )
            execution = self._newman_auth_execution(report, request_name)
            response = (execution or {}).get("response") or {}
            status_code = response.get("code")
            status_text = response.get("status") or ""
            content_type = self._response_header(response, "Content-Type") or "unknown content type"

            if status_code in self.TRANSIENT_AUTH_STATUS_CODES:
                return (
                    f"{request_name} returned HTTP {status_code} {status_text} "
                    f"({content_type})"
                )

            body_text = self._response_body_text(response)
            if status_code == 401 and "AuthenticationFailed" in body_text:
                scope = (
                    "auth health check"
                    if request_name in self.AUTH_HEALTH_REQUESTS
                    else "authenticated request"
                )
                return (
                    f"{request_name} returned transient HTTP 401 AuthenticationFailed during {scope} "
                    f"({content_type})"
                )

            if any(hint in error_text for hint in self.TRANSIENT_AUTH_ERROR_HINTS):
                return f"{request_name} failed with transient network error: {error_text.strip()}"

        return None

    def _newman_failure_text(self, report_path):
        if not report_path or not os.path.exists(report_path):
            return ""

        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError):
            return ""

        parts = []
        for failure in report.get("run", {}).get("failures", []) or []:
            source = failure.get("source") or {}
            error = failure.get("error") or {}
            source_name = source.get("name") or source.get("id") or "unknown request"
            error_text = " ".join(
                str(error.get(key) or "")
                for key in ("name", "test", "message")
            ).strip()
            if error_text:
                parts.append(f"{source_name}: {error_text}")

        return " | ".join(parts)

    def _newman_negotiation_failure_detail(self, report_path):
        detail = self._newman_failure_text(report_path)
        if not detail:
            return None

        lowered = detail.lower()
        if any(hint in lowered for hint in self.DSP_NEGOTIATION_RECOVERY_HINTS):
            return detail
        return None

    @staticmethod
    def _compact_detail(detail, limit=500):
        text = " ".join(str(detail or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    @staticmethod
    def _positive_int_from_values(values, keys, fallback):
        for key in keys:
            raw = str(values.get(key) or "").strip()
            if not raw:
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            if value > 0:
                return value
        return fallback

    def _should_wait_for_contract_agreement(self, environment_path):
        _, env_vars = self._read_environment_values(environment_path)
        return bool(env_vars.get("e2e_negotiation_id") and not env_vars.get("e2e_agreement_id"))

    @staticmethod
    def _management_url(connector, ds_domain, path):
        normalized_path = f"/{str(path or '').lstrip('/')}"
        return f"http://{connector}.{ds_domain}{normalized_path}"

    @staticmethod
    def _management_url_for_role(env_vars, role, connector, ds_domain, path):
        normalized_path = f"/{str(path or '').lstrip('/')}"
        base_url = str(env_vars.get(f"{role}BaseUrl") or "").strip().rstrip("/")
        if base_url:
            return f"{base_url}{normalized_path}"
        return NewmanExecutor._management_url(connector, ds_domain, normalized_path)

    @staticmethod
    def _response_preview(response, limit=300):
        try:
            text = str(getattr(response, "text", "") or "").strip()
        except Exception:
            text = ""
        text = " ".join(text.split())
        return text[:limit]

    @staticmethod
    def _emit_process_output(result):
        for stream_name in ("stdout", "stderr"):
            output = getattr(result, stream_name, None)
            if isinstance(output, str) and output:
                print(output, end="" if output.endswith("\n") else "\n")

    def _is_management_authentication_failure(self, response):
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code not in self.MANAGEMENT_AUTH_REFRESH_STATUS_CODES:
            return False
        preview = self._response_preview(response, limit=1000).lower()
        if not preview:
            return True
        return any(hint in preview for hint in self.MANAGEMENT_AUTH_FAILURE_HINTS)

    def _request_with_transient_retry(self, send_request, label, attempts, retry_delay):
        for attempt in range(1, attempts + 1):
            try:
                response = send_request()
            except requests.RequestException as exc:
                if attempt >= attempts:
                    raise RuntimeError(f"{label} request failed: {exc}") from exc
                print(
                    f"[INFO] {label} request failed with a transient network error: {exc}. "
                    f"Retrying in {retry_delay:g}s ({attempt + 1}/{attempts})"
                )
                time.sleep(retry_delay)
                continue

            if response.status_code in self.TRANSIENT_AUTH_STATUS_CODES and attempt < attempts:
                print(
                    f"[INFO] {label} returned transient HTTP {response.status_code}. "
                    f"Retrying in {retry_delay:g}s ({attempt + 1}/{attempts})"
                )
                time.sleep(retry_delay)
                continue

            return response

        raise RuntimeError(f"{label} request failed unexpectedly")

    def _connector_login(self, env_vars, role, attempts, retry_delay, timeout=None):
        keycloak_url = str(env_vars.get("keycloakUrl") or "").strip().rstrip("/")
        dataspace = str(env_vars.get("dataspace") or "").strip()
        client_id = str(env_vars.get("keycloakClientId") or "dataspace-users").strip()
        username = str(env_vars.get(f"{role}_user") or "").strip()
        password = str(env_vars.get(f"{role}_password") or "").strip()
        missing = [
            name
            for name, value in (
                ("keycloakUrl", keycloak_url),
                ("dataspace", dataspace),
                (f"{role}_user", username),
                (f"{role}_password", password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"{role} login missing environment values: {', '.join(missing)}")

        login_url = f"{keycloak_url}/realms/{dataspace}/protocol/openid-connect/token"
        payload = {
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
            "scope": "openid profile email",
        }
        response = self._request_with_transient_retry(
            lambda: requests.post(
                login_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=payload,
                timeout=timeout or self.MANAGEMENT_PREFLIGHT_TIMEOUT_SECONDS,
            ),
            f"{role} login",
            attempts,
            retry_delay,
        )
        if response.status_code != 200:
            preview = self._response_preview(response)
            raise RuntimeError(
                f"{role} login returned HTTP {response.status_code}"
                + (f": {preview}" if preview else "")
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{role} login returned a non-JSON body") from exc

        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"{role} login did not return access_token")
        return login_url, token

    def _post_management_json(self, url, token, payload, label, attempts, retry_delay, timeout=None):
        response = self._request_with_transient_retry(
            lambda: requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout or self.MANAGEMENT_PREFLIGHT_TIMEOUT_SECONDS,
            ),
            label,
            attempts,
            retry_delay,
        )
        if response.status_code != 200:
            preview = self._response_preview(response)
            message = f"{label} returned HTTP {response.status_code}" + (f": {preview}" if preview else "")
            if self._is_management_authentication_failure(response):
                raise ManagementAuthenticationError(message)
            raise RuntimeError(message)
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{label} returned a non-JSON body") from exc
        return response, body

    def _post_management_json_with_auth_refresh(
        self,
        env_vars,
        role,
        token,
        url,
        payload,
        label,
        attempts,
        retry_delay,
        timeout=None,
    ):
        current_token = token
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                response, body = self._post_management_json(
                    url,
                    current_token,
                    payload,
                    label,
                    attempts,
                    retry_delay,
                    timeout=timeout,
                )
                return response, body, current_token
            except ManagementAuthenticationError as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                _, current_token = self._connector_login(
                    env_vars,
                    role,
                    attempts,
                    retry_delay,
                    timeout=timeout,
                )
                continue

        raise last_error or RuntimeError(f"{label} failed after authentication refresh")

    def _refresh_connector_token_for_wait(self, environment_path, env_vars, role, token_key):
        current_token = env_vars.get(token_key)
        try:
            _, refreshed_token = self._connector_login(
                env_vars,
                role,
                self.TRANSIENT_AUTH_ATTEMPTS,
                self.TRANSIENT_AUTH_RETRY_DELAY_SECONDS,
            )
        except RuntimeError as exc:
            print(
                f"[WARNING] Could not refresh {role} management token before Level 6 wait; "
                f"using the current token. Detail: {exc}"
            )
            return current_token

        env_vars[token_key] = refreshed_token
        self._write_environment_values(environment_path, {token_key: refreshed_token})
        return refreshed_token

    @staticmethod
    def _preflight_body_summary(body):
        if isinstance(body, list):
            return f"items={len(body)}"
        if isinstance(body, dict):
            datasets = body.get("dcat:dataset")
            if isinstance(datasets, list):
                return f"datasets={len(datasets)}"
            if datasets:
                return "datasets=1"
            return f"keys={len(body)}"
        return type(body).__name__

    def run_management_api_preflight(self, env_vars, report_dir=None):
        attempts = self._positive_int_from_env(
            "PIONERA_NEWMAN_PREFLIGHT_ATTEMPTS",
            self._positive_int_from_mapping(
                env_vars,
                ("management_preflight_attempts", "MANAGEMENT_PREFLIGHT_ATTEMPTS"),
                self.MANAGEMENT_PREFLIGHT_ATTEMPTS,
            ),
        )
        retry_delay = self._positive_float_from_env(
            "PIONERA_NEWMAN_PREFLIGHT_RETRY_DELAY_SECONDS",
            self.MANAGEMENT_PREFLIGHT_RETRY_DELAY_SECONDS,
        )
        request_timeout = self._positive_int_from_env(
            "PIONERA_NEWMAN_PREFLIGHT_TIMEOUT_SECONDS",
            self._positive_int_from_mapping(
                env_vars,
                ("management_preflight_timeout_seconds", "MANAGEMENT_PREFLIGHT_TIMEOUT_SECONDS"),
                self.MANAGEMENT_PREFLIGHT_TIMEOUT_SECONDS,
            ),
        )
        catalog_timeout = self._positive_int_from_env(
            "PIONERA_NEWMAN_PREFLIGHT_CATALOG_TIMEOUT_SECONDS",
            self._positive_int_from_mapping(
                env_vars,
                (
                    "management_preflight_catalog_timeout_seconds",
                    "MANAGEMENT_PREFLIGHT_CATALOG_TIMEOUT_SECONDS",
                ),
                request_timeout,
            ),
        )
        provider = str(env_vars.get("provider") or "").strip()
        consumer = str(env_vars.get("consumer") or "").strip()
        ds_domain = str(env_vars.get("dsDomain") or "").strip()
        provider_protocol = str(env_vars.get("providerProtocolAddress") or "").strip()
        provider_participant_id = str(env_vars.get("providerParticipantId") or provider).strip()
        diagnostics = {
            "provider": provider,
            "consumer": consumer,
            "dsDomain": ds_domain,
            "checks": [],
        }
        failures = []
        report_path = None

        def record_check(name, endpoint, ok, detail, status_code=None):
            diagnostics["checks"].append(
                {
                    "name": name,
                    "endpoint": endpoint,
                    "ok": bool(ok),
                    "status_code": status_code,
                    "detail": str(detail or ""),
                }
            )
            if not ok:
                failures.append(f"{name}: {detail}")

        provider_token = None
        consumer_token = None

        try:
            provider_login_url, provider_token = self._connector_login(
                env_vars,
                "provider",
                attempts,
                retry_delay,
                timeout=request_timeout,
            )
            record_check("provider-login", provider_login_url, True, "access_token acquired", 200)
        except RuntimeError as exc:
            provider_login_url = str(env_vars.get("keycloakUrl") or "").strip()
            record_check("provider-login", provider_login_url, False, str(exc))

        try:
            consumer_login_url, consumer_token = self._connector_login(
                env_vars,
                "consumer",
                attempts,
                retry_delay,
                timeout=request_timeout,
            )
            record_check("consumer-login", consumer_login_url, True, "access_token acquired", 200)
        except RuntimeError as exc:
            consumer_login_url = str(env_vars.get("keycloakUrl") or "").strip()
            record_check("consumer-login", consumer_login_url, False, str(exc))

        if provider_token and provider and ds_domain:
            url = self._management_url_for_role(
                env_vars,
                "provider",
                provider,
                ds_domain,
                "/management/v3/assets/request",
            )
            try:
                response, body, provider_token = self._post_management_json_with_auth_refresh(
                    env_vars,
                    "provider",
                    provider_token,
                    url,
                    {
                        "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                        "offset": 0,
                        "limit": 1,
                        "filterExpression": [],
                    },
                    "provider assets preflight",
                    attempts,
                    retry_delay,
                    timeout=request_timeout,
                )
                record_check(
                    "provider-assets-request",
                    url,
                    True,
                    self._preflight_body_summary(body),
                    response.status_code,
                )
            except RuntimeError as exc:
                record_check("provider-assets-request", url, False, str(exc))

        if consumer_token and consumer and ds_domain:
            url = self._management_url_for_role(
                env_vars,
                "consumer",
                consumer,
                ds_domain,
                "/management/v3/contractnegotiations/request",
            )
            try:
                response, body, consumer_token = self._post_management_json_with_auth_refresh(
                    env_vars,
                    "consumer",
                    consumer_token,
                    url,
                    {
                        "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                        "offset": 0,
                        "limit": 1,
                    },
                    "consumer negotiation preflight",
                    attempts,
                    retry_delay,
                    timeout=request_timeout,
                )
                record_check(
                    "consumer-contractnegotiations-request",
                    url,
                    True,
                    self._preflight_body_summary(body),
                    response.status_code,
                )
            except RuntimeError as exc:
                record_check("consumer-contractnegotiations-request", url, False, str(exc))

        if consumer_token and consumer and ds_domain and provider_protocol and provider_participant_id:
            url = self._management_url_for_role(
                env_vars,
                "consumer",
                consumer,
                ds_domain,
                "/management/v3/catalog/request",
            )
            try:
                response, body, consumer_token = self._post_management_json_with_auth_refresh(
                    env_vars,
                    "consumer",
                    consumer_token,
                    url,
                    {
                        "@context": {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                        "@type": "CatalogRequest",
                        "counterPartyAddress": provider_protocol,
                        "counterPartyId": provider_participant_id,
                        "protocol": "dataspace-protocol-http",
                        "querySpec": {
                            "offset": 0,
                            "limit": 1,
                            "filterExpression": [],
                        },
                    },
                    "consumer catalog preflight",
                    attempts,
                    retry_delay,
                    timeout=catalog_timeout,
                )
                record_check(
                    "consumer-catalog-request",
                    url,
                    True,
                    self._preflight_body_summary(body),
                    response.status_code,
                )
            except RuntimeError as exc:
                record_check("consumer-catalog-request", url, False, str(exc))

        if report_dir:
            os.makedirs(report_dir, exist_ok=True)
            report_path = os.path.join(report_dir, "00_management_api_preflight.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(diagnostics, f, indent=2)

        if failures:
            message = (
                f"Newman management preflight failed for provider={provider}, consumer={consumer}: "
                + "; ".join(failures)
            )
            if report_path:
                message += f". See {report_path}"
            raise RuntimeError(message)

        return diagnostics

    @staticmethod
    def _extract_identifier(item):
        if not isinstance(item, dict):
            return None
        return item.get("@id") or item.get("id")

    @classmethod
    def _find_contract_agreement(cls, body, agreement_id):
        if isinstance(body, list):
            for item in body:
                if cls._extract_identifier(item) == agreement_id:
                    return item
            return None

        if isinstance(body, dict) and cls._extract_identifier(body) == agreement_id:
            return body

        return None

    @staticmethod
    def _find_negotiation(body, negotiation_id):
        if isinstance(body, list):
            for item in body:
                if not isinstance(item, dict):
                    continue
                if item.get("@id") == negotiation_id or item.get("id") == negotiation_id:
                    return item
            return None if negotiation_id else (body[0] if body else None)

        if isinstance(body, dict):
            if not negotiation_id:
                return body
            if body.get("@id") == negotiation_id or body.get("id") == negotiation_id:
                return body

        return None

    def _query_contract_agreement(self, connector, ds_domain, token, agreement_id, env_vars=None, role=None):
        direct_url = self._management_url_for_role(
            env_vars or {},
            role or "",
            connector,
            ds_domain,
            f"/management/v3/contractagreements/{agreement_id}",
        )
        list_url = self._management_url_for_role(
            env_vars or {},
            role or "",
            connector,
            ds_domain,
            "/management/v3/contractagreements/request",
        )
        issues = []

        try:
            response = requests.get(
                direct_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=10,
                verify=False,
            )
        except requests.RequestException as exc:
            issues.append(f"direct lookup failed: {exc}")
        else:
            if response.status_code == 200:
                try:
                    body = response.json()
                except ValueError:
                    issues.append("direct lookup body is not valid JSON")
                else:
                    agreement = self._find_contract_agreement(body, agreement_id)
                    if agreement is not None:
                        return agreement, None
                    issues.append(f"direct lookup did not return agreement {agreement_id}")
            elif response.status_code not in {404, 405}:
                issues.append(f"direct lookup HTTP {response.status_code}")

        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
            },
            "offset": 0,
            "limit": 100,
        }
        try:
            response = requests.post(
                list_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
                verify=False,
            )
        except requests.RequestException as exc:
            issues.append(f"list lookup failed: {exc}")
        else:
            if response.status_code == 200:
                try:
                    body = response.json()
                except ValueError:
                    issues.append("list lookup body is not valid JSON")
                else:
                    agreement = self._find_contract_agreement(body, agreement_id)
                    if agreement is not None:
                        return agreement, None
                    issues.append(f"agreement {agreement_id} not found in list lookup")
            else:
                issues.append(f"list lookup HTTP {response.status_code}")

        return None, "; ".join(issues)

    def wait_for_contract_agreement_visibility(
        self,
        environment_path,
        agreement_id=None,
        timeout=None,
        poll_interval=None,
    ):
        poll_interval = (
            self.CONTRACT_AGREEMENT_POLL_INTERVAL_SECONDS
            if poll_interval is None
            else poll_interval
        )

        _, env_vars = self._read_environment_values(environment_path)
        timeout = (
            self._positive_int_from_values(
                env_vars,
                (
                    "e2e_contract_agreement_visibility_timeout_seconds",
                    "PIONERA_NEWMAN_CONTRACT_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS",
                    "NEWMAN_CONTRACT_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS",
                ),
                self._positive_int_from_env(
                    "PIONERA_NEWMAN_CONTRACT_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS",
                    self.CONTRACT_AGREEMENT_VISIBILITY_TIMEOUT_SECONDS,
                ),
            )
            if timeout is None
            else timeout
        )
        agreement_id = agreement_id or env_vars.get("e2e_agreement_id")
        provider = env_vars.get("provider")
        consumer = env_vars.get("consumer")
        ds_domain = env_vars.get("dsDomain")
        provider_jwt = env_vars.get("provider_jwt")
        consumer_jwt = env_vars.get("consumer_jwt")
        missing = [
            key for key, value in (
                ("e2e_agreement_id", agreement_id),
                ("provider", provider),
                ("consumer", consumer),
                ("dsDomain", ds_domain),
                ("provider_jwt", provider_jwt),
                ("consumer_jwt", consumer_jwt),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Cannot wait for contract agreement visibility because these environment variables "
                "are missing: " + ", ".join(missing)
            )

        provider_jwt = self._refresh_connector_token_for_wait(
            environment_path,
            env_vars,
            "provider",
            "provider_jwt",
        )
        consumer_jwt = self._refresh_connector_token_for_wait(
            environment_path,
            env_vars,
            "consumer",
            "consumer_jwt",
        )

        deadline = time.time() + float(timeout)
        visible = set()
        last_errors = {}
        checks = (
            ("provider", provider, provider_jwt),
            ("consumer", consumer, consumer_jwt),
        )

        while time.time() <= deadline:
            for role, connector, token in checks:
                if role in visible:
                    continue
                agreement, issue = self._query_contract_agreement(
                    connector,
                    ds_domain,
                    token,
                    agreement_id,
                    env_vars=env_vars,
                    role=role,
                )
                if agreement is not None:
                    visible.add(role)
                    last_errors.pop(role, None)
                elif issue:
                    last_errors[role] = issue

            if len(visible) == len(checks):
                print(
                    "[INFO] contractAgreementId visible before transfer: "
                    f"{agreement_id}"
                )
                return {
                    "agreement_id": agreement_id,
                    "provider_visible": True,
                    "consumer_visible": True,
                }

            remaining = deadline - time.time()
            if remaining <= 0:
                break

            missing_roles = [role for role, _, _ in checks if role not in visible]
            detail = "; ".join(
                f"{role}: {last_errors[role]}"
                for role in missing_roles
                if role in last_errors
            )
            print(
                "[INFO] Waiting for contractAgreementId visibility before "
                f"06_consumer_transfer.json ({agreement_id}; missing={','.join(missing_roles)}"
                + (f"; detail={self._compact_detail(detail)}" if detail else "")
                + ")"
            )
            time.sleep(min(float(poll_interval), remaining))

        missing_roles = [role for role, _, _ in checks if role not in visible]
        detail = "; ".join(
            f"{role}: {last_errors[role]}"
            for role in missing_roles
            if role in last_errors
        )
        raise RuntimeError(
            f"Contract agreement {agreement_id} was not visible before 06_consumer_transfer.json "
            f"(missing={','.join(missing_roles)})"
            + (f"; last_errors={self._compact_detail(detail)}" if detail else "")
        )

    @staticmethod
    def _negotiation_summary(negotiation):
        if not isinstance(negotiation, dict):
            return ""

        fields = []
        for key in ("@id", "id", "type", "state", "counterPartyId", "contractAgreementId", "errorDetail"):
            value = negotiation.get(key)
            if value not in (None, ""):
                fields.append(f"{key}={value}")
        return ", ".join(fields)

    def _provider_negotiation_diagnostic(self, env_vars):
        provider = env_vars.get("provider")
        consumer = env_vars.get("consumer")
        ds_domain = env_vars.get("dsDomain")
        provider_jwt = env_vars.get("provider_jwt")
        missing = [
            key for key, value in (
                ("provider", provider),
                ("consumer", consumer),
                ("dsDomain", ds_domain),
                ("provider_jwt", provider_jwt),
            )
            if not value
        ]
        if missing:
            return "provider diagnostics unavailable; missing " + ", ".join(missing)

        url = self._management_url_for_role(
            env_vars,
            "provider",
            provider,
            ds_domain,
            "/management/v3/contractnegotiations/request",
        )
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
            },
            "offset": 0,
            "limit": 100,
        }
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {provider_jwt}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
                verify=False,
            )
        except requests.RequestException as exc:
            return f"provider diagnostics request failed: {exc}"

        if response.status_code != 200:
            return f"provider diagnostics returned HTTP {response.status_code}"

        try:
            body = response.json()
        except ValueError:
            return "provider diagnostics response body is not valid JSON"

        if not isinstance(body, list):
            return "provider diagnostics response body is not a negotiation list"

        candidates = [
            item for item in body
            if isinstance(item, dict) and item.get("counterPartyId") == consumer
        ]
        if not candidates:
            return f"provider diagnostics found no negotiation with counterPartyId={consumer}"

        candidates.sort(key=lambda item: item.get("createdAt") or 0, reverse=True)
        terminated = [
            item for item in candidates
            if item.get("state") in {"TERMINATING", "TERMINATED"}
        ]
        selected = terminated[0] if terminated else candidates[0]
        summary = self._negotiation_summary(selected)
        return summary or "provider diagnostics found a negotiation but could not summarize it"

    def wait_for_contract_agreement(self, environment_path, timeout=None, poll_interval=None):
        poll_interval = (
            self.CONTRACT_AGREEMENT_POLL_INTERVAL_SECONDS
            if poll_interval is None
            else poll_interval
        )

        _, env_vars = self._read_environment_values(environment_path)
        timeout = (
            self._positive_int_from_values(
                env_vars,
                (
                    "e2e_contract_agreement_timeout_seconds",
                    "PIONERA_NEWMAN_CONTRACT_AGREEMENT_TIMEOUT_SECONDS",
                    "NEWMAN_CONTRACT_AGREEMENT_TIMEOUT_SECONDS",
                ),
                self._positive_int_from_env(
                    "PIONERA_NEWMAN_CONTRACT_AGREEMENT_TIMEOUT_SECONDS",
                    self.CONTRACT_AGREEMENT_TIMEOUT_SECONDS,
                ),
            )
            if timeout is None
            else timeout
        )
        agreement_id = env_vars.get("e2e_agreement_id")
        if agreement_id:
            return agreement_id

        negotiation_id = env_vars.get("e2e_negotiation_id")
        consumer = env_vars.get("consumer")
        ds_domain = env_vars.get("dsDomain")
        consumer_jwt = env_vars.get("consumer_jwt")
        missing = [
            key for key, value in (
                ("e2e_negotiation_id", negotiation_id),
                ("consumer", consumer),
                ("dsDomain", ds_domain),
                ("consumer_jwt", consumer_jwt),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Cannot wait for contractAgreementId because these environment variables are missing: "
                + ", ".join(missing)
            )

        consumer_jwt = self._refresh_connector_token_for_wait(
            environment_path,
            env_vars,
            "consumer",
            "consumer_jwt",
        )

        direct_url = self._management_url_for_role(
            env_vars,
            "consumer",
            consumer,
            ds_domain,
            f"/management/v3/contractnegotiations/{negotiation_id}",
        )
        list_url = self._management_url_for_role(
            env_vars,
            "consumer",
            consumer,
            ds_domain,
            "/management/v3/contractnegotiations/request",
        )
        payload = {
            "@context": {
                "@vocab": "https://w3id.org/edc/v0.0.1/ns/"
            },
            "offset": 0,
            "limit": 100,
        }
        deadline = time.time() + float(timeout)
        last_state = None
        last_issue = None

        while time.time() <= deadline:
            negotiation = None
            try:
                response = requests.get(
                    direct_url,
                    headers={
                        "Authorization": f"Bearer {consumer_jwt}",
                        "Accept": "application/json",
                    },
                    timeout=10,
                    verify=False,
                )
            except requests.RequestException as exc:
                last_issue = f"direct lookup failed: {exc}"
            else:
                if response.status_code == 200:
                    try:
                        body = response.json()
                    except ValueError:
                        last_issue = "direct lookup body is not valid JSON"
                    else:
                        negotiation = self._find_negotiation(body, negotiation_id)
                        if negotiation is None:
                            last_issue = f"direct lookup did not return negotiation {negotiation_id}"
                else:
                    last_issue = f"direct lookup HTTP {response.status_code}"

            if negotiation is None:
                try:
                    response = requests.post(
                        list_url,
                        headers={
                            "Authorization": f"Bearer {consumer_jwt}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=10,
                        verify=False,
                    )
                except requests.RequestException as exc:
                    last_issue = f"{last_issue}; list lookup failed: {exc}" if last_issue else str(exc)
                else:
                    if response.status_code != 200:
                        list_issue = f"list lookup HTTP {response.status_code}"
                        last_issue = f"{last_issue}; {list_issue}" if last_issue else list_issue
                    else:
                        try:
                            body = response.json()
                        except ValueError:
                            list_issue = "list lookup body is not valid JSON"
                            last_issue = f"{last_issue}; {list_issue}" if last_issue else list_issue
                        else:
                            negotiation = self._find_negotiation(body, negotiation_id)
                            if negotiation is None:
                                list_issue = f"negotiation {negotiation_id} not found"
                                last_issue = f"{last_issue}; {list_issue}" if last_issue else list_issue

            if negotiation is not None:
                last_state = negotiation.get("state")
                agreement_id = negotiation.get("contractAgreementId")
                if agreement_id:
                    self._write_environment_values(
                        environment_path,
                        {"e2e_agreement_id": agreement_id},
                    )
                    print(
                        "[INFO] contractAgreementId obtained before transfer: "
                        f"{agreement_id}"
                    )
                    return agreement_id
                last_issue = negotiation.get("errorDetail") or f"state={last_state or 'unknown'}"
                if last_state in {"TERMINATING", "TERMINATED"}:
                    provider_detail = self._provider_negotiation_diagnostic(env_vars)
                    if provider_detail:
                        last_issue = f"{last_issue}; provider_side=({provider_detail})"
                    raise RuntimeError(
                        f"Negotiation reached {last_state} before contractAgreementId. "
                        f"Negotiation={negotiation_id}, detail={last_issue}"
                    )

            remaining = deadline - time.time()
            if remaining <= 0:
                break

            wait_detail = last_issue or f"state={last_state or 'unknown'}"
            print(
                "[INFO] Waiting for contractAgreementId from negotiation "
                f"{negotiation_id} ({wait_detail})"
            )
            time.sleep(min(float(poll_interval), remaining))

        raise RuntimeError(
            "Timed out waiting for contractAgreementId before 06_consumer_transfer.json. "
            f"Negotiation={negotiation_id}, last_state={last_state or 'unknown'}, "
            f"detail={last_issue or 'no detail'}"
        )

    def run_newman(self, collection_path, env_vars, report_path=None, environment_path=None):
        """
        Execute a Postman collection using Newman with dynamic environment variables,
        injected test scripts, and optional JSON report export.
        """
        print(f"\nExecuting: newman run {collection_path}")

        test_script = self.load_test_scripts(collection_path)
        newman_cmd = self.ensure_available()
        if newman_cmd is None:
            print("ERROR: Newman is not installed or not available locally")
            print("Install with: npm install or npm install -g newman")
            return None

        runtime_collection_path, temporary_collection_path = self._runtime_collection_path(
            collection_path,
            env_vars,
        )

        cmd = newman_cmd + [
            "run",
            runtime_collection_path,
            "--reporters",
            "cli,json",
            "--color",
            "on",
            "--insecure",
        ]

        collection_name = os.path.basename(collection_path)
        if collection_name in {
            "04_consumer_catalog.json",
            "05_consumer_negotiation.json",
            "06_consumer_transfer.json",
        }:
            cmd.extend([
                "--delay-request",
                str(self.ASYNC_COLLECTION_DELAY_REQUEST_MS),
            ])

        if environment_path:
            cmd.extend([
                "--environment",
                environment_path,
                "--export-environment",
                environment_path,
            ])
        else:
            for key, value in env_vars.items():
                cmd.extend([
                    "--env-var",
                    f"{key}={value}"
                ])

        cmd.extend([
            "--env-var",
            f"test_script={test_script}"
        ])

        if report_path:
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            cmd.extend([
                "--reporter-json-export",
                report_path,
            ])

        max_attempts = (
            self._positive_int_from_env(
                "PIONERA_NEWMAN_TRANSIENT_AUTH_ATTEMPTS",
                self.TRANSIENT_AUTH_ATTEMPTS,
            )
            if report_path
            else 1
        )
        retry_delay = self._positive_float_from_env(
            "PIONERA_NEWMAN_TRANSIENT_AUTH_RETRY_DELAY_SECONDS",
            self.TRANSIENT_AUTH_RETRY_DELAY_SECONDS,
        )

        try:
            for attempt in range(1, max_attempts + 1):
                if report_path and os.path.exists(report_path):
                    os.remove(report_path)

                try:
                    result = subprocess.run(
                        cmd,
                        check=False,
                        capture_output=True,
                        text=True
                    )
                except FileNotFoundError:
                    print("ERROR: Newman is not installed or not available locally")
                    print("Install with: npm install or npm install -g newman")
                    return None

                if result.returncode == 0:
                    self._emit_process_output(result)
                    return report_path

                transient_auth_detail = self._newman_auth_failure_detail(report_path)
                if transient_auth_detail and attempt < max_attempts:
                    print(
                        "[INFO] Newman auth endpoint was temporarily unavailable: "
                        f"{transient_auth_detail}. Retrying "
                        f"{os.path.basename(collection_path)} in {retry_delay:g}s "
                        f"({attempt + 1}/{max_attempts})"
                    )
                    time.sleep(retry_delay)
                    continue

                self._emit_process_output(result)
                print(f"[WARNING] Newman returned exit code {result.returncode}")
                return report_path

            return report_path
        finally:
            if temporary_collection_path:
                try:
                    os.remove(temporary_collection_path)
                except OSError:
                    pass

    @staticmethod
    def _collection_report_path(report_dir, collection_name, suffix=""):
        if not report_dir:
            return None
        report_name = f"{os.path.splitext(collection_name)[0]}{suffix}.json"
        return os.path.join(report_dir, report_name)

    def _is_recoverable_dsp_negotiation_failure(self, error, report_path):
        detail = " ".join(
            item
            for item in (
                str(error or ""),
                self._newman_negotiation_failure_detail(report_path) or "",
            )
            if item
        )
        lowered = detail.lower()
        return any(hint in lowered for hint in self.DSP_NEGOTIATION_RECOVERY_HINTS)

    def _rerun_catalog_and_negotiation_for_dsp_recovery(
        self,
        env_vars,
        environment_path,
        report_dir,
        exported_reports,
        collection_base,
        recovery_attempt,
        recovery_attempts,
    ):
        suffix = f"_recovery_{recovery_attempt:02d}"
        self._clear_environment_values(
            environment_path,
            self.E2E_NEGOTIATION_STATE_KEYS,
        )

        latest_negotiation_report = None
        for collection_name in ("04_consumer_catalog.json", "05_consumer_negotiation.json"):
            collection_path = os.path.join(collection_base, collection_name)
            report_path = self._collection_report_path(report_dir, collection_name, suffix=suffix)
            print(
                f"[recovery {recovery_attempt}/{recovery_attempts}] "
                f"Running collection: {collection_name}"
            )
            exported_report = self.run_newman(
                collection_path,
                env_vars,
                report_path=report_path,
                environment_path=environment_path,
            )
            if exported_report:
                exported_reports.append(exported_report)

            if collection_name == "04_consumer_catalog.json":
                self._require_environment_values(
                    environment_path,
                    ("e2e_offer_policy_id", "e2e_catalog_asset_id"),
                    "contract negotiation recovery",
                )
            else:
                latest_negotiation_report = exported_report or report_path

        return latest_negotiation_report

    @staticmethod
    def _archive_recovered_reports(report_paths, exported_reports):
        for report_path in dict.fromkeys(path for path in report_paths if path):
            if not os.path.exists(report_path):
                continue

            archive_path = f"{report_path}.recovered"
            index = 2
            while os.path.exists(archive_path):
                archive_path = f"{report_path}.recovered_{index}"
                index += 1

            try:
                os.replace(report_path, archive_path)
            except OSError as exc:
                print(f"[WARNING] Could not archive recovered Newman report {report_path}: {exc}")
                continue

            while report_path in exported_reports:
                exported_reports.remove(report_path)
            print(
                "[INFO] Archived recovered failed Newman report: "
                f"{os.path.basename(report_path)} -> {os.path.basename(archive_path)}"
            )

    def _wait_for_contract_agreement_with_dsp_recovery(
        self,
        env_vars,
        environment_path,
        report_dir,
        exported_reports,
        collection_base,
        negotiation_report_path,
    ):
        recovery_attempts = self._positive_int_from_env(
            "PIONERA_NEWMAN_DSP_NEGOTIATION_RECOVERY_ATTEMPTS",
            self.DSP_NEGOTIATION_RECOVERY_ATTEMPTS,
        )
        recovery_delay = self._positive_float_from_env(
            "PIONERA_NEWMAN_DSP_NEGOTIATION_RECOVERY_DELAY_SECONDS",
            self.DSP_NEGOTIATION_RECOVERY_DELAY_SECONDS,
        )
        current_report_path = negotiation_report_path
        recovered_failure_reports = []

        for attempt in range(1, recovery_attempts + 1):
            try:
                agreement_id = self.wait_for_contract_agreement(environment_path)
                if recovered_failure_reports:
                    self._archive_recovered_reports(
                        recovered_failure_reports,
                        exported_reports,
                    )
                return agreement_id
            except RuntimeError as exc:
                if (
                    attempt >= recovery_attempts
                    or not self._is_recoverable_dsp_negotiation_failure(exc, current_report_path)
                ):
                    raise

                if current_report_path:
                    recovered_failure_reports.append(current_report_path)
                detail = (
                    self._newman_negotiation_failure_detail(current_report_path)
                    or str(exc)
                )
                print(
                    "[INFO] Contract negotiation reached a recoverable DSP/OAuth symptom: "
                    f"{self._compact_detail(detail)}"
                )
                print(
                    "[INFO] Clearing E2E negotiation state and re-running catalog plus "
                    f"negotiation after {recovery_delay:g}s "
                    f"({attempt + 1}/{recovery_attempts})."
                )
                time.sleep(recovery_delay)
                current_report_path = self._rerun_catalog_and_negotiation_for_dsp_recovery(
                    env_vars,
                    environment_path,
                    report_dir,
                    exported_reports,
                    collection_base,
                    attempt + 1,
                    recovery_attempts,
                )

        raise RuntimeError("Contract agreement recovery exhausted unexpectedly")

    def run_validation_collections(self, env_vars, report_dir=None):
        """Run all validation collections in sequence and optionally export JSON reports."""
        base = os.path.join("validation", "core", "collections")

        collections = [
            "01_environment_health.json",
            "02_connector_management_api.json",
            "03_provider_setup.json",
            "04_consumer_catalog.json",
            "05_consumer_negotiation.json",
            "06_consumer_transfer.json"
        ]

        total = len(collections)
        exported_reports = []

        with tempfile.TemporaryDirectory(prefix="validation-newman-env-") as tmpdir:
            environment_path = os.path.join(tmpdir, "environment.json")
            self._write_environment_file(env_vars, environment_path)

            for i, c in enumerate(collections, 1):
                collection_path = os.path.join(base, c)
                print(f"[{i}/{total}] Running collection: {c}")

                report_path = self._collection_report_path(report_dir, c)

                exported_report = self.run_newman(
                    collection_path,
                    env_vars,
                    report_path=report_path,
                    environment_path=environment_path,
                )
                if exported_report:
                    exported_reports.append(exported_report)

                if c == "04_consumer_catalog.json":
                    self._require_environment_values(
                        environment_path,
                        ("e2e_offer_policy_id", "e2e_catalog_asset_id"),
                        "contract negotiation",
                    )

                if c == "05_consumer_negotiation.json":
                    agreement_id = None
                    if self._should_wait_for_contract_agreement(environment_path):
                        agreement_id = self._wait_for_contract_agreement_with_dsp_recovery(
                            env_vars,
                            environment_path,
                            report_dir,
                            exported_reports,
                            base,
                            exported_report or report_path,
                        )
                    else:
                        _, current_env_vars = self._read_environment_values(environment_path)
                        agreement_id = current_env_vars.get("e2e_agreement_id")

                    if agreement_id:
                        self.wait_for_contract_agreement_visibility(
                            environment_path,
                            agreement_id=agreement_id,
                        )

        return exported_reports

    def describe(self) -> str:
        return "NewmanExecutor runs Postman collections using Newman."

