"""Pure INESData access URL helpers.

These helpers are intentionally free from CLI/bootstrap dependencies so they
can be reused by the menu, previews and tests without requiring optional
packages such as ``click``.
"""

import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from deployers.infrastructure.lib.public_hostnames import (  # noqa: E402
    clean_public_hostname,
    resolved_common_service_hostnames,
)
from deployers.shared.lib.vm_distributed_public_access import resolve_vm_distributed_public_urls  # noqa: E402


URL_DEV = ".dev.ds.dataspaceunit.upm"
PUBLIC_COMMON_ACCESS_KEYS = (
    "VM_SINGLE_PUBLIC_URL",
    "VM_SINGLE_HTTP_URL",
    "VM_COMMON_PUBLIC_URL",
    "VM_COMMON_HTTP_URL",
    "PUBLIC_PORTAL_PUBLIC_URL",
    "PUBLIC_PORTAL_BACKEND_PUBLIC_URL",
    "REGISTRATION_SERVICE_PUBLIC_URL",
    "KEYCLOAK_FRONTEND_URL",
    "KEYCLOAK_PUBLIC_URL",
    "MINIO_API_PUBLIC_URL",
    "MINIO_PUBLIC_URL",
    "MINIO_CONSOLE_PUBLIC_URL",
    "COMPONENTS_PUBLIC_BASE_URL",
    "PUBLIC_HOSTNAME",
)


def clean_hostname(value):
    return clean_public_hostname(value)


def normalize_base_href(value):
    base_href = str(value or "/edc-dashboard/").strip() or "/edc-dashboard/"
    if not base_href.startswith("/"):
        base_href = f"/{base_href}"
    if not base_href.endswith("/"):
        base_href = f"{base_href}/"
    return base_href


def normalize_url(value):
    return str(value or "").strip().rstrip("/")


def normalize_public_url_with_trailing_slash(value):
    normalized = normalize_url(value)
    if not normalized:
        return ""
    return f"{normalized}/"


def connector_short_name(connector, dataspace):
    value = str(connector or "").strip()
    if value.startswith("conn-"):
        value = value[len("conn-"):]
    suffix = f"-{dataspace}"
    if dataspace and value.endswith(suffix):
        value = value[: -len(suffix)]
    return value


def split_config_list(raw_value):
    return [
        item.strip()
        for item in str(raw_value or "").split(",")
        if item.strip()
    ]


def connector_matches_configured_name(connector, dataspace, configured_name):
    configured = str(configured_name or "").strip()
    if not configured:
        return False
    aliases = {
        str(connector or "").strip(),
        connector_short_name(connector, dataspace),
    }
    if not configured.startswith("conn-") and dataspace:
        aliases.add(f"conn-{configured}-{dataspace}")
    return configured in aliases


def connector_public_base_url(connector, dataspace, config):
    public_urls = resolve_vm_distributed_public_urls(config)
    role_options = (
        ("VM_PROVIDER_CONNECTORS", "VM_PROVIDER_PUBLIC_URL", "VM_PROVIDER_HTTP_URL"),
        ("VM_CONSUMER_CONNECTORS", "VM_CONSUMER_PUBLIC_URL", "VM_CONSUMER_HTTP_URL"),
    )
    for connectors_key, public_url_key, fallback_url_key in role_options:
        for configured_connector in split_config_list(config.get(connectors_key)):
            if connector_matches_configured_name(connector, dataspace, configured_connector):
                return normalize_url(
                    config.get(public_url_key)
                    or public_urls.get(public_url_key)
                    or config.get(fallback_url_key)
                )
    return ""


def normalize_keycloak_frontend_url(value, realm_name=None):
    frontend_url = normalize_url(value)
    if not frontend_url:
        return ""

    realm = str(realm_name or "").strip().strip("/")
    if realm:
        for suffix in (
            f"/realms/{realm}/.well-known/openid-configuration",
            f"/realms/{realm}",
        ):
            if frontend_url.endswith(suffix):
                frontend_url = frontend_url[: -len(suffix)].rstrip("/")
                break

    return frontend_url


