"""Kafka-related validation helpers for Level 6."""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Callable

KAFKA_LEVEL6_RUN_FLAG = "PIONERA_LEVEL6_RUN_KAFKA"
KAFKA_LEVEL6_SKIP_FLAG = "PIONERA_LEVEL6_SKIP_KAFKA"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_bootstrap_servers(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = str(value).split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def _bootstrap_host(address: str) -> str:
    raw = str(address or "").strip()
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    if raw.startswith("[") and "]:" in raw:
        host, _, _port = raw.rpartition(":")
        return host.strip("[]").strip().lower()
    if ":" in raw:
        host, _port = raw.rsplit(":", 1)
        return host.strip().lower()
    return raw.strip().lower()


def _invalid_vm_distributed_connector_bootstrap_reason(address: str) -> str:
    host = _bootstrap_host(address)
    if not host:
        return "empty-host"
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return "loopback-address"
    if host in {"host.minikube.internal", "host.docker.internal"}:
        return "local-runtime-host-alias"
    if host == "framework-kafka":
        return "kubernetes-service-short-name"
    if host.endswith(".svc") or ".svc." in host or host.endswith(".svc.cluster.local"):
        return "kubernetes-cluster-dns"
    return ""


def _configured_connector_image(deployer_config: dict[str, Any], env: dict[str, str]) -> bool:
    connector_name = (
        env.get("PIONERA_INESDATA_CONNECTOR_IMAGE_NAME")
        or env.get("INESDATA_CONNECTOR_IMAGE_NAME")
        or deployer_config.get("INESDATA_CONNECTOR_IMAGE_NAME")
    )
    connector_tag = (
        env.get("PIONERA_INESDATA_CONNECTOR_IMAGE_TAG")
        or env.get("INESDATA_CONNECTOR_IMAGE_TAG")
        or deployer_config.get("INESDATA_CONNECTOR_IMAGE_TAG")
    )
    return bool(str(connector_name or "").strip() and str(connector_tag or "").strip())


def _level4_local_images_enabled(deployer_config: dict[str, Any], env: dict[str, str]) -> bool:
    for key in (
        "PIONERA_INESDATA_LOCAL_IMAGES_MODE",
        "INESDATA_LOCAL_IMAGES_MODE",
        "LEVEL4_INESDATA_LOCAL_IMAGES_MODE",
        "LEVEL4_LOCAL_IMAGES_MODE",
    ):
        value = env.get(key)
        if value is None:
            value = deployer_config.get(key)
        if value is None or not str(value).strip():
            continue
        normalized = str(value).strip().lower()
        return normalized not in {"0", "false", "no", "off", "disabled", "disable"}
    return False


def _remote_image_import_enabled(deployer_config: dict[str, Any], env: dict[str, str]) -> bool:
    value = env.get("VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT")
    if value is None:
        value = deployer_config.get("VM_DISTRIBUTED_REMOTE_IMAGE_IMPORT")
    return _truthy(value)


def validate_kafka_runtime_preflight(
    runtime_config: dict[str, Any] | None,
    deployer_config: dict[str, Any] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate the Kafka runtime contract before running Level 6 transfer tests."""
    runtime_config = runtime_config if isinstance(runtime_config, dict) else {}
    deployer_config = deployer_config if isinstance(deployer_config, dict) else {}
    env = env or os.environ
    topology = str(
        runtime_config.get("topology")
        or deployer_config.get("TOPOLOGY")
        or ""
    ).strip().lower()

    result = {
        "status": "passed",
        "topology": topology or "unknown",
        "errors": [],
        "warnings": [],
        "connector_bootstrap_servers": [],
    }

    if topology != "vm-distributed":
        return result

    connector_bootstrap = (
        env.get("KAFKA_CLUSTER_BOOTSTRAP_SERVERS")
        or runtime_config.get("cluster_bootstrap_servers")
        or deployer_config.get("KAFKA_CLUSTER_BOOTSTRAP_SERVERS")
    )
    if not connector_bootstrap:
        fallback_bootstrap = (
            env.get("KAFKA_BOOTSTRAP_SERVERS")
            or runtime_config.get("bootstrap_servers")
            or deployer_config.get("KAFKA_BOOTSTRAP_SERVERS")
        )
        if fallback_bootstrap:
            connector_bootstrap = fallback_bootstrap
            result["warnings"].append(
                "KAFKA_CLUSTER_BOOTSTRAP_SERVERS is empty; using KAFKA_BOOTSTRAP_SERVERS as the connector-visible Kafka endpoint."
            )

    connector_bootstrap_servers = _normalize_bootstrap_servers(connector_bootstrap)
    result["connector_bootstrap_servers"] = connector_bootstrap_servers
    if not connector_bootstrap_servers:
        result["errors"].append(
            "vm-distributed Kafka validation requires KAFKA_CLUSTER_BOOTSTRAP_SERVERS or KAFKA_BOOTSTRAP_SERVERS with an endpoint reachable from every connector VM/cluster."
        )

    invalid = []
    for address in connector_bootstrap_servers:
        reason = _invalid_vm_distributed_connector_bootstrap_reason(address)
        if reason:
            invalid.append({"address": address, "reason": reason})
    if invalid:
        result["errors"].append(
            "vm-distributed Kafka connector bootstrap cannot use localhost, minikube/docker host aliases, or Kubernetes ClusterIP/DNS names."
        )
        result["invalid_connector_bootstrap_servers"] = invalid

    if not _configured_connector_image(deployer_config, env):
        if not _level4_local_images_enabled(deployer_config, env) and not _remote_image_import_enabled(deployer_config, env):
            result["warnings"].append(
                "INESDATA_CONNECTOR_IMAGE_NAME/TAG are not configured and Level 4 local image import is disabled. Ensure the chart image includes EDC data-plane-kafka support before running Kafka transfer validation."
            )

    if result["errors"]:
        result["status"] = "failed"
    return result


def should_run_kafka_edc_validation(
    *,
    flag_enabled: Callable[[str, bool], bool] | None = None,
) -> bool:
    """Kafka transfer validation is opt-in in Level 6 because it is slow."""
    flag_enabled = flag_enabled or (lambda _name, default=False: default)
    if flag_enabled(KAFKA_LEVEL6_SKIP_FLAG, False):
        return False
    return flag_enabled(KAFKA_LEVEL6_RUN_FLAG, False)


def run_kafka_edc_validation(
    connectors: list[str],
    experiment_dir: str,
    *,
    validator: Any,
    experiment_storage: Any,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    if len(connectors) < 2:
        results = [
            {
                "status": "skipped",
                "reason": "not_enough_connectors",
                "timestamp": datetime.now().isoformat(),
            }
        ]
        experiment_storage.save_kafka_edc_results_json(results, experiment_dir)
        return results

    try:
        run_kwargs = {
            "experiment_dir": experiment_dir,
        }
        if progress_callback is not None:
            run_kwargs["progress_callback"] = progress_callback
        results = list(validator.run_all(connectors, **run_kwargs) or [])
    except Exception as exc:
        results = [
            {
                "status": "failed",
                "reason": "execution_error",
                "timestamp": datetime.now().isoformat(),
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        ]
    experiment_storage.save_kafka_edc_results_json(results, experiment_dir)
    return results
