"""Connector host synchronization helpers used by Level 6 validation."""

from __future__ import annotations

import warnings
from typing import Any, Callable
from urllib.parse import urlparse

import requests


def connector_hosts_resolve(
    connectors: list[str],
    *,
    domain: str | None,
    resolver: Callable[[str], str],
) -> list[str]:
    unresolved: list[str] = []
    if not domain:
        return unresolved

    for connector in connectors or []:
        host = f"{connector}.{domain}"
        try:
            resolver(host)
        except OSError:
            unresolved.append(host)

    return unresolved


def ensure_connector_hosts(
    connectors: list[str],
    *,
    config_adapter: Any,
    infrastructure_adapter: Any,
    domain: str | None,
    resolver: Callable[[str], str],
    header_comment: str = "# Dataspace Connector Hosts",
) -> None:
    connector_hosts = config_adapter.generate_connector_hosts(connectors)
    if connector_hosts:
        infrastructure_adapter.manage_hosts_entries(
            connector_hosts,
            header_comment=header_comment,
        )

    unresolved = connector_hosts_resolve(
        connectors,
        domain=domain,
        resolver=resolver,
    )
    if unresolved:
        joined = ", ".join(unresolved)
        raise RuntimeError(
            "Connector hostnames do not resolve locally. "
            f"Check /etc/hosts and minikube tunnel for: {joined}"
        )


def normalize_public_endpoint_url(value: str | None) -> str | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    if not raw_value.startswith(("http://", "https://")):
        raw_value = f"http://{raw_value}"
    parsed = urlparse(raw_value)
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname or hostname in {"localhost", "127.0.0.1", "::1"}:
        return None
    if hostname.endswith(".svc") or ".svc." in hostname:
        return None
    return raw_value.rstrip("/")


def normalize_public_endpoint_tls_verify_mode(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    raw_value = str(value).strip().lower()
    aliases = {
        "1": "true",
        "yes": "true",
        "on": "true",
        "0": "false",
        "no": "false",
        "off": "false",
        "detect": "auto",
    }
    mode = aliases.get(raw_value, raw_value)
    return mode if mode in {"auto", "true", "false"} else None


def _request_public_endpoint(requester: Callable[..., Any], url: str, **kwargs: Any) -> Any:
    try:
        return requester(url, **kwargs)
    except TypeError as exc:
        if "verify" in kwargs and "verify" in str(exc):
            kwargs.pop("verify", None)
            return requester(url, **kwargs)
        raise


def _public_endpoint_tls_verify_kwargs(url: str, mode: str | None) -> dict[str, bool]:
    if not mode:
        return {}
    if str(urlparse(url).scheme or "").lower() != "https":
        return {}
    if mode in {"auto", "true"}:
        return {"verify": True}
    if mode == "false":
        return {"verify": False}
    return {}


def check_public_endpoints_access(
    endpoints: list[dict[str, str]],
    *,
    requester: Callable[..., Any] | None = None,
    timeout: int = 5,
    tls_verify: Any = None,
) -> dict[str, Any]:
    request = requester or requests.get
    tls_verify_mode = normalize_public_endpoint_tls_verify_mode(tls_verify)
    checked: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    tls_warnings: list[dict[str, str]] = []

    for endpoint in endpoints or []:
        label = str(endpoint.get("label") or endpoint.get("url") or "endpoint")
        url = normalize_public_endpoint_url(endpoint.get("url"))
        if not url:
            continue
        request_kwargs = {
            "timeout": timeout,
            "allow_redirects": False,
            **_public_endpoint_tls_verify_kwargs(url, tls_verify_mode),
        }
        try:
            response = _request_public_endpoint(request, url, **request_kwargs)
            checked.append(
                {
                    "label": label,
                    "url": url,
                    "status_code": getattr(response, "status_code", None),
                }
            )
        except requests.exceptions.SSLError as exc:
            if tls_verify_mode != "auto" or str(urlparse(url).scheme or "").lower() != "https":
                failures.append(
                    {
                        "label": label,
                        "url": url,
                        "error": str(exc),
                    }
                )
                continue
            try:
                retry_kwargs = dict(request_kwargs)
                retry_kwargs["verify"] = False
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    response = _request_public_endpoint(request, url, **retry_kwargs)
                checked.append(
                    {
                        "label": label,
                        "url": url,
                        "status_code": getattr(response, "status_code", None),
                        "tls_verification": "disabled-after-certificate-failure",
                    }
                )
                tls_warnings.append(
                    {
                        "label": label,
                        "url": url,
                        "reason": "certificate-verification-failed",
                        "detail": str(exc),
                    }
                )
            except Exception as retry_exc:
                failures.append(
                    {
                        "label": label,
                        "url": url,
                        "error": (
                            f"{str(exc)} | retry without TLS verification: {str(retry_exc)}"
                        ),
                    }
                )
        except Exception as exc:
            failures.append(
                {
                    "label": label,
                    "url": url,
                    "error": str(exc),
                }
            )

    return {
        "status": "failed" if failures else "passed-with-warnings" if tls_warnings else "passed",
        "checked": checked,
        "failures": failures,
        "tls_warnings": tls_warnings,
    }


def format_public_endpoint_access_error(result: dict[str, Any], *, topology: str = "local") -> str:
    failures = list(result.get("failures") or [])
    lines = ["Public ingress endpoints are not reachable from this machine."]
    for failure in failures:
        lines.append(
            "- "
            f"{failure.get('label')}: {failure.get('url')} "
            f"({failure.get('error')})"
        )

    if str(topology or "local").strip().lower() == "local":
        lines.extend(
            [
                "For local topology, keep `minikube tunnel` running in a separate terminal.",
                "If that terminal shows `[sudo] password for <user>:`, enter your Linux/WSL sudo password there, then retry the level.",
                "The framework does not collect, store or proxy sudo passwords.",
                "Level 6 full validation still requires these public hostnames for Newman and Playwright.",
                "The local Kafka HTTP port-forward fallback is only a safety net for isolated local Kafka checks; it does not replace public ingress for the complete Level 6 flow.",
            ]
        )
    else:
        lines.append(
            "Check DNS/hosts entries and the ingress endpoint for the selected VM topology."
        )
    return "\n".join(lines)


def ensure_public_endpoints_accessible(
    endpoints: list[dict[str, str]],
    *,
    topology: str = "local",
    requester: Callable[..., Any] | None = None,
    timeout: int = 5,
    tls_verify: Any = None,
) -> dict[str, Any]:
    result = check_public_endpoints_access(
        endpoints,
        requester=requester,
        timeout=timeout,
        tls_verify=tls_verify,
    )
    if result["status"] == "failed":
        raise RuntimeError(format_public_endpoint_access_error(result, topology=topology))
    return result
