"""Stable infrastructure import path for namespace profile resolution."""

from deployers.shared.lib.namespaces import (
    COMPACT_NAMESPACE_PROFILE,
    ROLE_ALIGNED_NAMESPACE_PROFILE,
    SUPPORTED_NAMESPACE_PROFILES,
    normalize_namespace_profile,
    resolve_namespace_profile_plan,
)

__all__ = [
    "COMPACT_NAMESPACE_PROFILE",
    "ROLE_ALIGNED_NAMESPACE_PROFILE",
    "SUPPORTED_NAMESPACE_PROFILES",
    "normalize_namespace_profile",
    "resolve_namespace_profile_plan",
]
