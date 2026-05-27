"""Shared connector configuration helpers."""

from __future__ import annotations

from typing import Any


def normalize_connector_name(raw_name: Any, dataspace_name: str) -> str:
    connector = str(raw_name or "").strip()
    if not connector:
        return ""
    if connector.startswith("conn-"):
        return connector
    ds_name = str(dataspace_name or "").strip()
    return f"conn-{connector}-{ds_name}" if ds_name else connector


def parse_connector_list(raw_value: Any, dataspace_name: str) -> list[str]:
    connectors: list[str] = []
    for token in str(raw_value or "").split(","):
        connector = normalize_connector_name(token, dataspace_name)
        if connector and connector not in connectors:
            connectors.append(connector)
    return connectors


def parse_connector_mapping(raw_value: Any, dataspace_name: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for token in str(raw_value or "").split(","):
        item = token.strip()
        if not item:
            continue
        key = ""
        value = ""
        for separator in ("=", ":"):
            if separator in item:
                key, value = item.split(separator, 1)
                break
        if not key:
            continue
        connector = normalize_connector_name(key, dataspace_name)
        target = str(value or "").strip()
        if connector and target:
            mapping[connector] = target
    return mapping


def parse_connector_pairs(raw_value: Any, dataspace_name: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for token in str(raw_value or "").split(","):
        item = token.strip()
        if not item:
            continue
        left = ""
        right = ""
        for separator in ("->", ">", "="):
            if separator in item:
                left, right = item.split(separator, 1)
                break
        if not left:
            continue
        source = normalize_connector_name(left, dataspace_name)
        target = normalize_connector_name(right, dataspace_name)
        if source and target and source != target and (source, target) not in pairs:
            pairs.append((source, target))
    return pairs

