"""Compatibility facade for deployer infrastructure helpers."""

from .namespaces import (
    COMPACT_NAMESPACE_PROFILE,
    ROLE_ALIGNED_NAMESPACE_PROFILE,
    SUPPORTED_NAMESPACE_PROFILES,
    normalize_namespace_profile,
    resolve_namespace_profile_plan,
)
from .paths import resolve_shared_artifact_dir, shared_artifact_roots, use_shared_deployer_artifacts

__all__ = [
    "COMPACT_NAMESPACE_PROFILE",
    "ROLE_ALIGNED_NAMESPACE_PROFILE",
    "SUPPORTED_NAMESPACE_PROFILES",
    "normalize_namespace_profile",
    "resolve_namespace_profile_plan",
    "resolve_shared_artifact_dir",
    "shared_artifact_roots",
    "use_shared_deployer_artifacts",
]
