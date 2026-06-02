from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from typing import Any
from urllib.parse import urlparse

from .public_hostnames import (
    canonical_common_service_hostnames,
    clean_public_hostname,
    legacy_common_service_hostnames,
    normalize_common_domain_base,
    resolved_common_service_hostnames,
)
from .connectors import normalize_connector_name, parse_connector_list, parse_connector_mapping
from .topology import (
    ROLE_COMMON,
    ROLE_COMPONENTS,
    ROLE_CONNECTORS,
    ROLE_CONSUMER,
    ROLE_PROVIDER,
    ROLE_REGISTRATION_SERVICE,
)


_BEGIN_PREFIX = "# BEGIN Validation-Environment "
_END_PREFIX = "# END Validation-Environment "
DEFAULT_HOST_ADDRESS = "127.0.0.1"


@dataclass(frozen=True, slots=True)
class HostEntry:
    address: str
    hostname: str

    def render(self) -> str:
        return f"{self.address} {self.hostname}"


@dataclass(frozen=True, slots=True)
class HostBlock:
    name: str
    entries: list[HostEntry]

    def render(self) -> str:
        return render_managed_block(self.name, list(self.entries))


def render_managed_block(block_name: str, entries: list[HostEntry | str]) -> str:
    rendered_entries = []
    for entry in entries:
        if isinstance(entry, HostEntry):
            rendered_entries.append(entry.render())
        else:
            rendered_entries.append(str(entry).strip())

    lines = [f"{_BEGIN_PREFIX}{block_name}"]
    lines.extend(line for line in rendered_entries if line)
    lines.append(f"{_END_PREFIX}{block_name}")
    return "\n".join(lines)


def upsert_managed_block(existing_content: str, block_name: str, entries: list[HostEntry | str]) -> str:
    block = render_managed_block(block_name, entries)
    begin_marker = f"{_BEGIN_PREFIX}{block_name}"
    end_marker = f"{_END_PREFIX}{block_name}"
    raw_content = existing_content or ""
    lines = raw_content.splitlines()

    start_index = None
    end_index = None
    for index, line in enumerate(lines):
        if line.strip() == begin_marker:
            start_index = index
            break

    if start_index is not None:
        for index in range(start_index + 1, len(lines)):
            if lines[index].strip() == end_marker:
                end_index = index
                break

    if start_index is not None and end_index is not None:
        updated = "\n".join(lines[:start_index]).rstrip()
        suffix = "\n".join(lines[end_index + 1 :]).lstrip()
        parts = [part for part in (updated, block, suffix) if part]
        return "\n\n".join(parts).rstrip() + "\n"

    if not raw_content.strip():
        return block + "\n"

    return raw_content.rstrip() + "\n\n" + block + "\n"


def build_context_host_blocks(
    context: Any,
    *,
    address: str | None = None,
    include_common: bool = True,
) -> list[HostBlock]:
    """Build managed hosts blocks from a deployer context."""

    config = dict(getattr(context, "config", {}) or {})
    common_address = _address_for_role(context, ROLE_COMMON, address)
    dataspace_address = _address_for_role(context, ROLE_REGISTRATION_SERVICE, address)
    connector_address = _address_for_role(context, ROLE_CONNECTORS, address)
    component_address = _address_for_role(context, ROLE_COMPONENTS, address)
    dataspace_name = _clean_token(getattr(context, "dataspace_name", ""))
    ds_domain_base = _clean_token(getattr(context, "ds_domain_base", "") or config.get("DS_DOMAIN_BASE", ""))
    deployer_name = _clean_token(getattr(context, "deployer", "deployer")) or "deployer"
    connectors = [_clean_token(connector) for connector in list(getattr(context, "connectors", []) or [])]
    components = [_clean_token(component) for component in list(getattr(context, "components", []) or [])]

    blocks: list[HostBlock] = []
    if include_common:
        common_entries = _build_common_entries(
            config,
            address=common_address,
            topology=getattr(context, "topology", ""),
        )
        if common_entries:
            blocks.append(HostBlock("shared common", common_entries))

    if dataspace_name and ds_domain_base:
        blocks.append(
            HostBlock(
                f"dataspace {dataspace_name}",
                [HostEntry(dataspace_address, f"registration-service-{dataspace_name}.{ds_domain_base}")],
            )
        )

    connector_entries = []
    for connector in connectors:
        if not connector or not ds_domain_base:
            continue
        address = _connector_address_for_context(
            context,
            connector,
            dataspace_name=dataspace_name,
            fallback=connector_address,
        )
        connector_entries.append(HostEntry(address, f"{connector}.{ds_domain_base}"))
    if connector_entries:
        blocks.append(
            HostBlock(
                f"connectors {deployer_name} {dataspace_name}".strip(),
                _dedupe_entries(connector_entries),
            )
        )

    component_entries = [
        HostEntry(component_address, f"{_component_hostname(component, dataspace_name)}.{ds_domain_base}")
        for component in components
        if component and ds_domain_base
    ]
    if component_entries:
        blocks.append(
            HostBlock(
                f"components {dataspace_name}",
                _dedupe_entries(component_entries),
            )
        )

    return blocks