def keycloak_public_base_url(config, dataspace):
    public_urls = resolve_vm_distributed_public_urls(config)
    explicit_url = (
        config.get("KEYCLOAK_FRONTEND_URL")
        or config.get("KEYCLOAK_PUBLIC_URL")
        or public_urls.get("KEYCLOAK_FRONTEND_URL")
        or public_urls.get("KEYCLOAK_PUBLIC_URL")
    )
    if explicit_url:
        return normalize_keycloak_frontend_url(explicit_url, dataspace)

    public_hostname = clean_hostname(config.get("PUBLIC_HOSTNAME"))
    if public_hostname:
        return f"https://{public_hostname}/auth"

    return ""


def minio_console_public_url(config):
    public_urls = resolve_vm_distributed_public_urls(config)
    explicit_url = config.get("MINIO_CONSOLE_PUBLIC_URL") or public_urls.get("MINIO_CONSOLE_PUBLIC_URL")
    if explicit_url:
        return normalize_public_url_with_trailing_slash(explicit_url)

    public_hostname = clean_hostname(config.get("PUBLIC_HOSTNAME"))
    if public_hostname:
        return f"https://{public_hostname}/s3-console/"

    common_public_url = normalize_url(config.get("VM_COMMON_PUBLIC_URL") or config.get("VM_COMMON_HTTP_URL"))
    if common_public_url:
        return f"{common_public_url}/s3-console/"

    return ""


def minio_api_public_url(config):
    public_urls = resolve_vm_distributed_public_urls(config)
    return normalize_url(
        config.get("MINIO_API_PUBLIC_URL")
        or config.get("MINIO_PUBLIC_URL")
        or public_urls.get("MINIO_API_PUBLIC_URL")
        or public_urls.get("MINIO_PUBLIC_URL")
    )


def _is_vm_distributed_public_common_mode(config):
    values = config or {}
    topology = str(
        values.get("TOPOLOGY")
        or values.get("PIONERA_TOPOLOGY")
        or values.get("INESDATA_TOPOLOGY")
        or ""
    ).strip().lower().replace("_", "-")
    if topology == "vm-distributed":
        return True
    if topology == "vm-single" and str(values.get("VM_SINGLE_HTTP_URL") or values.get("VM_SINGLE_PUBLIC_URL") or "").strip():
        return True
    return any(str(values.get(key) or "").strip() for key in PUBLIC_COMMON_ACCESS_KEYS)


def common_public_access_urls(dataspace, config):
    if not _is_vm_distributed_public_common_mode(config):
        return {}

    urls = {}
    keycloak_base = keycloak_public_base_url(config, dataspace)
    if keycloak_base:
        urls.update(
            {
                "keycloak_realm": f"{keycloak_base}/realms/{dataspace}",
                "keycloak_account": f"{keycloak_base}/realms/{dataspace}/account",
                "keycloak_admin_console": f"{keycloak_base}/admin/{dataspace}/console/",
            }
        )

    minio_api = minio_api_public_url(config)
    if minio_api:
        urls["minio_api"] = minio_api

    minio_console = minio_console_public_url(config)
    if minio_console:
        urls["minio_console"] = minio_console

    return urls


def dataspace_public_access_urls(dataspace, config):
    if not _is_vm_distributed_public_common_mode(config):
        return {}

    values = {**dict(config or {}), **resolve_vm_distributed_public_urls(config)}
    urls = {}

    public_portal = normalize_public_url_with_trailing_slash(
        values.get("PUBLIC_PORTAL_PUBLIC_URL")
        or values.get("DATASPACE_PUBLIC_PORTAL_URL")
    )
    if public_portal:
        urls["public_portal_login"] = public_portal

    public_portal_backend = normalize_url(
        values.get("PUBLIC_PORTAL_BACKEND_PUBLIC_URL")
        or values.get("DATASPACE_PUBLIC_PORTAL_BACKEND_URL")
    )
    if public_portal_backend:
        urls["public_portal_backend_admin"] = (
            public_portal_backend
            if public_portal_backend.rstrip("/").endswith("/admin")
            else f"{public_portal_backend}/admin"
        )

    registration_service = normalize_url(
        values.get("REGISTRATION_SERVICE_PUBLIC_URL")
        or values.get("DATASPACE_REGISTRATION_SERVICE_PUBLIC_URL")
    )
    if registration_service:
        urls["registration_service"] = registration_service

    return urls


