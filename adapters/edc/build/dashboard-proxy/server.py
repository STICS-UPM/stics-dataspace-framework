#!/usr/bin/env python3

import base64
import hashlib
import http.cookies
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

PROXY_CONNECTOR_PREFIX = "/edc-dashboard-api/connectors/"


class ProxySettings:
    def __init__(self):
        config_file = os.getenv("PROXY_CONFIG_FILE", "/app/config/proxy-config.json")
        auth_file = os.getenv("PROXY_AUTH_FILE", "/app/config/proxy-auth.json")

        with open(config_file, "r", encoding="utf-8") as handle:
            config_payload = json.load(handle)
        with open(auth_file, "r", encoding="utf-8") as handle:
            auth_payload = json.load(handle)

        self.auth_mode = config_payload.get("authMode", "service-account")
        self.client_id = config_payload.get("clientId", "dataspace-users")
        self.scope = config_payload.get("scope", "openid profile email")
        self.token_url = config_payload.get("tokenUrl", "")
        self.authorization_url = config_payload.get("authorizationUrl", "")
        self.logout_url = config_payload.get("logoutUrl", "")
        self.callback_path = config_payload.get("callbackPath", "/edc-dashboard-api/auth/callback")
        self.login_path = config_payload.get("loginPath", "/edc-dashboard-api/auth/login")
        self.logout_path = config_payload.get("logoutPath", "/edc-dashboard-api/auth/logout")
        self.post_login_redirect_path = config_payload.get("postLoginRedirectPath", "/edc-dashboard/")
        self.post_logout_redirect_path = config_payload.get("postLogoutRedirectPath", "/edc-dashboard/")
        self.cookie_name = config_payload.get("cookieName", "edc_dashboard_session")
        self.flash_cookie_name = f"{self.cookie_name}_flash"
        self.cookie_secure = bool(config_payload.get("cookieSecure", False))
        self.connectors = {
            entry.get("connectorName"): entry
            for entry in config_payload.get("connectors", [])
            if entry.get("connectorName")
        }
        self.passwords = {
            entry.get("connectorName"): entry.get("password", "")
            for entry in auth_payload.get("connectors", [])
            if entry.get("connectorName")
        }
        self.token_cache = {}
        self.token_lock = Lock()
        self.auth_request_ttl_seconds = int(config_payload.get("authRequestTtlSeconds", 300))
        self.session_ttl_seconds = int(config_payload.get("sessionTtlSeconds", 3600))
        self.flash_ttl_seconds = int(config_payload.get("flashTtlSeconds", 120))
        self.auth_requests = {}
        self.auth_request_lock = Lock()
        self.sessions = {}
        self.sessions_lock = Lock()
        self.flash_messages = {}
        self.flash_messages_lock = Lock()

    def connector_names(self):
        return sorted(self.connectors.keys())

    def connector_config(self, connector_name):
        return self.connectors.get(connector_name)

    def connector_password(self, connector_name):
        return self.passwords.get(connector_name, "")

    def _token_request_body(self, connector_name):
        connector = self.connector_config(connector_name) or {}
        username = connector.get("username", "")
        password = self.connector_password(connector_name)
        return urllib.parse.urlencode(
            {
                "grant_type": "password",
                "client_id": self.client_id,
                "username": username,
                "password": password,
                "scope": "openid profile email",
            }
        ).encode("utf-8")

    def management_token(self, connector_name):
        if self.auth_mode != "service-account":
            return None
        if not self.token_url:
            raise RuntimeError("Missing tokenUrl in proxy-config.json")

        now = time.time()
        with self.token_lock:
            cached = self.token_cache.get(connector_name)
            if cached and cached["expires_at"] > now:
                return cached["token"]

        request = urllib.request.Request(
            self.token_url,
            data=self._token_request_body(connector_name),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))

        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 60))
        if not token:
            raise RuntimeError("Keycloak token response did not contain access_token")

        with self.token_lock:
            self.token_cache[connector_name] = {
                "token": token,
                "expires_at": now + max(expires_in - 30, 1),
            }
        return token

    @staticmethod
    def _base64url(input_bytes):
        return base64.urlsafe_b64encode(input_bytes).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_jwt_claims(token):
        if not token or "." not in token:
            return {}
        try:
            payload_segment = token.split(".")[1]
            padding = "=" * (-len(payload_segment) % 4)
            raw = base64.urlsafe_b64decode(payload_segment + padding)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _token_expiration(payload):
        if not payload:
            return None
        if payload.get("expires_in"):
            return time.time() + int(payload.get("expires_in", 0))
        access_claims = ProxySettings._decode_jwt_claims(payload.get("access_token"))
        exp = access_claims.get("exp")
        return float(exp) if exp else None

    def _token_exchange(self, form_data):
        request = urllib.request.Request(
            self.token_url,
            data=urllib.parse.urlencode(form_data).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def create_auth_request(self, return_to):
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = self._base64url(hashlib.sha256(verifier.encode("utf-8")).digest())
        with self.auth_request_lock:
            self.auth_requests[state] = {
                "created_at": time.time(),
                "verifier": verifier,
                "return_to": return_to,
            }
        return state, verifier, challenge

    def consume_auth_request(self, state):
        with self.auth_request_lock:
            payload = self.auth_requests.pop(state, None)
        if not payload:
            return None
        if payload["created_at"] + self.auth_request_ttl_seconds < time.time():
            return None
        return payload

    def exchange_authorization_code(self, code, redirect_uri, verifier):
        return self._token_exchange(
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            }
        )

    def refresh_oidc_session(self, session_id):
        with self.sessions_lock:
            session = self.sessions.get(session_id)
        if not session:
            return None
        refresh_token = session.get("refresh_token")
        if not refresh_token:
            return None
        try:
            payload = self._token_exchange(
                {
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": refresh_token,
                }
            )
        except Exception:
            self.delete_session(session_id)
            return None
        return self._store_session(session_id, payload)

    def _store_session(self, session_id, token_payload):
        claims = self._decode_jwt_claims(token_payload.get("id_token") or token_payload.get("access_token"))
        expires_at = self._token_expiration(token_payload) or (time.time() + self.session_ttl_seconds)
        session = {
            "session_id": session_id,
            "access_token": token_payload.get("access_token"),
            "refresh_token": token_payload.get("refresh_token"),
            "id_token": token_payload.get("id_token"),
            "claims": claims,
            "expires_at": expires_at,
        }
        with self.sessions_lock:
            self.sessions[session_id] = session
        return session

    def create_oidc_session(self, token_payload):
        session_id = secrets.token_urlsafe(32)
        return self._store_session(session_id, token_payload)

    def delete_session(self, session_id):
        if not session_id:
            return
        with self.sessions_lock:
            self.sessions.pop(session_id, None)

    def oidc_session(self, session_id):
        if not session_id:
            return None
        with self.sessions_lock:
            session = self.sessions.get(session_id)
        if not session:
            return None
        if session.get("expires_at", 0) > time.time() + 30:
            return session
        return self.refresh_oidc_session(session_id)

    def create_flash_notice(self, event, message, level="info"):
        flash_id = secrets.token_urlsafe(24)
        with self.flash_messages_lock:
            self.flash_messages[flash_id] = {
                "created_at": time.time(),
                "event": event,
                "message": message,
                "level": level,
            }
        return flash_id

    def consume_flash_notice(self, flash_id):
        if not flash_id:
            return None
        with self.flash_messages_lock:
            payload = self.flash_messages.pop(flash_id, None)
        if not payload:
            return None
        if payload["created_at"] + self.flash_ttl_seconds < time.time():
            return None
        return {
            "event": payload.get("event"),
            "message": payload.get("message"),
            "level": payload.get("level", "info"),
        }