def blocks_as_dict(blocks: list[HostBlock]) -> dict[str, list[str]]:
    return {block.name: [entry.render() for entry in block.entries] for block in blocks}


def hostnames_by_level(blocks: list[HostBlock]) -> dict[str, list[str]]:
    levels = {
        "level_1_2": [],
        "level_3": [],
        "level_4": [],
        "level_5": [],
    }

    for block in blocks:
        hostnames = [entry.hostname for entry in block.entries]
        if block.name == "shared common":
            levels["level_1_2"].extend(hostnames)
        elif block.name.startswith("dataspace "):
            levels["level_3"].extend(hostnames)
        elif block.name.startswith("connectors "):
            levels["level_4"].extend(hostnames)
        elif block.name.startswith("components "):
            levels["level_5"].extend(hostnames)

    return levels


def upsert_managed_blocks(existing_content: str, blocks: list[HostBlock]) -> str:
    updated = existing_content or ""
    for block in blocks:
        updated = upsert_managed_block(updated, block.name, list(block.entries))
    return updated


def apply_managed_blocks(
    hosts_file: str,
    blocks: list[HostBlock],
    *,
    config: dict[str, Any] | None = None,
    use_sudo: bool = False,
) -> dict[str, Any]:
    existing_content = ""
    if os.path.exists(hosts_file):
        with open(hosts_file, "r", encoding="utf-8") as handle:
            existing_content = handle.read()

    legacy_external_hostnames = detect_legacy_external_hostnames(
        existing_content,
        block_names=[block.name for block in blocks],
        config=config,
    )
    public_hostnames_to_reconcile = _public_proxy_hostnames_to_reconcile(
        existing_content,
        blocks,
        config=config,
    )
    updated_content, missing_blocks, skipped_existing = merge_missing_managed_blocks(
        existing_content,
        blocks,
        reconciled_hostnames=public_hostnames_to_reconcile,
    )
    changed = updated_content != existing_content
    elevated = False
    if changed:
        try:
            with open(hosts_file, "w", encoding="utf-8") as handle:
                handle.write(updated_content)
        except PermissionError:
            if not use_sudo:
                raise
            _write_hosts_file_with_sudo(hosts_file, updated_content)
            elevated = True

    return {
        "hosts_file": hosts_file,
        "changed": changed,
        "elevated": elevated,
        "blocks": blocks_as_dict(missing_blocks),
        "skipped_existing": skipped_existing,
        "legacy_external_hostnames": legacy_external_hostnames,
        "reconciled_public_hostnames": public_hostnames_to_reconcile,
    }