def access_protocol(environment):
    return "https" if str(environment or "").strip().upper() == "PRO" else "http"


def dataspace_domain_base(config, environment):
    if str(environment or "").strip().upper() == "PRO":
        return "ds.dataspaceunit-project.eu"
    configured = str(config.get("DS_DOMAIN_BASE", "")).strip()
    return configured or URL_DEV.lstrip(".")


def build_dataspace_access_urls(dataspace, environment, config):
    if _is_vm_distributed_public_common_mode(config):
        urls = dataspace_public_access_urls(dataspace, config)
    else:
        protocol = access_protocol(environment)
        ds_domain = dataspace_domain_base(config, environment)
        urls = {
            "public_portal_login": f"{protocol}://{dataspace}.{ds_domain}",
            "public_portal_backend_admin": f"{protocol}://backend-{dataspace}.{ds_domain}/admin",
            "registration_service": f"{protocol}://registration-service-{dataspace}.{ds_domain}",
        }
    urls.update(common_access_urls(dataspace, environment, config))
    return urls


def build_connector_access_urls(connector, dataspace, environment, config, dashboard=False):
    protocol = access_protocol(environment)
    ds_domain = dataspace_domain_base(config, environment)
    connector_base = f"{protocol}://{connector}.{ds_domain}"
    connector_interface_base_href = normalize_base_href(
        config.get("INESDATA_CONNECTOR_INTERFACE_BASE_HREF", "/inesdata-connector-interface/")
    )
    urls = {
        "connector_ingress": connector_base,
        "connector_interface_login": f"{connector_base}{connector_interface_base_href}",
        "connector_management_api": f"{connector_base}/management",
        "connector_protocol_api": f"{connector_base}/protocol",
        "connector_shared_api": f"{connector_base}/shared",
        "minio_bucket": f"{dataspace}-{connector}",
    }
    if dashboard:
        dashboard_base_href = normalize_base_href(config.get("EDC_DASHBOARD_BASE_HREF", "/edc-dashboard/"))
        urls["edc_dashboard_login"] = f"{connector_base}{dashboard_base_href}"
        if str(config.get("EDC_DASHBOARD_PROXY_AUTH_MODE", "")).strip().lower() == "oidc-bff":
            urls["edc_dashboard_oidc_login"] = f"{connector_base}/edc-dashboard-api/auth/login"
    urls.update(common_access_urls(dataspace, environment, config))
    return urls


def build_connector_public_access_urls(connector, dataspace, environment, config, dashboard=False):
    connector_base = connector_public_base_url(connector, dataspace, config)
    connector_interface_base_href = normalize_base_href(
        config.get("INESDATA_CONNECTOR_INTERFACE_BASE_HREF", "/inesdata-connector-interface/")
    )
    urls = {}
    if connector_base:
        urls.update(
            {
                "connector_ingress": connector_base,
                "connector_interface_login": f"{connector_base}{connector_interface_base_href}",
                "connector_management_api": f"{connector_base}/management",
                "connector_protocol_api": f"{connector_base}/protocol",
                "connector_shared_api": f"{connector_base}/shared",
                "minio_bucket": f"{dataspace}-{connector}",
            }
        )
        if dashboard:
            dashboard_base_href = normalize_base_href(config.get("EDC_DASHBOARD_BASE_HREF", "/edc-dashboard/"))
            urls["edc_dashboard_login"] = f"{connector_base}{dashboard_base_href}"
            if str(config.get("EDC_DASHBOARD_PROXY_AUTH_MODE", "")).strip().lower() == "oidc-bff":
                urls["edc_dashboard_oidc_login"] = f"{connector_base}/edc-dashboard-api/auth/login"

    keycloak_base = keycloak_public_base_url(config, dataspace)
    if keycloak_base:
        urls.update(
            {
                "keycloak_realm": f"{keycloak_base}/realms/{dataspace}",
                "keycloak_account": f"{keycloak_base}/realms/{dataspace}/account",
                "keycloak_admin_console": f"{keycloak_base}/admin/{dataspace}/console/",
            }
        )

    minio_console = minio_console_public_url(config)
    if minio_console:
        urls["minio_console"] = minio_console

    minio_api = minio_api_public_url(config)
    if minio_api:
        urls["minio_api"] = minio_api

    return urls


