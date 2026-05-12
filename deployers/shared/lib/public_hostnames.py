from __future__ import annotations

import ipaddress
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse


DEFAULT_COMMON_DOMAIN_BASE = "dev.ed.dataspaceunit.upm"

KEYCLOAK_HOSTNAME = "keycloak_hostname"
KEYCLOAK_ADMIN_HOSTNAME = "keycloak_admin_hostname"
MINIO_HOSTNAME = "minio_hostname"
MINIO_CONSOLE_HOSTNAME = "minio_console_hostname"

_SERVICE_KEYS = (
    KEYCLOAK_HOSTNAME,
    KEYCLOAK_ADMIN_HOSTNAME,
    MINIO_HOSTNAME,
    MINIO_CONSOLE_HOSTNAME,
)


def clean_public_hostname(value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    parsed = urlparse(raw_value)
    if parsed.netloc:
        return parsed.netloc.strip()
    if "://" not in raw_value:
        return raw_value.split("/", 1)[0].strip()
    return ""


def is_loopback_hostname(value: Any) -> bool:
    hostname = clean_public_hostname(value).lower()
    if not hostname:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def is_cluster_internal_hostname(value: Any) -> bool:
    hostname = clean_public_hostname(value).lower()
    if not hostname:
        return False
    return (
        hostname.endswith(".svc")
        or ".svc." in hostname
        or hostname.endswith(".cluster.local")
        or ".cluster.local" in hostname
    )


def is_public_hostname_candidate(value: Any) -> bool:
    hostname = clean_public_hostname(value)
    if not hostname:
        return False
    return not is_loopback_hostname(hostname) and not is_cluster_internal_hostname(hostname)


def _promote_keycloak_hostname(hostname: str) -> str:
    cleaned = clean_public_hostname(hostname)
    if cleaned.startswith("keycloak-admin."):
        return cleaned.replace("keycloak-admin.", "admin.auth.", 1)
    if cleaned.startswith("keycloak."):
        return cleaned.replace("keycloak.", "auth.", 1)
    return cleaned


def normalize_common_domain_base(value: Any, *, default: str = DEFAULT_COMMON_DOMAIN_BASE) -> str:
    normalized = str(value or "").strip()
    return normalized or default


def canonical_common_service_hostnames(domain_base: Any) -> dict[str, str]:
    normalized_domain = normalize_common_domain_base(domain_base)
    return {
        KEYCLOAK_HOSTNAME: f"auth.{normalized_domain}",
        KEYCLOAK_ADMIN_HOSTNAME: f"admin.auth.{normalized_domain}",
        MINIO_HOSTNAME: f"minio.{normalized_domain}",
        MINIO_CONSOLE_HOSTNAME: f"console.minio-s3.{normalized_domain}",
    }


def legacy_common_service_hostnames(domain_base: Any) -> dict[str, str]:
    normalized_domain = normalize_common_domain_base(domain_base)
    return {
        KEYCLOAK_HOSTNAME: f"keycloak.{normalized_domain}",
        KEYCLOAK_ADMIN_HOSTNAME: f"keycloak-admin.{normalized_domain}",
        MINIO_HOSTNAME: f"minio.{normalized_domain}",
        MINIO_CONSOLE_HOSTNAME: f"console.minio-s3.{normalized_domain}",
    }


def resolved_common_service_hostnames(config: Mapping[str, Any] | None) -> dict[str, str]:
    values = dict(config or {})
    domain_base = normalize_common_domain_base(values.get("DOMAIN_BASE"))
    canonical = canonical_common_service_hostnames(domain_base)
    resolved = dict(canonical)

    keycloak_hostname = clean_public_hostname(values.get("KEYCLOAK_HOSTNAME"))
    if not is_public_hostname_candidate(keycloak_hostname):
        keycloak_hostname = clean_public_hostname(values.get("KC_INTERNAL_URL"))
    if is_public_hostname_candidate(keycloak_hostname):
        resolved[KEYCLOAK_HOSTNAME] = _promote_keycloak_hostname(keycloak_hostname)

    keycloak_admin_hostname = clean_public_hostname(values.get("KEYCLOAK_ADMIN_HOSTNAME"))
    if not is_public_hostname_candidate(keycloak_admin_hostname):
        keycloak_admin_hostname = clean_public_hostname(values.get("KC_URL"))
    if is_public_hostname_candidate(keycloak_admin_hostname):
        promoted_admin_hostname = _promote_keycloak_hostname(keycloak_admin_hostname)
        if promoted_admin_hostname.startswith("auth."):
            resolved[KEYCLOAK_ADMIN_HOSTNAME] = canonical[KEYCLOAK_ADMIN_HOSTNAME]
        elif promoted_admin_hostname.startswith("admin.auth."):
            resolved[KEYCLOAK_ADMIN_HOSTNAME] = promoted_admin_hostname
        else:
            resolved[KEYCLOAK_ADMIN_HOSTNAME] = keycloak_admin_hostname

    minio_hostname = clean_public_hostname(values.get("MINIO_HOSTNAME"))
    if not is_public_hostname_candidate(minio_hostname):
        minio_hostname = clean_public_hostname(values.get("MINIO_ENDPOINT"))
    if is_public_hostname_candidate(minio_hostname):
        resolved[MINIO_HOSTNAME] = minio_hostname

    minio_console_hostname = clean_public_hostname(values.get("MINIO_CONSOLE_HOSTNAME"))
    if is_public_hostname_candidate(minio_console_hostname):
        resolved[MINIO_CONSOLE_HOSTNAME] = minio_console_hostname

    return resolved


def canonical_common_service_config_values(domain_base: Any, *, protocol: str = "http") -> dict[str, str]:
    hostnames = canonical_common_service_hostnames(domain_base)
    protocol_prefix = f"{str(protocol or 'http').strip().rstrip(':/')}://"
    return {
        "KC_INTERNAL_URL": f"{protocol_prefix}{hostnames[KEYCLOAK_HOSTNAME]}",
        "KC_URL": f"{protocol_prefix}{hostnames[KEYCLOAK_ADMIN_HOSTNAME]}",
        "KEYCLOAK_HOSTNAME": hostnames[KEYCLOAK_HOSTNAME],
        "KEYCLOAK_ADMIN_HOSTNAME": hostnames[KEYCLOAK_ADMIN_HOSTNAME],
        "MINIO_HOSTNAME": hostnames[MINIO_HOSTNAME],
        "MINIO_CONSOLE_HOSTNAME": hostnames[MINIO_CONSOLE_HOSTNAME],
    }


def replace_hostname_in_url(value: Any, hostname: str) -> str:
    raw_value = str(value or "").strip()
    replacement = str(hostname or "").strip()
    if not raw_value:
        return replacement
    if not replacement:
        return raw_value
    parsed = urlparse(raw_value)
    if parsed.netloc:
        port = f":{parsed.port}" if parsed.port else ""
        return urlunparse(parsed._replace(netloc=f"{replacement}{port}"))
    if "://" not in raw_value:
        return replacement
    return raw_value


def resolved_common_service_urls(config: Mapping[str, Any] | None, *, protocol: str = "http") -> dict[str, str]:
    values = dict(config or {})
    domain_base = normalize_common_domain_base(values.get("DOMAIN_BASE"))
    resolved_hostnames = resolved_common_service_hostnames(values)
    legacy_hostnames = legacy_common_service_hostnames(domain_base)
    protocol_prefix = f"{str(protocol or 'http').strip().rstrip(':/')}://"

    resolved_internal_url = str(values.get("KC_INTERNAL_URL") or "").strip()
    if clean_public_hostname(resolved_internal_url) == legacy_hostnames[KEYCLOAK_HOSTNAME]:
        resolved_internal_url = replace_hostname_in_url(
            resolved_internal_url,
            resolved_hostnames[KEYCLOAK_HOSTNAME],
        )
    elif not resolved_internal_url:
        resolved_internal_url = f"{protocol_prefix}{resolved_hostnames[KEYCLOAK_HOSTNAME]}"

    resolved_admin_url = str(values.get("KC_URL") or "").strip()
    if clean_public_hostname(resolved_admin_url) == legacy_hostnames[KEYCLOAK_ADMIN_HOSTNAME]:
        resolved_admin_url = replace_hostname_in_url(
            resolved_admin_url,
            resolved_hostnames[KEYCLOAK_ADMIN_HOSTNAME],
        )
    elif clean_public_hostname(resolved_admin_url) == legacy_hostnames[KEYCLOAK_HOSTNAME]:
        resolved_admin_url = replace_hostname_in_url(
            resolved_admin_url,
            resolved_hostnames[KEYCLOAK_HOSTNAME],
        )
    elif not resolved_admin_url:
        resolved_admin_url = f"{protocol_prefix}{resolved_hostnames[KEYCLOAK_ADMIN_HOSTNAME]}"

    return {
        "KC_INTERNAL_URL": resolved_internal_url,
        "KC_URL": resolved_admin_url,
    }