def _write_hosts_file_with_sudo(hosts_file: str, content: str) -> None:
    try:
        subprocess.run(
            ["sudo", "tee", hosts_file],
            input=content,
            text=True,
            stdout=subprocess.DEVNULL,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PermissionError("sudo is not available to update the hosts file") from exc
    except subprocess.CalledProcessError as exc:
        raise PermissionError("sudo could not update the hosts file") from exc


def merge_missing_managed_blocks(
    existing_content: str,
    blocks: list[HostBlock],
    *,
    reconciled_hostnames: list[str] | None = None,
) -> tuple[str, list[HostBlock], dict[str, list[str]]]:
    """Merge only host entries that are not already present outside target blocks."""

    block_names = [block.name for block in blocks]
    base_content = remove_managed_blocks(existing_content, block_names)
    base_content = remove_hostnames(base_content, reconciled_hostnames or [])
    existing_hostnames = parse_hostnames(base_content)
    missing_blocks = []
    skipped_existing: dict[str, list[str]] = {}

    for block in blocks:
        missing_entries = []
        skipped_entries = []
        for entry in block.entries:
            if entry.hostname.lower() in existing_hostnames:
                skipped_entries.append(entry.render())
            else:
                missing_entries.append(entry)

        if skipped_entries:
            skipped_existing[block.name] = skipped_entries
        if missing_entries:
            missing_blocks.append(HostBlock(block.name, missing_entries))

    updated_content = upsert_managed_blocks(base_content, missing_blocks)
    return updated_content, missing_blocks, skipped_existing


def remove_hostnames(existing_content: str, hostnames: list[str]) -> str:
    target_hostnames = {str(hostname or "").strip().lower() for hostname in hostnames if str(hostname or "").strip()}
    if not target_hostnames:
        return existing_content or ""

    kept_lines = []
    for raw_line in (existing_content or "").splitlines():
        active_part, separator, comment = raw_line.partition("#")
        parts = active_part.split()
        if len(parts) < 2:
            kept_lines.append(raw_line)
            continue

        address = parts[0]
        remaining_hostnames = [hostname for hostname in parts[1:] if hostname.lower() not in target_hostnames]
        if len(remaining_hostnames) == len(parts) - 1:
            kept_lines.append(raw_line)
            continue
        if not remaining_hostnames:
            continue

        rebuilt_line = f"{address} {' '.join(remaining_hostnames)}"
        if separator:
            rebuilt_line = f"{rebuilt_line} #{comment.strip()}" if comment.strip() else f"{rebuilt_line} #"
        kept_lines.append(rebuilt_line)

    if not kept_lines:
        return ""
    return "\n".join(kept_lines).rstrip() + "\n"


def remove_managed_blocks(existing_content: str, block_names: list[str]) -> str:
    target_names = {str(name or "").strip() for name in block_names if str(name or "").strip()}
    if not target_names:
        return existing_content or ""

    lines = (existing_content or "").splitlines()
    kept_lines = []
    skipping_until = None

    for line in lines:
        stripped = line.strip()
        if skipping_until is not None:
            if stripped == f"{_END_PREFIX}{skipping_until}":
                skipping_until = None
            continue

        if stripped.startswith(_BEGIN_PREFIX):
            block_name = stripped[len(_BEGIN_PREFIX):].strip()
            if block_name in target_names:
                skipping_until = block_name
                continue

        kept_lines.append(line)

    if not kept_lines:
        return ""
    return "\n".join(kept_lines).rstrip() + "\n"


def detect_legacy_external_hostnames(
    existing_content: str,
    *,
    block_names: list[str],
    config: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    values = dict(config or {})
    domain_base = normalize_common_domain_base(values.get("DOMAIN_BASE"))
    legacy_hostnames = legacy_common_service_hostnames(domain_base)
    canonical_hostnames = canonical_common_service_hostnames(domain_base)
    base_content = remove_managed_blocks(existing_content, block_names)
    existing_hostnames = parse_hostnames(base_content)
    warnings: list[dict[str, str]] = []

    for key, legacy_hostname in legacy_hostnames.items():
        canonical_hostname = canonical_hostnames[key]
        if (
            legacy_hostname
            and canonical_hostname
            and legacy_hostname.lower() in existing_hostnames
            and legacy_hostname != canonical_hostname
        ):
            warnings.append(
                {
                    "legacy": legacy_hostname,
                    "canonical": canonical_hostname,
                }
            )

    return warnings


def parse_hostnames(content: str) -> set[str]:
    hostnames: set[str] = set()
    for raw_line in (content or "").splitlines():
        active_part = raw_line.split("#", 1)[0].strip()
        if not active_part:
            continue
        parts = active_part.split()
        if len(parts) < 2:
            continue
        for hostname in parts[1:]:
            cleaned = hostname.strip().lower()
            if cleaned:
                hostnames.add(cleaned)
    return hostnames


def parse_hostname_addresses(content: str) -> dict[str, set[str]]:
    addresses: dict[str, set[str]] = {}
    for raw_line in (content or "").splitlines():
        active_part = raw_line.split("#", 1)[0].strip()
        if not active_part:
            continue
        parts = active_part.split()
        if len(parts) < 2:
            continue
        address = parts[0].strip()
        if not address:
            continue
        for hostname in parts[1:]:
            cleaned = hostname.strip().lower()
            if cleaned:
                addresses.setdefault(cleaned, set()).add(address)
    return addresses


def _build_common_entries(config: dict[str, Any], *, address: str, topology: str | None = None) -> list[HostEntry]:
    resolved_hostnames = resolved_common_service_hostnames(config)
    public_address = _vm_distributed_public_proxy_address(config, topology=topology)
    public_hostnames = _vm_distributed_public_endpoint_hostnames(config) if public_address else set()
    hostnames = [
        resolved_hostnames["keycloak_hostname"],
        resolved_hostnames["minio_hostname"],
        resolved_hostnames["keycloak_admin_hostname"],
        resolved_hostnames["minio_console_hostname"],
    ]

    return _dedupe_entries(
        [HostEntry(address, hostname) for hostname in hostnames if hostname and hostname not in public_hostnames]
        + [HostEntry(public_address, hostname) for hostname in sorted(public_hostnames) if hostname]
    )


def _vm_distributed_public_proxy_address(config: dict[str, Any], *, topology: str | None = None) -> str:
    if str(topology or "").strip().lower() != "vm-distributed":
        return ""
    return str(
        config.get("VM_PUBLIC_PROXY_IP")
        or config.get("PUBLIC_PROXY_IP")
        or config.get("VM_PUBLIC_ACCESS_IP")
        or ""
    ).strip()


def _public_proxy_hostnames_to_reconcile(
    existing_content: str,
    blocks: list[HostBlock],
    *,
    config: dict[str, Any] | None = None,
) -> list[str]:
    values = dict(config or {})
    public_address = str(
        values.get("VM_PUBLIC_PROXY_IP")
        or values.get("PUBLIC_PROXY_IP")
        or values.get("VM_PUBLIC_ACCESS_IP")
        or ""
    ).strip()
    if not public_address:
        return []

    public_hostnames = _vm_distributed_public_endpoint_hostnames(values)
    if not public_hostnames:
        return []

    managed_public_hostnames = {
        entry.hostname.lower()
        for block in blocks
        for entry in block.entries
        if entry.address == public_address and entry.hostname.lower() in public_hostnames
    }
    if not managed_public_hostnames:
        return []

    base_content = remove_managed_blocks(existing_content, [block.name for block in blocks])
    addresses_by_hostname = parse_hostname_addresses(base_content)
    hostnames_to_reconcile = []
    for hostname in sorted(managed_public_hostnames):
        addresses = addresses_by_hostname.get(hostname, set())
        if addresses and any(address != public_address for address in addresses):
            hostnames_to_reconcile.append(hostname)
    return hostnames_to_reconcile


def _vm_distributed_public_endpoint_hostnames(config: dict[str, Any]) -> set[str]:
    hostnames = set()
    for key in (
        "VM_COMMON_PUBLIC_URL",
        "KEYCLOAK_FRONTEND_URL",
        "KEYCLOAK_PUBLIC_URL",
        "MINIO_API_PUBLIC_URL",
        "MINIO_PUBLIC_URL",
        "MINIO_CONSOLE_PUBLIC_URL",
        "PIONERA_LEVEL6_MINIO_ENDPOINT",
        "LEVEL6_MINIO_ENDPOINT",
        "EDC_LEVEL6_MINIO_ENDPOINT",
        "COMPONENTS_PUBLIC_BASE_URL",
    ):
        hostname = clean_public_hostname(config.get(key))
        if hostname:
            hostnames.add(hostname)
    return hostnames


def _address_for_role(context: Any, role: str, override: str | None = None) -> str:
    explicit_address = _clean_token(override)
    if explicit_address:
        return explicit_address

    topology_profile = getattr(context, "topology_profile", None)
    address_for = getattr(topology_profile, "address_for", None)
    if callable(address_for):
        return address_for(role, fallback=DEFAULT_HOST_ADDRESS)

    return DEFAULT_HOST_ADDRESS


def _connector_address_for_context(context: Any, connector: str, *, dataspace_name: str, fallback: str) -> str:
    role = _connector_role_for_context(context, connector, dataspace_name=dataspace_name)
    if not role:
        return fallback

    topology_profile = getattr(context, "topology_profile", None)
    address_for = getattr(topology_profile, "address_for", None)
    if callable(address_for):
        return address_for(role, fallback=fallback)
    return fallback


def _connector_role_for_context(context: Any, connector: str, *, dataspace_name: str) -> str:
    config = dict(getattr(context, "config", {}) or {})
    normalized_connector = normalize_connector_name(connector, dataspace_name)
    mapping = parse_connector_mapping(config.get("DS_1_CONNECTOR_NAMESPACES"), dataspace_name)
    mapped_role = _role_from_connector_location(mapping.get(normalized_connector), context)
    if mapped_role:
        return mapped_role

    if _connector_in_configured_role(config.get("VM_PROVIDER_CONNECTORS"), normalized_connector, dataspace_name):
        return ROLE_PROVIDER
    if _connector_in_configured_role(config.get("VM_CONSUMER_CONNECTORS"), normalized_connector, dataspace_name):
        return ROLE_CONSUMER
    return _historical_connector_role_for_context(context, normalized_connector, dataspace_name=dataspace_name)


def _historical_connector_role_for_context(context: Any, connector: str, *, dataspace_name: str) -> str:
    config = dict(getattr(context, "config", {}) or {})
    connectors = parse_connector_list(config.get("DS_1_CONNECTORS"), dataspace_name)
    if not connectors:
        connectors = [
            normalize_connector_name(item, dataspace_name)
            for item in list(getattr(context, "connectors", []) or [])
            if normalize_connector_name(item, dataspace_name)
        ]

    try:
        position = connectors.index(connector)
    except ValueError:
        return ""

    if position == 0:
        return ROLE_PROVIDER
    if position == 1:
        return ROLE_CONSUMER
    return ROLE_REGISTRATION_SERVICE


def _role_from_connector_location(location: Any, context: Any) -> str:
    normalized = str(location or "").strip().lower()
    if not normalized:
        return ""
    if normalized == ROLE_PROVIDER:
        return ROLE_PROVIDER
    if normalized == ROLE_CONSUMER:
        return ROLE_CONSUMER

    for roles in (getattr(context, "namespace_roles", None), getattr(context, "planned_namespace_roles", None)):
        provider_namespace = str(getattr(roles, "provider_namespace", "") or "").strip().lower()
        consumer_namespace = str(getattr(roles, "consumer_namespace", "") or "").strip().lower()
        registration_namespace = str(getattr(roles, "registration_service_namespace", "") or "").strip().lower()
        if normalized and normalized == provider_namespace:
            return ROLE_PROVIDER
        if normalized and normalized == consumer_namespace:
            return ROLE_CONSUMER
        if normalized and normalized == registration_namespace:
            return ROLE_REGISTRATION_SERVICE
    if normalized in {"dataspace", "default", "registration", "registration_service", "core"}:
        return ROLE_REGISTRATION_SERVICE
    return ""


def _connector_in_configured_role(raw_value: Any, connector: str, dataspace_name: str) -> bool:
    configured = set(parse_connector_list(raw_value, dataspace_name))
    if connector in configured:
        return True

    short_name = _connector_short_name(connector, dataspace_name)
    raw_tokens = {str(token or "").strip().lower() for token in str(raw_value or "").split(",") if str(token or "").strip()}
    return connector.lower() in raw_tokens or bool(short_name and short_name.lower() in raw_tokens)


def _connector_short_name(connector: str, dataspace_name: str) -> str:
    normalized_connector = normalize_connector_name(connector, dataspace_name)
    prefix = "conn-"
    suffix = f"-{dataspace_name}" if dataspace_name else ""
    if normalized_connector.startswith(prefix) and suffix and normalized_connector.endswith(suffix):
        return normalized_connector[len(prefix):-len(suffix)]
    if normalized_connector.startswith(prefix):
        return normalized_connector[len(prefix):]
    return normalized_connector


def _component_hostname(component: str, dataspace_name: str) -> str:
    if dataspace_name and component.endswith(f"-{dataspace_name}"):
        return component
    if dataspace_name:
        return f"{component}-{dataspace_name}"
    return component


def _clean_token(value: Any) -> str:
    return str(value or "").strip()


def _hostname_from_url(value: Any) -> str:
    raw_value = _clean_token(value)
    if not raw_value:
        return ""
    parsed = urlparse(raw_value)
    if parsed.hostname:
        return parsed.hostname
    if "://" not in raw_value:
        return raw_value.split("/", 1)[0].split(":", 1)[0]
    return ""


def _dedupe_entries(entries: list[HostEntry]) -> list[HostEntry]:
    seen = set()
    deduped: list[HostEntry] = []
    for entry in entries:
        key = (entry.address, entry.hostname)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped
