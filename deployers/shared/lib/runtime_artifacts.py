"""Runtime artifact paths for topology-aware deployments.

Sensitive deployment artifacts must not be shared accidentally between
topologies. This module centralizes the path rules so adapters do not invent
their own layout for Vault keys, connector credentials or certificates.
"""

from __future__ import annotations

import os
from pathlib import Path

from deployers.infrastructure.lib.paths import project_root


LOCAL_TOPOLOGY = "local"
VM_SINGLE_TOPOLOGY = "vm-single"
VM_DISTRIBUTED_TOPOLOGY = "vm-distributed"
SUPPORTED_TOPOLOGIES = {LOCAL_TOPOLOGY, VM_SINGLE_TOPOLOGY, VM_DISTRIBUTED_TOPOLOGY}


def normalize_topology(value: str | None) -> str:
    normalized = str(value or LOCAL_TOPOLOGY).strip().lower().replace("_", "-")
    return normalized if normalized in SUPPORTED_TOPOLOGIES else LOCAL_TOPOLOGY


def clean_segment(value: str | None, fallback: str) -> str:
    segment = str(value or "").strip()
    if not segment:
        segment = fallback
    for separator in (os.sep, "/", "\\"):
        segment = segment.replace(separator, "_")
    return segment or fallback


def deployment_id(config: dict[str, str] | None = None) -> str:
    values = config or {}
    raw_value = (
        os.getenv("PIONERA_DEPLOYMENT_ID")
        or values.get("DEPLOYMENT_ID")
        or values.get("RUNTIME_ARTIFACT_DEPLOYMENT_ID")
        or values.get("VALIDATION_ENVIRONMENT_ID")
        or ""
    )
    return clean_segment(raw_value, "").strip("_")


def artifact_layout(config: dict[str, str] | None = None) -> str:
    values = config or {}
    layout = (
        os.getenv("PIONERA_RUNTIME_ARTIFACT_LAYOUT")
        or values.get("RUNTIME_ARTIFACT_LAYOUT")
        or "auto"
    )
    normalized = str(layout or "auto").strip().lower().replace("_", "-")
    if normalized in {"legacy", "flat"}:
        return "legacy"
    if normalized in {"scoped", "topology", "topology-scoped"}:
        return "scoped"
    return "auto"


def use_scoped_layout(topology: str, config: dict[str, str] | None = None) -> bool:
    layout = artifact_layout(config)
    if layout == "legacy":
        return False
    if layout == "scoped":
        return True
    return normalize_topology(topology) != LOCAL_TOPOLOGY or bool(deployment_id(config))


def legacy_fallback_allowed(topology: str, config: dict[str, str] | None = None) -> bool:
    if not use_scoped_layout(topology, config):
        return True
    return str(os.getenv("PIONERA_RUNTIME_ARTIFACT_LEGACY_FALLBACK") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def deployer_root(adapter: str, root: str | Path | None = None) -> Path:
    base = Path(root) if root else project_root()
    return base.joinpath("deployers", clean_segment(adapter, "inesdata"))


def shared_root(root: str | Path | None = None) -> Path:
    base = Path(root) if root else project_root()
    return base.joinpath("deployers", "shared")


def legacy_dataspace_runtime_dir(
    adapter: str,
    environment: str,
    dataspace: str,
    *,
    root: str | Path | None = None,
) -> Path:
    return deployer_root(adapter, root).joinpath(
        "deployments",
        clean_segment(environment, "DEV"),
        clean_segment(dataspace, "dataspace"),
    )


def dataspace_runtime_dir(
    adapter: str,
    environment: str,
    dataspace: str,
    *,
    topology: str = LOCAL_TOPOLOGY,
    config: dict[str, str] | None = None,
    root: str | Path | None = None,
) -> Path:
    if not use_scoped_layout(topology, config):
        return legacy_dataspace_runtime_dir(adapter, environment, dataspace, root=root)

    parts = [
        "deployments",
        clean_segment(environment, "DEV"),
        normalize_topology(topology),
    ]
    current_deployment_id = deployment_id(config)
    if current_deployment_id:
        parts.append(current_deployment_id)
    parts.append(clean_segment(dataspace, "dataspace"))
    return deployer_root(adapter, root).joinpath(*parts)


def connector_credentials_path(
    adapter: str,
    environment: str,
    dataspace: str,
    connector: str,
    *,
    topology: str = LOCAL_TOPOLOGY,
    config: dict[str, str] | None = None,
    root: str | Path | None = None,
    prefer_existing: bool = False,
) -> Path:
    legacy = legacy_dataspace_runtime_dir(adapter, environment, dataspace, root=root).joinpath(
        f"credentials-connector-{clean_segment(connector, 'connector')}.json"
    )
    if not use_scoped_layout(topology, config):
        return legacy

    preferred = dataspace_runtime_dir(
        adapter,
        environment,
        dataspace,
        topology=topology,
        config=config,
        root=root,
    ).joinpath("connectors", clean_segment(connector, "connector"), "credentials.json")
    if prefer_existing and legacy_fallback_allowed(topology, config) and not preferred.exists() and legacy.exists():
        return legacy
    return preferred


def connector_certificates_dir(
    adapter: str,
    environment: str,
    dataspace: str,
    connector: str | None = None,
    *,
    topology: str = LOCAL_TOPOLOGY,
    config: dict[str, str] | None = None,
    root: str | Path | None = None,
) -> Path:
    runtime_dir = dataspace_runtime_dir(
        adapter,
        environment,
        dataspace,
        topology=topology,
        config=config,
        root=root,
    )
    connector_segment = clean_segment(connector, "connector") if connector else None
    if connector_segment and use_scoped_layout(topology, config):
        return runtime_dir.joinpath("connectors", connector_segment, "certs")
    return runtime_dir.joinpath("certs")


def legacy_vault_keys_path(*, root: str | Path | None = None) -> Path:
    return shared_root(root).joinpath("common", "init-keys-vault.json")


def vault_keys_path(
    environment: str,
    *,
    topology: str = LOCAL_TOPOLOGY,
    config: dict[str, str] | None = None,
    root: str | Path | None = None,
    prefer_existing: bool = False,
) -> Path:
    if not use_scoped_layout(topology, config):
        return legacy_vault_keys_path(root=root)

    parts = [
        "deployments",
        clean_segment(environment, "DEV"),
        normalize_topology(topology),
    ]
    current_deployment_id = deployment_id(config)
    if current_deployment_id:
        parts.append(current_deployment_id)
    parts.extend(["common", "init-keys-vault.json"])
    preferred = shared_root(root).joinpath(*parts)
    legacy = legacy_vault_keys_path(root=root)
    if prefer_existing and legacy_fallback_allowed(topology, config) and not preferred.exists() and legacy.exists():
        return legacy
    return preferred


__all__ = [
    "LOCAL_TOPOLOGY",
    "VM_DISTRIBUTED_TOPOLOGY",
    "VM_SINGLE_TOPOLOGY",
    "artifact_layout",
    "connector_certificates_dir",
    "connector_credentials_path",
    "dataspace_runtime_dir",
    "deployment_id",
    "legacy_dataspace_runtime_dir",
    "legacy_fallback_allowed",
    "legacy_vault_keys_path",
    "normalize_topology",
    "use_scoped_layout",
    "vault_keys_path",
]