SETTINGS = ProxySettings()


class DashboardProxyHandler(BaseHTTPRequestHandler):
    server_version = "EDCDashboardProxy/0.1"

    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def do_PUT(self):
        self._handle_request()

    def do_PATCH(self):
        self._handle_request()

    def do_DELETE(self):
        self._handle_request()

    def do_OPTIONS(self):
        self._handle_request()

    def do_HEAD(self):
        self._handle_request()

    def _send_json(self, status_code, payload, set_cookie_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        for header_value in set_cookie_headers or []:
            self.send_header("Set-Cookie", header_value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_redirect(self, location, set_cookie_headers=None):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        for header_value in set_cookie_headers or []:
            self.send_header("Set-Cookie", header_value)
        self.end_headers()

    def _cookie_value(self, name):
        raw_cookie = self.headers.get("Cookie", "")
        if not raw_cookie:
            return None
        cookie = http.cookies.SimpleCookie()
        cookie.load(raw_cookie)
        morsel = cookie.get(name)
        return morsel.value if morsel else None

    @staticmethod
    def _normalize_return_to(value, fallback):
        candidate = value or fallback
        if not candidate or not candidate.startswith("/"):
            return fallback
        if candidate.startswith("//"):
            return fallback
        return candidate

    def _external_base_url(self):
        forwarded_proto = self.headers.get("X-Forwarded-Proto")
        forwarded_host = self.headers.get("X-Forwarded-Host")
        host = forwarded_host or self.headers.get("Host") or "localhost"
        scheme = forwarded_proto or ("https" if SETTINGS.cookie_secure else "http")
        return f"{scheme}://{host}"

    def _callback_url(self):
        return f"{self._external_base_url()}{SETTINGS.callback_path}"

    def _clear_session_cookie_header(self):
        parts = [
            f"{SETTINGS.cookie_name}=",
            "Path=/",
            "HttpOnly",
            "Max-Age=0",
            "SameSite=Lax",
        ]
        if SETTINGS.cookie_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _clear_flash_cookie_header(self):
        parts = [
            f"{SETTINGS.flash_cookie_name}=",
            "Path=/",
            "Max-Age=0",
            "SameSite=Lax",
        ]
        if SETTINGS.cookie_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _session_cookie_header(self, session_id):
        parts = [
            f"{SETTINGS.cookie_name}={session_id}",
            "Path=/",
            "HttpOnly",
            f"Max-Age={SETTINGS.session_ttl_seconds}",
            "SameSite=Lax",
        ]
        if SETTINGS.cookie_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _flash_cookie_header(self, flash_id):
        parts = [
            f"{SETTINGS.flash_cookie_name}={flash_id}",
            "Path=/",
            f"Max-Age={SETTINGS.flash_ttl_seconds}",
            "SameSite=Lax",
        ]
        if SETTINGS.cookie_secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _oidc_session(self):
        session_id = self._cookie_value(SETTINGS.cookie_name)
        return SETTINGS.oidc_session(session_id)

    def _consume_flash_notice(self):
        flash_cookie_id = self._cookie_value(SETTINGS.flash_cookie_name)
        if not flash_cookie_id:
            return None, []
        flash_notice = SETTINGS.consume_flash_notice(flash_cookie_id)
        return flash_notice, [self._clear_flash_cookie_header()]

    def _redirect_with_flash_notice(self, location, event, message, level="info", set_cookie_headers=None):
        flash_id = SETTINGS.create_flash_notice(event, message, level=level)
        headers = list(set_cookie_headers or [])
        headers.append(self._flash_cookie_header(flash_id))
        self._send_redirect(location, set_cookie_headers=headers)

    def _handle_auth_info(self):
        flash_notice, flash_cookie_headers = self._consume_flash_notice()
        if SETTINGS.auth_mode == "oidc-bff":
            session = self._oidc_session()
            claims = (session or {}).get("claims", {})
            self._send_json(
                200,
                {
                    "authMode": SETTINGS.auth_mode,
                    "authenticated": bool(session),
                    "connectors": SETTINGS.connector_names(),
                    "loginPath": SETTINGS.login_path,
                    "logoutPath": SETTINGS.logout_path,
                    "flashNotice": flash_notice,
                    "user": {
                        "username": claims.get("preferred_username"),
                        "name": claims.get("name"),
                        "email": claims.get("email"),
                        "subject": claims.get("sub"),
                    } if session else None,
                },
                set_cookie_headers=flash_cookie_headers,
            )
            return

        self._send_json(
            200,
            {
                "authMode": SETTINGS.auth_mode,
                "authenticated": True,
                "connectors": SETTINGS.connector_names(),
                "user": {
                    "username": "service-account",
                    "name": "service-account",
                },
                "flashNotice": flash_notice,
            },
            set_cookie_headers=flash_cookie_headers,
        )

    def _read_request_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return None
        return self.rfile.read(content_length)

    def _rewrite_dashboard_proxy_url(self, value):
        if not isinstance(value, str) or not value.startswith(PROXY_CONNECTOR_PREFIX):
            return value

        parsed = urllib.parse.urlsplit(value)
        relative = parsed.path[len(PROXY_CONNECTOR_PREFIX):]
        parts = [part for part in relative.split("/") if part]
        if len(parts) < 2:
            return value

        connector_name = parts[0]
        service_name = parts[1]
        remaining_path = "/".join(parts[2:])
        if service_name not in {"management", "api", "control", "protocol"}:
            return value

        try:
            return self._target_url(connector_name, service_name, remaining_path, parsed.query)
        except KeyError:
            return value

    def _rewrite_proxy_payload(self, payload):
        if isinstance(payload, dict):
            return {key: self._rewrite_proxy_payload(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._rewrite_proxy_payload(entry) for entry in payload]
        if isinstance(payload, str):
            return self._rewrite_dashboard_proxy_url(payload)
        return payload

    def _normalized_request_body(self):
        body = self._read_request_body()
        if not body:
            return body

        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            return body

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return body

        rewritten_payload = self._rewrite_proxy_payload(payload)
        return json.dumps(rewritten_payload).encode("utf-8")

    def _forward_headers(self, connector_name, service_name, access_token=None):
        forwarded = {}
        for header_name, header_value in self.headers.items():
            if header_name.lower() in HOP_BY_HOP_HEADERS:
                continue
            if header_name.lower() == "host":
                continue
            if header_name.lower() == "cookie":
                continue
            if header_name.lower() == "content-length":
                continue
            forwarded[header_name] = header_value

        if service_name in {"management", "api", "control"}:
            token = access_token or SETTINGS.management_token(connector_name)
            if token:
                forwarded["Authorization"] = f"Bearer {token}"
        return forwarded

    def _target_url(self, connector_name, service_name, remaining_path, query_string):
        connector = SETTINGS.connector_config(connector_name)
        if not connector:
            raise KeyError(f"Unknown connector: {connector_name}")

        target_key = {
            "management": "managementTarget",
            "api": "defaultTarget",
            "control": "controlTarget",
            "protocol": "protocolTarget",
        }[service_name]
        base_url = (connector.get(target_key) or "").rstrip("/")
        suffix = f"/{remaining_path}" if remaining_path else ""
        url = f"{base_url}{suffix}"
        if query_string:
            url = f"{url}?{query_string}"
        return url

    def _proxy_request(self, connector_name, service_name, remaining_path, query_string):
        access_token = None
        if SETTINGS.auth_mode == "oidc-bff" and service_name in {"management", "api", "control"}:
            session = self._oidc_session()
            if not session or not session.get("access_token"):
                self._send_json(
                    401,
                    {
                        "message": "Authentication required",
                        "authMode": SETTINGS.auth_mode,
                        "loginPath": SETTINGS.login_path,
                        "authEvent": "session-expired",
                    },
                )
                return
            access_token = session.get("access_token")

        target_url = self._target_url(connector_name, service_name, remaining_path, query_string)
        request = urllib.request.Request(
            target_url,
            data=self._normalized_request_body(),
            headers=self._forward_headers(connector_name, service_name, access_token=access_token),
            method=self.command,
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                status = response.getcode()
                response_headers = response.headers
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code
            response_headers = exc.headers
        except Exception as exc:
            self._send_json(502, {"message": str(exc)})
            return

        self.send_response(status)
        for header_name, header_value in response_headers.items():
            if header_name.lower() in HOP_BY_HOP_HEADERS:
                continue
            if header_name.lower() == "content-length":
                continue
            self.send_header(header_name, header_value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle_connector_health(self, connector_name):
        connector = SETTINGS.connector_config(connector_name)
        if not connector:
            self._send_json(404, {"message": f"Unknown connector: {connector_name}"})
            return

        # The dashboard expects a lightweight health endpoint on the "api" base URL.
        # Our proxy synthesizes it so same-origin health checks don't fail even if the
        # underlying connector runtime does not expose /api/check/health.
        self._send_json(
            200,
            {
                "isSystemHealthy": True,
                "connectorName": connector_name,
                "authMode": SETTINGS.auth_mode,
            },
        )

    def _handle_oidc_login(self, parsed):
        if not SETTINGS.authorization_url or not SETTINGS.token_url:
            self._send_json(500, {"message": "OIDC BFF mode is missing authorizationUrl/tokenUrl"})
            return
        return_to = self._normalize_return_to(
            urllib.parse.parse_qs(parsed.query).get("returnTo", [None])[0],
            SETTINGS.post_login_redirect_path,
        )
        state, verifier, challenge = SETTINGS.create_auth_request(return_to)
        redirect_uri = self._callback_url()
        query_params = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": SETTINGS.client_id,
                "redirect_uri": redirect_uri,
                "scope": SETTINGS.scope,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        location = f"{SETTINGS.authorization_url}?{query_params}"
        self._send_redirect(location)

    def _handle_oidc_callback(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        if params.get("error"):
            error_value = params.get("error", ["unknown"])[0]
            error_description = params.get("error_description", [None])[0]
            self._redirect_with_flash_notice(
                SETTINGS.post_login_redirect_path,
                event="callback-error",
                message=error_description or f"OIDC authorization failed: {error_value}",
                level="error",
                set_cookie_headers=[self._clear_session_cookie_header()],
            )
            return

        state = params.get("state", [None])[0]
        code = params.get("code", [None])[0]
        if not state or not code:
            self._redirect_with_flash_notice(
                SETTINGS.post_login_redirect_path,
                event="callback-error",
                message="OIDC callback requires both code and state.",
                level="error",
                set_cookie_headers=[self._clear_session_cookie_header()],
            )
            return

        auth_request = SETTINGS.consume_auth_request(state)
        if not auth_request:
            self._redirect_with_flash_notice(
                SETTINGS.post_login_redirect_path,
                event="callback-error",
                message="The login request expired or is no longer valid. Please try again.",
                level="error",
                set_cookie_headers=[self._clear_session_cookie_header()],
            )
            return

        try:
            token_payload = SETTINGS.exchange_authorization_code(
                code,
                self._callback_url(),
                auth_request["verifier"],
            )
        except Exception as exc:
            self._redirect_with_flash_notice(
                SETTINGS.post_login_redirect_path,
                event="callback-error",
                message=f"Keycloak token exchange failed: {str(exc)}",
                level="error",
                set_cookie_headers=[self._clear_session_cookie_header()],
            )
            return

        session = SETTINGS.create_oidc_session(token_payload)
        self._send_redirect(
            auth_request["return_to"],
            set_cookie_headers=[self._session_cookie_header(session["session_id"])],
        )

    def _handle_oidc_logout(self):
        session_id = self._cookie_value(SETTINGS.cookie_name)
        session = SETTINGS.oidc_session(session_id) if session_id else None
        id_token = (session or {}).get("id_token")
        SETTINGS.delete_session(session_id)

        flash_id = SETTINGS.create_flash_notice(
            "logged-out",
            "Your dashboard session has been closed.",
            level="info",
        )
        post_logout_redirect_uri = f"{self._external_base_url()}{SETTINGS.post_logout_redirect_path}"
        if SETTINGS.logout_url:
            query_params = {"post_logout_redirect_uri": post_logout_redirect_uri}
            if id_token:
                query_params["id_token_hint"] = id_token
            location = f"{SETTINGS.logout_url}?{urllib.parse.urlencode(query_params)}"
        else:
            location = SETTINGS.post_logout_redirect_path

        self._send_redirect(
            location,
            set_cookie_headers=[
                self._clear_session_cookie_header(),
                self._flash_cookie_header(flash_id),
            ],
        )

    def _handle_request(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/edc-dashboard-api/auth/me":
            self._handle_auth_info()
            return
        if parsed.path == SETTINGS.login_path:
            if SETTINGS.auth_mode != "oidc-bff":
                self._send_json(501, {"message": "Login is only available in oidc-bff mode"})
            else:
                self._handle_oidc_login(parsed)
            return
        if parsed.path == SETTINGS.callback_path:
            if SETTINGS.auth_mode != "oidc-bff":
                self._send_json(501, {"message": "OIDC callback is only available in oidc-bff mode"})
            else:
                self._handle_oidc_callback(parsed)
            return
        if parsed.path == SETTINGS.logout_path:
            if SETTINGS.auth_mode != "oidc-bff":
                self._send_json(501, {"message": "Logout is only available in oidc-bff mode"})
            else:
                self._handle_oidc_logout()
            return

        if not parsed.path.startswith(PROXY_CONNECTOR_PREFIX):
            self._send_json(404, {"message": "Unsupported dashboard proxy path"})
            return

        relative = parsed.path[len(PROXY_CONNECTOR_PREFIX):]
        parts = [part for part in relative.split("/") if part]
        if len(parts) < 2:
            self._send_json(404, {"message": "Connector or service segment missing"})
            return

        connector_name = parts[0]
        service_name = parts[1]
        remaining_path = "/".join(parts[2:])
        if service_name not in {"management", "api", "control", "protocol"}:
            self._send_json(404, {"message": f"Unsupported proxied service: {service_name}"})
            return

        try:
            if service_name == "api" and remaining_path == "check/health":
                self._handle_connector_health(connector_name)
                return
            self._proxy_request(connector_name, service_name, remaining_path, parsed.query)
        except KeyError as exc:
            self._send_json(404, {"message": str(exc)})

    def log_message(self, format_string, *args):
        print(format_string % args, flush=True)


def main():
    port = int(os.getenv("PROXY_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardProxyHandler)
    print(f"EDC dashboard proxy listening on port {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
