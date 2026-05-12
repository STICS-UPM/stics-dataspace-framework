from __future__ import annotations

from typing import Any


LOCAL_SINGLE_ADAPTER_MEMORY_MB = 14336
LOCAL_COEXISTENCE_MEMORY_MB = 18432


def parse_memory_quantity_mb(value: Any) -> int | None:
    """Parse Kubernetes/Docker/config memory values into MiB."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    lowered = raw_value.lower()
    multipliers = (
        ("ki", 1 / 1024),
        ("mi", 1),
        ("gi", 1024),
        ("k", 1 / 1024),
        ("m", 1),
        ("g", 1024),
    )
    for suffix, multiplier in multipliers:
        if lowered.endswith(suffix):
            number = lowered[: -len(suffix)].strip()
            try:
                return int(float(number) * multiplier)
            except (TypeError, ValueError):
                return None

    try:
        parsed = int(float(raw_value))
    except (TypeError, ValueError):
        return None

    if parsed <= 0:
        return None
    # Docker reports MemTotal in bytes; framework config uses MiB.
    if parsed > 1024 * 1024:
        return int(parsed / (1024 * 1024))
    return parsed


def node_capacity_memory_mb(nodes_payload: dict[str, Any] | None) -> int | None:
    """Return the smallest allocatable memory reported by Ready/known nodes."""
    capacities = []
    for node in (nodes_payload or {}).get("items") or []:
        allocatable = node.get("status", {}).get("allocatable") or {}
        capacity = node.get("status", {}).get("capacity") or {}
        memory = parse_memory_quantity_mb(allocatable.get("memory") or capacity.get("memory"))
        if memory:
            capacities.append(memory)
    return min(capacities) if capacities else None


def summarize_local_workloads(
    pods_payload: dict[str, Any] | None,
    *,
    adapter_namespaces: dict[str, str],
    component_namespaces: list[str] | tuple[str, ...] = ("components",),
) -> dict[str, Any]:
    """Summarize local adapter workloads currently present in the cluster."""
    namespace_to_adapter = {
        str(namespace or "").strip(): str(adapter or "").strip().lower()
        for adapter, namespace in (adapter_namespaces or {}).items()
        if str(namespace or "").strip() and str(adapter or "").strip()
    }
    component_namespace_set = {
        str(namespace or "").strip()
        for namespace in component_namespaces
        if str(namespace or "").strip()
    }
    active_adapters: set[str] = set()
    active_component_namespaces: set[str] = set()
    namespace_pod_counts: dict[str, int] = {}
    active_pod_count = 0

    for pod in (pods_payload or {}).get("items") or []:
        metadata = pod.get("metadata") or {}
        status = pod.get("status") or {}
        phase = str(status.get("phase") or "").strip()
        namespace = str(metadata.get("namespace") or "").strip()
        if not namespace or phase in {"Succeeded", "Failed"}:
            continue

        active_pod_count += 1
        namespace_pod_counts[namespace] = namespace_pod_counts.get(namespace, 0) + 1
        adapter = namespace_to_adapter.get(namespace)
        if adapter:
            active_adapters.add(adapter)
        if namespace in component_namespace_set:
            active_component_namespaces.add(namespace)

    coexistence_detected = len(active_adapters) >= 2 or (
        "edc" in active_adapters and bool(active_component_namespaces)
    )
    return {
        "active_adapters": sorted(active_adapters),
        "active_component_namespaces": sorted(active_component_namespaces),
        "adapter_namespaces": dict(sorted((adapter_namespaces or {}).items())),
        "namespace_pod_counts": dict(sorted(namespace_pod_counts.items())),
        "active_pod_count": active_pod_count,
        "coexistence_detected": coexistence_detected,
    }


def evaluate_local_coexistence_capacity(
    workload_summary: dict[str, Any] | None,
    *,
    node_memory_mb: int | None = None,
    docker_memory_mb: int | None = None,
    configured_minikube_memory_mb: int | None = None,
    required_memory_mb: int = LOCAL_COEXISTENCE_MEMORY_MB,
    guard_mode: str = "fail",
) -> dict[str, Any]:
    """Evaluate whether the local cluster can safely host both adapters."""
    summary = dict(workload_summary or {})
    coexistence_detected = bool(summary.get("coexistence_detected"))
    normalized_guard_mode = str(guard_mode or "fail").strip().lower()
    if normalized_guard_mode in {"0", "false", "no", "off", "disabled"}:
        normalized_guard_mode = "off"
    if normalized_guard_mode not in {"off", "warn", "warning", "fail", "strict"}:
        normalized_guard_mode = "fail"
    if normalized_guard_mode == "warning":
        normalized_guard_mode = "warn"
    if normalized_guard_mode == "strict":
        normalized_guard_mode = "fail"

    available_candidates = [
        value
        for value in (node_memory_mb, docker_memory_mb, configured_minikube_memory_mb)
        if isinstance(value, int) and value > 0
    ]
    effective_memory_mb = min(available_candidates) if available_candidates else None

    result = {
        "status": "passed",
        "coexistence_detected": coexistence_detected,
        "required_memory_mb": int(required_memory_mb),
        "node_memory_mb": node_memory_mb,
        "docker_memory_mb": docker_memory_mb,
        "configured_minikube_memory_mb": configured_minikube_memory_mb,
        "effective_memory_mb": effective_memory_mb,
        "guard_mode": normalized_guard_mode,
        "workloads": summary,
        "warnings": [],
        "blocking_issues": [],
        "recommendations": [],
    }

    if normalized_guard_mode == "off":
        result["status"] = "skipped"
        result["reason"] = "disabled"
        return result

    if not coexistence_detected:
        result["reason"] = "single-adapter-or-no-coexistence"
        return result

    result["recommendations"] = [
        f"Set Docker Desktop memory above {required_memory_mb} MiB.",
        f"Set MINIKUBE_MEMORY={required_memory_mb} in deployers/infrastructure/topologies/local.config.",
        "Recreate the local cluster from Level 1 after changing Minikube resources.",
        "If the host cannot provide that memory, recreate from Level 1 before switching adapters or use vm-single.",
    ]

    if effective_memory_mb is None:
        issue = {
            "name": "local_coexistence_memory_unknown",
            "detail": "Could not determine local cluster memory capacity.",
        }
        result["warnings"].append(issue)
        result["status"] = "warning" if normalized_guard_mode == "warn" else "failed"
        if result["status"] == "failed":
            result["blocking_issues"].append(issue)
        return result

    if effective_memory_mb < required_memory_mb:
        issue = {
            "name": "local_coexistence_insufficient_memory",
            "detail": (
                f"Local coexistence requires at least {required_memory_mb} MiB, "
                f"but the effective capacity is {effective_memory_mb} MiB."
            ),
        }
        result["warnings"].append(issue)
        if normalized_guard_mode == "warn":
            result["status"] = "warning"
        else:
            result["status"] = "failed"
            result["blocking_issues"].append(issue)

    return result
