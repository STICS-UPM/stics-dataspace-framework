from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse

from .config_loader import load_deployer_config
from .connectors import normalize_connector_name, parse_connector_list, parse_connector_mapping


@dataclass(frozen=True, slots=True)
class PublicConnector:
    short_name: str
    full_name: str
    canonical_hostname: str


@dataclass(frozen=True, slots=True)
class PublicRoleEndpoint:
    role: str
    vm_ip: str
    public_url: str
    public_hostname: str
    listen_port: int
    target_port: int
    connectors: tuple[PublicConnector, ...]


@dataclass(frozen=True, slots=True)
class VmDistributedPublicAccessPlan:
    dataspace_name: str
    ds_domain_base: str
    common: PublicRoleEndpoint
    provider: PublicRoleEndpoint
    consumer: PublicRoleEndpoint


def load_vm_distributed_public_access_config(root_dir: str, adapter: str = "inesdata") -> dict[str, str]:
    """Load the effective config used to render vm-distributed public access artifacts."""
    root = os.path.abspath(root_dir)
    normalized_adapter = str(adapter or "inesdata").strip().lower() or "inesdata"
    paths = [
        os.path.join(root, "deployers", "infrastructure", "deployer.config.example"),
        os.path.join(root, "deployers", "infrastructure", "deployer.config"),
        os.path.join(root, "deployers", "infrastructure", "topologies", "vm-distributed.config.example"),
        os.path.join(root, "deployers", "infrastructure", "topologies", "vm-distributed.config"),
        os.path.join(root, "deployers", normalized_adapter, "deployer.config.example"),
        os.path.join(root, "deployers", normalized_adapter, "deployer.config"),
    ]
    config: dict[str, str] = {}
    for path in paths:
        config.update(load_deployer_config(path))
    return config


def build_vm_distributed_public_access_plan(config: dict[str, str]) -> VmDistributedPublicAccessPlan:
    values = dict(config or {})
    values.update(resolve_vm_distributed_public_urls(values))
    ds_name = str(values.get("DS_1_NAME") or "pionera").strip() or "pionera"
    ds_domain_base = str(values.get("DS_DOMAIN_BASE") or values.get("DOMAIN_BASE") or "").strip()

    provider_connectors = _role_connectors(values, ds_name, "provider")
    consumer_connectors = _role_connectors(values, ds_name, "consumer")

    return VmDistributedPublicAccessPlan(
        dataspace_name=ds_name,
        ds_domain_base=ds_domain_base,
        common=_endpoint(
            values,
            role="common",
            ip_key="VM_COMMON_IP",
            public_url_key="VM_COMMON_PUBLIC_URL",
            http_port_key="VM_COMMON_INGRESS_HTTP_PORT",
            nodeport_key="VM_COMMON_INGRESS_NODEPORT",
            connectors=(),
            default_port=80,
        ),
        provider=_endpoint(
            values,
            role="provider",
            ip_key="VM_PROVIDER_IP",
            public_url_key="VM_PROVIDER_PUBLIC_URL",
            http_port_key="VM_PROVIDER_INGRESS_HTTP_PORT",
            nodeport_key="VM_PROVIDER_INGRESS_NODEPORT",
            connectors=tuple(_public_connector(item, ds_name, ds_domain_base) for item in provider_connectors),
            default_port=80,
        ),
        consumer=_endpoint(
            values,
            role="consumer",
            ip_key="VM_CONSUMER_IP",
            public_url_key="VM_CONSUMER_PUBLIC_URL",
            http_port_key="VM_CONSUMER_INGRESS_HTTP_PORT",
            nodeport_key="VM_CONSUMER_INGRESS_NODEPORT",
            connectors=tuple(_public_connector(item, ds_name, ds_domain_base) for item in consumer_connectors),
            default_port=80,
        ),
    )


