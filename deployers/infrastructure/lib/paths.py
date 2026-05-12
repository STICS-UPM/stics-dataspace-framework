"""Shared artifact path resolution for deployer migration."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def shared_artifact_dir(*parts: str) -> Path:
    return project_root().joinpath("deployers", "shared", *parts)


def deployer_dir(deployer: str, *parts: str) -> Path:
    return project_root().joinpath("deployers", deployer, *parts)


def infrastructure_dir(*parts: str) -> Path:
    return project_root().joinpath("deployers", "infrastructure", *parts)


def infrastructure_deployer_config_path() -> Path:
    return infrastructure_dir("deployer.config")


def infrastructure_deployer_config_example_path() -> Path:
    return infrastructure_dir("deployer.config.example")


def deployer_config_path(deployer: str) -> Path:
    return deployer_dir(deployer, "deployer.config")


def deployer_config_example_path(deployer: str) -> Path:
    return deployer_dir(deployer, "deployer.config.example")


def legacy_deployer_artifact_dir(deployer: str, *parts: str) -> Path:
    return project_root().joinpath("deployers", deployer, *parts)


def resolve_shared_artifact_dir(
    *parts: str,
    legacy_deployer: str = "inesdata",
    required_file: str | None = None,
) -> str:
    """Return the migrated shared artifact path when present, otherwise legacy."""

    if not use_shared_deployer_artifacts():
        return str(legacy_deployer_artifact_dir(legacy_deployer, *parts))

    shared_dir = shared_artifact_dir(*parts)
    if _artifact_dir_ready(shared_dir, required_file=required_file):
        return str(shared_dir)
    return str(legacy_deployer_artifact_dir(legacy_deployer, *parts))


def shared_artifact_roots(
    *parts: str,
    legacy_deployer: str = "inesdata",
) -> list[str]:
    """Return shared and legacy artifact roots, preserving fallback compatibility."""

    legacy_dir = legacy_deployer_artifact_dir(legacy_deployer, *parts)
    if use_shared_deployer_artifacts():
        candidates = [
            shared_artifact_dir(*parts),
            legacy_dir,
        ]
    else:
        candidates = [legacy_dir]
    roots: list[str] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_dir():
            roots.append(str(candidate))
    return roots


def _artifact_dir_ready(path: Path, *, required_file: str | None = None) -> bool:
    if not path.is_dir():
        return False
    if not required_file:
        return True
    return path.joinpath(required_file).is_file()


def use_shared_deployer_artifacts() -> bool:
    raw_value = os.getenv("PIONERA_USE_SHARED_DEPLOYER_ARTIFACTS")
    if raw_value is None:
        return True
    return str(raw_value).strip().lower() not in {"0", "false", "no", "off"}


__all__ = [
    "deployer_config_example_path",
    "deployer_config_path",
    "deployer_dir",
    "infrastructure_deployer_config_example_path",
    "infrastructure_deployer_config_path",
    "infrastructure_dir",
    "legacy_deployer_artifact_dir",
    "project_root",
    "resolve_shared_artifact_dir",
    "shared_artifact_dir",
    "shared_artifact_roots",
    "use_shared_deployer_artifacts",
]