def common_access_urls(dataspace, environment, config):
    protocol = access_protocol(environment)
    resolved_hostnames = resolved_common_service_hostnames(config)
    keycloak_hostname = resolved_hostnames["keycloak_hostname"]
    keycloak_admin_hostname = resolved_hostnames["keycloak_admin_hostname"]
    minio_api_hostname = resolved_hostnames["minio_hostname"]
    minio_console_hostname = resolved_hostnames["minio_console_hostname"]
    urls = {
        "keycloak_realm": f"{protocol}://{keycloak_hostname}/realms/{dataspace}",
        "keycloak_account": f"{protocol}://{keycloak_hostname}/realms/{dataspace}/account",
        "keycloak_admin_console": f"{protocol}://{keycloak_admin_hostname}/admin/{dataspace}/console/",
        "minio_api": f"{protocol}://{minio_api_hostname}",
        "minio_console": f"{protocol}://{minio_console_hostname}",
    }
    urls.update(common_public_access_urls(dataspace, config))
    return urls


def dataspace_index(config, dataspace_name, dataspace_namespace=None):
    target_name = str(dataspace_name or "").strip()
    target_namespace = str(dataspace_namespace or "").strip()
    index = 1

    while True:
        configured_name = str(config.get(f"DS_{index}_NAME", "") or "").strip()
        configured_namespace = str(config.get(f"DS_{index}_NAMESPACE", "") or configured_name).strip()
        if not configured_name:
            break
        if target_name and configured_name == target_name:
            return index
        if target_namespace and configured_namespace == target_namespace:
            return index
        index += 1

    return 1


def registration_service_namespace(config, dataspace_name, dataspace_namespace=None):
    resolved_namespace = str(dataspace_namespace or dataspace_name or "").strip() or str(dataspace_name or "").strip()
    index = dataspace_index(config, dataspace_name, dataspace_namespace)
    configured = str(config.get(f"DS_{index}_REGISTRATION_NAMESPACE", "") or "").strip()
    if configured:
        return configured

    profile = str(config.get("NAMESPACE_PROFILE", "compact") or "compact").strip().lower().replace("_", "-")
    if profile in {"role-aligned", "rolealigned", "aligned", "roles"}:
        return f"{dataspace_name}-core"

    return resolved_namespace


def registration_service_internal_hostname(
    config,
    dataspace_name,
    environment,
    *,
    connector_namespace=None,
    dataspace_namespace=None,
):
    if str(environment or "").strip().upper() == "PRO":
        return f"registration-service-{dataspace_name}.ds.dataspaceunit-project.eu"

    index = dataspace_index(config, dataspace_name, dataspace_namespace)
    resolved_dataspace_namespace = (
        str(dataspace_namespace or "").strip()
        or str(config.get(f"DS_{index}_NAMESPACE", "") or "").strip()
        or str(dataspace_name or "").strip()
    )
    resolved_connector_namespace = str(connector_namespace or resolved_dataspace_namespace).strip() or resolved_dataspace_namespace
    resolved_registration_namespace = registration_service_namespace(
        config,
        dataspace_name,
        resolved_dataspace_namespace,
    )
    service_name = f"{dataspace_name}-registration-service"
    if resolved_registration_namespace and resolved_registration_namespace != resolved_connector_namespace:
        return f"{service_name}.{resolved_registration_namespace}.svc.cluster.local:8080"
    return f"{service_name}:8080"