def resolve_vm_distributed_public_urls(config: dict[str, str] | None) -> dict[str, str]:
    """Resolve explicit-or-default browser-facing URLs for vm-distributed.

    Explicit full URLs always win. Missing role URLs are inferred from the
    configured domains with the conventional org1/org2/org3 defaults.
    """
    values = dict(config or {})
    common_domain = _clean_domain(values.get("DOMAIN_BASE") or values.get("DS_DOMAIN_BASE"))
    connector_domain = _clean_domain(values.get("DS_DOMAIN_BASE") or values.get("DOMAIN_BASE"))

    common_url = _clean_public_url(values.get("VM_COMMON_PUBLIC_URL")) or _default_role_url("org1", common_domain)
    provider_url = _clean_public_url(values.get("VM_PROVIDER_PUBLIC_URL")) or _default_role_url("org2", connector_domain)
    consumer_url = _clean_public_url(values.get("VM_CONSUMER_PUBLIC_URL")) or _default_role_url("org3", connector_domain)

    resolved: dict[str, str] = {}
    if common_url:
        resolved["VM_COMMON_PUBLIC_URL"] = common_url
    if provider_url:
        resolved["VM_PROVIDER_PUBLIC_URL"] = provider_url
    if consumer_url:
        resolved["VM_CONSUMER_PUBLIC_URL"] = consumer_url

    keycloak_frontend_url = _clean_public_url(values.get("KEYCLOAK_FRONTEND_URL"))
    keycloak_public_url = _clean_public_url(values.get("KEYCLOAK_PUBLIC_URL"))
    if keycloak_frontend_url:
        resolved["KEYCLOAK_FRONTEND_URL"] = keycloak_frontend_url
    elif keycloak_public_url:
        resolved["KEYCLOAK_PUBLIC_URL"] = keycloak_public_url
    elif common_url:
        resolved["KEYCLOAK_FRONTEND_URL"] = _join_url_path(common_url, "auth")

    minio_console_url = _clean_public_url(values.get("MINIO_CONSOLE_PUBLIC_URL"))
    if minio_console_url:
        resolved["MINIO_CONSOLE_PUBLIC_URL"] = minio_console_url
    elif common_url:
        resolved["MINIO_CONSOLE_PUBLIC_URL"] = _join_url_path(common_url, "s3-console")

    minio_api_url = _clean_public_url(values.get("MINIO_API_PUBLIC_URL") or values.get("MINIO_PUBLIC_URL"))
    if minio_api_url:
        resolved["MINIO_API_PUBLIC_URL"] = minio_api_url
    elif common_url:
        resolved["MINIO_API_PUBLIC_URL"] = common_url

    components_base_url = _clean_public_url(values.get("COMPONENTS_PUBLIC_BASE_URL"))
    if components_base_url:
        resolved["COMPONENTS_PUBLIC_BASE_URL"] = components_base_url
    elif common_url:
        resolved["COMPONENTS_PUBLIC_BASE_URL"] = common_url

    public_portal_backend_url = _clean_public_url(
        values.get("PUBLIC_PORTAL_BACKEND_PUBLIC_URL")
        or values.get("DATASPACE_PUBLIC_PORTAL_BACKEND_URL")
    )
    if public_portal_backend_url:
        resolved["PUBLIC_PORTAL_BACKEND_PUBLIC_URL"] = public_portal_backend_url
        resolved["DATASPACE_PUBLIC_PORTAL_BACKEND_URL"] = public_portal_backend_url
    elif common_url:
        inferred_backend_url = _join_url_path(common_url, "public-portal-backend")
        resolved["PUBLIC_PORTAL_BACKEND_PUBLIC_URL"] = inferred_backend_url
        resolved["DATASPACE_PUBLIC_PORTAL_BACKEND_URL"] = inferred_backend_url

    return resolved


def render_role_http_entrypoint_nginx(endpoint: PublicRoleEndpoint) -> str:
    """Render a VM-local NGINX bridge from the public HTTP port to the Kubernetes ingress port."""
    server_names = _dedupe([endpoint.public_hostname, *(item.canonical_hostname for item in endpoint.connectors)])
    server_name_line = " ".join(server_names) if server_names else "_"
    return (
        f"# Generated from vm-distributed config for {endpoint.role} public access.\n"
        "# Install on the target VM only when the university HTTPS entrypoint expects local HTTP on this VM.\n"
        "server {\n"
        f"    listen {endpoint.listen_port};\n"
        f"    server_name {server_name_line};\n\n"
        "    client_max_body_size 0;\n\n"
        "    location / {\n"
        f"        proxy_pass http://127.0.0.1:{endpoint.target_port};\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Host $host;\n"
        "        proxy_set_header X-Forwarded-Port $server_port;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_set_header Upgrade $http_upgrade;\n"
        '        proxy_set_header Connection "upgrade";\n'
        "        proxy_buffering off;\n"
        "        proxy_request_buffering off;\n"
        "    }\n"
        "}\n"
    )


