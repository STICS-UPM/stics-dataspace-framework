from __future__ import annotations

import datetime as _dt
import json
import subprocess
import time
from typing import Any, Callable


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


def _utc_timestamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _condition_status(conditions: list[dict[str, Any]], condition_type: str) -> str:
    for condition in conditions or []:
        if condition.get("type") == condition_type:
            return str(condition.get("status") or "")
    return ""


def _event_count(event: dict[str, Any]) -> int:
    for value in (
        event.get("count"),
        (event.get("series") or {}).get("count") if isinstance(event.get("series"), dict) else None,
    ):
        try:
            if value not in (None, ""):
                return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return 1


class LocalStabilityMonitor:
    def __init__(
        self,
        namespaces: list[str] | None = None,
        *,
        run_command: CommandRunner | None = None,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        self.namespaces = self._normalize_namespaces(namespaces)
        self.run_command = run_command or self._default_run_command
        self.sleep = sleep or time.sleep
        self.monotonic = monotonic or time.monotonic

    @staticmethod
    def _normalize_namespaces(namespaces: list[str] | None) -> list[str]:
        result = []
        for namespace in namespaces or []:
            value = str(namespace or "").strip()
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _default_run_command(command: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(command, check=False, capture_output=True, text=True)

    def _run_json(self, command: list[str], *, required: bool) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        try:
            result = self.run_command(command)
        except FileNotFoundError:
            return None, {
                "status": "failed" if required else "warning",
                "command": command,
                "reason": "command-not-found",
                "detail": f"{command[0]} is not available",
            }
        except Exception as exc:
            return None, {
                "status": "failed" if required else "warning",
                "command": command,
                "reason": "command-error",
                "detail": str(exc),
            }

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return None, {
                "status": "failed" if required else "warning",
                "command": command,
                "reason": "command-failed",
                "detail": detail or f"exit code {result.returncode}",
            }

        try:
            return json.loads(result.stdout or "{}"), {
                "status": "passed",
                "command": command,
            }
        except json.JSONDecodeError:
            return None, {
                "status": "failed" if required else "warning",
                "command": command,
                "reason": "invalid-json",
                "detail": "command output is not valid JSON",
            }

    def snapshot(self) -> dict[str, Any]:
        checks = []
        warnings = []
        blocking_issues = []
        nodes = []
        pods = []
        restart_index = {}
        node_not_ready_event_count = 0

        node_payload, node_check = self._run_json(["kubectl", "get", "nodes", "-o", "json"], required=True)
        checks.append({"name": "kubernetes_nodes", **node_check})
        if node_payload is None:
            blocking_issues.append(node_check)
        else:
            for node in node_payload.get("items") or []:
                name = node.get("metadata", {}).get("name")
                conditions = node.get("status", {}).get("conditions") or []
                ready = _condition_status(conditions, "Ready") == "True"
                nodes.append({"name": name, "ready": ready})
            if not nodes:
                blocking_issues.append({"name": "kubernetes_nodes", "detail": "no nodes found"})
            elif not any(node.get("ready") for node in nodes):
                blocking_issues.append({"name": "kubernetes_nodes", "detail": "no Ready nodes found"})

        pod_command = ["kubectl", "get", "pods"]
        if self.namespaces:
            pod_command.extend(["-A"])
        else:
            pod_command.extend(["-A"])
        pod_command.extend(["-o", "json"])
        pod_payload, pod_check = self._run_json(pod_command, required=True)
        checks.append({"name": "kubernetes_pods", **pod_check})
        if pod_payload is None:
            blocking_issues.append(pod_check)
        else:
            selected_namespaces = set(self.namespaces)
            non_ready_pods = []
            for pod in pod_payload.get("items") or []:
                metadata = pod.get("metadata") or {}
                namespace = str(metadata.get("namespace") or "").strip()
                if selected_namespaces and namespace not in selected_namespaces:
                    continue
                name = str(metadata.get("name") or "").strip()
                status = pod.get("status") or {}
                phase = str(status.get("phase") or "").strip()
                conditions = status.get("conditions") or []
                succeeded = phase == "Succeeded"
                ready = succeeded or _condition_status(conditions, "Ready") == "True"
                restarts = 0
                for container in (status.get("initContainerStatuses") or []) + (status.get("containerStatuses") or []):
                    container_name = str(container.get("name") or "").strip()
                    restart_count = int(container.get("restartCount") or 0)
                    restarts += restart_count
                    if container_name:
                        restart_index[f"{namespace}/{name}/{container_name}"] = restart_count
                pod_summary = {
                    "namespace": namespace,
                    "name": name,
                    "phase": phase,
                    "ready": ready,
                    "restarts": restarts,
                }
                pods.append(pod_summary)
                if not ready:
                    non_ready_pods.append(pod_summary)
            if non_ready_pods:
                blocking_issues.append(
                    {
                        "name": "kubernetes_pods",
                        "detail": f"{len(non_ready_pods)} pod(s) are not Ready",
                        "pods": non_ready_pods[:10],
                    }
                )

        events_payload, events_check = self._run_json(["kubectl", "get", "events", "-A", "-o", "json"], required=False)
        checks.append({"name": "kubernetes_events", **events_check})
        if events_payload is None and events_check.get("status") == "warning":
            warnings.append(events_check)
        elif events_payload is not None:
            for event in events_payload.get("items") or []:
                reason = str(event.get("reason") or "").strip()
                message = str(event.get("message") or "").strip()
                if reason == "NodeNotReady" or "NodeNotReady" in message:
                    node_not_ready_event_count += _event_count(event)
            if node_not_ready_event_count:
                warnings.append(
                    {
                        "name": "node_not_ready_events",
                        "detail": f"{node_not_ready_event_count} NodeNotReady event(s) are present",
                    }
                )

        restart_total = sum(restart_index.values())
        if restart_total:
            warnings.append(
                {
                    "name": "pod_restarts",
                    "detail": f"{restart_total} restart(s) are already present in the selected namespaces",
                }
            )

        if blocking_issues:
            status = "failed"
        elif warnings:
            status = "warning"
        else:
            status = "passed"

        return {
            "status": status,
            "timestamp": _utc_timestamp(),
            "namespaces": self.namespaces,
            "checks": checks,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
            "nodes": nodes,
            "pods": pods,
            "restart_index": restart_index,
            "restart_total": restart_total,
            "node_not_ready_event_count": node_not_ready_event_count,
        }

    def wait_until_ready(self, *, timeout_seconds: int = 120, poll_interval_seconds: int = 5) -> dict[str, Any]:
        timeout_seconds = max(0, int(timeout_seconds))
        poll_interval_seconds = max(1, int(poll_interval_seconds))
        deadline = self.monotonic() + timeout_seconds
        attempts = 0
        last_snapshot = None

        while True:
            attempts += 1
            last_snapshot = self.snapshot()
            last_snapshot["wait"] = {
                "attempts": attempts,
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
                "timed_out": False,
            }
            if last_snapshot.get("status") in {"passed", "warning"}:
                return last_snapshot

            remaining = deadline - self.monotonic()
            if remaining <= 0:
                last_snapshot["wait"]["timed_out"] = True
                return last_snapshot
            self.sleep(min(poll_interval_seconds, remaining))


def compare_local_stability(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    before = before or {}
    after = after or {}
    restart_deltas = []
    before_restarts = before.get("restart_index") if isinstance(before.get("restart_index"), dict) else {}
    after_restarts = after.get("restart_index") if isinstance(after.get("restart_index"), dict) else {}
    for key, value in sorted(after_restarts.items()):
        try:
            delta = int(value or 0) - int(before_restarts.get(key) or 0)
        except (TypeError, ValueError):
            delta = 0
        if delta > 0:
            restart_deltas.append({"container": key, "delta": delta, "after": value})

    try:
        node_not_ready_delta = int(after.get("node_not_ready_event_count") or 0) - int(
            before.get("node_not_ready_event_count") or 0
        )
    except (TypeError, ValueError):
        node_not_ready_delta = 0
    node_not_ready_delta = max(0, node_not_ready_delta)

    warnings = []
    if restart_deltas:
        warnings.append(
            {
                "name": "pod_restart_delta",
                "detail": f"{len(restart_deltas)} container(s) restarted during validation",
            }
        )
    if node_not_ready_delta:
        warnings.append(
            {
                "name": "node_not_ready_delta",
                "detail": f"{node_not_ready_delta} NodeNotReady event(s) appeared during validation",
            }
        )

    after_status = str(after.get("status") or "").strip().lower()
    if after_status == "failed":
        status = "failed"
    elif warnings or after_status == "warning":
        status = "warning"
    else:
        status = "passed"

    return {
        "status": status,
        "timestamp": _utc_timestamp(),
        "restart_deltas": restart_deltas,
        "node_not_ready_delta": node_not_ready_delta,
        "warnings": warnings,
    }
