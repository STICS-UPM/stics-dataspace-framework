"""Stable infrastructure import path for local hosts management."""

from deployers.shared.lib.hosts_manager import (
    DEFAULT_HOST_ADDRESS,
    HostBlock,
    HostEntry,
    apply_managed_blocks,
    blocks_as_dict,
    build_context_host_blocks,
    detect_legacy_external_hostnames,
    hostnames_by_level,
    merge_missing_managed_blocks,
    parse_hostnames,
    remove_managed_blocks,
    render_managed_block,
    upsert_managed_block,
    upsert_managed_blocks,
)

__all__ = [
    "DEFAULT_HOST_ADDRESS",
    "HostBlock",
    "HostEntry",
    "apply_managed_blocks",
    "blocks_as_dict",
    "build_context_host_blocks",
    "detect_legacy_external_hostnames",
    "hostnames_by_level",
    "merge_missing_managed_blocks",
    "parse_hostnames",
    "remove_managed_blocks",
    "render_managed_block",
    "upsert_managed_block",
    "upsert_managed_blocks",
]