def render_public_access_summary(plan: VmDistributedPublicAccessPlan) -> str:
    provider_names = ", ".join(item.full_name for item in plan.provider.connectors) or "(none)"
    consumer_names = ", ".join(item.full_name for item in plan.consumer.connectors) or "(none)"
    return (
        "# vm-distributed Public Access Plan\n\n"
        "Generated from the framework configuration files.\n\n"
        "| Role | Public URL | VM IP | Public HTTP port | Connectors |\n"
        "| --- | --- | --- | --- | --- |\n"
        f"| common | {plan.common.public_url} | {plan.common.vm_ip} | {plan.common.listen_port} | services |\n"
        f"| provider | {plan.provider.public_url} | {plan.provider.vm_ip} | {plan.provider.listen_port} | {provider_names} |\n"
        f"| consumer | {plan.consumer.public_url} | {plan.consumer.vm_ip} | {plan.consumer.listen_port} | {consumer_names} |\n"
    )


def _endpoint(
    values: dict[str, str],
    *,
    role: str,
    ip_key: str,
    public_url_key: str,
    http_port_key: str,
    nodeport_key: str,
    connectors: tuple[PublicConnector, ...],
    default_port: int,
) -> PublicRoleEndpoint:
    listen_port = _int_value(values.get(http_port_key), default_port)
    target_port = _int_value(values.get(nodeport_key) or values.get("K3S_INGRESS_HTTP_NODEPORT"), listen_port)
    public_url = str(values.get(public_url_key) or "").strip()
    return PublicRoleEndpoint(
        role=role,
        vm_ip=str(values.get(ip_key) or "").strip(),
        public_url=public_url,
        public_hostname=_hostname_from_url(public_url),
        listen_port=listen_port,
        target_port=target_port,
        connectors=connectors,
    )


def _role_connectors(values: dict[str, str], ds_name: str, role: str) -> list[str]:
    explicit_key = "VM_PROVIDER_CONNECTORS" if role == "provider" else "VM_CONSUMER_CONNECTORS"
    explicit = parse_connector_list(values.get(explicit_key), ds_name)
    if explicit:
        return explicit

    mapping = parse_connector_mapping(values.get("DS_1_CONNECTOR_NAMESPACES"), ds_name)
    mapped = [connector for connector, mapped_role in mapping.items() if str(mapped_role).strip().lower() == role]
    if mapped:
        return mapped

    connectors = parse_connector_list(values.get("DS_1_CONNECTORS"), ds_name)
    if role == "provider" and connectors:
        return [connectors[0]]
    if role == "consumer" and len(connectors) > 1:
        return [connectors[1]]
    return []


def _public_connector(connector: str, ds_name: str, ds_domain_base: str) -> PublicConnector:
    full_name = normalize_connector_name(connector, ds_name)
    short_name = _short_connector_name(full_name, ds_name)
    canonical_hostname = f"{full_name}.{ds_domain_base}" if ds_domain_base else full_name
    return PublicConnector(short_name=short_name, full_name=full_name, canonical_hostname=canonical_hostname)


def _short_connector_name(connector: str, ds_name: str) -> str:
    prefix = "conn-"
    suffix = f"-{ds_name}" if ds_name else ""
    if connector.startswith(prefix) and suffix and connector.endswith(suffix):
        return connector[len(prefix) : -len(suffix)]
    if connector.startswith(prefix):
        return connector[len(prefix) :]
    return connector


def _hostname_from_url(raw_url: str) -> str:
    parsed = urlparse(str(raw_url or "").strip())
    return parsed.hostname or ""


def _clean_domain(value: str | None) -> str:
    return str(value or "").strip().strip(".")


def _clean_public_url(value: str | None) -> str:
    return str(value or "").strip().rstrip("/")


def _default_role_url(prefix: str, domain_base: str) -> str:
    normalized_prefix = str(prefix or "").strip().strip(".")
    normalized_domain = _clean_domain(domain_base)
    if not normalized_prefix or not normalized_domain:
        return ""
    return f"https://{normalized_prefix}.{normalized_domain}"


def _join_url_path(base_url: str, path: str) -> str:
    normalized_base = _clean_public_url(base_url)
    normalized_path = str(path or "").strip().strip("/")
    if not normalized_base or not normalized_path:
        return normalized_base
    return f"{normalized_base}/{normalized_path}"


def _int_value(value: str | None, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return int(default)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result
