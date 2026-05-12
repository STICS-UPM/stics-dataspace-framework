import argparse
import contextlib
import getpass
import importlib
import inspect
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.parse

from runtime_dependencies import ensure_runtime_dependencies


ensure_runtime_dependencies(
    requirements_path=os.path.join(os.path.dirname(__file__), "requirements.txt"),
    module_names=("requests", "matplotlib", "kafka", "docker", "testcontainers", "yaml", "minio", "tabulate"),
    label="framework root",
    module_requirements={
        "requests": "requests",
        "matplotlib": "matplotlib",
        "kafka": "kafka-python",
        "docker": "docker",
        "testcontainers": "testcontainers",
        "yaml": "PyYAML",
        "minio": "minio",
        "tabulate": "tabulate",
    },
)

from framework.experiment_runner import ExperimentRunner
from framework.experiment_storage import ExperimentStorage
from framework.kafka_edc_validation import KafkaEdcValidationSuite
from framework.kafka_manager import KafkaManager
from framework.local_capacity import (
    LOCAL_COEXISTENCE_MEMORY_MB,
    evaluate_local_coexistence_capacity,
    node_capacity_memory_mb,
    parse_memory_quantity_mb,
    summarize_local_workloads,
)
from framework.local_stability import LocalStabilityMonitor, compare_local_stability
from framework.metrics_collector import MetricsCollector
from framework.reporting.experiment_loader import ExperimentLoader
from framework.reporting.report_generator import ExperimentReportGenerator
from framework.transfer_storage_verifier import TransferStorageVerifier
from framework.validation_engine import ValidationEngine
from framework import local_menu_tools
from deployers.infrastructure.lib.hosts_manager import (
    apply_managed_blocks,
    blocks_as_dict,
    build_context_host_blocks,
    detect_legacy_external_hostnames,
    hostnames_by_level,
    parse_hostnames,
)
from deployers.infrastructure.lib.config_loader import (
    apply_pionera_environment_overrides,
    detect_topology_key_migration_warnings,
    load_deployer_config as load_raw_deployer_config,
    load_layered_deployer_config,
    topology_overlay_config_path,
)
from deployers.infrastructure.lib.public_hostnames import (
    resolved_common_service_hostnames,
    resolved_common_service_urls,
)
from deployers.infrastructure.lib.orchestrator import DeployerOrchestrator
from deployers.infrastructure.lib.topology import SUPPORTED_TOPOLOGIES as DEPLOYER_SUPPORTED_TOPOLOGIES
from deployers.infrastructure.lib.topology import LOCAL_TOPOLOGY, normalize_topology
from deployers.shared.lib.cluster_runtime import (
    SUPPORTED_CLUSTER_TYPES,
    build_cluster_runtime,
    normalize_cluster_type,
)
from validation.core.test_data_cleanup import run_pre_validation_cleanup
from validation.orchestration.hosts import (
    ensure_public_endpoints_accessible,
    normalize_public_endpoint_url,
)
from validation.orchestration.components import (
    run_component_validations as run_level6_component_validations,
    should_run_component_validation as should_run_level6_component_validation,
)
from validation.orchestration.kafka import run_kafka_edc_validation
from validation.orchestration.reports import (
    build_experiment_dashboard,
    discover_report_experiments,
    format_report_experiment_summary,
    launch_playwright_report,
    launch_static_report_server,
    open_local_url,
)
from validation.orchestration.targets import (
    build_validation_target_plan,
    discover_validation_targets,
    format_validation_target_plan,
    load_validation_target,
    run_validation_target_read_only,
)
from validation.components.runner import (
    run_component_validations as run_registered_component_validations,
    summarize_component_results,
)
from validation.ui import interactive_menu as ui_interactive_menu
from validation.ui.ui_runner import run_playwright_validation
import requests


ADAPTER_REGISTRY = {
    "inesdata": "adapters.inesdata.adapter:InesdataAdapter",
    "edc": "adapters.edc.adapter:EdcAdapter",
}
DEPLOYER_REGISTRY = {
    "inesdata": "deployers.inesdata.deployer:InesdataDeployer",
    "edc": "deployers.edc.deployer:EdcDeployer",
}

SUPPORTED_COMMANDS = ("deploy", "validate", "metrics", "run", "hosts", "local-repair", "recreate-dataspace")
SUPPORTED_TOPOLOGIES = DEPLOYER_SUPPORTED_TOPOLOGIES
SUPPORTED_VALIDATION_MODES = ("auto", "stable", "fast")
LEVEL_DESCRIPTIONS = {
    1: "Setup Cluster",
    2: "Deploy Common Services",
    3: "Deploy Dataspace",
    4: "Deploy Connectors",
    5: "Deploy Components",
    6: "Run Validation Tests",
}


def _env_flag(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in ("1", "true", "yes", "on")


def _argv_has_topology_option(argv):
    args = list(sys.argv[1:] if argv is None else argv)
    for index, value in enumerate(args):
        if value == "--topology":
            return index + 1 < len(args)
        if value.startswith("--topology="):
            return True
    return False


def _resolve_level6_validation_mode(mode=None, topology="local", env=None):
    env = env if env is not None else os.environ
    requested = str(
        mode
        or env.get("PIONERA_VALIDATION_MODE")
        or env.get("LEVEL6_VALIDATION_MODE")
        or "auto"
    ).strip().lower()
    if requested == "local-stable":
        requested = "stable"
    if requested not in SUPPORTED_VALIDATION_MODES:
        raise ValueError(
            "Unsupported validation mode "
            f"'{requested}'. Choose from {', '.join(SUPPORTED_VALIDATION_MODES)}."
        )

    normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
    effective = "stable" if requested == "auto" and normalized_topology == LOCAL_TOPOLOGY else requested
    if effective == "auto":
        effective = "fast"

    return {
        "requested": requested,
        "effective": effective,
        "topology": normalized_topology,
        "local_stable": normalized_topology == LOCAL_TOPOLOGY and effective == "stable",
    }


def _should_run_level6_local_stability_checks(validation_mode_info, deployer_name=None, validation_profile=None, env=None):
    env = env if env is not None else os.environ
    if str(env.get("PIONERA_LOCAL_STABILITY_CHECKS", "true")).strip().lower() in ("0", "false", "no", "off"):
        return False
    if not isinstance(validation_mode_info, dict) or not validation_mode_info.get("local_stable"):
        return False
    supported = {"inesdata", "edc"}
    if str(deployer_name or "").strip().lower() not in supported:
        return False
    if validation_profile is None:
        return True
    return str(getattr(validation_profile, "adapter", "") or "").strip().lower() in supported


def _level6_local_stability_namespaces(deployer_context):
    namespaces = []
    roles = _context_namespace_roles_dict(deployer_context) if deployer_context is not None else {}
    for value in roles.values():
        namespace = str(value or "").strip()
        if namespace and namespace not in namespaces:
            namespaces.append(namespace)

    config = getattr(deployer_context, "config", {}) if deployer_context is not None else {}
    if isinstance(config, dict):
        for key in ("NS_COMMON", "COMMON_SERVICES_NAMESPACE", "COMPONENTS_NAMESPACE"):
            namespace = str(config.get(key) or "").strip()
            if namespace and namespace not in namespaces:
                namespaces.append(namespace)

    for namespace in ("common-srvs", "components", "ingress-nginx", "kube-system"):
        if namespace not in namespaces:
            namespaces.append(namespace)
    return namespaces


def _write_level6_local_stability_artifact(experiment_dir, name, payload):
    if not experiment_dir:
        return None
    path = os.path.join(experiment_dir, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path


def _level6_local_stability_failure_message(snapshot):
    issues = list(snapshot.get("blocking_issues") or []) if isinstance(snapshot, dict) else []
    details = []
    for issue in issues[:5]:
        name = str(issue.get("name") or "check").strip()
        detail = str(issue.get("detail") or issue.get("reason") or "not ready").strip()
        details.append(f"{name}: {detail}")
    suffix = f" Details: {'; '.join(details)}" if details else ""
    artifact = snapshot.get("artifact") if isinstance(snapshot, dict) else None
    artifact_suffix = f" Artifact: {artifact}" if artifact else ""
    return (
        "Local stable validation cannot start because the local Kubernetes runtime "
        f"is not ready after the stability wait window.{suffix}{artifact_suffix}"
    )


def _print_level6_local_stability(label, payload):
    if not isinstance(payload, dict):
        return
    status = str(payload.get("status") or "").strip().lower()
    if not status or status == "skipped":
        return
    warnings = list(payload.get("warnings") or [])
    blocking = list(payload.get("blocking_issues") or [])
    if status == "passed":
        print(f"Local stability {label}: ready.")
    elif status == "warning":
        print(f"Local stability {label}: warning ({len(warnings)} warning(s)).")
    elif status == "failed":
        print(f"Local stability {label}: failed ({len(blocking)} blocking issue(s)).")


def _run_json_command(command):
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None


def _docker_memory_total_mb():
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.MemTotal}}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return parse_memory_quantity_mb((result.stdout or "").strip())


def _adapter_default_namespace(adapter_name):
    defaults = {"inesdata": "core-control", "edc": "edc-control"}
    return defaults.get(str(adapter_name or "").strip().lower(), "")


def _adapter_config_namespace(adapter_name):
    normalized = str(adapter_name or "").strip().lower()
    if not normalized:
        return ""
    root_dir = os.path.dirname(__file__)
    config = {}
    for filename in ("deployer.config.example", "deployer.config"):
        config_path = os.path.join(root_dir, "deployers", normalized, filename)
        config.update(load_raw_deployer_config(config_path))
    return (
        str(
            config.get("DS_1_NAMESPACE")
            or config.get("NAMESPACE")
            or config.get("DS_1_NAME")
            or config.get("DS_NAME")
            or _adapter_default_namespace(normalized)
        ).strip()
    )


def _local_capacity_guard_mode(env=None):
    env = env if env is not None else os.environ
    return str(env.get("PIONERA_LOCAL_COEXISTENCE_GUARD") or "fail").strip().lower() or "fail"


def _level6_local_capacity_failure_message(payload):
    issues = list(payload.get("blocking_issues") or []) if isinstance(payload, dict) else []
    details = []
    for issue in issues[:5]:
        detail = str(issue.get("detail") or issue.get("name") or "insufficient local capacity").strip()
        details.append(detail)
    suffix = f" Details: {'; '.join(details)}" if details else ""
    recommendations = list(payload.get("recommendations") or []) if isinstance(payload, dict) else []
    recommendation_suffix = f" Recommended action: {recommendations[0]}" if recommendations else ""
    artifact = payload.get("artifact") if isinstance(payload, dict) else None
    artifact_suffix = f" Artifact: {artifact}" if artifact else ""
    return (
        "Local EDC/INESData coexistence is not clean enough to run Level 6 safely."
        f"{suffix}{recommendation_suffix}{artifact_suffix}"
    )


def _print_level6_local_capacity(payload):
    if not isinstance(payload, dict):
        return
    status = str(payload.get("status") or "").strip().lower()
    if not status or status == "skipped":
        return
    if status == "passed":
        print("Local coexistence capacity preflight: ready.")
    elif status == "warning":
        print("Local coexistence capacity preflight: warning.")
    elif status == "failed":
        print("Local coexistence capacity preflight: failed.")


def _local_capacity_probe(adapter_namespaces):
    nodes_payload = _run_json_command(["kubectl", "get", "nodes", "-o", "json"])
    pods_payload = _run_json_command(["kubectl", "get", "pods", "-A", "-o", "json"])
    node_memory_mb = node_capacity_memory_mb(nodes_payload)
    docker_memory_mb = _docker_memory_total_mb()
    configured_memory_mb = None
    try:
        infrastructure_config = load_layered_deployer_config(
            [_infrastructure_deployer_config_path()],
            topology=LOCAL_TOPOLOGY,
        )
        configured_memory_mb = parse_memory_quantity_mb(infrastructure_config.get("MINIKUBE_MEMORY"))
    except Exception:
        configured_memory_mb = None

    summary = summarize_local_workloads(
        pods_payload,
        adapter_namespaces=adapter_namespaces,
        component_namespaces=["components"],
    )
    return summary, node_memory_mb, docker_memory_mb, configured_memory_mb


def _local_capacity_adapter_namespaces(deployer_name=None, deployer_context=None):
    adapter_namespaces = {
        "inesdata": _adapter_config_namespace("inesdata"),
        "edc": _adapter_config_namespace("edc"),
    }
    current_roles = _context_namespace_roles_dict(deployer_context)
    current_namespace = str(current_roles.get("registration_service_namespace") or "").strip()
    current_adapter = str(deployer_name or "").strip().lower()
    if current_adapter in adapter_namespaces and current_namespace:
        adapter_namespaces[current_adapter] = current_namespace
    return adapter_namespaces


def _local_adapter_switch_confirmation_token(target_adapter):
    normalized = str(target_adapter or "").strip().upper()
    return f"SWITCH TO {normalized}" if normalized else "SWITCH LOCAL ADAPTER"


def _unique_non_empty(values):
    unique = []
    for value in values or []:
        normalized = str(value or "").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _local_switch_protected_namespaces():
    return {
        "default",
        "kube-system",
        "kube-public",
        "kube-node-lease",
        "common-srvs",
        "ingress-nginx",
    }


def _local_adapter_runtime_cleanup_entries(adapters_to_remove):
    root_dir = os.path.dirname(__file__)
    entries = []
    for adapter_name in _unique_non_empty(adapters_to_remove):
        normalized = adapter_name.lower()
        if normalized not in {"inesdata", "edc"}:
            continue
        config = {}
        for filename in ("deployer.config.example", "deployer.config"):
            config_path = os.path.join(root_dir, "deployers", normalized, filename)
            config.update(load_raw_deployer_config(config_path))

        environment = str(config.get("ENVIRONMENT") or "DEV").strip().upper() or "DEV"
        dataspace = str(
            config.get("DS_1_NAME")
            or config.get("DS_NAME")
            or _adapter_default_namespace(normalized)
        ).strip()
        if not dataspace:
            continue

        deployments_root = os.path.abspath(os.path.join(root_dir, "deployers", normalized, "deployments"))
        runtime_dir = os.path.abspath(os.path.join(deployments_root, environment, dataspace))
        if runtime_dir == deployments_root or not runtime_dir.startswith(deployments_root + os.sep):
            continue
        entries.append(
            {
                "adapter": normalized,
                "path": runtime_dir,
                "managed_root": deployments_root,
            }
        )
    return entries


def _build_local_adapter_switch_plan(payload, target_adapter):
    workloads = payload.get("workloads", {}) if isinstance(payload, dict) else {}
    target = str(target_adapter or "").strip().lower()
    active_adapters = set(workloads.get("active_adapters") or [])
    adapter_namespaces = dict(workloads.get("adapter_namespaces") or {})
    active_component_namespaces = _unique_non_empty(workloads.get("active_component_namespaces") or [])

    adapters_to_remove = set(active_adapters - {target})
    if target == "edc" and active_component_namespaces:
        adapters_to_remove.add("inesdata")
    adapters_to_remove = sorted(adapter for adapter in adapters_to_remove if adapter in {"inesdata", "edc"})

    namespace_actions = []
    for adapter_name in adapters_to_remove:
        namespace = str(adapter_namespaces.get(adapter_name) or _adapter_config_namespace(adapter_name) or "").strip()
        if namespace:
            namespace_actions.append(
                {
                    "namespace": namespace,
                    "reason": f"{adapter_name}-adapter",
                    "adapter": adapter_name,
                    "allow_components_namespace": False,
                }
            )

    if "inesdata" in adapters_to_remove or target == "edc":
        for namespace in active_component_namespaces:
            namespace_actions.append(
                {
                    "namespace": namespace,
                    "reason": "components",
                    "adapter": "inesdata",
                    "allow_components_namespace": True,
                }
            )

    deduped_actions = []
    seen_namespaces = set()
    blocked_namespaces = []
    protected = _local_switch_protected_namespaces()
    for action in namespace_actions:
        namespace = str(action.get("namespace") or "").strip()
        if not namespace or namespace in seen_namespaces:
            continue
        seen_namespaces.add(namespace)
        is_components_namespace = namespace == "components"
        if namespace in protected or (is_components_namespace and not action.get("allow_components_namespace")):
            blocked_namespaces.append(namespace)
            continue
        deduped_actions.append({**action, "namespace": namespace})

    return {
        "status": "planned",
        "target_adapter": target,
        "confirmation_token": _local_adapter_switch_confirmation_token(target),
        "adapters_to_remove": adapters_to_remove,
        "namespace_actions": deduped_actions,
        "namespaces_to_delete": [action["namespace"] for action in deduped_actions],
        "blocked_namespaces": sorted(blocked_namespaces),
        "runtime_dirs": _local_adapter_runtime_cleanup_entries(adapters_to_remove),
        "preserved_namespaces": ["common-srvs"],
    }


def _print_local_adapter_switch_plan(plan):
    print()
    print("LOCAL ADAPTER SWITCH REQUIRED")
    print(f"Target adapter: {plan.get('target_adapter')}")
    adapters = ", ".join(plan.get("adapters_to_remove") or []) or "none"
    namespaces = ", ".join(plan.get("namespaces_to_delete") or []) or "none"
    print(f"Adapters to remove: {adapters}")
    print(f"Namespaces to delete: {namespaces}")
    print("Preserved namespaces: common-srvs")
    runtime_dirs = [entry.get("path") for entry in plan.get("runtime_dirs") or [] if entry.get("path")]
    if runtime_dirs:
        print("Managed runtime directories to remove:")
        for runtime_dir in runtime_dirs:
            print(f"- {runtime_dir}")


def _local_adapter_switch_approved(plan, env=None):
    env = env if env is not None else os.environ
    mode = str(env.get("PIONERA_LOCAL_ADAPTER_SWITCH") or "prompt").strip().lower()
    if mode in {"0", "false", "no", "off", "disabled"}:
        return False

    token = str(plan.get("confirmation_token") or "").strip()
    provided = str(env.get("PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM") or "").strip()
    if token and provided == token:
        return True

    if not bool(getattr(sys.stdin, "isatty", lambda: False)()):
        return False

    _print_local_adapter_switch_plan(plan)
    print()
    print("This will remove the previous local adapter installation.")
    print("(common services are not removed)")
    answer = _interactive_read(f"Type {token} to continue: ")
    return bool(token and answer == token)


def _run_switch_command(args):
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return types.SimpleNamespace(returncode=127, stdout="", stderr=str(exc))


def _wait_for_local_switch_namespace_deleted(namespace, timeout=120, poll_interval=3):
    deadline = time.time() + timeout
    while time.time() <= deadline:
        result = _run_switch_command(["kubectl", "get", "namespace", namespace])
        if result.returncode != 0:
            return True
        time.sleep(poll_interval)
    return False


def _safe_remove_local_switch_runtime_dir(entry):
    runtime_dir = os.path.abspath(str(entry.get("path") or ""))
    managed_root = os.path.abspath(str(entry.get("managed_root") or ""))
    if not runtime_dir or not managed_root:
        return {"status": "skipped", "reason": "missing-path", "path": runtime_dir}
    if runtime_dir == managed_root or not runtime_dir.startswith(managed_root + os.sep):
        return {"status": "skipped", "reason": "outside-managed-root", "path": runtime_dir}
    if not os.path.exists(runtime_dir):
        return {"status": "skipped", "reason": "not-found", "path": runtime_dir}
    shutil.rmtree(runtime_dir)
    return {"status": "removed", "path": runtime_dir}


def _execute_local_adapter_switch_plan(plan):
    if not plan.get("namespace_actions") and not plan.get("runtime_dirs"):
        return {**plan, "status": "skipped", "reason": "no-managed-resources"}
    if plan.get("blocked_namespaces"):
        blocked = ", ".join(plan.get("blocked_namespaces") or [])
        raise RuntimeError(f"Local adapter switch refused protected namespaces: {blocked}")

    print()
    print("Switching local adapter resources...")
    namespace_results = []
    for action in plan.get("namespace_actions") or []:
        namespace = action["namespace"]
        print(f"- Deleting namespace {namespace}")
        result = _run_switch_command(
            ["kubectl", "delete", "namespace", namespace, "--ignore-not-found=true"]
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip() or f"kubectl exited with {result.returncode}"
            raise RuntimeError(f"Could not delete namespace '{namespace}'. Root cause: {detail}")
        if not _wait_for_local_switch_namespace_deleted(namespace):
            raise RuntimeError(f"Timed out waiting for namespace '{namespace}' to be deleted")
        namespace_results.append({"namespace": namespace, "status": "deleted", "reason": action.get("reason")})

    runtime_results = []
    for entry in plan.get("runtime_dirs") or []:
        result = _safe_remove_local_switch_runtime_dir(entry)
        runtime_results.append(result)
        if result.get("status") == "removed":
            print(f"- Removed runtime artifacts {result['path']}")

    return {
        **plan,
        "status": "completed",
        "deleted_namespaces": [result["namespace"] for result in namespace_results],
        "namespace_results": namespace_results,
        "runtime_results": runtime_results,
    }


def _try_local_adapter_switch(payload, target_adapter):
    plan = _build_local_adapter_switch_plan(payload, target_adapter)
    if not plan.get("namespace_actions") and not plan.get("runtime_dirs"):
        return {**plan, "status": "skipped", "reason": "no-switch-plan"}
    if not _local_adapter_switch_approved(plan):
        return {**plan, "status": "declined"}
    return _execute_local_adapter_switch_plan(plan)


def _local_capacity_install_failure_message(payload, deployer_name, level_id):
    issues = list(payload.get("blocking_issues") or []) if isinstance(payload, dict) else []
    details = []
    for issue in issues[:5]:
        detail = str(issue.get("detail") or issue.get("name") or "insufficient local capacity").strip()
        details.append(detail)
    suffix = f" Details: {'; '.join(details)}" if details else ""
    workloads = payload.get("workloads", {}) if isinstance(payload, dict) else {}
    active = ", ".join(workloads.get("active_adapters") or [])
    components = ", ".join(workloads.get("active_component_namespaces") or [])
    active_suffix = f" Active adapters detected: {active}." if active else ""
    component_suffix = f" Active component namespaces detected: {components}." if components else ""
    token = _local_adapter_switch_confirmation_token(deployer_name)
    return (
        f"Cannot continue Level {level_id} for adapter '{deployer_name}' because local capacity "
        f"only supports one adapter at a time.{active_suffix}{component_suffix}{suffix} "
        "Recreate the local cluster from Level 1 before switching adapters, or increase Docker "
        f"Desktop memory and set LOCAL_RESOURCE_PROFILE=coexistence with MINIKUBE_MEMORY={LOCAL_COEXISTENCE_MEMORY_MB}. "
        f"To let the framework switch adapters, confirm the prompt or set PIONERA_LOCAL_ADAPTER_SWITCH_CONFIRM='{token}'."
    )


def _run_local_adapter_install_capacity_preflight(
    deployer_name,
    topology,
    level_id,
    *,
    deployer_context=None,
):
    normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
    current_adapter = str(deployer_name or "").strip().lower()
    if normalized_topology != LOCAL_TOPOLOGY or current_adapter not in {"inesdata", "edc"}:
        return {"status": "skipped", "reason": "not-local-adapter-install"}

    adapter_namespaces = _local_capacity_adapter_namespaces(
        deployer_name=current_adapter,
        deployer_context=deployer_context,
    )
    summary, node_memory_mb, docker_memory_mb, configured_memory_mb = _local_capacity_probe(adapter_namespaces)
    active_adapters = set(summary.get("active_adapters") or [])
    other_active_adapters = sorted(active_adapters - {current_adapter})
    component_namespaces_active = bool(summary.get("active_component_namespaces"))
    will_create_or_extend_coexistence = bool(other_active_adapters) or bool(summary.get("coexistence_detected"))
    if current_adapter == "edc" and component_namespaces_active:
        will_create_or_extend_coexistence = True
    summary["installing_adapter"] = current_adapter
    summary["other_active_adapters"] = other_active_adapters
    summary["coexistence_detected"] = bool(will_create_or_extend_coexistence)

    payload = evaluate_local_coexistence_capacity(
        summary,
        node_memory_mb=node_memory_mb,
        docker_memory_mb=docker_memory_mb,
        configured_minikube_memory_mb=configured_memory_mb,
        required_memory_mb=LOCAL_COEXISTENCE_MEMORY_MB,
        guard_mode=_local_capacity_guard_mode(),
    )
    if payload.get("status") == "failed":
        switch_result = _try_local_adapter_switch(payload, current_adapter)
        if switch_result.get("status") == "completed":
            summary, node_memory_mb, docker_memory_mb, configured_memory_mb = _local_capacity_probe(adapter_namespaces)
            summary["installing_adapter"] = current_adapter
            summary["other_active_adapters"] = sorted(set(summary.get("active_adapters") or []) - {current_adapter})
            payload = evaluate_local_coexistence_capacity(
                summary,
                node_memory_mb=node_memory_mb,
                docker_memory_mb=docker_memory_mb,
                configured_minikube_memory_mb=configured_memory_mb,
                required_memory_mb=LOCAL_COEXISTENCE_MEMORY_MB,
                guard_mode=_local_capacity_guard_mode(),
            )
            payload["switch"] = switch_result
            if payload.get("status") != "failed":
                print("Local adapter install capacity preflight: ready after switching local adapter.")
                return payload
        print("Local adapter install capacity preflight: failed.")
        payload["switch"] = switch_result
        raise RuntimeError(_local_capacity_install_failure_message(payload, current_adapter, level_id))
    if payload.get("status") == "warning":
        print("Local adapter install capacity preflight: warning.")
    return payload


def _run_level6_local_capacity_preflight(
    validation_mode_info,
    deployer_name,
    deployer_context,
    experiment_dir,
    *,
    validation_profile=None,
):
    if not _should_run_level6_local_stability_checks(
        validation_mode_info,
        deployer_name=deployer_name,
        validation_profile=validation_profile,
    ):
        return {"status": "skipped", "reason": "not-local-stable-runtime"}

    adapter_namespaces = _local_capacity_adapter_namespaces(
        deployer_name=deployer_name,
        deployer_context=deployer_context,
    )
    summary, node_memory_mb, docker_memory_mb, configured_memory_mb = _local_capacity_probe(adapter_namespaces)
    payload = evaluate_local_coexistence_capacity(
        summary,
        node_memory_mb=node_memory_mb,
        docker_memory_mb=docker_memory_mb,
        configured_minikube_memory_mb=configured_memory_mb,
        required_memory_mb=LOCAL_COEXISTENCE_MEMORY_MB,
        guard_mode=_local_capacity_guard_mode(),
    )
    payload["artifact"] = _write_level6_local_stability_artifact(
        experiment_dir,
        "local_capacity_preflight.json",
        payload,
    )
    _print_level6_local_capacity(payload)
    if payload.get("status") == "failed":
        raise RuntimeError(_level6_local_capacity_failure_message(payload))
    return payload


def _run_level6_local_stability_preflight(
    validation_mode_info,
    deployer_name,
    deployer_context,
    experiment_dir,
    *,
    validation_profile=None,
    monitor_cls=LocalStabilityMonitor,
):
    if not _should_run_level6_local_stability_checks(
        validation_mode_info,
        deployer_name=deployer_name,
        validation_profile=validation_profile,
    ):
        return {"status": "skipped", "reason": "not-local-stable-runtime"}

    namespaces = _level6_local_stability_namespaces(deployer_context)
    timeout = _positive_int_env("PIONERA_LOCAL_STABILITY_TIMEOUT_SECONDS", 120)
    poll_interval = max(1, _positive_int_env("PIONERA_LOCAL_STABILITY_POLL_SECONDS", 5))
    print("\nChecking local Kubernetes stability before Level 6...")
    monitor = monitor_cls(namespaces)
    snapshot = monitor.wait_until_ready(
        timeout_seconds=timeout,
        poll_interval_seconds=poll_interval,
    )
    snapshot["artifact"] = _write_level6_local_stability_artifact(
        experiment_dir,
        "local_stability_preflight.json",
        snapshot,
    )
    _print_level6_local_stability("preflight", snapshot)

    if snapshot.get("status") == "failed" and _env_flag("PIONERA_LOCAL_STABILITY_STRICT", default=True):
        raise RuntimeError(_level6_local_stability_failure_message(snapshot))
    return snapshot


def _run_level6_local_stability_postflight(
    validation_mode_info,
    deployer_name,
    deployer_context,
    experiment_dir,
    preflight_snapshot,
    *,
    validation_profile=None,
    monitor_cls=LocalStabilityMonitor,
):
    if not _should_run_level6_local_stability_checks(
        validation_mode_info,
        deployer_name=deployer_name,
        validation_profile=validation_profile,
    ):
        return {"status": "skipped", "reason": "not-local-stable-runtime"}
    if not isinstance(preflight_snapshot, dict) or preflight_snapshot.get("status") == "skipped":
        return {"status": "skipped", "reason": "missing-preflight"}

    namespaces = _level6_local_stability_namespaces(deployer_context)
    timeout = _positive_int_env("PIONERA_LOCAL_STABILITY_TIMEOUT_SECONDS", 120)
    poll_interval = max(1, _positive_int_env("PIONERA_LOCAL_STABILITY_POLL_SECONDS", 5))
    monitor = monitor_cls(namespaces)
    snapshot = monitor.wait_until_ready(
        timeout_seconds=timeout,
        poll_interval_seconds=poll_interval,
    )
    comparison = compare_local_stability(preflight_snapshot, snapshot)
    result = {
        "status": comparison.get("status"),
        "snapshot": snapshot,
        "comparison": comparison,
        "warnings": list(comparison.get("warnings") or []) + list(snapshot.get("warnings") or []),
        "blocking_issues": list(snapshot.get("blocking_issues") or []),
    }
    result["artifact"] = _write_level6_local_stability_artifact(
        experiment_dir,
        "local_stability_postflight.json",
        result,
    )
    _print_level6_local_stability("postflight", result)
    return result


@contextlib.contextmanager
def _temporary_environment(overrides=None):
    updates = dict(overrides or {})
    if not updates:
        yield
        return

    sentinel = object()
    previous = {}
    try:
        for key, value in updates.items():
            previous[key] = os.environ.get(key, sentinel)
            os.environ[key] = str(value)
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


@contextlib.contextmanager
def _temporary_adapter_auto_mode(adapter, enabled=True):
    targets = [
        adapter,
        getattr(adapter, "deployment", None),
        getattr(getattr(adapter, "deployment", None), "_delegate", None),
        getattr(adapter, "connectors", None),
        getattr(adapter, "infrastructure", None),
    ]
    sentinel = object()
    previous = []
    try:
        for target in targets:
            if target is None or not hasattr(target, "auto_mode_getter"):
                continue
            previous.append((target, getattr(target, "auto_mode_getter", sentinel)))
            setattr(target, "auto_mode_getter", lambda enabled=enabled: bool(enabled))
        yield
    finally:
        for target, old_value in previous:
            if old_value is sentinel:
                delattr(target, "auto_mode_getter")
            else:
                setattr(target, "auto_mode_getter", old_value)


_REDACTED_VALUE = "***REDACTED***"
_SENSITIVE_KEY_MARKERS = (
    "PASSWORD",
    "PASSWD",
    "TOKEN",
    "SECRET",
    "CLIENT_SECRET",
    "ACCESS_KEY",
    "SECRET_KEY",
    "PRIVATE_KEY",
)


def _is_sensitive_preview_key(key):
    normalized = str(key or "").strip().upper()
    if not normalized:
        return False
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _sanitize_preview_data(value, parent_key=None):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if _is_sensitive_preview_key(key):
                sanitized[key] = _REDACTED_VALUE
            else:
                sanitized[key] = _sanitize_preview_data(item, parent_key=key)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_preview_data(item, parent_key=parent_key) for item in value]
    return value


def _mapping_flag(mapping, key, default=False):
    if not isinstance(mapping, dict):
        return default
    raw_value = mapping.get(key)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in ("1", "true", "yes", "on")


def _mapping_value(mapping, *keys, default=None):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        raw_value = mapping.get(key)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            return value
    return default


def _edc_dashboard_runtime_present(deployer_context):
    runtime_dir = str(getattr(deployer_context, "runtime_dir", "") or "").strip()
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    if not runtime_dir or not connectors:
        return False

    for connector in connectors:
        dashboard_dir = os.path.join(runtime_dir, "dashboard", connector)
        if os.path.isfile(os.path.join(dashboard_dir, "app-config.json")) and os.path.isfile(
            os.path.join(dashboard_dir, "edc-connector-config.json")
        ):
            return True
    return False


def _edc_dashboard_runtime_auth_mode(deployer_context):
    runtime_dir = str(getattr(deployer_context, "runtime_dir", "") or "").strip()
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    if not runtime_dir or not connectors:
        return None

    for connector in connectors:
        values_file = os.path.join(runtime_dir, f"values-{connector}.yaml")
        if not os.path.isfile(values_file):
            continue
        try:
            with open(values_file, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    stripped = raw_line.strip()
                    if not stripped.startswith("authMode:"):
                        continue
                    auth_mode = stripped.split(":", 1)[1].strip().strip("'\"")
                    if auth_mode:
                        return auth_mode.lower()
        except OSError:
            continue
    return None


def _edc_dashboard_namespace(deployer_context):
    namespace_roles = getattr(deployer_context, "namespace_roles", None)
    namespace = str(getattr(namespace_roles, "provider_namespace", "") or "").strip()
    if namespace:
        return namespace
    namespace = str(getattr(namespace_roles, "consumer_namespace", "") or "").strip()
    if namespace:
        return namespace
    return str(getattr(deployer_context, "dataspace_name", "") or "").strip()


def _namespace_role_value(roles, key, default=""):
    if hasattr(roles, key):
        value = getattr(roles, key)
    elif isinstance(roles, dict):
        value = roles.get(key)
    else:
        value = None
    return str(value or default).strip()


def _edc_dashboard_connector_namespaces(deployer_context):
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    default_namespace = _edc_dashboard_namespace(deployer_context)
    if not connectors:
        return {}

    runtime_roles = getattr(deployer_context, "namespace_roles", None)
    provider_namespace = _namespace_role_value(
        runtime_roles,
        "provider_namespace",
        default_namespace,
    ) or default_namespace
    consumer_namespace = _namespace_role_value(
        runtime_roles,
        "consumer_namespace",
        provider_namespace,
    ) or provider_namespace

    if _context_namespace_profile(deployer_context) == "role-aligned":
        planned_roles = getattr(deployer_context, "planned_namespace_roles", None)
        provider_namespace = _namespace_role_value(
            planned_roles,
            "provider_namespace",
            provider_namespace,
        ) or provider_namespace
        consumer_namespace = _namespace_role_value(
            planned_roles,
            "consumer_namespace",
            consumer_namespace,
        ) or consumer_namespace

    connector_namespaces = {connectors[0]: provider_namespace}
    if len(connectors) >= 2:
        connector_namespaces[connectors[1]] = consumer_namespace
    for connector in connectors[2:]:
        connector_namespaces[connector] = default_namespace
    return connector_namespaces


def _inesdata_interface_connector_namespaces(deployer_context):
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    default_namespace = str(getattr(deployer_context, "dataspace_name", "") or "").strip()
    if not connectors:
        return {}

    runtime_roles = getattr(deployer_context, "namespace_roles", None)
    provider_namespace = _namespace_role_value(
        runtime_roles,
        "provider_namespace",
        default_namespace,
    ) or default_namespace
    consumer_namespace = _namespace_role_value(
        runtime_roles,
        "consumer_namespace",
        provider_namespace,
    ) or provider_namespace

    if _context_namespace_profile(deployer_context) == "role-aligned":
        planned_roles = getattr(deployer_context, "planned_namespace_roles", None)
        provider_namespace = _namespace_role_value(
            planned_roles,
            "provider_namespace",
            provider_namespace,
        ) or provider_namespace
        consumer_namespace = _namespace_role_value(
            planned_roles,
            "consumer_namespace",
            consumer_namespace,
        ) or consumer_namespace

    connector_namespaces = {connectors[0]: provider_namespace}
    if len(connectors) >= 2:
        connector_namespaces[connectors[1]] = consumer_namespace
    for connector in connectors[2:]:
        connector_namespaces[connector] = default_namespace
    return connector_namespaces


def _context_namespace_profile(context):
    return str(getattr(context, "namespace_profile", "compact") or "compact").strip() or "compact"


def _context_namespace_roles_dict(context):
    namespace_roles = getattr(context, "namespace_roles", None)
    if hasattr(namespace_roles, "as_dict"):
        return namespace_roles.as_dict()
    if isinstance(namespace_roles, dict):
        return dict(namespace_roles)
    return {}


def _context_planned_namespace_roles_dict(context):
    planned_roles = getattr(context, "planned_namespace_roles", None)
    if hasattr(planned_roles, "as_dict"):
        return planned_roles.as_dict()
    if isinstance(planned_roles, dict):
        return dict(planned_roles)
    return _context_namespace_roles_dict(context)


def _build_namespace_plan_summary(context):
    requested_profile = _context_namespace_profile(context)
    execution_roles = _context_namespace_roles_dict(context)
    planned_roles = _context_planned_namespace_roles_dict(context)
    changed_roles = {}
    for role_name, current_value in execution_roles.items():
        planned_value = planned_roles.get(role_name)
        if current_value != planned_value:
            changed_roles[role_name] = {
                "current": current_value,
                "planned": planned_value,
            }
    preview_only = bool(changed_roles)
    notes = []
    if preview_only:
        notes.append("Current runtime remains on the compatibility namespace layout in this phase.")
        notes.append("Planned role-aligned namespaces are preview-only until Level 3, Level 4, and charts are migrated.")
    return {
        "status": "preview-only" if preview_only else "active",
        "requested_profile": requested_profile,
        "change_count": len(changed_roles),
        "changed_roles": changed_roles,
        "notes": notes,
    }


def _positive_float_env(name, default):
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return float(default)
    try:
        return max(0.0, float(raw_value))
    except ValueError:
        print(f"[WARNING] Ignoring invalid {name}={raw_value!r}; using {default}")
        return float(default)


def _positive_int_env(name, default):
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return int(default)
    try:
        return max(0, int(raw_value))
    except ValueError:
        print(f"[WARNING] Ignoring invalid {name}={raw_value!r}; using {default}")
        return int(default)


def _kubectl_endpoint_ready(namespace, service_name):
    command = [
        "kubectl",
        "get",
        "endpoints",
        service_name,
        "-n",
        namespace,
        "-o",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "kubectl is not available"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or f"kubectl returned exit code {result.returncode}"

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False, "kubectl endpoint output is not valid JSON"

    subsets = payload.get("subsets") or []
    for subset in subsets:
        addresses = subset.get("addresses") or []
        ports = subset.get("ports") or []
        if addresses and ports:
            return True, f"{len(addresses)} endpoint address(es)"
    return False, "service has no ready endpoints"


def _probe_service_ready_across_namespaces(service_name, namespaces):
    unique_namespaces = []
    for namespace in namespaces or []:
        normalized = str(namespace or "").strip()
        if normalized and normalized not in unique_namespaces:
            unique_namespaces.append(normalized)

    if not unique_namespaces:
        return False, "no namespaces configured", None

    details = []
    for namespace in unique_namespaces:
        ready, detail = _kubectl_endpoint_ready(namespace, service_name)
        if ready:
            return True, detail, namespace
        details.append(f"{namespace}: {detail}")

    return False, "; ".join(details), unique_namespaces[0]


def _edc_dashboard_public_base_url(connector_name, deployer_context):
    ds_domain = str(getattr(deployer_context, "ds_domain_base", "") or "").strip()
    connector = str(connector_name or "").strip()
    if not connector or not ds_domain:
        return None
    return normalize_public_endpoint_url(f"http://{connector}.{ds_domain}")


def _public_keycloak_base_url(deployer_context):
    config = dict(getattr(deployer_context, "config", {}) or {})
    resolved_urls = resolved_common_service_urls(config)
    for key in ("KC_INTERNAL_URL", "KC_URL"):
        normalized = normalize_public_endpoint_url(_mapping_value(resolved_urls, key))
        if normalized:
            return normalized
    resolved_hostnames = resolved_common_service_hostnames(config)
    normalized = normalize_public_endpoint_url(f"http://{resolved_hostnames['keycloak_hostname']}")
    if normalized:
        return normalized
    return None


def _edc_keycloak_public_base_url(deployer_context):
    return _public_keycloak_base_url(deployer_context)


def _normalize_readiness_url(url, *, preserve_trailing_slash=False):
    normalized_url = normalize_public_endpoint_url(url)
    if (
        normalized_url
        and preserve_trailing_slash
        and str(url or "").strip().endswith("/")
        and not normalized_url.endswith("/")
    ):
        normalized_url = f"{normalized_url}/"
    return normalized_url


def _http_readiness_gate(
    label,
    url,
    expected_statuses,
    timeout_seconds,
    *,
    preserve_trailing_slash=False,
):
    normalized_url = _normalize_readiness_url(
        url,
        preserve_trailing_slash=preserve_trailing_slash,
    )
    if not normalized_url:
        return {
            "gate": label,
            "url": url,
            "ready": False,
            "detail": "public URL is empty or not resolvable from the local machine",
        }

    try:
        response = requests.get(
            normalized_url,
            timeout=timeout_seconds,
            allow_redirects=False,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return {
            "gate": label,
            "url": normalized_url,
            "ready": False,
            "detail": f"HTTP probe failed: {exc}",
        }

    status_code = int(getattr(response, "status_code", 0) or 0)
    ready = status_code in set(expected_statuses)
    detail = f"HTTP {status_code}"
    location = str(getattr(response, "headers", {}).get("Location") or "").strip()
    if location:
        detail = f"{detail} -> {location}"

    return {
        "gate": label,
        "url": normalized_url,
        "status_code": status_code,
        "ready": ready,
        "detail": detail,
    }


def _http_form_readiness_gate(label, url, form_data, expected_statuses, timeout_seconds):
    normalized_url = _normalize_readiness_url(url)
    if not normalized_url:
        return {
            "gate": label,
            "url": url,
            "ready": False,
            "detail": "public URL is empty or not resolvable from the local machine",
        }

    try:
        response = requests.post(
            normalized_url,
            data=form_data,
            timeout=timeout_seconds,
            allow_redirects=False,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return {
            "gate": label,
            "url": normalized_url,
            "ready": False,
            "detail": f"HTTP probe failed: {exc}",
        }

    status_code = int(getattr(response, "status_code", 0) or 0)
    ready = status_code in set(expected_statuses)
    return {
        "gate": label,
        "url": normalized_url,
        "status_code": status_code,
        "ready": ready,
        "detail": f"HTTP {status_code}",
    }


def _edc_http_readiness_gate(label, url, expected_statuses, timeout_seconds):
    return _http_readiness_gate(label, url, expected_statuses, timeout_seconds)


def _inesdata_connector_public_base_url(connector_name, deployer_context):
    ds_domain = str(getattr(deployer_context, "ds_domain_base", "") or "").strip()
    connector = str(connector_name or "").strip()
    if not connector or not ds_domain:
        return None
    return f"http://{connector}.{ds_domain}/inesdata-connector-interface/"


def _inesdata_connector_credentials_path(deployer_context, connector_name):
    runtime_dir = str(getattr(deployer_context, "runtime_dir", "") or "").strip()
    connector = str(connector_name or "").strip()
    if not runtime_dir or not connector:
        return None
    return os.path.join(runtime_dir, f"credentials-connector-{connector}.json")


def _load_inesdata_connector_user_credentials(deployer_context, connector_name):
    credentials_path = _inesdata_connector_credentials_path(deployer_context, connector_name)
    if not credentials_path:
        return None, "runtime_dir is not configured"
    if not os.path.isfile(credentials_path):
        return None, f"credentials file not found: {credentials_path}"

    try:
        with open(credentials_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return None, f"failed to read {credentials_path}: {exc}"

    connector_user = payload.get("connector_user") if isinstance(payload, dict) else {}
    username = str((connector_user or {}).get("user") or "").strip()
    password = str((connector_user or {}).get("passwd") or "").strip()
    if not username or not password:
        return None, f"connector_user credentials missing in {credentials_path}"

    return {
        "username": username,
        "password": password,
    }, None


def _inesdata_keycloak_password_grant_gate(
    deployer_context,
    connector_name,
    dataspace,
    timeout_seconds,
):
    keycloak_base_url = _public_keycloak_base_url(deployer_context)
    if not keycloak_base_url or not dataspace:
        return {
            "gate": f"keycloak-password-grant:{connector_name}",
            "url": keycloak_base_url,
            "ready": False,
            "detail": "Keycloak public URL or dataspace is not configured",
        }

    credentials, error_detail = _load_inesdata_connector_user_credentials(
        deployer_context,
        connector_name,
    )
    if not credentials:
        return {
            "gate": f"keycloak-password-grant:{connector_name}",
            "url": (
                f"{keycloak_base_url}/realms/"
                f"{urllib.parse.quote(dataspace, safe='')}/protocol/openid-connect/token"
            ),
            "ready": False,
            "detail": error_detail or "connector credentials are not available",
        }

    token_url = (
        f"{keycloak_base_url}/realms/"
        f"{urllib.parse.quote(dataspace, safe='')}/protocol/openid-connect/token"
    )
    return _http_form_readiness_gate(
        f"keycloak-password-grant:{connector_name}",
        token_url,
        form_data={
            "grant_type": "password",
            "client_id": "dataspace-users",
            "username": credentials["username"],
            "password": credentials["password"],
            "scope": "openid profile email",
        },
        expected_statuses={200},
        timeout_seconds=timeout_seconds,
    )


def _edc_dashboard_http_gates(deployer_context, connectors, timeout_seconds):
    dataspace = str(getattr(deployer_context, "dataspace_name", "") or "").strip()
    gates = []

    keycloak_base_url = _public_keycloak_base_url(deployer_context)
    if keycloak_base_url and dataspace:
        metadata_url = (
            f"{keycloak_base_url}/realms/"
            f"{urllib.parse.quote(dataspace, safe='')}/.well-known/openid-configuration"
        )
        gates.append(
            _http_readiness_gate(
                "keycloak-metadata",
                metadata_url,
                expected_statuses={200},
                timeout_seconds=timeout_seconds,
            )
        )
    else:
        gates.append(
            {
                "gate": "keycloak-metadata",
                "url": keycloak_base_url,
                "ready": False,
                "detail": "Keycloak public URL is not configured",
            }
        )

    for connector in connectors:
        base_url = _edc_dashboard_public_base_url(connector, deployer_context)
        if not base_url:
            gates.append(
                {
                    "gate": f"dashboard-route:{connector}",
                    "url": None,
                    "ready": False,
                    "detail": "connector public URL is not configured",
                }
            )
            continue

        gates.append(
            _http_readiness_gate(
                f"dashboard-route:{connector}",
                f"{base_url}/edc-dashboard/",
                expected_statuses={200, 301, 302, 303, 307, 308},
                timeout_seconds=timeout_seconds,
            )
        )
        gates.append(
            _http_readiness_gate(
                f"dashboard-auth-me:{connector}",
                f"{base_url}/edc-dashboard-api/auth/me",
                expected_statuses={200, 401},
                timeout_seconds=timeout_seconds,
            )
        )
        gates.append(
            _http_readiness_gate(
                f"connector-management:{connector}",
                f"{base_url}/management/v3/assets/request",
                expected_statuses={200, 400, 401, 403, 404, 405},
                timeout_seconds=timeout_seconds,
            )
        )

    return gates


def _probe_edc_dashboard_readiness(deployer_context):
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    connector_namespaces = _edc_dashboard_connector_namespaces(deployer_context)
    namespaces = sorted({namespace for namespace in connector_namespaces.values() if namespace})
    namespace = namespaces[0] if len(namespaces) == 1 else ""
    gates = []
    http_timeout = _positive_float_env("PIONERA_EDC_DASHBOARD_HTTP_TIMEOUT_SECONDS", 5)

    if not connector_namespaces:
        return {
            "status": "failed",
            "namespace": namespace,
            "namespaces": namespaces,
            "connector_namespaces": connector_namespaces,
            "connectors": connectors,
            "gates": [{"gate": "namespace", "ready": False, "detail": "namespace is empty"}],
        }

    if not connectors:
        return {
            "status": "failed",
            "namespace": namespace,
            "namespaces": namespaces,
            "connector_namespaces": connector_namespaces,
            "connectors": connectors,
            "gates": [{"gate": "connectors", "ready": False, "detail": "no connectors resolved"}],
        }

    for connector in connectors:
        connector_namespace = connector_namespaces.get(connector) or namespace
        for suffix in ("dashboard", "dashboard-proxy"):
            service_name = f"{connector}-{suffix}"
            ready, detail = _kubectl_endpoint_ready(connector_namespace, service_name)
            gates.append({
                "gate": f"{suffix}:{connector}",
                "namespace": connector_namespace,
                "service": service_name,
                "ready": ready,
                "detail": detail,
            })

    gates.extend(_edc_dashboard_http_gates(deployer_context, connectors, http_timeout))

    status = "passed" if all(gate["ready"] for gate in gates) else "failed"
    return {
        "status": status,
        "namespace": namespace,
        "namespaces": namespaces,
        "connector_namespaces": connector_namespaces,
        "connectors": connectors,
        "gates": gates,
    }


def _write_edc_dashboard_readiness(experiment_dir, readiness):
    if not experiment_dir:
        return None
    output_dir = os.path.join(experiment_dir, "ui", "edc")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "dashboard_readiness.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(readiness, handle, indent=2)
    return output_path


def _wait_for_edc_dashboard_readiness(deployer_context, experiment_dir=None):
    timeout = _positive_float_env("PIONERA_EDC_DASHBOARD_READINESS_TIMEOUT_SECONDS", 90)
    poll_interval = _positive_float_env("PIONERA_EDC_DASHBOARD_READINESS_POLL_SECONDS", 3)
    deadline = time.monotonic() + timeout
    readiness = None

    while True:
        readiness = _probe_edc_dashboard_readiness(deployer_context)
        readiness["timeout_seconds"] = timeout
        readiness["poll_interval_seconds"] = poll_interval
        if readiness.get("status") == "passed":
            readiness["artifact"] = _write_edc_dashboard_readiness(experiment_dir, readiness)
            return readiness

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            readiness["artifact"] = _write_edc_dashboard_readiness(experiment_dir, readiness)
            return readiness

        time.sleep(min(poll_interval, remaining))


def _edc_dashboard_readiness_failure_message(readiness):
    failed_gates = [
        gate for gate in readiness.get("gates", [])
        if not gate.get("ready")
    ]
    if not failed_gates:
        return "EDC dashboard readiness did not pass"

    details = []
    for gate in failed_gates[:6]:
        service = gate.get("service") or gate.get("gate")
        detail = gate.get("detail") or "not ready"
        details.append(f"{service}: {detail}")
    if len(failed_gates) > 6:
        details.append(f"... and {len(failed_gates) - 6} more")

    artifact = readiness.get("artifact")
    artifact_text = f" Details saved in {artifact}." if artifact else ""
    return (
        "Playwright validation for 'edc' requires the dashboard and dashboard-proxy "
        "services to have ready endpoints and public HTTP routes. Missing readiness: "
        + "; ".join(details)
        + artifact_text
    )


def _probe_inesdata_portal_readiness(deployer_context):
    connectors = list(getattr(deployer_context, "connectors", []) or [])
    connector_namespaces = _inesdata_interface_connector_namespaces(deployer_context)
    namespaces = list(connector_namespaces.values())
    registration_namespace = _namespace_role_value(
        getattr(deployer_context, "namespace_roles", None),
        "registration_service_namespace",
    )
    if registration_namespace:
        namespaces.append(registration_namespace)
    http_timeout = _positive_float_env("PIONERA_INESDATA_PORTAL_HTTP_TIMEOUT_SECONDS", 5)
    dataspace = str(getattr(deployer_context, "dataspace_name", "") or "").strip()
    gates = []

    if not connectors:
        return {
            "status": "failed",
            "namespaces": namespaces,
            "connectors": connectors,
            "gates": [{"gate": "connectors", "ready": False, "detail": "no connectors resolved"}],
        }

    keycloak_base_url = _public_keycloak_base_url(deployer_context)
    if keycloak_base_url and dataspace:
        metadata_url = (
            f"{keycloak_base_url}/realms/"
            f"{urllib.parse.quote(dataspace, safe='')}/.well-known/openid-configuration"
        )
        gates.append(
            _http_readiness_gate(
                "keycloak-metadata",
                metadata_url,
                expected_statuses={200},
                timeout_seconds=http_timeout,
            )
        )
    else:
        gates.append(
            {
                "gate": "keycloak-metadata",
                "url": keycloak_base_url,
                "ready": False,
                "detail": "Keycloak public URL is not configured",
            }
        )

    for connector in connectors:
        service_name = f"{connector}-interface"
        connector_namespace = connector_namespaces.get(connector)
        service_ready, service_detail = _kubectl_endpoint_ready(
            connector_namespace,
            service_name,
        )
        gates.append(
            {
                "gate": f"interface:{connector}",
                "namespace": connector_namespace,
                "service": service_name,
                "ready": service_ready,
                "detail": service_detail,
            }
        )
        gates.append(
            _http_readiness_gate(
                f"portal-route:{connector}",
                _inesdata_connector_public_base_url(connector, deployer_context),
                expected_statuses={200},
                timeout_seconds=http_timeout,
                preserve_trailing_slash=True,
            )
        )
        gates.append(
            _inesdata_keycloak_password_grant_gate(
                deployer_context,
                connector,
                dataspace,
                http_timeout,
            )
        )

    status = "passed" if all(gate["ready"] for gate in gates) else "failed"
    return {
        "status": status,
        "namespaces": namespaces,
        "connector_namespaces": connector_namespaces,
        "connectors": connectors,
        "gates": gates,
    }


def _write_inesdata_portal_readiness(experiment_dir, readiness):
    if not experiment_dir:
        return None
    output_dir = os.path.join(experiment_dir, "ui", "inesdata")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "portal_readiness.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(readiness, handle, indent=2)
    return output_path


def _wait_for_inesdata_portal_readiness(deployer_context, experiment_dir=None):
    timeout = _positive_float_env("PIONERA_INESDATA_PORTAL_READINESS_TIMEOUT_SECONDS", 90)
    poll_interval = _positive_float_env("PIONERA_INESDATA_PORTAL_READINESS_POLL_SECONDS", 3)
    stable_polls_required = max(1, _positive_int_env("PIONERA_INESDATA_PORTAL_STABLE_POLLS", 2))
    deadline = time.monotonic() + timeout
    readiness = None
    stable_polls_observed = 0

    while True:
        readiness = _probe_inesdata_portal_readiness(deployer_context)
        readiness["timeout_seconds"] = timeout
        readiness["poll_interval_seconds"] = poll_interval
        readiness["stable_polls_required"] = stable_polls_required
        if readiness.get("status") == "passed":
            stable_polls_observed += 1
            readiness["stable_polls_observed"] = stable_polls_observed
            if stable_polls_observed >= stable_polls_required:
                readiness["artifact"] = _write_inesdata_portal_readiness(experiment_dir, readiness)
                return readiness
        else:
            stable_polls_observed = 0
            readiness["stable_polls_observed"] = 0

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if readiness.get("status") == "passed" and stable_polls_observed < stable_polls_required:
                readiness["status"] = "failed"
                readiness.setdefault("gates", []).append(
                    {
                        "gate": "stability-window",
                        "ready": False,
                        "detail": (
                            f"observed {stable_polls_observed} consecutive successful polls; "
                            f"require {stable_polls_required}"
                        ),
                    }
                )
                readiness["stable_polls_observed"] = stable_polls_observed
            readiness["artifact"] = _write_inesdata_portal_readiness(experiment_dir, readiness)
            return readiness

        time.sleep(min(poll_interval, remaining))


def _inesdata_portal_readiness_failure_message(readiness):
    failed_gates = [
        gate for gate in readiness.get("gates", [])
        if not gate.get("ready")
    ]
    if not failed_gates:
        return "INESData portal readiness did not pass"

    details = []
    for gate in failed_gates[:6]:
        service = gate.get("service") or gate.get("gate")
        detail = gate.get("detail") or "not ready"
        details.append(f"{service}: {detail}")
    if len(failed_gates) > 6:
        details.append(f"... and {len(failed_gates) - 6} more")

    artifact = readiness.get("artifact")
    artifact_text = f" Details saved in {artifact}." if artifact else ""
    return (
        "Playwright validation for 'inesdata' requires the connector interface services "
        "and public portal routes to be ready. Missing readiness: "
        + "; ".join(details)
        + artifact_text
    )


def resolve_adapter_class(adapter_name, adapter_registry=None):
    """Resolve an adapter class from the configured registry."""
    registry = adapter_registry or ADAPTER_REGISTRY

    if adapter_name not in registry:
        supported = ", ".join(sorted(registry))
        raise ValueError(f"Unsupported adapter '{adapter_name}'. Supported adapters: {supported}")

    try:
        module_path, class_name = registry[adapter_name].split(":", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ValueError(
            f"Failed to load adapter '{adapter_name}' from '{registry[adapter_name]}': {exc}"
        ) from exc


def build_adapter(adapter_name="inesdata", adapter_registry=None, dry_run=False, topology="local"):
    """Instantiate the selected dataspace adapter."""
    adapter_class = resolve_adapter_class(adapter_name, adapter_registry=adapter_registry)

    try:
        parameters = inspect.signature(adapter_class).parameters
    except (TypeError, ValueError):
        parameters = {}

    kwargs = {}
    if "dry_run" in parameters:
        kwargs["dry_run"] = dry_run

    if "topology" in parameters:
        kwargs["topology"] = topology

    if kwargs:
        return adapter_class(**kwargs)

    return adapter_class()


def resolve_deployer_class(deployer_name, deployer_registry=None):
    """Resolve a deployer wrapper class from the configured registry."""
    registry = deployer_registry or DEPLOYER_REGISTRY

    if deployer_name not in registry:
        supported = ", ".join(sorted(registry))
        raise ValueError(f"Unsupported deployer '{deployer_name}'. Supported deployers: {supported}")

    try:
        module_path, class_name = registry[deployer_name].split(":", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ValueError(
            f"Failed to load deployer '{deployer_name}' from '{registry[deployer_name]}': {exc}"
        ) from exc


def build_deployer(
    deployer_name="inesdata",
    deployer_registry=None,
    adapter_registry=None,
    dry_run=False,
    topology="local",
    adapter=None,
):
    """Instantiate the selected deployer wrapper without altering the active CLI flow."""
    deployer_class = resolve_deployer_class(deployer_name, deployer_registry=deployer_registry)
    resolved_adapter = adapter or build_adapter(
        deployer_name,
        adapter_registry=adapter_registry,
        dry_run=dry_run,
        topology=topology,
    )

    try:
        parameters = inspect.signature(deployer_class).parameters
    except (TypeError, ValueError):
        parameters = {}

    kwargs = {}
    if "adapter" in parameters:
        kwargs["adapter"] = resolved_adapter
    if "topology" in parameters:
        kwargs["topology"] = topology

    if kwargs:
        return deployer_class(**kwargs)

    return deployer_class()


def build_deployer_orchestrator(
    deployer_name="inesdata",
    deployer_registry=None,
    adapter_registry=None,
    dry_run=False,
    topology="local",
    adapter=None,
    validation_executor=None,
):
    """Build the future deployer orchestrator without changing production command routing."""
    deployer = build_deployer(
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        adapter_registry=adapter_registry,
        dry_run=dry_run,
        topology=topology,
        adapter=adapter,
    )
    return DeployerOrchestrator(deployer, validation_executor=validation_executor)


def _resolve_adapter_callable(adapter, *paths: str, default=None):
    for path in paths:
        current = adapter
        try:
            for attribute in path.split("."):
                current = getattr(current, attribute)
        except AttributeError:
            continue

        if callable(current) or current is not None:
            return current

    return default


def build_validation_engine(adapter, engine_cls=ValidationEngine):
    """Build a generic validation engine from adapter-provided dependencies."""
    cleanup_test_entities = _resolve_adapter_callable(
        adapter,
        "connectors.cleanup_test_entities",
        "cleanup_test_entities",
        default=lambda connector: None,
    )
    load_connector_credentials = _resolve_adapter_callable(
        adapter,
        "connectors.load_connector_credentials",
        "load_connector_credentials",
    )
    load_deployer_config = _resolve_adapter_callable(
        adapter,
        "config_adapter.load_deployer_config",
        "load_deployer_config",
    )
    validation_test_entities_absent = _resolve_adapter_callable(
        adapter,
        "connectors.validation_test_entities_absent",
        "validation_test_entities_absent",
        default=lambda connector: (True, []),
    )
    ds_domain_resolver = _resolve_adapter_callable(
        adapter,
        "config.ds_domain_base",
        "ds_domain_base",
    )
    protocol_address_resolver = _resolve_adapter_callable(
        adapter,
        "connectors.build_internal_protocol_address",
    )
    ds_name = "pionera"
    config = getattr(adapter, "config", None)
    dataspace_name_getter = getattr(config, "dataspace_name", None)
    if callable(dataspace_name_getter):
        resolved_name = dataspace_name_getter()
        if resolved_name:
            ds_name = resolved_name
    else:
        config_adapter = getattr(adapter, "config_adapter", None)
        dataspace_name_getter = getattr(config_adapter, "primary_dataspace_name", None)
        if callable(dataspace_name_getter):
            resolved_name = dataspace_name_getter()
            if resolved_name:
                ds_name = resolved_name
        else:
            ds_name = getattr(config, "DS_NAME", "pionera")
    transfer_storage_verifier = TransferStorageVerifier(
        load_connector_credentials=load_connector_credentials,
        load_deployer_config=load_deployer_config,
        experiment_storage=ExperimentStorage,
    )

    return engine_cls(
        load_connector_credentials=load_connector_credentials,
        load_deployer_config=load_deployer_config,
        cleanup_test_entities=cleanup_test_entities,
        validation_test_entities_absent=validation_test_entities_absent,
        ds_domain_resolver=ds_domain_resolver,
        ds_name=ds_name,
        transfer_storage_verifier=transfer_storage_verifier,
        protocol_address_resolver=protocol_address_resolver,
    )


def build_kafka_manager(adapter, manager_cls=KafkaManager, kafka_runtime_config=None):
    """Build a Kafka manager that can reuse external brokers or auto-provision one."""
    kafka_config_loader = _resolve_adapter_callable(
        adapter,
        "get_kafka_config",
        default=lambda: {},
    )
    return manager_cls(
        runtime_config=kafka_runtime_config or {},
        adapter_config_loader=kafka_config_loader,
    )


class _Level6KafkaPreparationHandle:
    """Prepare Kafka in the background while Newman keeps running in the foreground."""

    def __init__(self, kafka_manager):
        self.kafka_manager = kafka_manager
        self._lock = threading.Lock()
        self._thread = None
        self._result = {
            "status": "pending",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "finished_at": None,
            "duration_seconds": None,
            "bootstrap_servers": None,
            "cluster_bootstrap_servers": None,
            "started_by_framework": False,
            "provisioning_mode": None,
            "error": None,
        }

    def start(self):
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._run,
            name="level6-kafka-preparation",
            daemon=True,
        )
        self._thread.start()
        return self

    def _run(self):
        started = time.time()
        error_payload = None
        try:
            resolved = self.kafka_manager.ensure_kafka_running()
            if resolved:
                status = "ready"
            else:
                status = "failed"
                error_message = getattr(self.kafka_manager, "last_error", None) or "Kafka runtime did not become available"
                error_payload = {
                    "type": "RuntimeError",
                    "message": str(error_message),
                }
        except Exception as exc:
            resolved = None
            status = "failed"
            error_payload = {
                "type": type(exc).__name__,
                "message": str(exc),
            }

        payload = {
            "status": status,
            "started_at": self._result.get("started_at"),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_seconds": round(time.time() - started, 2),
            "bootstrap_servers": resolved or getattr(self.kafka_manager, "bootstrap_servers", None),
            "cluster_bootstrap_servers": getattr(self.kafka_manager, "cluster_bootstrap_servers", None),
            "started_by_framework": bool(getattr(self.kafka_manager, "started_by_framework", False)),
            "provisioning_mode": getattr(self.kafka_manager, "provisioning_mode", None),
            "error": error_payload,
        }
        with self._lock:
            self._result = payload

    def wait(self):
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            return dict(self._result)

    def stop_runtime(self):
        stop_method = getattr(self.kafka_manager, "stop_kafka", None)
        if callable(stop_method):
            stop_method()


class _Level6LocalHttpPortForwardFallback:
    """Temporary local-only HTTP fallback for Level 6 Kafka validation."""

    KEYCLOAK_SERVICE_NAME = "common-srvs-keycloak"
    KEYCLOAK_REMOTE_PORT = 80
    CONNECTOR_MANAGEMENT_REMOTE_PORT = 19193

    def __init__(self, adapter, connectors, validator):
        self.adapter = adapter
        self.connectors = list(dict.fromkeys(connectors or []))
        self.validator = validator
        self._processes = []
        self._keycloak_port = None
        self._connector_ports = {}

    @staticmethod
    def _enabled():
        return _env_flag("PIONERA_LEVEL6_LOCAL_HTTP_PORT_FORWARD_FALLBACK", False)

    def _is_local_topology(self):
        topology = str(getattr(self.adapter, "topology", "local") or "local").strip().lower()
        return topology == "local"

    @staticmethod
    def _normalize_http_url(url):
        value = str(url or "").strip()
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            return f"http://{value}"
        return value

    @staticmethod
    def _probe_http_url(url, timeout=3):
        normalized = _Level6LocalHttpPortForwardFallback._normalize_http_url(url)
        if not normalized:
            return False
        try:
            response = requests.get(normalized, timeout=timeout, allow_redirects=False)
        except requests.RequestException:
            return False
        return int(getattr(response, "status_code", 0) or 0) < 500

    @staticmethod
    def _reserve_local_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    @staticmethod
    def _wait_for_local_port(port, timeout=15):
        deadline = time.time() + max(float(timeout), 1.0)
        while time.time() <= deadline:
            try:
                with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    @staticmethod
    def _terminate_process(process):
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _common_services_namespace(self):
        config = getattr(self.adapter, "config", None)
        return str(getattr(config, "NS_COMMON", "common-srvs") or "common-srvs").strip() or "common-srvs"

    def _connector_namespace(self, connector):
        connectors = getattr(self.adapter, "connectors", None)
        resolver = getattr(connectors, "connector_target_namespace", None)
        if callable(resolver):
            resolved = str(resolver(connector) or "").strip()
            if resolved:
                return resolved
        config = getattr(self.adapter, "config", None)
        namespace_getter = getattr(config, "namespace_demo", None)
        if callable(namespace_getter):
            resolved = str(namespace_getter() or "").strip()
            if resolved:
                return resolved
        return str(getattr(config, "DS_NAME", "pionera") or "pionera").strip() or "pionera"

    def _public_keycloak_url(self):
        config_loader = getattr(self.validator, "load_deployer_config", None)
        config = config_loader() if callable(config_loader) else {}
        if not isinstance(config, dict):
            config = {}
        return self._normalize_http_url(config.get("KC_INTERNAL_URL") or config.get("KC_URL"))

    def _keycloak_probe_url(self):
        dataspace_name = getattr(self.validator, "_dataspace_name", lambda: "pionera")()
        keycloak_url = self._public_keycloak_url()
        if not keycloak_url:
            return ""
        return f"{keycloak_url}/realms/{dataspace_name}/protocol/openid-connect/token"

    def _connector_probe_url(self, connector):
        return self.validator._management_url(connector, "/management/v3/assets/request")

    def _start_service_port_forward(self, namespace, service_name, remote_port):
        local_port = self._reserve_local_port()
        process = subprocess.Popen(
            [
                "kubectl",
                "port-forward",
                "-n",
                str(namespace),
                f"svc/{service_name}",
                f"{local_port}:{int(remote_port)}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not self._wait_for_local_port(local_port):
            self._terminate_process(process)
            raise RuntimeError(
                f"Local Level 6 HTTP fallback could not expose {service_name} "
                f"in namespace {namespace} on local port {local_port}"
            )
        self._processes.append(process)
        return int(local_port)

    def activate_if_needed(self):
        if not self._enabled() or not self._is_local_topology():
            return False

        keycloak_needs_fallback = not self._probe_http_url(self._keycloak_probe_url())
        connectors_needing_fallback = [
            connector
            for connector in self.connectors
            if not self._probe_http_url(self._connector_probe_url(connector))
        ]

        if not keycloak_needs_fallback and not connectors_needing_fallback:
            return False

        started_keycloak = False
        started_connectors = []
        try:
            if keycloak_needs_fallback:
                self._keycloak_port = self._start_service_port_forward(
                    self._common_services_namespace(),
                    self.KEYCLOAK_SERVICE_NAME,
                    self.KEYCLOAK_REMOTE_PORT,
                )
                started_keycloak = True

            for connector in connectors_needing_fallback:
                self._connector_ports[connector] = self._start_service_port_forward(
                    self._connector_namespace(connector),
                    connector,
                    self.CONNECTOR_MANAGEMENT_REMOTE_PORT,
                )
                started_connectors.append(connector)
        except Exception:
            self.close()
            raise

        if self._keycloak_port is not None:
            self.validator.keycloak_url_resolver = (
                lambda port=self._keycloak_port: f"http://127.0.0.1:{port}"
            )

        if self._connector_ports:
            def _management_url_resolver(connector, path):
                local_port = self._connector_ports.get(connector)
                if local_port is None:
                    return ""
                return f"http://127.0.0.1:{local_port}{path}"

            self.validator.management_url_resolver = _management_url_resolver

        activated_parts = []
        if started_keycloak:
            activated_parts.append("Keycloak")
        if started_connectors:
            activated_parts.append(f"{len(started_connectors)} connector management API(s)")
        if activated_parts:
            print(
                "Level 6 local HTTP fallback activated via port-forward for "
                + " and ".join(activated_parts)
                + "."
            )
        return True

    def close(self):
        for process in reversed(self._processes):
            self._terminate_process(process)
        self._processes.clear()


def _save_level6_kafka_preparation_artifact(preparation, experiment_dir):
    if not experiment_dir or not isinstance(preparation, dict):
        return None

    path = os.path.join(experiment_dir, "kafka_runtime_preparation.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(preparation, handle, indent=2, ensure_ascii=False)
    print(f"Kafka runtime preparation saved to {path}")
    return path


def _start_level6_kafka_preparation(
    adapter,
    connectors,
    *,
    validation_profile=None,
    deployer_name=None,
    kafka_manager_cls=KafkaManager,
    background=True,
):
    if len(list(connectors or [])) < 2:
        return None
    if not _supports_level6_kafka_edc(
        adapter,
        validation_profile=validation_profile,
        deployer_name=deployer_name,
    ):
        return None

    kafka_manager = build_kafka_manager(adapter, manager_cls=kafka_manager_cls)
    if not background:
        print("\nKafka runtime preparation deferred until Kafka validation (stable local mode).")
        return None
    print("\nPreparing Kafka runtime in background while Newman validation runs...")
    return _Level6KafkaPreparationHandle(kafka_manager).start()


def _finalize_level6_kafka_preparation(
    kafka_preparation,
    experiment_dir,
    *,
    cleanup=False,
):
    if kafka_preparation is None:
        return None

    result = kafka_preparation.wait()
    _save_level6_kafka_preparation_artifact(result, experiment_dir)
    if cleanup:
        kafka_preparation.stop_runtime()
    return result


def _adapter_level6_kafka_name(adapter, validation_profile=None, deployer_name=None):
    candidates = []
    if validation_profile is not None:
        candidates.append(getattr(validation_profile, "adapter", ""))
    if deployer_name:
        candidates.append(deployer_name)
    try:
        candidates.append(_infer_deployer_name_from_adapter(adapter))
    except Exception:
        pass

    for candidate in candidates:
        normalized = str(candidate or "").strip().lower()
        if normalized:
            return normalized
    return ""


def _supports_level6_kafka_edc(adapter, validation_profile=None, deployer_name=None):
    adapter_name = _adapter_level6_kafka_name(
        adapter,
        validation_profile=validation_profile,
        deployer_name=deployer_name,
    )
    if adapter_name not in {"edc", "inesdata"}:
        return False

    capability_getter = getattr(adapter, "supports_kafka_transfer_validation", None)
    if callable(capability_getter) and capability_getter() is False:
        return False

    return callable(_resolve_adapter_callable(adapter, "get_kafka_config"))


def _dataspace_name_loader(adapter):
    config = getattr(adapter, "config", None)
    dataspace_name_getter = getattr(config, "dataspace_name", None)
    if callable(dataspace_name_getter):
        return dataspace_name_getter

    config_adapter = getattr(adapter, "config_adapter", None)
    dataspace_name_getter = getattr(config_adapter, "primary_dataspace_name", None)
    if callable(dataspace_name_getter):
        return dataspace_name_getter

    return lambda: getattr(config, "DS_NAME", "pionera")


def build_kafka_edc_validation_suite(
    adapter,
    suite_cls=KafkaEdcValidationSuite,
    experiment_storage=ExperimentStorage,
    kafka_manager_cls=KafkaManager,
    kafka_manager=None,
):
    """Build the Level 6 functional EDC+Kafka validator from adapter hooks."""
    load_connector_credentials = _resolve_adapter_callable(
        adapter,
        "connectors.load_connector_credentials",
        "load_connector_credentials",
    )
    load_deployer_config = _resolve_adapter_callable(
        adapter,
        "config_adapter.load_deployer_config",
        "load_deployer_config",
    )
    ds_domain_resolver = _resolve_adapter_callable(
        adapter,
        "config.ds_domain_base",
        "ds_domain_base",
    )
    kafka_runtime_loader = _resolve_adapter_callable(
        adapter,
        "get_kafka_config",
        default=lambda: {},
    )
    ensure_kafka_topic = _resolve_adapter_callable(
        adapter,
        "ensure_kafka_topic",
    )
    protocol_address_resolver = _resolve_adapter_callable(
        adapter,
        "connectors.build_internal_protocol_address",
    )

    missing_dependencies = [
        name
        for name, dependency in (
            ("load_connector_credentials", load_connector_credentials),
            ("load_deployer_config", load_deployer_config),
            ("ds_domain_resolver", ds_domain_resolver),
        )
        if not callable(dependency)
    ]
    if missing_dependencies:
        missing = ", ".join(missing_dependencies)
        raise RuntimeError(f"Kafka transfer validation cannot run because adapter is missing: {missing}")

    kafka_manager = kafka_manager or build_kafka_manager(adapter, manager_cls=kafka_manager_cls)
    return suite_cls(
        load_connector_credentials=load_connector_credentials,
        load_deployer_config=load_deployer_config,
        kafka_runtime_loader=kafka_runtime_loader,
        ensure_kafka_topic=ensure_kafka_topic,
        kafka_manager=kafka_manager,
        experiment_storage=experiment_storage,
        ds_domain_resolver=ds_domain_resolver,
        ds_name_loader=_dataspace_name_loader(adapter),
        protocol_address_resolver=protocol_address_resolver,
    )


def _save_kafka_edc_results(results, experiment_dir, experiment_storage=ExperimentStorage):
    saver = getattr(experiment_storage, "save_kafka_edc_results_json", None)
    if callable(saver):
        saver(results, experiment_dir)


def _format_console_metric(value, suffix=""):
    if value in (None, ""):
        return "n/a"
    return f"{value}{suffix}"


def _console_supports_color(stream=None):
    if os.getenv("NO_COLOR") is not None:
        return False

    force_color = os.getenv("FORCE_COLOR")
    if force_color is not None:
        return str(force_color).strip().lower() not in ("0", "false", "no", "off", "")

    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def _colorize_console_icon(icon, status, *, stream=None):
    color_codes = {
        "passed": "\033[32m",
        "failed": "\033[31m",
        "skipped": "\033[33m",
        "unknown": "\033[36m",
    }
    normalized = str(status or "unknown").lower()
    if not _console_supports_color(stream=stream):
        return icon
    return f"{color_codes.get(normalized, color_codes['unknown'])}{icon}\033[0m"


def _console_status_label(status, *, stream=None):
    status_labels = {
        "passed": "✓",
        "failed": "✗",
        "skipped": "-",
    }
    normalized = str(status or "unknown").lower()
    icon = status_labels.get(normalized, "?")
    return _colorize_console_icon(icon, normalized, stream=stream)


def _print_kafka_transfer_steps(result, indent="    "):
    steps = result.get("steps") if isinstance(result, dict) else None
    if not isinstance(steps, list) or not steps:
        return

    detail_keys = (
        "http_status",
        "state",
        "topic",
        "asset_id",
        "agreement_id",
        "transfer_id",
        "messages_consumed",
        "average_latency_ms",
    )
    print(f"{indent}Steps:")
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = _console_status_label(step.get("status", "unknown"))
        name = step.get("name", "unknown_step")
        details = [
            f"{key}={step[key]}"
            for key in detail_keys
            if step.get(key) not in (None, "")
        ]
        suffix = f" ({', '.join(details)})" if details else ""
        print(f"{indent}  {status} {name}{suffix}")


def _print_kafka_edc_result(result, *, indent="  ", verbose_messages=None):
    verbose_messages = bool(verbose_messages)
    provider = result.get("provider", "unknown-provider")
    consumer = result.get("consumer", "unknown-consumer")
    status = result.get("status", "unknown")
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    artifact_path = result.get("artifact_path")

    if status == "passed":
        print(f"{indent}{_console_status_label(status)} Kafka transfer: {provider} -> {consumer}")
        _print_kafka_transfer_steps(result, indent=f"{indent}  ")
        if result.get("source_topic") or result.get("destination_topic"):
            print(f"{indent}  Topics: {result.get('source_topic')} -> {result.get('destination_topic')}")
        if metrics:
            print(
                f"{indent}  Messages: "
                f"produced={_format_console_metric(metrics.get('messages_produced'))} "
                f"consumed={_format_console_metric(metrics.get('messages_consumed'))}"
            )
            print(
                f"{indent}  Latency: "
                f"avg={_format_console_metric(metrics.get('average_latency_ms'), 'ms')} "
                f"p50={_format_console_metric(metrics.get('p50_latency_ms'), 'ms')} "
                f"p95={_format_console_metric(metrics.get('p95_latency_ms'), 'ms')} "
                f"p99={_format_console_metric(metrics.get('p99_latency_ms'), 'ms')}"
            )
            print(
                f"{indent}  Throughput: "
                f"{_format_console_metric(metrics.get('throughput_messages_per_second'), ' msg/s')}"
            )
            if verbose_messages:
                for sample in metrics.get("message_samples") or []:
                    print(
                        f"{indent}  Message: "
                        f"id={sample.get('message_id')} "
                        f"status={sample.get('status')} "
                        f"latency={sample.get('latency_ms', 'n/a')}ms"
                    )
        if artifact_path:
            print(f"{indent}  Artifact: {artifact_path}")
        return

    if status == "failed":
        error = (result.get("error") or {}).get("message", "unknown reason")
        print(f"{indent}{_console_status_label(status)} Kafka transfer: {provider} -> {consumer} ({error})")
        _print_kafka_transfer_steps(result, indent=f"{indent}  ")
        if artifact_path:
            print(f"{indent}  Artifact: {artifact_path}")
        return

    reason = result.get("reason", "unknown reason")
    print(f"{indent}{_console_status_label(status)} Kafka transfer: {provider} -> {consumer} ({reason})")
    _print_kafka_transfer_steps(result, indent=f"{indent}  ")
    if artifact_path:
        print(f"{indent}  Artifact: {artifact_path}")


def _print_kafka_edc_summary(results, *, indent="  "):
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    unknown_count = 0
    for result in results or []:
        normalized = str(result.get("status", "unknown")).lower()
        if normalized in counts:
            counts[normalized] += 1
        else:
            unknown_count += 1

    summary_parts = [
        f"{_console_status_label('passed')} {counts['passed']}",
        f"{_console_status_label('failed')} {counts['failed']}",
        f"{_console_status_label('skipped')} {counts['skipped']}",
    ]
    if unknown_count:
        summary_parts.append(f"{_console_status_label('unknown')} {unknown_count}")
    print(f"{indent}Summary: {'  '.join(summary_parts)}")


def _print_kafka_edc_results(results, *, include_heading=True, include_results=True, include_summary=True):
    if include_heading:
        print("Kafka transfer validation results:")
    verbose_messages = _env_flag(
        "PIONERA_KAFKA_TRANSFER_LOG_MESSAGES",
        _env_flag("KAFKA_TRANSFER_LOG_MESSAGES", False),
    )
    if include_results:
        for result in results or []:
            _print_kafka_edc_result(result, verbose_messages=verbose_messages)
    if include_summary and results:
        _print_kafka_edc_summary(results)


def run_level6_kafka_edc_after_newman(
    adapter,
    connectors,
    experiment_dir,
    *,
    validation_profile=None,
    deployer_name=None,
    experiment_storage=ExperimentStorage,
    suite_cls=KafkaEdcValidationSuite,
    kafka_manager_cls=KafkaManager,
    kafka_preparation=None,
):
    """Run the functional EDC+Kafka suite automatically after Newman in Level 6."""
    if not _supports_level6_kafka_edc(
        adapter,
        validation_profile=validation_profile,
        deployer_name=deployer_name,
    ):
        return []

    print("\nRunning Kafka transfer validation suite...")
    kafka_preparation_result = _finalize_level6_kafka_preparation(
        kafka_preparation,
        experiment_dir,
    )
    prepared_kafka_manager = getattr(kafka_preparation, "kafka_manager", None) if kafka_preparation is not None else None
    if isinstance(kafka_preparation_result, dict):
        if kafka_preparation_result.get("status") == "ready":
            print("Kafka runtime preparation completed while Newman was running.")
        elif kafka_preparation_result.get("status") == "failed":
            error = kafka_preparation_result.get("error") if isinstance(kafka_preparation_result.get("error"), dict) else {}
            message = error.get("message") or "unknown reason"
            print(f"Kafka runtime preparation did not complete during Newman: {message}")
            print("Performing a final Kafka readiness check now...")
    progress_state = {"heading_printed": False}

    def _print_progress_result(result):
        if not progress_state["heading_printed"]:
            print("Kafka transfer validation results:")
            progress_state["heading_printed"] = True
        verbose_messages = _env_flag(
            "PIONERA_KAFKA_TRANSFER_LOG_MESSAGES",
            _env_flag("KAFKA_TRANSFER_LOG_MESSAGES", False),
        )
        _print_kafka_edc_result(result, verbose_messages=verbose_messages)

    try:
        validator = build_kafka_edc_validation_suite(
            adapter,
            suite_cls=suite_cls,
            experiment_storage=experiment_storage,
            kafka_manager_cls=kafka_manager_cls,
            kafka_manager=prepared_kafka_manager,
        )
        http_fallback = _Level6LocalHttpPortForwardFallback(adapter, connectors, validator)
        http_fallback.activate_if_needed()
        try:
            results = run_kafka_edc_validation(
                list(connectors or []),
                experiment_dir,
                validator=validator,
                experiment_storage=experiment_storage,
                progress_callback=_print_progress_result,
            )
        finally:
            http_fallback.close()
    except Exception as exc:
        results = [
            {
                "status": "failed",
                "reason": "execution_error",
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        ]
        _save_kafka_edc_results(results, experiment_dir, experiment_storage=experiment_storage)

    _print_kafka_edc_results(
        results,
        include_heading=not progress_state["heading_printed"],
        include_results=not progress_state["heading_printed"],
        include_summary=True,
    )
    return list(results or [])


def build_metrics_collector(
    adapter,
    collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    kafka_enabled=False,
    kafka_runtime_config=None,
):
    """Build a generic metrics collector from adapter-provided dependencies."""
    build_connector_url = _resolve_adapter_callable(
        adapter,
        "connectors.build_connector_url",
        "build_connector_url",
    )
    is_kafka_available = _resolve_adapter_callable(
        adapter,
        "is_kafka_available",
    )
    ensure_kafka_topic = _resolve_adapter_callable(
        adapter,
        "ensure_kafka_topic",
    )
    auto_mode_getter = _resolve_adapter_callable(
        adapter,
        "auto_mode_getter",
        default=False,
    )
    kafka_config_loader = _resolve_adapter_callable(
        adapter,
        "get_kafka_config",
        default=lambda: {},
    )
    connector_log_fetcher = _resolve_connector_log_fetcher(adapter)

    return collector_cls(
        build_connector_url=build_connector_url,
        is_kafka_available=is_kafka_available,
        ensure_kafka_topic=ensure_kafka_topic,
        experiment_storage=experiment_storage,
        auto_mode=auto_mode_getter,
        kafka_enabled=kafka_enabled,
        kafka_config_loader=kafka_config_loader,
        kafka_runtime_config=kafka_runtime_config or {},
        connector_log_fetcher=connector_log_fetcher,
    )


def build_runner(
    adapter_name="inesdata",
    runner_cls=ExperimentRunner,
    adapter_registry=None,
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    dry_run=False,
    iterations=1,
    kafka_enabled=False,
    kafka_runtime_config=None,
    kafka_manager_cls=KafkaManager,
    baseline=False,
    topology="local",
):
    """Create the experiment runner with the selected adapter."""
    adapter = build_adapter(
        adapter_name,
        adapter_registry=adapter_registry,
        dry_run=dry_run,
        topology=topology,
    )
    validation_engine = build_validation_engine(adapter, engine_cls=validation_engine_cls)
    metrics_collector = build_metrics_collector(
        adapter,
        collector_cls=metrics_collector_cls,
        experiment_storage=experiment_storage,
        kafka_enabled=kafka_enabled,
        kafka_runtime_config=kafka_runtime_config,
    )
    kafka_manager = None
    if kafka_enabled:
        kafka_manager = build_kafka_manager(
            adapter,
            manager_cls=kafka_manager_cls,
            kafka_runtime_config=kafka_runtime_config,
        )
    return runner_cls(
        adapter=adapter,
        validation_engine=validation_engine,
        metrics_collector=metrics_collector,
        experiment_storage=experiment_storage,
        iterations=iterations,
        kafka_manager=kafka_manager,
        baseline=baseline,
    )


def build_dry_run_preview(
    adapter_name,
    command,
    adapter_registry=None,
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    iterations=1,
    kafka_enabled=False,
    baseline=False,
    topology="local",
    deployer_registry=None,
    include_deployer_dry_run=None,
    with_connectors=False,
    recover_connectors=False,
    validation_mode=None,
):
    """Build a safe preview of what a command would execute."""
    adapter = build_adapter(
        adapter_name,
        adapter_registry=adapter_registry,
        dry_run=True,
        topology=topology,
    )
    preview = {
        "status": "dry-run",
        "adapter": adapter_name,
        "command": command,
        "adapter_class": type(adapter).__name__,
        "topology": topology,
        "dry_run": getattr(adapter, "dry_run", True),
        "iterations": iterations,
        "kafka_enabled": kafka_enabled,
        "baseline": baseline,
        "validation_mode": _resolve_level6_validation_mode(validation_mode, topology=topology),
        "config_migration_warnings": _infrastructure_config_migration_warnings(),
        "actions": [],
    }

    if include_deployer_dry_run is None:
        include_deployer_dry_run = _env_flag(
            "PIONERA_ENABLE_DEPLOYER_DRY_RUN",
            default=str(topology or "local").strip().lower() != "local",
        )

    if include_deployer_dry_run:
        preview["deployer_orchestrator"] = _build_deployer_dry_run_preview(
            adapter_name=adapter_name,
            command=command,
            topology=topology,
            adapter=adapter,
            adapter_registry=adapter_registry,
            deployer_registry=deployer_registry,
        )

    adapter_preview = _resolve_adapter_preview(adapter, command)
    if adapter_preview is not None:
        preview["preflight"] = adapter_preview

    if command == "deploy":
        preview["actions"] = ["deploy_infrastructure", "deploy_dataspace", "deploy_connectors"]
        return preview

    if command == "validate":
        validation_engine = build_validation_engine(adapter, engine_cls=validation_engine_cls)
        preview["actions"] = [
            "resolve_connectors",
            "run_pre_validation_cleanup_if_enabled",
            "run_validation",
            "run_kafka_validation",
            "run_playwright_validation",
            "run_component_validation",
        ]
        preview["validation_engine"] = type(validation_engine).__name__
        preview["cleanup_available"] = callable(
            _resolve_adapter_callable(
                adapter,
                "connectors.cleanup_test_entities",
                "cleanup_test_entities",
            )
        )
        return preview

    if command == "metrics":
        metrics_collector = build_metrics_collector(
            adapter,
            collector_cls=metrics_collector_cls,
            experiment_storage=experiment_storage,
            kafka_enabled=kafka_enabled,
        )
        preview["actions"] = ["resolve_connectors", "collect_metrics", "store_results"]
        if kafka_enabled:
            preview["actions"].append("run_kafka_benchmark")
        preview["metrics_collector"] = type(metrics_collector).__name__
        preview["kafka_config_available"] = callable(
            _resolve_adapter_callable(adapter, "get_kafka_config")
        ) or any(
            bool(value) for value in (
                __import__("os").getenv("KAFKA_BOOTSTRAP_SERVERS"),
                __import__("os").getenv("KAFKA_TOPIC_NAME"),
            )
        )
        return preview

    if command == "hosts":
        preview["actions"] = ["resolve_deployer_context", "plan_hosts_entries"]
        try:
            _resolved_name, context = _resolve_deployer_context(
                adapter,
                deployer_name=adapter_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
            preview["namespace_profile"] = _context_namespace_profile(context)
            preview["namespace_roles"] = _context_namespace_roles_dict(context)
            preview["planned_namespace_roles"] = _context_planned_namespace_roles_dict(context)
            preview["hosts_plan"] = _build_shadow_host_sync_plan(context)
        except Exception as exc:
            preview["hosts_plan"] = {
                "status": "unavailable",
                "reason": str(exc),
            }
        return preview

    if command == "local-repair":
        preview["actions"] = [
            "collect_local_access_doctor_report",
            "resolve_deployer_context",
            "plan_hosts_reconciliation",
            "apply_hosts_reconciliation",
            "verify_public_ingress_endpoints",
        ]
        if recover_connectors:
            preview["actions"].append("recover_connector_runtimes")
        preview["recover_connectors"] = bool(recover_connectors)
        preview["doctor"] = _collect_local_repair_doctor_report()
        try:
            _resolved_name, context = _resolve_deployer_context(
                adapter,
                deployer_name=adapter_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
            readiness = _build_hosts_readiness_plan(
                context,
                levels=_local_repair_levels(),
            )
            preview["namespace_profile"] = _context_namespace_profile(context)
            preview["namespace_roles"] = _context_namespace_roles_dict(context)
            preview["planned_namespace_roles"] = _context_planned_namespace_roles_dict(context)
            preview["hosts_plan"] = readiness.get("hosts_plan")
            preview["missing_hostnames"] = readiness.get("missing_hostnames", [])
            preview["public_endpoint_preflight"] = {
                "status": "planned",
                "connector_endpoints_included": bool(recover_connectors),
            }
        except Exception as exc:
            preview["hosts_plan"] = {
                "status": "unavailable",
                "reason": str(exc),
            }
        return preview

    if command == "recreate-dataspace":
        preview["actions"] = [
            "resolve_deployer_context",
            "render_recreate_dataspace_plan",
            "require_exact_dataspace_confirmation",
            "delete_selected_dataspace_resources",
            "run_level_3_again",
        ]
        if with_connectors:
            preview["actions"].append("run_level_4_connectors")
        else:
            preview["actions"].append("skip_level_4_connectors")
        preview["with_connectors"] = bool(with_connectors)
        try:
            _resolved_name, context = _resolve_deployer_context(
                adapter,
                deployer_name=adapter_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
            preview["recreate_dataspace_plan"] = _build_recreate_dataspace_plan(adapter, context)
        except Exception as exc:
            preview["recreate_dataspace_plan"] = {
                "status": "unavailable",
                "reason": str(exc),
            }
        return preview

    preview["actions"] = [
        "deploy_infrastructure",
        "deploy_dataspace",
        "deploy_connectors",
        "run_validation",
        "collect_metrics",
        "store_results",
    ]
    if kafka_enabled:
        preview["actions"].append("run_kafka_benchmark")
    preview["runner"] = ExperimentRunner.__name__
    return preview


def _resolve_adapter_preview(adapter, command):
    preview_method = _resolve_adapter_callable(adapter, f"preview_{command}")
    if callable(preview_method):
        return preview_method()

    preview_method = _resolve_adapter_callable(adapter, "preview_command")
    if callable(preview_method):
        return preview_method(command)

    return None


def _build_deployer_dry_run_preview(
    adapter_name,
    command,
    topology="local",
    adapter=None,
    adapter_registry=None,
    deployer_registry=None,
):
    orchestrator = build_deployer_orchestrator(
        deployer_name=adapter_name,
        deployer_registry=deployer_registry,
        adapter_registry=adapter_registry,
        adapter=adapter,
        dry_run=True,
        topology=topology,
    )
    context = orchestrator.resolve_context(topology=topology)
    deployer = orchestrator.deployer
    preview = {
        "status": "available",
        "deployer": getattr(deployer, "name", lambda: type(deployer).__name__.lower())(),
        "deployer_class": type(deployer).__name__,
        "topology": topology,
        "config_migration_warnings": _infrastructure_config_migration_warnings(),
        "namespace_profile": _context_namespace_profile(context),
        "namespace_roles": _context_namespace_roles_dict(context),
        "planned_namespace_roles": _context_planned_namespace_roles_dict(context),
        "namespace_plan_summary": _build_namespace_plan_summary(context),
        "context": _sanitize_preview_data(context.as_dict()),
    }

    if command == "deploy":
        preview["actions"] = [
            "resolve_context",
            "deploy_infrastructure",
            "deploy_dataspace",
            "deploy_connectors",
            "deploy_components",
        ]
        return preview

    profile = orchestrator.get_validation_profile(context)
    if command == "validate":
        preview["actions"] = [
            "resolve_context",
            "get_validation_profile",
            "run_pre_validation_cleanup_if_enabled",
            "run_newman_if_enabled",
            "run_playwright_if_enabled",
            "run_component_validation_if_enabled",
        ]
        preview["validation_profile"] = profile.as_dict()
        return preview

    if command == "metrics":
        preview["actions"] = [
            "resolve_context",
            "resolve_connectors",
            "collect_metrics",
        ]
        return preview

    if command == "hosts":
        preview["actions"] = [
            "resolve_context",
            "plan_hosts_entries",
            "apply_hosts_entries_if_explicitly_enabled",
        ]
        preview["hosts_plan"] = _build_shadow_host_sync_plan(context)
        return preview

    if command == "local-repair":
        preview["actions"] = [
            "resolve_context",
            "plan_hosts_entries",
            "apply_hosts_entries_via_main_when_requested",
            "verify_public_ingress_endpoints",
        ]
        preview["hosts_plan"] = _build_shadow_host_sync_plan(context)
        return preview

    if command == "recreate-dataspace":
        preview["actions"] = [
            "resolve_context",
            "render_recreate_dataspace_plan",
            "require_exact_dataspace_confirmation",
            "delete_selected_dataspace_resources",
            "run_level_3_again",
        ]
        return preview

    preview["actions"] = [
        "resolve_context",
        "deploy_infrastructure",
        "deploy_dataspace",
        "deploy_connectors",
        "deploy_components",
        "get_validation_profile",
        "run_pre_validation_cleanup_if_enabled",
        "run_newman_if_enabled",
        "run_playwright_if_enabled",
        "run_component_validation_if_enabled",
        "collect_metrics",
    ]
    preview["validation_profile"] = profile.as_dict()
    return preview


def _resolve_connectors(adapter):
    connectors = _resolve_adapter_callable(adapter, "get_cluster_connectors")
    if callable(connectors):
        resolved = connectors()
        if resolved:
            return resolved

    deploy_connectors = _resolve_adapter_callable(adapter, "deploy_connectors")
    if callable(deploy_connectors):
        resolved = deploy_connectors()
        if resolved:
            return resolved

    raise RuntimeError("Unable to resolve connectors from the selected adapter")


def _infer_deployer_name_from_adapter(adapter):
    config = getattr(adapter, "config", None)
    adapter_name = getattr(config, "ADAPTER_NAME", None) if config is not None else None
    if adapter_name:
        return str(adapter_name).strip().lower()

    adapter_type_name = type(adapter).__name__.lower()
    if "edc" in adapter_type_name:
        return "edc"
    if "inesdata" in adapter_type_name:
        return "inesdata"
    return adapter_type_name


def _should_use_deployer_validate():
    if _env_flag("PIONERA_DISABLE_DEPLOYER_VALIDATE", default=False):
        return False

    raw_value = os.getenv("PIONERA_USE_DEPLOYER_VALIDATE")
    if raw_value is None:
        return True

    return _env_flag("PIONERA_USE_DEPLOYER_VALIDATE", default=True)


def _should_run_deployer_playwright(force=False, validation_profile=None):
    if _env_flag("PIONERA_DISABLE_DEPLOYER_PLAYWRIGHT", default=False):
        return False
    if force:
        return True
    if os.getenv("PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT") is not None:
        return _env_flag("PIONERA_ENABLE_DEPLOYER_PLAYWRIGHT", default=False)
    return bool(getattr(validation_profile, "playwright_enabled", False))


def _should_run_test_data_cleanup(validation_profile=None):
    if _env_flag("PIONERA_DISABLE_TEST_DATA_CLEANUP", default=False):
        return False
    if os.getenv("PIONERA_TEST_DATA_CLEANUP") is not None:
        return _env_flag("PIONERA_TEST_DATA_CLEANUP", default=False)
    return bool(getattr(validation_profile, "test_data_cleanup_enabled", False))


def _test_data_cleanup_mode():
    return str(os.getenv("PIONERA_TEST_DATA_CLEANUP_MODE") or "safe").strip().lower() or "safe"


def _should_write_test_data_cleanup_report():
    return _env_flag("PIONERA_TEST_DATA_CLEANUP_REPORT", default=True)


def _append_public_endpoint(endpoints, seen, label, url):
    normalized_url = normalize_public_endpoint_url(url)
    if not normalized_url or normalized_url in seen:
        return
    seen.add(normalized_url)
    endpoints.append({"label": label, "url": normalized_url})


def _level6_public_endpoint_candidates(adapter, connectors, deployer_context):
    endpoints = []
    seen = set()
    config = dict(getattr(deployer_context, "config", {}) or {})
    resolved_urls = resolved_common_service_urls(config)
    resolved_hostnames = resolved_common_service_hostnames(config)
    ds_domain = str(getattr(deployer_context, "ds_domain_base", "") or "").strip()
    dataspace = str(getattr(deployer_context, "dataspace_name", "") or "").strip()

    _append_public_endpoint(endpoints, seen, "Keycloak admin", resolved_urls.get("KC_URL"))
    _append_public_endpoint(endpoints, seen, "Keycloak public", resolved_urls.get("KC_INTERNAL_URL"))
    _append_public_endpoint(
        endpoints,
        seen,
        "Keycloak hostname",
        resolved_hostnames.get("keycloak_hostname"),
    )
    _append_public_endpoint(
        endpoints,
        seen,
        "MinIO API",
        resolved_hostnames.get("minio_hostname"),
    )

    if dataspace and ds_domain:
        _append_public_endpoint(
            endpoints,
            seen,
            "Registration service",
            f"http://registration-service-{dataspace}.{ds_domain}",
        )

    connector_adapter = getattr(adapter, "connectors", None)
    connector_base_url = getattr(connector_adapter, "connector_base_url", None)
    build_connector_url = getattr(connector_adapter, "build_connector_url", None)
    for connector in connectors or []:
        url = None
        if callable(connector_base_url):
            try:
                url = connector_base_url(connector)
            except Exception:
                url = None
        if not url and callable(build_connector_url):
            try:
                url = build_connector_url(connector)
            except Exception:
                url = None
        _append_public_endpoint(endpoints, seen, f"Connector {connector}", url)

    return endpoints


def _run_public_endpoint_preflight(
    adapter,
    connectors,
    deployer_context,
    *,
    enabled=True,
    announce=True,
):
    if not enabled:
        return {"status": "skipped", "reason": "disabled"}
    if deployer_context is None:
        return {"status": "skipped", "reason": "missing-deployer-context"}
    if getattr(adapter, "infrastructure", None) is None:
        return {"status": "skipped", "reason": "adapter-has-no-infrastructure-adapter"}

    topology = str(getattr(deployer_context, "topology", "local") or "local").strip().lower()
    endpoints = _level6_public_endpoint_candidates(adapter, connectors, deployer_context)
    if not endpoints:
        return {"status": "skipped", "reason": "no-public-endpoints"}

    if announce:
        print("\nVerifying public ingress hostnames...")
    result = ensure_public_endpoints_accessible(endpoints, topology=topology)
    if announce:
        print("Public ingress hostnames OK\n")
    return result


def _ensure_level6_public_endpoint_access(adapter, connectors, deployer_context):
    return _run_public_endpoint_preflight(
        adapter,
        connectors,
        deployer_context,
        enabled=_env_flag("PIONERA_LEVEL6_PUBLIC_ENDPOINT_PREFLIGHT", default=True),
        announce=True,
    )


def _run_local_repair_public_endpoint_preflight(adapter, deployer_context, *, connectors=None):
    return _run_public_endpoint_preflight(
        adapter,
        list(connectors or []),
        deployer_context,
        enabled=_env_flag("PIONERA_LOCAL_REPAIR_PUBLIC_ENDPOINT_PREFLIGHT", default=True),
        announce=True,
    )


def _cleanup_failure_messages(cleanup_result):
    messages = []
    for connector in cleanup_result.get("connectors") or []:
        for error in connector.get("errors") or []:
            message = str(error.get("message") or "").strip()
            if message:
                messages.append(message)
        storage = connector.get("storage") or {}
        for error in storage.get("errors") or []:
            message = str(error.get("message") or "").strip()
            if message:
                messages.append(message)
    return messages


def _test_data_cleanup_failure_hint(cleanup_result):
    messages = _cleanup_failure_messages(cleanup_result)
    if not messages:
        return ""

    joined = "\n".join(messages)
    keycloak_credentials_mismatch = (
        "invalid_grant" in joined
        or "Invalid user credentials" in joined
        or "Token request" in joined and "HTTP 401" in joined
    )
    minio_credentials_mismatch = "InvalidAccessKeyId" in joined

    if keycloak_credentials_mismatch and minio_credentials_mismatch:
        return (
            " Local deployment artifacts are out of sync with the running dataspace "
            "credentials in Keycloak and MinIO. Run Level 4 again from this same checkout "
            "before Level 6, or run Level 6 from the checkout that deployed the current connectors."
        )
    if keycloak_credentials_mismatch:
        return (
            " Local connector credentials do not match Keycloak. Run Level 4 again from this "
            "same checkout before Level 6, or validate from the checkout that deployed the connectors."
        )
    if minio_credentials_mismatch:
        return (
            " Local connector storage credentials do not match MinIO. Run Level 4 again from this "
            "same checkout before Level 6, or validate from the checkout that deployed the connectors."
        )
    return ""


def _run_test_data_cleanup_if_enabled(adapter, connectors, deployer_context, experiment_dir, validation_profile=None):
    if not _should_run_test_data_cleanup(validation_profile=validation_profile):
        return {
            "status": "skipped",
            "reason": "disabled",
        }

    if deployer_context is None:
        return {
            "status": "skipped",
            "reason": "missing-deployer-context",
        }

    context_topology = normalize_topology(
        deployer_context.get("topology") if isinstance(deployer_context, dict) else getattr(deployer_context, "topology", None)
    )
    infrastructure = getattr(adapter, "infrastructure", None)
    ensure_local_access = getattr(infrastructure, "ensure_local_infra_access", None)
    if context_topology == LOCAL_TOPOLOGY and callable(ensure_local_access) and not ensure_local_access():
        raise RuntimeError(
            "Pre-validation test data cleanup failed. Local infrastructure access is not ready."
        )

    cleanup_result = run_pre_validation_cleanup(
        adapter=adapter,
        context=deployer_context,
        connectors=list(connectors or []),
        experiment_dir=experiment_dir,
        mode=_test_data_cleanup_mode(),
        report_enabled=_should_write_test_data_cleanup_report(),
    )
    if cleanup_result.get("status") == "failed":
        report_path = cleanup_result.get("report_path")
        hint = _test_data_cleanup_failure_hint(cleanup_result)
        detail = f" See {report_path} for details." if report_path else ""
        raise RuntimeError(f"Pre-validation test data cleanup failed.{hint}{detail}")
    return cleanup_result


def _legacy_validation_runtime(adapter):
    return {
        "connectors": _resolve_connectors(adapter),
        "validation_profile": None,
        "deployer_context": None,
        "deployer_name": None,
    }


def _should_use_deployer_metrics():
    if _env_flag("PIONERA_DISABLE_DEPLOYER_METRICS", default=False):
        return False

    raw_value = os.getenv("PIONERA_USE_DEPLOYER_METRICS")
    if raw_value is None:
        return True

    return _env_flag("PIONERA_USE_DEPLOYER_METRICS", default=True)


def _should_use_deployer_deploy():
    if _env_flag("PIONERA_DISABLE_DEPLOYER_DEPLOY", default=False):
        return False

    raw_value = os.getenv("PIONERA_USE_DEPLOYER_DEPLOY")
    if raw_value is None:
        return False

    return _env_flag("PIONERA_USE_DEPLOYER_DEPLOY", default=False)


def _should_sync_deployer_hosts():
    if _env_flag("PIONERA_DISABLE_HOSTS_SYNC", default=False):
        return False
    return _env_flag("PIONERA_SYNC_HOSTS", default=False)


def _should_update_hosts_with_sudo():
    if _env_flag("PIONERA_HOSTS_USE_SUDO", default=False):
        return True
    hosts_file = _deployer_hosts_file()
    if not hosts_file:
        return False
    normalized = os.path.abspath(os.path.expanduser(hosts_file))
    if normalized not in {"/etc/hosts", "/private/etc/hosts"}:
        return False
    return not os.access(normalized, os.W_OK)


def _deployer_hosts_address_override():
    value = str(os.getenv("PIONERA_HOSTS_ADDRESS") or "").strip()
    return value or None


def _deployer_hosts_default_address(context=None):
    override = _deployer_hosts_address_override()
    if override:
        return override

    topology_profile = getattr(context, "topology_profile", None)
    default_address = str(getattr(topology_profile, "default_address", "") or "").strip()
    return default_address or "127.0.0.1"


def _deployer_hosts_file():
    configured = str(os.getenv("PIONERA_HOSTS_FILE") or "").strip()
    if configured:
        return configured
    if _should_sync_deployer_hosts():
        return local_menu_tools.get_hosts_path() or ""
    return ""


def _infrastructure_deployer_config_path():
    return os.path.join(os.path.dirname(__file__), "deployers", "infrastructure", "deployer.config")


def _infrastructure_deployer_config_example_path():
    return os.path.join(os.path.dirname(__file__), "deployers", "infrastructure", "deployer.config.example")


def _infrastructure_topology_config_path(topology):
    return topology_overlay_config_path(_infrastructure_deployer_config_path(), topology)


def _infrastructure_topology_config_example_path(topology):
    normalized_topology = str(topology or "").strip().lower()
    if not normalized_topology:
        return ""
    return os.path.join(
        os.path.dirname(__file__),
        "deployers",
        "infrastructure",
        "topologies",
        f"{normalized_topology}.config.example",
    )


def _framework_relative_path(path):
    if not path:
        return ""
    root_dir = os.path.dirname(__file__)
    try:
        common_path = os.path.commonpath([os.path.abspath(path), root_dir])
    except ValueError:
        return path
    if common_path != os.path.abspath(root_dir):
        return path
    return os.path.relpath(path, root_dir)


def _infrastructure_config_migration_warnings():
    warnings = []
    for item in detect_topology_key_migration_warnings(_infrastructure_deployer_config_path()):
        normalized = dict(item)
        normalized["base_path"] = _framework_relative_path(item.get("base_path"))
        normalized["recommended_overlay_paths"] = [
            _framework_relative_path(path)
            for path in list(item.get("recommended_overlay_paths") or [])
            if path
        ]
        overlay_targets = list(normalized.get("recommended_overlay_paths") or [])
        if len(overlay_targets) == 1:
            destination = overlay_targets[0]
        else:
            destination = ", ".join(overlay_targets)
        normalized["message"] = (
            f"{normalized.get('key')} still lives in {normalized.get('base_path')}. "
            f"Move it to {destination}."
        )
        warnings.append(normalized)
    return warnings


def _load_effective_infrastructure_deployer_config(topology=None):
    return load_layered_deployer_config(
        [_infrastructure_deployer_config_path()],
        topology=topology,
        apply_environment=True,
    )


def _normalized_topology_address(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.upper() in {"X", "AUTO", "REPLACE_ME"}:
        return ""
    return text


def _effective_vm_single_cluster_type():
    try:
        config = _load_effective_infrastructure_deployer_config(topology="vm-single")
        return build_cluster_runtime(config, topology="vm-single").get("cluster_type", "minikube")
    except Exception:
        return "minikube"


def _configured_vm_single_address():
    config = _load_effective_infrastructure_deployer_config(topology="vm-single")
    cluster_type = _effective_vm_single_cluster_type()
    candidates = _detect_vm_single_address_candidates() if cluster_type == "k3s" else {}
    vm_ip = _normalized_topology_address(candidates.get("vm_ip"))
    minikube_ip = _normalized_topology_address(candidates.get("minikube_ip"))
    for key in (
        "VM_SINGLE_ADDRESS",
        "VM_SINGLE_IP",
        "VM_EXTERNAL_IP",
        "HOSTS_ADDRESS",
        "INGRESS_EXTERNAL_IP",
    ):
        value = _normalized_topology_address(config.get(key))
        if value:
            if cluster_type == "k3s" and vm_ip and minikube_ip and value == minikube_ip:
                continue
            return value
    return ""


def _command_stdout(args):
    try:
        completed = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return str(completed.stdout or "").strip()


def _detect_vm_single_address_candidates():
    cluster_type = _effective_vm_single_cluster_type()
    vm_ip = ""
    for token in _command_stdout(["hostname", "-I"]).split():
        candidate = _normalized_topology_address(token)
        if candidate and not candidate.startswith("127."):
            vm_ip = candidate
            break

    minikube_ip = ""
    for token in _command_stdout(["minikube", "ip"]).split():
        candidate = _normalized_topology_address(token)
        if candidate:
            minikube_ip = candidate
            break

    if cluster_type == "k3s" and vm_ip:
        recommended_source = "vm"
        recommended_address = vm_ip
    else:
        recommended_source = "minikube" if minikube_ip else ("vm" if vm_ip else "")
        recommended_address = minikube_ip or vm_ip
    return {
        "vm_ip": vm_ip,
        "minikube_ip": minikube_ip,
        "recommended_address": recommended_address,
        "recommended_source": recommended_source,
        "cluster_type": cluster_type,
    }


def _synchronize_vm_single_addresses_after_level1():
    candidates = _detect_vm_single_address_candidates()
    minikube_ip = _normalized_topology_address(candidates.get("minikube_ip"))
    vm_ip = _normalized_topology_address(candidates.get("vm_ip"))
    cluster_type = str(candidates.get("cluster_type") or _effective_vm_single_cluster_type()).strip()
    target_ip = vm_ip if cluster_type == "k3s" else minikube_ip
    source = "vm" if cluster_type == "k3s" else "minikube"
    if not target_ip:
        reason = "vm-ip-unavailable" if cluster_type == "k3s" else "minikube-ip-unavailable"
        return {"status": "skipped", "reason": reason}

    _seed_infrastructure_deployer_config_if_missing()
    config_path = _seed_infrastructure_topology_config_if_missing("vm-single")
    raw_config = _load_effective_infrastructure_deployer_config(topology="vm-single")
    current_vm_external = _normalized_topology_address(raw_config.get("VM_EXTERNAL_IP"))
    current_ingress = _normalized_topology_address(raw_config.get("INGRESS_EXTERNAL_IP"))
    baseline_shared = current_vm_external or current_ingress or vm_ip

    updates = {}

    def _should_sync_shared(current_value):
        if not current_value:
            return True
        if current_value == target_ip:
            return False
        if cluster_type == "k3s" and minikube_ip and current_value == minikube_ip:
            return True
        return bool(vm_ip) and current_value == vm_ip

    if _should_sync_shared(current_vm_external):
        updates["VM_EXTERNAL_IP"] = target_ip
    if _should_sync_shared(current_ingress):
        updates["INGRESS_EXTERNAL_IP"] = target_ip

    syncing_from_provisional_shared = bool(vm_ip) and baseline_shared == vm_ip
    shared_updated = bool({"VM_EXTERNAL_IP", "INGRESS_EXTERNAL_IP"} & set(updates))

    for key in ("VM_COMMON_IP", "VM_DATASPACE_IP", "VM_CONNECTORS_IP", "VM_COMPONENTS_IP"):
        current_value = _normalized_topology_address(raw_config.get(key))
        if current_value == target_ip:
            continue
        if cluster_type == "k3s" and minikube_ip and current_value == minikube_ip:
            updates[key] = target_ip
            continue
        if not current_value:
            if shared_updated or syncing_from_provisional_shared:
                updates[key] = target_ip
            continue
        if vm_ip and current_value == vm_ip:
            updates[key] = target_ip
            continue
        if syncing_from_provisional_shared and current_value == baseline_shared:
            updates[key] = target_ip

    if not updates:
        return {"status": "skipped", "reason": "already-configured"}

    _write_key_value_updates(
        config_path,
        updates,
        (
            "VM_EXTERNAL_IP",
            "VM_COMMON_IP",
            "VM_DATASPACE_IP",
            "VM_CONNECTORS_IP",
            "VM_COMPONENTS_IP",
            "INGRESS_EXTERNAL_IP",
        ),
    )
    print(f"Updated vm-single topology address values from detected {source} ip.")
    return {"status": "updated", "source": source}


def _write_key_value_updates(path, updates, preferred_order):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    seen = set()
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key, _value = stripped.split("=", 1)
                    key = key.strip()
                    if key in updates:
                        lines.append(f"{key}={updates[key]}\n")
                        seen.add(key)
                        continue
                lines.append(raw_line if raw_line.endswith("\n") else f"{raw_line}\n")

    ordered_keys = [key for key in preferred_order if key in updates and key not in seen]
    ordered_keys.extend(sorted(key for key in updates if key not in seen and key not in ordered_keys))
    for key in ordered_keys:
        lines.append(f"{key}={updates[key]}\n")

    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def _seed_infrastructure_deployer_config_if_missing():
    config_path = _infrastructure_deployer_config_path()
    if os.path.isfile(config_path):
        return config_path

    example_path = _infrastructure_deployer_config_example_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    if os.path.isfile(example_path):
        shutil.copy2(example_path, config_path)
    else:
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("")
    return config_path


def _seed_infrastructure_topology_config_if_missing(topology):
    config_path = _infrastructure_topology_config_path(topology)
    if not config_path:
        return ""
    if os.path.isfile(config_path):
        return config_path

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    example_path = _infrastructure_topology_config_example_path(topology)
    if example_path and os.path.isfile(example_path):
        shutil.copy2(example_path, config_path)
    else:
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("")
    return config_path


def _interactive_offer_vm_single_address_configuration(required=False):
    if _configured_vm_single_address():
        return True

    candidates = _detect_vm_single_address_candidates()
    recommended_address = str(candidates.get("recommended_address") or "").strip()
    recommended_source = str(candidates.get("recommended_source") or "").strip()

    print()
    print("vm-single needs a topology address for ingress hostnames and public URLs.")
    if candidates.get("vm_ip"):
        print("Detected a candidate address from hostname -I.")
    if candidates.get("minikube_ip"):
        print("Detected a candidate address from minikube ip.")

    if not recommended_address:
        print("Could not detect a vm-single address automatically.")
        print("Set VM_EXTERNAL_IP or INGRESS_EXTERNAL_IP in deployers/infrastructure/topologies/vm-single.config.")
        return not required

    source_label = "minikube ip" if recommended_source == "minikube" else "hostname -I"
    if not _interactive_confirm(
        f"Populate VM_EXTERNAL_IP and INGRESS_EXTERNAL_IP from detected {source_label} now?",
        default=required,
    ):
        if required:
            print("Cannot continue until vm-single address is configured.")
            print("Set VM_EXTERNAL_IP/INGRESS_EXTERNAL_IP or choose T again later.")
            return False
        return True

    _seed_infrastructure_deployer_config_if_missing()
    config_path = _seed_infrastructure_topology_config_if_missing("vm-single")
    _write_key_value_updates(
        config_path,
        {
            "VM_EXTERNAL_IP": recommended_address,
            "INGRESS_EXTERNAL_IP": recommended_address,
        },
        ("VM_EXTERNAL_IP", "INGRESS_EXTERNAL_IP"),
    )
    print("Updated deployers/infrastructure/topologies/vm-single.config with vm-single address values.")
    return True


def _menu_action_requires_vm_single_address(choice):
    normalized = str(choice or "").strip().upper()
    if normalized in {"0", "P", "H", "U", "X"}:
        return True
    return normalized in {"3", "4", "5", "6"}


def _should_use_deployer_run():
    if _env_flag("PIONERA_DISABLE_DEPLOYER_RUN", default=False):
        return False

    raw_value = os.getenv("PIONERA_USE_DEPLOYER_RUN")
    if raw_value is None:
        return False

    return _env_flag("PIONERA_USE_DEPLOYER_RUN", default=False)


def _should_execute_deployer_deploy(deployer_name=None, topology="local"):
    if not _should_use_deployer_deploy():
        return False
    if not _env_flag("PIONERA_EXECUTE_DEPLOYER_DEPLOY", default=False):
        return False

    normalized_deployer = str(deployer_name or "").strip().lower()
    normalized_topology = str(topology or "local").strip().lower()
    return normalized_deployer == "edc" and normalized_topology == "local"


def _should_execute_deployer_run(deployer_name=None, topology="local"):
    if not _should_use_deployer_run():
        return False
    if not _env_flag("PIONERA_EXECUTE_DEPLOYER_RUN", default=False):
        return False

    normalized_deployer = str(deployer_name or "").strip().lower()
    normalized_topology = str(topology or "local").strip().lower()
    return normalized_deployer == "edc" and normalized_topology == "local"


def _legacy_metrics_runtime(adapter):
    return {
        "connectors": _resolve_connectors(adapter),
        "deployer_context": None,
        "deployer_name": None,
    }


def _vm_single_validation_context_failure_message(exc):
    detail = str(exc or "").strip()
    message = (
        "Could not resolve deployer-aware validation context for topology 'vm-single'. "
        "Configure PIONERA_VM_EXTERNAL_IP, PIONERA_VM_SINGLE_IP, "
        "PIONERA_VM_SINGLE_ADDRESS, PIONERA_HOSTS_ADDRESS, or "
        "PIONERA_INGRESS_EXTERNAL_IP before running Level 6 or 'validate'."
    )
    if detail:
        return f"{message} Original error: {detail}"
    return message


def _resolve_validation_runtime(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    if not _should_use_deployer_validate():
        return _legacy_validation_runtime(adapter)

    try:
        resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
        orchestrator = build_deployer_orchestrator(
            deployer_name=resolved_deployer_name,
            deployer_registry=deployer_registry,
            adapter=adapter,
            topology=topology,
        )
        context = orchestrator.resolve_context(topology=topology)
        profile = orchestrator.get_validation_profile(context)
        connectors = orchestrator.get_cluster_connectors(context)
        if not connectors:
            connectors = _resolve_connectors(adapter)
    except Exception as exc:
        if _env_flag("PIONERA_REQUIRE_DEPLOYER_VALIDATE", default=False):
            raise
        if normalize_topology(topology) == "vm-single":
            raise RuntimeError(_vm_single_validation_context_failure_message(exc)) from exc
        return _legacy_validation_runtime(adapter)

    return {
        "connectors": connectors,
        "validation_profile": profile,
        "deployer_context": context,
        "deployer_name": resolved_deployer_name,
    }


def _resolve_metrics_runtime(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    if not _should_use_deployer_metrics():
        return _legacy_metrics_runtime(adapter)

    try:
        resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
        orchestrator = build_deployer_orchestrator(
            deployer_name=resolved_deployer_name,
            deployer_registry=deployer_registry,
            adapter=adapter,
            topology=topology,
        )
        context = orchestrator.resolve_context(topology=topology)
        connectors = orchestrator.get_cluster_connectors(context)
        if not connectors:
            connectors = _resolve_connectors(adapter)
    except Exception:
        if _env_flag("PIONERA_REQUIRE_DEPLOYER_METRICS", default=False):
            raise
        return _legacy_metrics_runtime(adapter)

    return {
        "connectors": connectors,
        "deployer_context": context,
        "deployer_name": resolved_deployer_name,
    }


def _resolve_deployer_context(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
    orchestrator = build_deployer_orchestrator(
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        adapter=adapter,
        topology=topology,
    )
    return resolved_deployer_name, orchestrator.resolve_context(topology=topology)


def _build_shadow_host_sync_plan(context, levels=None):
    address_override = _deployer_hosts_address_override()
    all_blocks = build_context_host_blocks(context, address=address_override)
    blocks = _filter_host_blocks_for_levels(all_blocks, levels) if levels else list(all_blocks)
    levels_by_block = hostnames_by_level(blocks)
    topology_profile = getattr(context, "topology_profile", None)
    hosts_file = _deployer_hosts_file() or None
    legacy_external_hostnames = []
    if hosts_file:
        legacy_external_hostnames = detect_legacy_external_hostnames(
            _read_hosts_file_content(hosts_file),
            block_names=[block.name for block in all_blocks],
            config=dict(getattr(context, "config", {}) or {}),
        )
    return {
        "status": "planned",
        "hosts_file": hosts_file,
        "address": _deployer_hosts_default_address(context),
        "address_override": address_override,
        "namespace_profile": _context_namespace_profile(context),
        "namespace_roles": _context_namespace_roles_dict(context),
        "planned_namespace_roles": _context_planned_namespace_roles_dict(context),
        "namespace_plan_summary": _build_namespace_plan_summary(context),
        "topology_profile": (
            topology_profile.as_dict()
            if hasattr(topology_profile, "as_dict")
            else None
        ),
        "blocks": blocks_as_dict(blocks),
        "level_1_2": levels_by_block["level_1_2"],
        "level_3": levels_by_block["level_3"],
        "level_4": levels_by_block["level_4"],
        "level_5": levels_by_block["level_5"],
        "legacy_external_hostnames": legacy_external_hostnames,
    }


def _interactive_hosts_file_path():
    return _deployer_hosts_file() or local_menu_tools.get_hosts_path()


def _read_hosts_file_hostnames(hosts_file):
    if not hosts_file:
        return set()
    try:
        with open(hosts_file, "r", encoding="utf-8") as handle:
            return parse_hostnames(handle.read())
    except OSError:
        return set()


def _read_hosts_file_content(hosts_file):
    if not hosts_file:
        return ""
    try:
        with open(hosts_file, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _dedupe_ordered(values):
    deduped = []
    seen = set()
    for value in values or []:
        normalized = str(value or "").strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _host_plan_levels_required_for_levels(levels):
    selected_levels = {int(level) for level in (levels or [])}
    if not selected_levels:
        selected_levels = {3, 4, 5, 6}

    required = []
    if selected_levels.intersection({2, 3, 4, 5, 6}):
        required.append("level_1_2")
    if selected_levels.intersection({3, 4, 5, 6}):
        required.append("level_3")
    if selected_levels.intersection({4, 6}):
        required.append("level_4")
    if selected_levels.intersection({5, 6}):
        required.append("level_5")
    return _dedupe_ordered(required)


def _host_block_level_key(block):
    if not hasattr(block, "name"):
        return None
    name = str(getattr(block, "name", "") or "").strip()
    if name == "shared common":
        return "level_1_2"
    if name.startswith("dataspace "):
        return "level_3"
    if name.startswith("connectors "):
        return "level_4"
    if name.startswith("components "):
        return "level_5"
    return None


def _filter_host_blocks_for_levels(blocks, levels=None):
    required_keys = set(_host_plan_levels_required_for_levels(levels))
    if not required_keys:
        return []
    filtered = []
    for block in list(blocks or []):
        if _host_block_level_key(block) in required_keys:
            filtered.append(block)
    return filtered


def _build_hosts_readiness_plan(context, levels=None, hosts_file=None):
    plan = _build_shadow_host_sync_plan(context)
    resolved_hosts_file = hosts_file or _interactive_hosts_file_path()
    existing_content = _read_hosts_file_content(resolved_hosts_file)
    existing_hostnames = parse_hostnames(existing_content)
    required_keys = _host_plan_levels_required_for_levels(levels)
    blocks = build_context_host_blocks(context, address=_deployer_hosts_address_override())
    existing_addresses = _parse_hosts_addresses(existing_content)
    expected_entries = [
        entry
        for block in _filter_host_blocks_for_levels(blocks, levels)
        for entry in list(getattr(block, "entries", []) or [])
    ]
    required_hostnames = _dedupe_ordered(entry.hostname for entry in expected_entries)
    missing_hostnames = []
    for entry in expected_entries:
        hostname_key = str(entry.hostname or "").strip().lower()
        if not hostname_key:
            continue
        if hostname_key not in existing_hostnames:
            missing_hostnames.append(entry.hostname)
            continue
        expected_address = str(entry.address or "").strip()
        if expected_address and expected_address not in existing_addresses.get(hostname_key, set()):
            missing_hostnames.append(entry.hostname)
    missing_hostnames = _dedupe_ordered(missing_hostnames)
    legacy_external_hostnames = detect_legacy_external_hostnames(
        existing_content,
        block_names=[block.name for block in blocks],
        config=dict(getattr(context, "config", {}) or {}),
    )

    return {
        "status": "missing" if missing_hostnames else "ready",
        "hosts_file": resolved_hosts_file,
        "required_levels": required_keys,
        "required_hostnames": required_hostnames,
        "missing_hostnames": missing_hostnames,
        "legacy_external_hostnames": legacy_external_hostnames,
        "hosts_plan": plan,
    }


def _parse_hosts_addresses(content):
    addresses = {}
    for raw_line in (content or "").splitlines():
        active_part = raw_line.split("#", 1)[0].strip()
        if not active_part:
            continue
        parts = active_part.split()
        if len(parts) < 2:
            continue
        address = parts[0].strip()
        for hostname in parts[1:]:
            hostname_key = hostname.strip().lower()
            if hostname_key:
                addresses.setdefault(hostname_key, set()).add(address)
    return addresses


def _sync_deployer_hosts_if_enabled(context, levels=None):
    plan = _build_shadow_host_sync_plan(context, levels=levels)
    if not _should_sync_deployer_hosts():
        return {
            "status": "skipped",
            "reason": "disabled",
            "plan": plan,
        }

    hosts_file = _deployer_hosts_file()
    if not hosts_file:
        raise RuntimeError(
            "PIONERA_SYNC_HOSTS=true requires PIONERA_HOSTS_FILE to point to the hosts file to update. "
            "For Windows from WSL this is usually /mnt/c/Windows/System32/drivers/etc/hosts."
        )

    blocks = _filter_host_blocks_for_levels(
        build_context_host_blocks(context, address=_deployer_hosts_address_override()),
        levels,
    ) if levels else build_context_host_blocks(context, address=_deployer_hosts_address_override())
    result = apply_managed_blocks(
        hosts_file,
        blocks,
        config=dict(getattr(context, "config", {}) or {}),
        use_sudo=_should_update_hosts_with_sudo(),
    )
    return {
        "status": "updated" if result["changed"] else "unchanged",
        "hosts_file": result["hosts_file"],
        "changed": result["changed"],
        "elevated": result.get("elevated", False),
        "blocks": result["blocks"],
        "skipped_existing": result.get("skipped_existing", {}),
        "legacy_external_hostnames": result.get("legacy_external_hostnames", []),
    }


def _resolve_shadow_deploy_preflight(adapter):
    preview = _resolve_adapter_preview(adapter, "deploy")
    if isinstance(preview, dict):
        return _sanitize_preview_data(preview)
    return None


def _build_shadow_level_plan(context, preflight=None):
    components = list(getattr(context, "components", []) or [])
    level_plan = {
        "level_1_2": {
            "action": "deploy_infrastructure",
            "namespace_roles": ["common_services_namespace"],
            "status": "planned",
            "details": None,
        },
        "level_3": {
            "action": "deploy_dataspace",
            "namespace_roles": [
                "registration_service_namespace",
                "provider_namespace",
                "consumer_namespace",
            ],
            "status": "planned",
            "details": None,
        },
        "level_4": {
            "action": "deploy_connectors",
            "namespace_roles": ["provider_namespace", "consumer_namespace"],
            "status": "planned",
            "details": None,
        },
        "level_5": {
            "action": "deploy_components",
            "namespace_roles": ["components_namespace"],
            "status": "planned" if components else "not-applicable",
            "details": {"components": components} if components else {"components": []},
        },
    }

    if not isinstance(preflight, dict):
        return level_plan

    shared_common_services = preflight.get("shared_common_services")
    if isinstance(shared_common_services, dict):
        level_plan["level_1_2"]["status"] = shared_common_services.get("status", "planned")
        level_plan["level_1_2"]["details"] = shared_common_services

    shared_dataspace = preflight.get("shared_dataspace")
    if isinstance(shared_dataspace, dict):
        level_plan["level_3"]["status"] = shared_dataspace.get("status", "planned")
        level_plan["level_3"]["details"] = shared_dataspace

    connectors = preflight.get("connectors")
    if isinstance(connectors, dict):
        level_plan["level_4"]["status"] = connectors.get("status", "planned")
        level_plan["level_4"]["details"] = connectors

    if isinstance(preflight.get("components"), dict):
        component_preview = preflight["components"]
        level_plan["level_5"]["status"] = component_preview.get("status", level_plan["level_5"]["status"])
        level_plan["level_5"]["details"] = component_preview

    if isinstance(preflight.get("status"), str):
        overall_status = preflight["status"]
        if overall_status == "ready" and not components and level_plan["level_5"]["status"] == "not-applicable":
            level_plan["level_5"]["details"] = {"components": []}

    return level_plan


def _build_deployer_deploy_shadow_plan(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
    orchestrator = build_deployer_orchestrator(
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        adapter=adapter,
        topology=topology,
    )
    context = orchestrator.resolve_context(topology=topology)
    profile = orchestrator.get_validation_profile(context)
    preflight = _resolve_shadow_deploy_preflight(adapter)

    return {
        "mode": "shadow",
        "status": "planned",
        "deployer_name": resolved_deployer_name,
        "topology": topology,
        "namespace_profile": _context_namespace_profile(context),
        "namespace_plan_summary": _build_namespace_plan_summary(context),
        "actions": [
            "resolve_context",
            "plan_infrastructure",
            "plan_dataspace",
            "plan_connectors",
            "plan_components",
            "plan_validation_after_deploy",
        ],
        "namespace_roles": _context_namespace_roles_dict(context),
        "planned_namespace_roles": _context_planned_namespace_roles_dict(context),
        "deployer_context": _sanitize_preview_data(context.as_dict()),
        "hosts_plan": _build_shadow_host_sync_plan(context),
        "level_plan": _build_shadow_level_plan(context, preflight=preflight),
        "preflight": preflight,
        "validation_profile": profile.as_dict(),
    }


def _edc_local_connector_image_defaults():
    return {
        "name": os.getenv("PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_NAME", "validation-environment/edc-connector"),
        "tag": os.getenv("PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_TAG", "local"),
    }


def _edc_local_dashboard_image_defaults(config, adapter):
    config_cls = getattr(adapter, "config", None)
    return {
        "dashboard_name": str(
            config.get("EDC_DASHBOARD_IMAGE_NAME")
            or os.getenv("PIONERA_EDC_DASHBOARD_IMAGE_NAME")
            or getattr(config_cls, "EDC_DASHBOARD_IMAGE_NAME", "validation-environment/edc-dashboard")
            or ""
        ).strip(),
        "dashboard_tag": str(
            config.get("EDC_DASHBOARD_IMAGE_TAG")
            or os.getenv("PIONERA_EDC_DASHBOARD_IMAGE_TAG")
            or getattr(config_cls, "EDC_DASHBOARD_IMAGE_TAG", "latest")
            or ""
        ).strip(),
        "proxy_name": str(
            config.get("EDC_DASHBOARD_PROXY_IMAGE_NAME")
            or os.getenv("PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME")
            or getattr(config_cls, "EDC_DASHBOARD_PROXY_IMAGE_NAME", "validation-environment/edc-dashboard-proxy")
            or ""
        ).strip(),
        "proxy_tag": str(
            config.get("EDC_DASHBOARD_PROXY_IMAGE_TAG")
            or os.getenv("PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG")
            or getattr(config_cls, "EDC_DASHBOARD_PROXY_IMAGE_TAG", "latest")
            or ""
        ).strip(),
    }


def _edc_local_minikube_profile(adapter):
    env_profile = os.getenv("PIONERA_MINIKUBE_PROFILE") or os.getenv("MINIKUBE_PROFILE")
    if env_profile:
        return env_profile.strip() or "minikube"

    config_adapter = getattr(adapter, "config_adapter", None)
    config_loader = getattr(config_adapter, "load_deployer_config", None)
    config = dict(config_loader() or {}) if callable(config_loader) else {}
    return str(config.get("MINIKUBE_PROFILE") or "minikube").strip() or "minikube"


def _ensure_docker_client_ready_for_local_image_build(adapter):
    infrastructure = getattr(adapter, "infrastructure", None)
    ensure_config = getattr(infrastructure, "ensure_wsl_docker_config", None)
    if callable(ensure_config) and not ensure_config():
        raise RuntimeError("Could not adjust WSL Docker configuration safely before building local images.")
    return True


def _edc_local_cluster_runtime(adapter, topology="local"):
    config_adapter = getattr(adapter, "config_adapter", None)
    runtime_getter = getattr(config_adapter, "cluster_runtime", None)
    if callable(runtime_getter):
        try:
            return str((runtime_getter() or {}).get("cluster_type") or "minikube").strip().lower() or "minikube"
        except Exception:
            pass
    config_loader = getattr(config_adapter, "load_deployer_config", None)
    config = dict(config_loader() or {}) if callable(config_loader) else {}
    normalized_topology = normalize_topology(topology or getattr(adapter, "topology", None) or "local")
    return build_cluster_runtime(config, topology=normalized_topology).get("cluster_type", "minikube")


def _prepare_edc_local_connector_image_override(adapter):
    if _env_flag("PIONERA_SKIP_EDC_LOCAL_CONNECTOR_IMAGE_BUILD", default=False):
        raise RuntimeError(
            "EDC Level 4 local execution needs a connector image, but automatic local image "
            "preparation was disabled with PIONERA_SKIP_EDC_LOCAL_CONNECTOR_IMAGE_BUILD=true."
        )

    image = _edc_local_connector_image_defaults()
    image_name = str(image["name"] or "").strip()
    image_tag = str(image["tag"] or "").strip()
    if not image_name or not image_tag:
        raise RuntimeError(
            "EDC local connector image defaults are invalid. Set "
            "PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_NAME and PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_TAG."
        )

    root_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(root_dir, "adapters", "edc", "scripts", "build_image.sh")
    if not os.path.isfile(script_path):
        raise RuntimeError(f"EDC connector image build script not found: {script_path}")

    _ensure_docker_client_ready_for_local_image_build(adapter)
    minikube_profile = _edc_local_minikube_profile(adapter)
    cluster_runtime = _edc_local_cluster_runtime(adapter, topology=getattr(adapter, "topology", "local"))
    config_adapter = getattr(adapter, "config_adapter", None)
    source_dir_getter = getattr(config_adapter, "edc_connector_source_dir", None)
    repo_url_getter = getattr(config_adapter, "edc_reference_repo_url", None)
    repo_subdir_getter = getattr(config_adapter, "edc_reference_repo_subdir", None)
    source_dir = source_dir_getter() if callable(source_dir_getter) else os.path.join(
        root_dir,
        "adapters",
        "edc",
        "sources",
        "dashboard",
        "asset-filter-template",
    )
    repo_url = repo_url_getter() if callable(repo_url_getter) else "https://github.com/ProyectoPIONERA/EDC-asset-filter-dashboard"
    repo_subdir = repo_subdir_getter() if callable(repo_subdir_getter) else "asset-filter-template"
    command = [
        "bash",
        script_path,
        "--apply",
        "--source-dir",
        source_dir,
        "--sync-git-url",
        repo_url,
        "--sync-subdir",
        repo_subdir,
        "--image",
        image_name,
        "--tag",
        image_tag,
        "--minikube-profile",
        minikube_profile,
        "--cluster-runtime",
        cluster_runtime,
    ]

    print(
        "EDC connector image overrides are not configured. "
        f"Preparing local image automatically: {image_name}:{image_tag} "
        f"(cluster runtime: {cluster_runtime})"
    )
    result = subprocess.run(command, cwd=root_dir, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Automatic EDC connector image preparation failed. "
            f"Command returned exit code {result.returncode}: {' '.join(command)}"
        )

    os.environ["PIONERA_EDC_CONNECTOR_IMAGE_NAME"] = image_name
    os.environ["PIONERA_EDC_CONNECTOR_IMAGE_TAG"] = image_tag
    os.environ.setdefault("PIONERA_EDC_CONNECTOR_IMAGE_PULL_POLICY", "IfNotPresent")
    os.environ["PIONERA_EDC_LOCAL_CONNECTOR_IMAGE_PREPARED"] = "true"
    return {
        "image_name": image_name,
        "image_tag": image_tag,
        "minikube_profile": minikube_profile,
        "cluster_runtime": cluster_runtime,
    }


def _run_edc_local_image_script(script_path, minikube_profile, env, cluster_runtime="minikube"):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    command = [
        "bash",
        script_path,
        "--apply",
        "--minikube-profile",
        minikube_profile,
        "--cluster-runtime",
        cluster_runtime,
    ]
    result = subprocess.run(command, cwd=root_dir, check=False, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            "Automatic EDC local image preparation failed. "
            f"Command returned exit code {result.returncode}: {' '.join(command)}"
        )


def _prepare_edc_local_dashboard_images(adapter, config):
    if not _mapping_flag(config, "EDC_DASHBOARD_ENABLED", default=False):
        return {"status": "skipped", "reason": "dashboard-disabled"}

    if _env_flag("PIONERA_SKIP_EDC_LOCAL_DASHBOARD_IMAGE_BUILD", default=False):
        return {"status": "skipped", "reason": "disabled-by-env"}

    images = _edc_local_dashboard_image_defaults(config, adapter)
    missing = [key for key, value in images.items() if not value]
    if missing:
        raise RuntimeError(
            "EDC dashboard local image defaults are invalid. Missing: "
            + ", ".join(sorted(missing))
        )

    root_dir = os.path.dirname(os.path.abspath(__file__))
    dashboard_script = os.path.join(root_dir, "adapters", "edc", "scripts", "build_dashboard_image.sh")
    proxy_script = os.path.join(root_dir, "adapters", "edc", "scripts", "build_dashboard_proxy_image.sh")
    for script_path in (dashboard_script, proxy_script):
        if not os.path.isfile(script_path):
            raise RuntimeError(f"EDC dashboard image build script not found: {script_path}")

    _ensure_docker_client_ready_for_local_image_build(adapter)
    minikube_profile = _edc_local_minikube_profile(adapter)
    cluster_runtime = _edc_local_cluster_runtime(adapter, topology=getattr(adapter, "topology", "local"))
    env = dict(os.environ)
    env["PIONERA_EDC_DASHBOARD_IMAGE_NAME"] = images["dashboard_name"]
    env["PIONERA_EDC_DASHBOARD_IMAGE_TAG"] = images["dashboard_tag"]
    env["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME"] = images["proxy_name"]
    env["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG"] = images["proxy_tag"]

    print(
        "EDC dashboard is enabled. Preparing local dashboard images automatically: "
        f"{images['dashboard_name']}:{images['dashboard_tag']} and "
        f"{images['proxy_name']}:{images['proxy_tag']} "
        f"(cluster runtime: {cluster_runtime})"
    )
    _run_edc_local_image_script(dashboard_script, minikube_profile, env, cluster_runtime=cluster_runtime)
    _run_edc_local_image_script(proxy_script, minikube_profile, env, cluster_runtime=cluster_runtime)

    os.environ["PIONERA_EDC_DASHBOARD_IMAGE_NAME"] = images["dashboard_name"]
    os.environ["PIONERA_EDC_DASHBOARD_IMAGE_TAG"] = images["dashboard_tag"]
    os.environ["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_NAME"] = images["proxy_name"]
    os.environ["PIONERA_EDC_DASHBOARD_PROXY_IMAGE_TAG"] = images["proxy_tag"]
    os.environ.setdefault("PIONERA_EDC_DASHBOARD_IMAGE_PULL_POLICY", "IfNotPresent")
    os.environ.setdefault("PIONERA_EDC_DASHBOARD_PROXY_IMAGE_PULL_POLICY", "IfNotPresent")
    os.environ["PIONERA_EDC_LOCAL_DASHBOARD_IMAGES_PREPARED"] = "true"
    return {
        "status": "prepared",
        "dashboard_image": f"{images['dashboard_name']}:{images['dashboard_tag']}",
        "dashboard_proxy_image": f"{images['proxy_name']}:{images['proxy_tag']}",
        "minikube_profile": minikube_profile,
        "cluster_runtime": cluster_runtime,
    }


def _edc_topology_supports_local_image_preparation(topology):
    return normalize_topology(topology or LOCAL_TOPOLOGY) in {LOCAL_TOPOLOGY, "vm-single"}


def _ensure_safe_edc_deployer_execution(adapter, deployer_name=None, topology="local"):
    normalized_deployer = str(deployer_name or _infer_deployer_name_from_adapter(adapter)).strip().lower()
    if normalized_deployer != "edc":
        return

    config_adapter = getattr(adapter, "config_adapter", None)
    config_loader = getattr(config_adapter, "load_deployer_config", None)
    config = dict(config_loader() or {}) if callable(config_loader) else {}
    normalized_topology = str(topology or "local").strip().lower()

    dataspace_name = ""
    primary_dataspace_name = getattr(config_adapter, "primary_dataspace_name", None)
    if callable(primary_dataspace_name):
        dataspace_name = str(primary_dataspace_name() or "").strip()
    if not dataspace_name:
        dataspace_name = str(
            config.get("DS_1_NAME")
            or os.getenv("PIONERA_DS_1_NAME")
            or ""
        ).strip()

    shared_dataspaces = {"demo", "pionera"}
    allow_shared_dataspace = str(
        os.getenv("PIONERA_ALLOW_SHARED_EDC_DEPLOY", "false")
    ).strip().lower() in {"1", "true", "yes", "on"}

    if dataspace_name.lower() in shared_dataspaces and not allow_shared_dataspace:
        raise RuntimeError(
            "Real deployer execution for EDC refuses to target the shared dataspace "
            f"'{dataspace_name}'. Use an isolated dataspace such as 'pionera-edc' or set "
            "PIONERA_ALLOW_SHARED_EDC_DEPLOY=true to bypass this protection explicitly."
        )

    explicit_image_name = str(
        config.get("EDC_CONNECTOR_IMAGE_NAME")
        or os.getenv("PIONERA_EDC_CONNECTOR_IMAGE_NAME")
        or ""
    ).strip()
    explicit_image_tag = str(
        config.get("EDC_CONNECTOR_IMAGE_TAG")
        or os.getenv("PIONERA_EDC_CONNECTOR_IMAGE_TAG")
        or ""
    ).strip()

    config_cls = getattr(adapter, "config", None)
    default_image_name = str(
        getattr(config_cls, "EDC_CONNECTOR_IMAGE_NAME", "ghcr.io/proyectopionera/edc-connector") or ""
    ).strip()
    default_image_tag = str(
        getattr(config_cls, "EDC_CONNECTOR_IMAGE_TAG", "latest") or ""
    ).strip()

    if not explicit_image_name or not explicit_image_tag:
        if (
            _edc_topology_supports_local_image_preparation(normalized_topology)
            and not explicit_image_name
            and not explicit_image_tag
        ):
            prepared = _prepare_edc_local_connector_image_override(adapter)
            explicit_image_name = prepared["image_name"]
            explicit_image_tag = prepared["image_tag"]
        else:
            raise RuntimeError(
                "Real deployer execution for EDC requires explicit EDC connector image overrides. "
                "Set PIONERA_EDC_CONNECTOR_IMAGE_NAME and PIONERA_EDC_CONNECTOR_IMAGE_TAG first."
            )

    if not explicit_image_name or not explicit_image_tag:
        raise RuntimeError(
            "Real deployer execution for EDC requires explicit EDC connector image overrides. "
            "Set PIONERA_EDC_CONNECTOR_IMAGE_NAME and PIONERA_EDC_CONNECTOR_IMAGE_TAG first."
        )

    if explicit_image_name == default_image_name and explicit_image_tag == default_image_tag:
        raise RuntimeError(
            "Real deployer execution for EDC refuses to use the default connector image "
            f"'{default_image_name}:{default_image_tag}'. Provide an explicit working image override."
        )

    if _edc_topology_supports_local_image_preparation(normalized_topology):
        _prepare_edc_local_dashboard_images(adapter, config)


def _execute_deployer_deploy(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
    _ensure_safe_edc_deployer_execution(adapter, deployer_name=resolved_deployer_name, topology=topology)
    orchestrator = build_deployer_orchestrator(
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        adapter=adapter,
        topology=topology,
    )
    deployment = orchestrator.deploy(topology=topology)
    context = deployment["context"]
    profile = orchestrator.get_validation_profile(context)
    hosts_sync = _sync_deployer_hosts_if_enabled(context)

    return {
        "mode": "execute",
        "status": "completed",
        "deployer_name": resolved_deployer_name,
        "topology": topology,
        "namespace_profile": _context_namespace_profile(context),
        "namespace_roles": _context_namespace_roles_dict(context),
        "planned_namespace_roles": _context_planned_namespace_roles_dict(context),
        "deployer_context": _sanitize_preview_data(context.as_dict()),
        "hosts_sync": hosts_sync,
        "deployment": {
            "infrastructure": deployment.get("infrastructure"),
            "dataspace": deployment.get("dataspace"),
            "connectors": deployment.get("connectors"),
            "components": deployment.get("components"),
        },
        "validation_profile": profile.as_dict(),
    }


def _resolve_connector_log_fetcher(adapter):
    run_silent = getattr(adapter, "run_silent", None)
    config = getattr(adapter, "config", None)
    namespace = getattr(config, "NS_DS", None) if config is not None else None

    if not callable(run_silent) or not namespace:
        return None

    def fetch_connector_logs(connectors, metadata=None):
        logs = {}
        for connector in connectors or []:
            pod_name = f"{connector}-controlplane"
            output = run_silent(f"kubectl logs {pod_name} -n {namespace} --tail=500")
            if output:
                logs[connector] = output
        return logs

    return fetch_connector_logs


def _save_experiment_metadata(storage, experiment_dir, connectors, **kwargs):
    save_method = storage.save_experiment_metadata
    try:
        parameters = inspect.signature(save_method).parameters
    except (TypeError, ValueError):
        parameters = {}

    if len(parameters) <= 2:
        return save_method(experiment_dir, connectors)

    filtered_kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    return save_method(experiment_dir, connectors, **filtered_kwargs)


def _metadata_cluster_runtime_for_topology(topology="local"):
    normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
    try:
        config = _load_effective_infrastructure_deployer_config(topology=normalized_topology)
        runtime = build_cluster_runtime(config, topology=normalized_topology)
        return str(runtime.get("cluster_type") or "").strip() or "unknown"
    except Exception:
        if normalized_topology == LOCAL_TOPOLOGY:
            return "minikube"
        return "unknown"


def _experiment_metadata_context(adapter_name=None, topology="local", **extra):
    normalized_topology = normalize_topology(topology or LOCAL_TOPOLOGY)
    payload = {
        "adapter_name": adapter_name,
        "topology": normalized_topology,
        "cluster_runtime": _metadata_cluster_runtime_for_topology(normalized_topology),
    }
    payload.update(extra)
    return payload


def run_hosts(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    """Plan or apply local hosts entries for the selected deployer context."""
    resolved_deployer_name, context = _resolve_deployer_context(
        adapter,
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    plan = _build_shadow_host_sync_plan(context)
    sync = _sync_deployer_hosts_if_enabled(context)
    result_status = sync.get("status", "planned")
    if result_status == "skipped" and sync.get("reason") == "disabled":
        result_status = "planned"
    return {
        "status": result_status,
        "deployer_name": resolved_deployer_name,
        "topology": topology,
        "dataspace": getattr(context, "dataspace_name", None),
        "config_migration_warnings": _infrastructure_config_migration_warnings(),
        "hosts_plan": plan,
        "hosts_sync": sync,
    }


def _local_repair_levels(levels=None):
    selected = []
    for level in levels or (3, 4, 5, 6):
        try:
            normalized = int(level)
        except (TypeError, ValueError):
            continue
        if normalized in {3, 4, 5, 6} and normalized not in selected:
            selected.append(normalized)
    return selected or [3, 4, 5, 6]


def _filter_doctor_report(report, allowed_names=None):
    allowed = {str(name or "").strip().lower() for name in (allowed_names or []) if str(name or "").strip()}
    checks = []
    for item in list((report or {}).get("checks") or []):
        if not isinstance(item, dict):
            continue
        if allowed and str(item.get("name") or "").strip().lower() not in allowed:
            continue
        checks.append(dict(item))

    if any(item.get("status") == "missing" for item in checks):
        status = "not_ready"
    elif any(item.get("status") == "warning" for item in checks):
        status = "ready_with_warnings"
    else:
        status = "ready"

    return {
        "status": status,
        "checks": checks,
    }


def _collect_local_repair_doctor_report():
    report = local_menu_tools.collect_framework_doctor_report()
    return _filter_doctor_report(
        report,
        allowed_names=("kubectl", "minikube", "hosts file", "minikube tunnel"),
    )


def _doctor_check(report, name):
    normalized_name = str(name or "").strip().lower()
    for item in list((report or {}).get("checks") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip().lower() == normalized_name:
            return item
    return None


def _build_local_repair_next_step(
    *,
    topology="local",
    missing_hostnames=None,
    hosts_sync=None,
    doctor_report=None,
    connector_recovery=None,
    public_endpoint_preflight=None,
    apply_hosts=True,
    recover_connectors=False,
):
    missing = [str(hostname or "").strip() for hostname in (missing_hostnames or []) if str(hostname or "").strip()]
    sync = hosts_sync if isinstance(hosts_sync, dict) else {}
    connector = connector_recovery if isinstance(connector_recovery, dict) else {}
    endpoint_preflight = (
        public_endpoint_preflight
        if isinstance(public_endpoint_preflight, dict)
        else {}
    )

    if missing:
        if not apply_hosts:
            return "Run local-repair again with hosts reconciliation enabled, or use H before retrying the next level."
        if sync.get("reason") == "hosts-file-unavailable":
            return "Set PIONERA_HOSTS_FILE to a writable hosts file path and rerun local-repair."
        if sync.get("status") == "failed":
            return "Rerun local-repair with permissions to update the hosts file, or apply H manually and retry."
        return "Review the reported hostnames, reconcile the hosts file, and rerun local-repair."

    tunnel_check = _doctor_check(doctor_report, "minikube tunnel")
    if (
        normalize_topology(topology) == LOCAL_TOPOLOGY
        and isinstance(tunnel_check, dict)
        and str(tunnel_check.get("status") or "").strip().lower() != "ok"
    ):
        return "Start minikube tunnel in another terminal and rerun local-repair or the next validation level."

    if str(connector.get("status") or "").strip().lower() == "failed":
        return "Inspect connector rollout status and rerun local-repair with connector recovery enabled."

    if str(endpoint_preflight.get("status") or "").strip().lower() == "failed":
        if not recover_connectors:
            return (
                "Public ingress endpoints are still unreachable. "
                "If connector runtimes remained deployed after a local or WSL restart, rerun local-repair with connector recovery enabled."
            )
        return (
            "Public ingress endpoints are still unreachable. "
            "Review the affected services, then rerun local-repair after they are healthy."
        )

    if str(connector.get("status") or "").strip().lower() == "skipped":
        return "Run the next pending level. If connector runtimes stayed deployed after a WSL restart, rerun local-repair with connector recovery enabled."

    return "Run the next pending level, or go straight to Level 6 if deployment levels 1-5 are already complete."


def run_local_repair(
    adapter,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    levels=None,
    apply_hosts=True,
    recover_connectors=False,
):
    """Diagnose and repair local access prerequisites before validation levels."""
    normalized_topology = normalize_topology(topology)
    if normalized_topology not in {LOCAL_TOPOLOGY, "vm-single"}:
        return {
            "status": "skipped",
            "scope": "local repair",
            "adapter": deployer_name or _infer_deployer_name_from_adapter(adapter),
            "topology": topology,
            "next_step": "local-repair only applies to local and vm-single topologies.",
        }

    selected_levels = _local_repair_levels(levels)
    resolved_deployer_name, context = _resolve_deployer_context(
        adapter,
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    doctor_report = _collect_local_repair_doctor_report()
    readiness = _build_hosts_readiness_plan(context, levels=selected_levels)
    hosts_sync = {
        "status": "skipped",
        "reason": "not-requested" if not apply_hosts else "already-ready",
    }

    if apply_hosts:
        hosts_file = readiness.get("hosts_file")
        if not hosts_file:
            hosts_sync = {
                "status": "failed",
                "reason": "hosts-file-unavailable",
            }
        else:
            try:
                with _temporary_environment(
                    {
                        "PIONERA_SYNC_HOSTS": "true",
                        "PIONERA_HOSTS_FILE": hosts_file,
                    }
                ):
                    hosts_result = run_hosts(
                        adapter,
                        deployer_name=resolved_deployer_name,
                        deployer_registry=deployer_registry,
                        topology=topology,
                    )
                hosts_sync = dict(hosts_result.get("hosts_sync") or {})
            except Exception as exc:
                hosts_sync = {
                    "status": "failed",
                    "reason": "repair-error",
                    "error": str(exc),
                }

    refreshed = _build_hosts_readiness_plan(
        context,
        levels=selected_levels,
        hosts_file=readiness.get("hosts_file"),
    )
    connector_recovery = {
        "status": "skipped",
        "reason": "not-requested",
    }
    if recover_connectors:
        recovered = bool(local_menu_tools.run_connector_recovery_after_wsl_restart(adapter=adapter))
        connector_recovery = {
            "status": "completed" if recovered else "failed",
        }

    missing_hostnames = list(refreshed.get("missing_hostnames") or [])
    public_endpoint_preflight = {
        "status": "skipped",
        "reason": "missing-hostnames" if missing_hostnames else "connector-recovery-failed",
    }
    if not missing_hostnames and str(connector_recovery.get("status") or "").strip().lower() != "failed":
        connector_names = list(getattr(context, "connectors", []) or []) if recover_connectors else []
        try:
            public_endpoint_preflight = _run_local_repair_public_endpoint_preflight(
                adapter,
                context,
                connectors=connector_names,
            )
        except Exception as exc:
            public_endpoint_preflight = {
                "status": "failed",
                "error": str(exc),
            }

    status = "completed"
    if missing_hostnames or str(hosts_sync.get("status") or "").strip().lower() == "failed":
        status = "failed"
    elif str(public_endpoint_preflight.get("status") or "").strip().lower() == "failed":
        status = "failed"
    elif str(connector_recovery.get("status") or "").strip().lower() == "failed":
        status = "warning"
    elif str((doctor_report or {}).get("status") or "").strip().lower() != "ready":
        status = "warning"

    next_step = _build_local_repair_next_step(
        topology=topology,
        missing_hostnames=missing_hostnames,
        hosts_sync=hosts_sync,
        doctor_report=doctor_report,
        connector_recovery=connector_recovery,
        public_endpoint_preflight=public_endpoint_preflight,
        apply_hosts=apply_hosts,
        recover_connectors=recover_connectors,
    )

    return {
        "status": status,
        "scope": "local repair",
        "adapter": resolved_deployer_name,
        "topology": topology,
        "dataspace": getattr(context, "dataspace_name", None),
        "config_migration_warnings": _infrastructure_config_migration_warnings(),
        "doctor": doctor_report,
        "hosts_plan": refreshed.get("hosts_plan") or _build_shadow_host_sync_plan(context),
        "hosts_sync": hosts_sync,
        "missing_hostnames": missing_hostnames,
        "connector_recovery": connector_recovery,
        "public_endpoint_preflight": public_endpoint_preflight,
        "next_step": next_step,
    }


def _humanize_url_label(label):
    normalized = str(label or "").strip().replace("_", " ").replace("-", " ")
    normalized = " ".join(token for token in normalized.split() if token)
    return normalized.title() if normalized else "Url"


def _flatten_url_map(urls, prefix=None):
    flattened = []
    if not isinstance(urls, dict):
        return flattened

    for key, value in urls.items():
        if value in (None, "", [], {}):
            continue

        label = _humanize_url_label(key)
        if prefix:
            label = f"{prefix} {label}"

        if isinstance(value, dict):
            flattened.extend(_flatten_url_map(value, prefix=label))
            continue

        flattened.append((label, str(value)))

    return flattened


def _collect_url_hostnames(urls):
    hostnames = []
    seen = set()
    for _label, value in _flatten_url_map(urls):
        parsed = urllib.parse.urlparse(str(value or ""))
        hostname = str(parsed.hostname or "").strip()
        if hostname and hostname not in seen:
            seen.add(hostname)
            hostnames.append(hostname)
    return hostnames


def _collect_browser_urls(urls):
    browser_urls = []
    seen = set()
    for _label, value in _flatten_url_map(urls):
        text = str(value or "").strip()
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme in {"http", "https"} and parsed.netloc and text not in seen:
            seen.add(text)
            browser_urls.append(text)
    return browser_urls


def _detect_vm_access_ip(minikube_ip=None):
    minikube_prefix = ""
    if minikube_ip and "." in minikube_ip:
        minikube_prefix = ".".join(str(minikube_ip).split(".")[:3]) + "."

    candidates = []
    for token in _command_stdout(["hostname", "-I"]).split():
        candidate = _normalized_topology_address(token)
        if not candidate or candidate.startswith("127."):
            continue
        if candidate.startswith("172.17."):
            continue
        if minikube_prefix and candidate.startswith(minikube_prefix):
            continue
        candidates.append(candidate)

    if candidates:
        return candidates[0]
    for token in _command_stdout(["hostname", "-I"]).split():
        candidate = _normalized_topology_address(token)
        if candidate and not candidate.startswith("127."):
            return candidate
    return ""


def _build_vm_single_local_browser_access(urls):
    hostnames = _collect_url_hostnames(urls)
    browser_urls = _collect_browser_urls(urls)
    if not hostnames and not browser_urls:
        return {}

    minikube_ip = _normalized_topology_address(_command_stdout(["minikube", "ip"]))
    vm_ip = _detect_vm_access_ip(minikube_ip=minikube_ip)
    ssh_user = os.getenv("USER") or getpass.getuser()
    tunnel_target = minikube_ip or "<minikube-ip>"
    vm_target = vm_ip or "<vm-ip>"
    ssh_target = f"{ssh_user}@{vm_target}" if ssh_user else f"<user>@{vm_target}"

    return {
        "strategy": "ssh-tunnel",
        "vm_ip": vm_ip,
        "minikube_ip": minikube_ip,
        "ssh_user": ssh_user,
        "ssh_target": ssh_target,
        "tunnel_command_80": f"sudo ssh -N -L 127.0.0.1:80:{tunnel_target}:80 {ssh_target}",
        "tunnel_command_8080": f"ssh -N -L 127.0.0.1:8080:{tunnel_target}:80 {ssh_target}",
        "hosts_entries": [f"127.0.0.1 {hostname}" for hostname in hostnames],
        "browser_urls": browser_urls,
    }


def _append_local_browser_access_lines(lines, access):
    if not isinstance(access, dict) or not access:
        return

    lines.append("Local Browser Access:")
    if access.get("vm_ip"):
        lines.append(f"- VM IP: {access['vm_ip']}")
    if access.get("minikube_ip"):
        lines.append(f"- Minikube IP: {access['minikube_ip']}")
    if access.get("ssh_user"):
        lines.append(f"- SSH user: {access['ssh_user']}")

    command_80 = access.get("tunnel_command_80")
    command_8080 = access.get("tunnel_command_8080")
    if command_80:
        lines.append("- SSH tunnel for local port 80:")
        lines.append(f"  {command_80}")
    if command_8080:
        lines.append("- SSH tunnel without sudo:")
        lines.append(f"  {command_8080}")

    hosts_entries = [str(value or "").strip() for value in access.get("hosts_entries") or [] if str(value or "").strip()]
    if hosts_entries:
        lines.append("- Local hosts entries:")
        for entry in hosts_entries:
            lines.append(f"  {entry}")

    browser_urls = [str(value or "").strip() for value in access.get("browser_urls") or [] if str(value or "").strip()]
    if browser_urls:
        lines.append("- Browser URLs:")
        for url in browser_urls:
            lines.append(f"  {url}")
        lines.append("  If you use the 8080 tunnel, add :8080 to the hostname in these URLs.")


def _append_url_lines(lines, urls, heading="URLs", multiline=False):
    flattened = _flatten_url_map(urls)
    if not flattened:
        return

    lines.append(f"{heading}:")
    for label, value in flattened:
        if multiline:
            lines.append(f"- {label}:")
            lines.append(f"  {value}")
        else:
            lines.append(f"- {label}: {value}")


def _append_hosts_level_lines(lines, label, hostnames):
    values = [str(value or "").strip() for value in (hostnames or []) if str(value or "").strip()]
    if not values:
        return

    lines.append(f"{label}: {len(values)}")
    for value in values:
        lines.append(f"- {value}")


def _append_component_list_lines(lines, label, values):
    normalized = [str(value or "").strip() for value in (values or []) if str(value or "").strip()]
    if not normalized:
        return

    lines.append(f"{label}: {len(normalized)}")
    for value in normalized:
        lines.append(f"- {value}")


def _humanize_hosts_sync_reason(reason):
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return ""

    labels = {
        "already-ready": "already ready",
        "disabled": "disabled by configuration",
        "missing-deployer-context": "missing deployer context",
        "not-requested": "not requested",
        "repair-error": "repair error",
    }
    return labels.get(normalized, normalized.replace("-", " "))


def _doctor_result_label(status):
    normalized = str(status or "").strip().lower()
    if normalized in {"ready", "completed", "updated", "unchanged"}:
        return "Succeeded"
    if normalized == "ready_with_warnings":
        return "Warning"
    if normalized == "not_ready":
        return "Failed"
    return str(status or "Unknown").strip().title() or "Unknown"


def _humanize_public_endpoint_reason(reason):
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return ""

    labels = {
        "missing-hostnames": "waiting for hosts reconciliation",
        "connector-recovery-failed": "connector recovery failed",
        "disabled": "disabled",
        "missing-deployer-context": "missing deployer context",
        "no-public-endpoints": "no public endpoints",
    }
    return labels.get(normalized, normalized.replace("-", " "))


def _hosts_plan_hostnames(plan):
    if not isinstance(plan, dict):
        return []

    values = []
    for key in ("level_1_2", "level_3", "level_4", "level_5"):
        values.extend(plan.get(key) or [])
    return _dedupe_ordered(values)


def _level2_access_urls(urls):
    if not isinstance(urls, dict):
        return {}

    level_urls = {}
    keycloak_realm = str(urls.get("keycloak_realm") or "").strip()
    if keycloak_realm:
        parsed = urllib.parse.urlparse(keycloak_realm)
        if parsed.scheme and parsed.netloc:
            level_urls["keycloak"] = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

    keycloak_admin_console = str(urls.get("keycloak_admin_console") or "").strip()
    if keycloak_admin_console:
        parsed = urllib.parse.urlparse(keycloak_admin_console)
        if parsed.scheme and parsed.netloc:
            level_urls["keycloak_admin_console"] = urllib.parse.urlunparse(
                (parsed.scheme, parsed.netloc, "/admin/", "", "", "")
            )

    minio_console = str(urls.get("minio_console") or "").strip()
    if minio_console:
        level_urls["minio_console"] = minio_console

    minio_api = str(urls.get("minio_api") or "").strip()
    if minio_api:
        level_urls["minio_api"] = minio_api

    return level_urls


def _select_level_access_urls(level_id, urls):
    if not isinstance(urls, dict) or not urls:
        return {}

    if level_id == 2:
        return _level2_access_urls(urls)

    if level_id == 3:
        selected = {}
        for key in ("public_portal_login", "public_portal_backend_admin", "registration_service"):
            value = urls.get(key)
            if value:
                selected[key] = value
        return selected

    if level_id == 4:
        connectors = urls.get("connectors")
        return {"connectors": connectors} if isinstance(connectors, dict) and connectors else {}

    if level_id == 5:
        components = urls.get("components")
        return {"components": components} if isinstance(components, dict) and components else {}

    return {}


def _resolve_level_access_urls(adapter, level_id, deployer_name=None, deployer_registry=None, topology="local"):
    if int(level_id) not in {2, 3, 4, 5}:
        return {}

    try:
        available = run_available_access_urls(
            adapter,
            deployer_name=deployer_name,
            deployer_registry=deployer_registry,
            topology=topology,
        )
    except Exception:
        return {}

    return _select_level_access_urls(level_id, available.get("urls"))


def run_available_access_urls(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    """Resolve access URLs already implied by the current adapter configuration."""
    resolved_deployer_name, context = _resolve_deployer_context(
        adapter,
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )

    config = dict(getattr(context, "config", {}) or {})
    dataspace_name = str(getattr(context, "dataspace_name", "") or "").strip()
    environment = str(getattr(context, "environment", "DEV") or "DEV").strip()
    connectors = list(getattr(context, "connectors", []) or [])
    components = list(getattr(context, "components", []) or [])
    urls = {}

    if resolved_deployer_name == "inesdata":
        from deployers.inesdata.access_urls import (
            build_connector_access_urls as build_inesdata_connector_access_urls,
            build_dataspace_access_urls,
        )

        dataspace_urls = build_dataspace_access_urls(dataspace_name, environment, config)
        for key in (
            "public_portal_login",
            "public_portal_backend_admin",
            "registration_service",
            "keycloak_realm",
            "keycloak_account",
            "keycloak_admin_console",
            "minio_api",
            "minio_console",
        ):
            value = dataspace_urls.get(key)
            if value:
                urls[key] = value

        connector_urls = {}
        for connector in connectors:
            access_urls = build_inesdata_connector_access_urls(
                connector,
                dataspace_name,
                environment,
                config,
            )
            selected = {}
            for key in (
                "connector_ingress",
                "connector_interface_login",
                "connector_management_api",
                "connector_protocol_api",
                "connector_shared_api",
                "minio_bucket",
            ):
                value = access_urls.get(key)
                if value:
                    selected[key] = value
            if selected:
                connector_urls[connector] = selected
        if connector_urls:
            urls["connectors"] = connector_urls

        infer_component_urls = _resolve_adapter_callable(adapter, "components.infer_component_urls")
        if callable(infer_component_urls) and components:
            component_urls = infer_component_urls(components)
            if component_urls:
                urls["components"] = component_urls

    else:
        from deployers.edc.bootstrap import (
            access_protocol as edc_access_protocol,
            build_connector_access_urls as build_edc_connector_access_urls,
            common_access_urls as build_edc_common_access_urls,
            dataspace_domain_base as edc_dataspace_domain_base,
        )

        common_urls = build_edc_common_access_urls(config, dataspace_name, environment)
        for key in (
            "keycloak_realm",
            "keycloak_account",
            "keycloak_admin_console",
            "minio_api",
            "minio_console",
        ):
            value = common_urls.get(key)
            if value:
                urls[key] = value

        protocol = edc_access_protocol(environment)
        dataspace_domain = edc_dataspace_domain_base(config, environment)
        if dataspace_name and dataspace_domain:
            urls["registration_service"] = f"{protocol}://registration-service-{dataspace_name}.{dataspace_domain}"

        connector_urls = {}
        for connector in connectors:
            access_urls = build_edc_connector_access_urls(
                config,
                connector,
                dataspace_name,
                environment,
            )
            selected = {}
            for key in (
                "connector_ingress",
                "connector_management_api_v3",
                "connector_protocol_api",
                "connector_default_api",
                "connector_control_api",
                "edc_dashboard_login",
                "edc_dashboard_oidc_login",
                "minio_bucket",
            ):
                value = access_urls.get(key)
                if value:
                    selected[key] = value
            if selected:
                connector_urls[connector] = selected
        if connector_urls:
            urls["connectors"] = connector_urls

    result = {
        "status": "available",
        "adapter": resolved_deployer_name,
        "topology": topology,
        "dataspace": dataspace_name or None,
        "access_urls_view": True,
        "urls": urls,
    }
    if normalize_topology(topology) == "vm-single":
        local_browser_access = _build_vm_single_local_browser_access(urls)
        if local_browser_access:
            result["local_browser_access"] = local_browser_access
    return result


def _build_recreate_dataspace_plan(adapter, context):
    plan_getter = _resolve_adapter_callable(
        adapter,
        "build_recreate_dataspace_plan",
        "deployment.build_recreate_dataspace_plan",
    )
    adapter_plan = dict(plan_getter() or {}) if callable(plan_getter) else {}
    namespace_roles = getattr(context, "namespace_roles", None)
    namespace = getattr(namespace_roles, "registration_service_namespace", "") if namespace_roles else ""
    dataspace_name = getattr(context, "dataspace_name", "") or adapter_plan.get("dataspace")
    adapter_plan.setdefault("status", "planned")
    adapter_plan.setdefault("dataspace", dataspace_name)
    adapter_plan.setdefault("namespace", namespace or dataspace_name)
    adapter_plan.setdefault("runtime_dir", getattr(context, "runtime_dir", ""))
    adapter_plan.setdefault("preserves_shared_services", True)
    adapter_plan.setdefault("invalidates_level_4_connectors", True)
    adapter_plan.setdefault(
        "actions",
        [
            "uninstall_dataspace_helm_releases",
            "delete_dataspace_namespace",
            "delete_dataspace_bootstrap_state",
            "remove_generated_runtime_artifacts",
            "run_level_3_again",
        ],
    )
    adapter_plan["deployer_context"] = _sanitize_preview_data(context.as_dict())
    return adapter_plan


def run_recreate_dataspace(
    adapter,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    confirm_dataspace=None,
    with_connectors=False,
):
    """Recreate only the selected dataspace after exact-name confirmation."""
    resolved_deployer_name, context = _resolve_deployer_context(
        adapter,
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    plan = _build_recreate_dataspace_plan(adapter, context)
    dataspace_name = str(plan.get("dataspace") or "").strip()
    confirmation = str(confirm_dataspace or os.getenv("PIONERA_RECREATE_DATASPACE_CONFIRM") or "").strip()
    if confirmation != dataspace_name:
        raise RuntimeError(
            "Dataspace recreation is destructive and requires exact confirmation. "
            f"Provide --confirm-dataspace {dataspace_name}."
        )

    recreate = _resolve_adapter_callable(adapter, "recreate_dataspace", "deployment.recreate_dataspace")
    if not callable(recreate):
        raise RuntimeError(f"Adapter '{resolved_deployer_name}' does not expose recreate_dataspace()")

    with _temporary_adapter_auto_mode(adapter, enabled=True):
        result = recreate(confirm_dataspace=confirmation)
        connector_result = None
        next_step = "Run Level 4 again for this adapter because recreated Level 3 invalidates existing connectors."

        if with_connectors:
            try:
                connector_result = run_level(
                    adapter,
                    4,
                    deployer_name=resolved_deployer_name,
                    deployer_registry=deployer_registry,
                    topology=topology,
                )
                next_step = "Run Level 6 to validate the recreated dataspace and connectors."
            except Exception as exc:
                raise RuntimeError(
                    "Dataspace was recreated, but automatic Level 4 connector recreation failed. "
                    "Fix the Level 4 issue and run Level 4 manually for this adapter."
                ) from exc

    return {
        "status": "completed",
        "deployer_name": resolved_deployer_name,
        "topology": topology,
        "dataspace": dataspace_name,
        "config_migration_warnings": _infrastructure_config_migration_warnings(),
        "plan": plan,
        "result": result,
        "with_connectors": bool(with_connectors),
        "connectors": connector_result,
        "next_step": next_step,
    }


def run_deploy(adapter, deployer_name=None, deployer_registry=None, topology="local"):
    """Deploy infrastructure and connectors using the selected adapter."""
    if _should_use_deployer_deploy() or str(topology or "local").strip().lower() != "local":
        if _should_execute_deployer_deploy(deployer_name=deployer_name, topology=topology):
            return _execute_deployer_deploy(
                adapter,
                deployer_name=deployer_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
        return _build_deployer_deploy_shadow_plan(
            adapter,
            deployer_name=deployer_name,
            deployer_registry=deployer_registry,
            topology=topology,
        )

    deploy_infrastructure = _resolve_adapter_callable(adapter, "deploy_infrastructure")
    if callable(deploy_infrastructure):
        deploy_infrastructure()

    deploy_dataspace = _resolve_adapter_callable(adapter, "deploy_dataspace")
    if callable(deploy_dataspace):
        deploy_dataspace()

    deploy_connectors = _resolve_adapter_callable(adapter, "deploy_connectors")
    if not callable(deploy_connectors):
        raise RuntimeError("Selected adapter does not support connector deployment")

    return deploy_connectors()


def run_validate(
    adapter,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    experiment_storage=ExperimentStorage,
    experiment_dir=None,
    save_metadata=True,
    baseline=False,
    force_playwright=False,
    kafka_edc_validation_suite_cls=KafkaEdcValidationSuite,
    kafka_manager_cls=KafkaManager,
    validation_mode=None,
):
    """Run validation collections with the selected adapter."""
    validation_mode_info = _resolve_level6_validation_mode(validation_mode, topology=topology)
    validation_runtime = _resolve_validation_runtime(
        adapter,
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    connectors = validation_runtime["connectors"]
    validation_profile = validation_runtime["validation_profile"]
    deployer_context = validation_runtime["deployer_context"]
    resolved_deployer_name = validation_runtime.get("deployer_name") or deployer_name
    hosts_sync = (
        _sync_deployer_hosts_if_enabled(deployer_context)
        if deployer_context is not None
        else {"status": "skipped", "reason": "missing-deployer-context"}
    )
    experiment_dir = experiment_dir or experiment_storage.create_experiment_directory()
    if save_metadata:
        _save_experiment_metadata(
            experiment_storage,
            experiment_dir,
            connectors,
            **_experiment_metadata_context(
                adapter_name=resolved_deployer_name,
                topology=topology,
                adapter=type(adapter).__name__,
                baseline=baseline,
            ),
        )
    experiment_storage.newman_reports_dir(experiment_dir)
    local_capacity_preflight = _run_level6_local_capacity_preflight(
        validation_mode_info,
        resolved_deployer_name,
        deployer_context,
        experiment_dir,
        validation_profile=validation_profile,
    )
    local_stability_preflight = _run_level6_local_stability_preflight(
        validation_mode_info,
        resolved_deployer_name,
        deployer_context,
        experiment_dir,
        validation_profile=validation_profile,
    )
    local_stability_postflight = None
    kafka_preparation = _start_level6_kafka_preparation(
        adapter,
        connectors,
        validation_profile=validation_profile,
        deployer_name=resolved_deployer_name,
        kafka_manager_cls=kafka_manager_cls,
        background=not validation_mode_info["local_stable"],
    )
    public_endpoint_preflight = _ensure_level6_public_endpoint_access(
        adapter,
        connectors,
        deployer_context,
    )
    test_data_cleanup = _run_test_data_cleanup_if_enabled(
        adapter,
        connectors,
        deployer_context,
        experiment_dir,
        validation_profile=validation_profile,
    )

    validation_engine = build_validation_engine(adapter, engine_cls=validation_engine_cls)
    run_method = validation_engine.run

    try:
        parameters = inspect.signature(run_method).parameters
    except (TypeError, ValueError):
        parameters = {}

    metrics_collector = build_metrics_collector(
        adapter,
        collector_cls=MetricsCollector,
        experiment_storage=experiment_storage,
    )
    validation_result = None
    validation_error = None

    try:
        if "experiment_dir" in parameters:
            validation_result = run_method(connectors, experiment_dir=experiment_dir)
        else:
            validation_result = run_method(connectors)
    except Exception as exc:
        validation_error = exc

    newman_request_metrics = None
    try:
        collect_newman_metrics = getattr(metrics_collector, "collect_experiment_newman_metrics", None)
        if callable(collect_newman_metrics):
            newman_request_metrics = collect_newman_metrics(experiment_dir)
        else:
            newman_request_metrics = metrics_collector.collect_newman_request_metrics(
                experiment_storage.newman_reports_dir(experiment_dir),
                experiment_dir=experiment_dir,
            )
    except Exception:
        if validation_error is None:
            raise
        print("[WARNING] Newman metrics collection failed after validation error")
        newman_request_metrics = []

    if validation_error is not None:
        _finalize_level6_kafka_preparation(
            kafka_preparation,
            experiment_dir,
            cleanup=True,
        )
        local_stability_postflight = _run_level6_local_stability_postflight(
            validation_mode_info,
            resolved_deployer_name,
            deployer_context,
            experiment_dir,
            local_stability_preflight,
            validation_profile=validation_profile,
        )
        raise validation_error

    kafka_edc_results = run_level6_kafka_edc_after_newman(
        adapter,
        connectors,
        experiment_dir,
        validation_profile=validation_profile,
        deployer_name=resolved_deployer_name,
        experiment_storage=experiment_storage,
        suite_cls=kafka_edc_validation_suite_cls,
        kafka_manager_cls=kafka_manager_cls,
        kafka_preparation=kafka_preparation,
    )

    playwright_result = None
    playwright_failure = None
    component_results = []
    component_validation_summary = None
    if validation_profile is not None:
        if not getattr(validation_profile, "playwright_enabled", False):
            playwright_result = {
                "status": "skipped",
                "reason": "disabled-in-profile",
            }
        elif deployer_context is None:
            playwright_result = {
                "status": "skipped",
                "reason": "missing-deployer-context",
            }
        elif not _should_run_deployer_playwright(force=force_playwright, validation_profile=validation_profile):
            playwright_result = {
                "status": "skipped",
                "reason": "disabled",
            }
        else:
            adapter_name = getattr(validation_profile, "adapter", "").strip().lower()
            is_edc_playwright = adapter_name == "edc"
            is_inesdata_playwright = adapter_name == "inesdata"
            dashboard_runtime_present = _edc_dashboard_runtime_present(deployer_context) if is_edc_playwright else False
            if (
                is_edc_playwright
                and not (
                    _mapping_flag(getattr(deployer_context, "config", {}), "EDC_DASHBOARD_ENABLED", default=False)
                    or dashboard_runtime_present
                )
            ):
                raise RuntimeError(
                    "Playwright validation for 'edc' requires EDC_DASHBOARD_ENABLED=true and a deployed dashboard runtime"
                )
            edc_dashboard_auth_mode = str(
                getattr(deployer_context, "config", {}).get(
                    "EDC_DASHBOARD_PROXY_AUTH_MODE",
                    "",
                )
            ).strip().lower()
            if (
                is_edc_playwright
                and edc_dashboard_auth_mode != "oidc-bff"
            ):
                runtime_auth_mode = _edc_dashboard_runtime_auth_mode(deployer_context)
                if runtime_auth_mode:
                    edc_dashboard_auth_mode = runtime_auth_mode
                if edc_dashboard_auth_mode != "oidc-bff":
                    raise RuntimeError(
                        "Playwright validation for 'edc' requires EDC_DASHBOARD_PROXY_AUTH_MODE=oidc-bff"
                    )
            if not getattr(validation_profile, "playwright_config", None):
                raise RuntimeError(
                    "Validation profile enables Playwright but does not define a playwright_config"
                )
            if is_edc_playwright:
                readiness = _wait_for_edc_dashboard_readiness(
                    deployer_context,
                    experiment_dir=experiment_dir,
                )
                if readiness.get("status") != "passed":
                    raise RuntimeError(_edc_dashboard_readiness_failure_message(readiness))
            elif is_inesdata_playwright:
                readiness = _wait_for_inesdata_portal_readiness(
                    deployer_context,
                    experiment_dir=experiment_dir,
                )
                if readiness.get("status") != "passed":
                    raise RuntimeError(_inesdata_portal_readiness_failure_message(readiness))
            playwright_result = run_playwright_validation(
                profile=validation_profile,
                context=deployer_context,
                experiment_dir=experiment_dir,
            )
            if playwright_result.get("status") != "passed":
                playwright_failure = playwright_result.get("status")

        component_groups = list(getattr(validation_profile, "component_groups", []) or [])
        infer_component_urls = _resolve_adapter_callable(adapter, "components.infer_component_urls")
        if getattr(validation_profile, "component_validation_enabled", False):
            if deployer_context is None:
                component_results = [
                    {
                        "component": component,
                        "status": "skipped",
                        "reason": "missing-deployer-context",
                    }
                    for component in component_groups
                ]
            elif not callable(infer_component_urls):
                component_results = [
                    {
                        "component": component,
                        "status": "skipped",
                        "reason": "component_url_inference_unavailable",
                    }
                    for component in component_groups
                ]
            elif not should_run_level6_component_validation(
                component_groups,
                env=os.environ,
                env_flag_enabled=_env_flag,
            ):
                component_results = [
                    {
                        "component": component,
                        "status": "skipped",
                        "reason": "disabled",
                    }
                    for component in component_groups
                ]
            else:
                print("\nRunning component validation suite...")
                try:
                    component_results = run_level6_component_validations(
                        component_groups,
                        infer_component_urls=infer_component_urls,
                        run_component_validations_fn=run_registered_component_validations,
                        experiment_dir=experiment_dir,
                    ) or []
                except Exception as exc:
                    component_results = [
                        {
                            "component": "_component-validation",
                            "status": "failed",
                            "error": {
                                "type": type(exc).__name__,
                                "message": str(exc),
                            },
                        }
                    ]

                for result in component_results:
                    component = result.get("component", "unknown-component")
                    status = result.get("status", "unknown")
                    if status == "passed":
                        print(f"  Component validation passed for {component}")
                    elif status == "failed":
                        print(f"  Warning: component validation failed for {component}")
                    else:
                        reason = result.get("reason") or (result.get("error") or {}).get("message", "unknown reason")
                        print(f"  Component validation skipped for {component} ({reason})")
            if component_results:
                component_validation_summary = summarize_component_results(component_results)
            if playwright_failure is not None:
                local_stability_postflight = _run_level6_local_stability_postflight(
                    validation_mode_info,
                    resolved_deployer_name,
                    deployer_context,
                    experiment_dir,
                    local_stability_preflight,
                    validation_profile=validation_profile,
                )
                raise RuntimeError(
                    f"Playwright validation failed with status '{playwright_failure}'"
                )

    local_stability_postflight = _run_level6_local_stability_postflight(
        validation_mode_info,
        resolved_deployer_name,
        deployer_context,
        experiment_dir,
        local_stability_preflight,
        validation_profile=validation_profile,
    )

    return {
        "experiment_dir": experiment_dir,
        "validation": validation_result,
        "newman_request_metrics": newman_request_metrics,
        "kafka_edc_results": kafka_edc_results,
        "storage_checks": list(getattr(validation_engine, "last_storage_checks", []) or []),
        "playwright": playwright_result,
        "component_results": component_results,
        "component_validation_summary": component_validation_summary,
        "test_data_cleanup": test_data_cleanup,
        "public_endpoint_preflight": public_endpoint_preflight,
        "hosts_sync": hosts_sync,
        "local_capacity": {
            "preflight": local_capacity_preflight,
        },
        "local_stability": {
            "preflight": local_stability_preflight,
            "postflight": local_stability_postflight,
        },
        "validation_mode": validation_mode_info,
        "validation_profile": (
            validation_profile.as_dict()
            if validation_profile is not None
            else None
        ),
        "deployer_context": (
            _sanitize_preview_data(deployer_context.as_dict())
            if deployer_context is not None
            else None
        ),
    }


def run_metrics(
    adapter,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    experiment_dir=None,
    save_metadata=True,
    kafka_enabled=False,
    kafka_runtime_config=None,
    kafka_manager_cls=KafkaManager,
    baseline=False,
):
    """Run metrics collection with the selected adapter."""
    metrics_runtime = _resolve_metrics_runtime(
        adapter,
        deployer_name=deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    connectors = metrics_runtime["connectors"]
    hosts_sync = (
        _sync_deployer_hosts_if_enabled(metrics_runtime["deployer_context"])
        if metrics_runtime["deployer_context"] is not None
        else {"status": "skipped", "reason": "missing-deployer-context"}
    )
    metrics_collector = build_metrics_collector(
        adapter,
        collector_cls=metrics_collector_cls,
        experiment_storage=experiment_storage,
        kafka_enabled=kafka_enabled,
        kafka_runtime_config=kafka_runtime_config,
    )
    kafka_manager = None
    if kafka_enabled:
        kafka_manager = build_kafka_manager(
            adapter,
            manager_cls=kafka_manager_cls,
            kafka_runtime_config=kafka_runtime_config,
        )
    experiment_dir = experiment_dir or experiment_storage.create_experiment_directory()
    if save_metadata:
        _save_experiment_metadata(
            experiment_storage,
            experiment_dir,
            connectors,
            **_experiment_metadata_context(
                adapter_name=deployer_name or _infer_deployer_name_from_adapter(adapter),
                topology=topology,
                adapter=type(adapter).__name__,
                baseline=baseline,
            ),
        )
    metrics = metrics_collector.collect(connectors, experiment_dir=experiment_dir)
    sanitized_deployer_context = (
        _sanitize_preview_data(metrics_runtime["deployer_context"].as_dict())
        if metrics_runtime["deployer_context"] is not None
        else None
    )

    if isinstance(metrics, dict):
        metrics = dict(metrics)
        metrics.setdefault("deployer_context", sanitized_deployer_context)

    def _build_metrics_result(kafka_metrics_value=None):
        payload = {
            "experiment_dir": experiment_dir,
            "connectors": list(connectors),
            "metrics": metrics,
            "kafka_metrics": kafka_metrics_value,
            "deployer_context": sanitized_deployer_context,
            "hosts_sync": hosts_sync,
        }
        if isinstance(metrics, dict):
            payload.update(metrics)
            payload.setdefault("experiment_dir", experiment_dir)
            payload.setdefault("connectors", list(connectors))
            payload.setdefault("deployer_context", sanitized_deployer_context)
            payload.setdefault("hosts_sync", hosts_sync)
            payload["metrics"] = metrics
            payload["kafka_metrics"] = kafka_metrics_value
        return payload

    kafka_metrics = None
    if kafka_enabled:
        try:
            helper = getattr(metrics_collector, "run_kafka_benchmark_experiment", None)
            if callable(helper):
                kafka_metrics = helper(
                    experiment_dir,
                    iterations=1,
                    kafka_manager=kafka_manager,
                )
            else:
                kafka_runtime_overrides = None
                broker_source = None
                bootstrap_servers = kafka_manager.ensure_kafka_running() if kafka_manager is not None else None
                if kafka_manager is not None:
                    broker_source = "auto-provisioned" if getattr(kafka_manager, "started_by_framework", False) else "external"
                if bootstrap_servers:
                    kafka_runtime_overrides = {"bootstrap_servers": bootstrap_servers}
                    collect_kafka = metrics_collector.collect_kafka_benchmark
                    try:
                        parameters = inspect.signature(collect_kafka).parameters
                    except (TypeError, ValueError):
                        parameters = {}

                    kwargs = {"run_index": 1}
                    if "kafka_runtime_overrides" in parameters:
                        kwargs["kafka_runtime_overrides"] = kafka_runtime_overrides
                    kafka_metrics = collect_kafka(experiment_dir, **kwargs)
                    if isinstance(kafka_metrics, dict):
                        if broker_source is not None:
                            kafka_metrics.setdefault("broker_source", broker_source)
                        if bootstrap_servers is not None:
                            kafka_metrics.setdefault("bootstrap_servers", bootstrap_servers)
                        experiment_storage.save_kafka_metrics_json(kafka_metrics, experiment_dir)
                else:
                    reason = getattr(kafka_manager, "last_error", None) or "Kafka broker unavailable and auto-provisioning failed"
                    kafka_metrics = {
                        "kafka_benchmark": {
                            "status": "skipped",
                            "reason": reason,
                        }
                    }
                    if broker_source is not None:
                        kafka_metrics["broker_source"] = broker_source
                    experiment_storage.save_kafka_metrics_json(kafka_metrics, experiment_dir)

            if kafka_metrics is not None:
                return _build_metrics_result(kafka_metrics)
        finally:
            if kafka_manager is not None:
                kafka_manager.stop_kafka()

    return _build_metrics_result(kafka_metrics)


def _build_deployer_run_shadow_plan(
    adapter,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
):
    resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
    deploy_plan = _build_deployer_deploy_shadow_plan(
        adapter,
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    validation_runtime = _resolve_validation_runtime(
        adapter,
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    metrics_runtime = _resolve_metrics_runtime(
        adapter,
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )

    return {
        "mode": "shadow",
        "operation": "run",
        "status": "planned",
        "deployer_name": resolved_deployer_name,
        "topology": topology,
        "sequence": [
            "deploy",
            "validate",
            "metrics",
        ],
        "deploy": deploy_plan,
        "validate": {
            "connectors": list(validation_runtime["connectors"] or []),
            "validation_profile": (
                validation_runtime["validation_profile"].as_dict()
                if validation_runtime["validation_profile"] is not None
                else None
            ),
            "deployer_context": (
                _sanitize_preview_data(validation_runtime["deployer_context"].as_dict())
                if validation_runtime["deployer_context"] is not None
                else None
            ),
        },
        "metrics": {
            "connectors": list(metrics_runtime["connectors"] or []),
            "deployer_context": (
                _sanitize_preview_data(metrics_runtime["deployer_context"].as_dict())
                if metrics_runtime["deployer_context"] is not None
                else None
            ),
        },
    }


def run_run(
    adapter,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    kafka_enabled=False,
    kafka_runtime_config=None,
    kafka_manager_cls=KafkaManager,
    baseline=False,
    validation_mode=None,
):
    """Run the experimental deployer-backed deploy+validate+metrics chain."""
    resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
    if _should_execute_deployer_run(deployer_name=resolved_deployer_name, topology=topology):
        environment_overrides = {}
        if resolved_deployer_name == "edc" and os.getenv("PIONERA_EDC_DASHBOARD_ENABLED") is None:
            environment_overrides["PIONERA_EDC_DASHBOARD_ENABLED"] = "true"
        if (
            resolved_deployer_name == "edc"
            and not os.getenv("PIONERA_EDC_DASHBOARD_PROXY_AUTH_MODE")
        ):
            environment_overrides["PIONERA_EDC_DASHBOARD_PROXY_AUTH_MODE"] = "oidc-bff"

        with _temporary_environment(environment_overrides):
            deployment = _execute_deployer_deploy(
                adapter,
                deployer_name=resolved_deployer_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
            shared_experiment_dir = experiment_storage.create_experiment_directory()
            _save_experiment_metadata(
                experiment_storage,
                shared_experiment_dir,
                deployment["deployment"]["connectors"],
                **_experiment_metadata_context(
                    adapter_name=resolved_deployer_name,
                    topology=topology,
                    adapter=type(adapter).__name__,
                    baseline=baseline,
                ),
            )
            validation = run_validate(
                adapter,
                deployer_name=resolved_deployer_name,
                deployer_registry=deployer_registry,
                topology=topology,
                validation_engine_cls=validation_engine_cls,
                experiment_storage=experiment_storage,
                experiment_dir=shared_experiment_dir,
                save_metadata=False,
                baseline=baseline,
                validation_mode=validation_mode,
            )
            metrics = run_metrics(
                adapter,
                deployer_name=resolved_deployer_name,
                deployer_registry=deployer_registry,
                topology=topology,
                metrics_collector_cls=metrics_collector_cls,
                experiment_storage=experiment_storage,
                experiment_dir=shared_experiment_dir,
                save_metadata=False,
                kafka_enabled=kafka_enabled,
                kafka_runtime_config=kafka_runtime_config,
                kafka_manager_cls=kafka_manager_cls,
                baseline=baseline,
            )
        return {
            "mode": "execute",
            "operation": "run",
            "status": "completed",
            "deployer_name": resolved_deployer_name,
            "topology": topology,
            "experiment_dir": shared_experiment_dir,
            "sequence": [
                "deploy",
                "validate",
                "metrics",
            ],
            "namespace_roles": deployment["namespace_roles"],
            "deployer_context": deployment["deployer_context"],
            "hosts_sync": deployment.get("hosts_sync"),
            "deployment": deployment["deployment"],
            "validation": validation,
            "metrics": metrics,
            "validation_profile": deployment["validation_profile"],
        }

    return _build_deployer_run_shadow_plan(
        adapter,
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )


def _topology_runtime_environment_overrides(topology="local"):
    normalized_topology = normalize_topology(topology)
    if normalized_topology != "vm-single":
        return {}
    try:
        config = _load_effective_infrastructure_deployer_config(topology=normalized_topology)
        runtime = build_cluster_runtime(config, topology=normalized_topology)
    except Exception:
        return {}
    if runtime.get("cluster_type") != "k3s":
        return {}
    kubeconfig = str(runtime.get("k3s_kubeconfig") or "").strip()
    if not kubeconfig:
        return {}
    return {"KUBECONFIG": kubeconfig}


def run_level(
    adapter,
    level,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    baseline=False,
):
    """Run one numbered level using the selected adapter/deployer context."""
    try:
        level_id = int(level)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid level: {level}") from exc

    if level_id not in LEVEL_DESCRIPTIONS:
        supported = ", ".join(str(value) for value in sorted(LEVEL_DESCRIPTIONS))
        raise ValueError(f"Unsupported level '{level_id}'. Supported levels: {supported}")

    resolved_deployer_name = deployer_name or _infer_deployer_name_from_adapter(adapter)
    level_name = LEVEL_DESCRIPTIONS[level_id]
    normalized_topology = str(topology or "local").strip().lower()
    if os.environ.get("PIONERA_LEVEL_RUNTIME_ENV_ACTIVE") != "true":
        environment_overrides = _topology_runtime_environment_overrides(topology)
        if environment_overrides:
            environment_overrides["PIONERA_LEVEL_RUNTIME_ENV_ACTIVE"] = "true"
            with _temporary_environment(environment_overrides):
                return run_level(
                    adapter,
                    level_id,
                    deployer_name=resolved_deployer_name,
                    deployer_registry=deployer_registry,
                    topology=topology,
                    validation_engine_cls=validation_engine_cls,
                    metrics_collector_cls=metrics_collector_cls,
                    experiment_storage=experiment_storage,
                    baseline=baseline,
                )
    level_context = None
    level_local_capacity = None
    if normalized_topology != "local" and not (
        normalized_topology == "vm-single" and level_id in {1, 2, 3, 4, 5}
    ) and level_id in {1, 2, 3, 4, 5}:
        raise RuntimeError(
            f"Real Level {level_id} execution is not enabled for topology '{normalized_topology}' yet. "
            "Use the deployer dry-run/hosts plan first, then enable VM execution once the topology-specific "
            "deployment path is implemented."
        )

    if level_id == 1:
        if normalized_topology == "vm-single":
            setup_cluster_preflight = _resolve_adapter_callable(adapter, "infrastructure.setup_cluster_preflight")
            if not callable(setup_cluster_preflight):
                raise RuntimeError(
                    f"Adapter '{resolved_deployer_name}' does not expose Level 1 setup_cluster_preflight() "
                    f"for topology '{normalized_topology}'"
                )
            result = setup_cluster_preflight(topology=topology)
        else:
            setup_cluster = _resolve_adapter_callable(adapter, "setup_cluster")
            if not callable(setup_cluster):
                raise RuntimeError(f"Adapter '{resolved_deployer_name}' does not expose Level 1 setup_cluster()")
            result = setup_cluster()
    elif level_id == 2:
        if normalized_topology == "vm-single":
            deploy_infrastructure = _resolve_adapter_callable(
                adapter,
                "infrastructure.deploy_infrastructure_for_topology",
            )
            if not callable(deploy_infrastructure):
                raise RuntimeError(
                    f"Adapter '{resolved_deployer_name}' does not expose Level 2 "
                    f"deploy_infrastructure_for_topology() for topology '{normalized_topology}'"
                )
            result = deploy_infrastructure(topology=topology)
        else:
            deploy_infrastructure = _resolve_adapter_callable(adapter, "deploy_infrastructure")
            if not callable(deploy_infrastructure):
                raise RuntimeError(
                    f"Adapter '{resolved_deployer_name}' does not expose Level 2 deploy_infrastructure()"
                )
            result = deploy_infrastructure()
    elif level_id == 3:
        if normalized_topology == "vm-single":
            deploy_dataspace = _resolve_adapter_callable(
                adapter,
                "deployment.deploy_dataspace_for_topology",
            )
            if not callable(deploy_dataspace):
                raise RuntimeError(
                    f"Adapter '{resolved_deployer_name}' does not expose Level 3 "
                    f"deploy_dataspace_for_topology() for topology '{normalized_topology}'"
                )
            result = deploy_dataspace(topology=topology)
        else:
            level_local_capacity = _run_local_adapter_install_capacity_preflight(
                resolved_deployer_name,
                topology,
                level_id,
            )
            deploy_dataspace = _resolve_adapter_callable(adapter, "deploy_dataspace")
            if not callable(deploy_dataspace):
                raise RuntimeError(f"Adapter '{resolved_deployer_name}' does not expose Level 3 deploy_dataspace()")
            result = deploy_dataspace()
    elif level_id == 4:
        level_local_capacity = _run_local_adapter_install_capacity_preflight(
            resolved_deployer_name,
            topology,
            level_id,
        )
        if resolved_deployer_name == "edc":
            _ensure_safe_edc_deployer_execution(
                adapter,
                deployer_name=resolved_deployer_name,
                topology=topology,
            )
        deploy_connectors = _resolve_adapter_callable(adapter, "deploy_connectors")
        if not callable(deploy_connectors):
            raise RuntimeError(f"Adapter '{resolved_deployer_name}' does not expose Level 4 deploy_connectors()")
        result = deploy_connectors()
        if not result:
            raise RuntimeError(f"Level 4 finished without deployed connectors for adapter '{resolved_deployer_name}'")
    elif level_id == 5:
        orchestrator = build_deployer_orchestrator(
            deployer_name=resolved_deployer_name,
            deployer_registry=deployer_registry,
            adapter=adapter,
            topology=topology,
        )
        context = orchestrator.resolve_context(topology=topology)
        level_context = context
        level_local_capacity = _run_local_adapter_install_capacity_preflight(
            resolved_deployer_name,
            topology,
            level_id,
            deployer_context=context,
        )
        deploy_components = getattr(orchestrator.deployer, "deploy_components", None)
        if not callable(deploy_components):
            raise RuntimeError(f"Deployer '{resolved_deployer_name}' does not expose Level 5 deploy_components()")
        result = deploy_components(context)
    else:
        result = run_validate(
            adapter,
            deployer_name=resolved_deployer_name,
            deployer_registry=deployer_registry,
            topology=topology,
            validation_engine_cls=validation_engine_cls,
            experiment_storage=experiment_storage,
            baseline=baseline,
        )

    if level_id == 1:
        if normalized_topology == "vm-single":
            _synchronize_vm_single_addresses_after_level1()

    level_urls = _resolve_level_access_urls(
        adapter,
        level_id,
        deployer_name=resolved_deployer_name,
        deployer_registry=deployer_registry,
        topology=topology,
    )

    payload = {
        "level": level_id,
        "name": level_name,
        "status": "completed",
        "result": result,
    }
    if level_urls:
        payload["urls"] = level_urls
    if isinstance(level_local_capacity, dict):
        payload["local_capacity"] = {"install_preflight": level_local_capacity}
    payload.update(
        _safe_level_hosts_followup(
            adapter,
            level_id,
            deployer_name=resolved_deployer_name,
            deployer_registry=deployer_registry,
            topology=topology,
            context=level_context,
        )
    )
    return payload


def run_levels(
    adapter_name,
    levels=None,
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    baseline=False,
):
    """Run a sequence of numbered levels with one adapter instance."""
    selected_levels = [int(level) for level in (levels or sorted(LEVEL_DESCRIPTIONS))]
    adapter = build_adapter(
        adapter_name,
        adapter_registry=adapter_registry,
        dry_run=False,
        topology=topology,
    )

    completed = []
    for level_id in selected_levels:
        completed.append(
            run_level(
                adapter,
                level_id,
                deployer_name=adapter_name,
                deployer_registry=deployer_registry,
                topology=topology,
                validation_engine_cls=validation_engine_cls,
                metrics_collector_cls=metrics_collector_cls,
                experiment_storage=experiment_storage,
                baseline=baseline,
            )
        )

    return {
        "status": "completed",
        "adapter": adapter_name,
        "topology": topology,
        "levels": completed,
    }


def _interactive_read(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _interactive_confirm(prompt, default=False):
    default_label = "Y/n" if default else "y/N"
    answer = _interactive_read(f"{prompt} ({default_label}): ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "s", "si", "sí"}


def _shared_foundation_adapter_name(adapter_registry=None):
    registry = adapter_registry or ADAPTER_REGISTRY
    if not registry:
        raise RuntimeError("No adapters are registered.")
    if "inesdata" in registry:
        return "inesdata"
    return sorted(registry)[0]


def _interactive_require_adapter_selection(current_adapter, adapter_registry=None):
    registry = adapter_registry or ADAPTER_REGISTRY
    if current_adapter:
        return current_adapter
    if len(registry) == 1:
        return sorted(registry)[0]

    print()
    print("This action needs an adapter selection for Levels 3-6.")
    selected_adapter = _select_adapter_interactive(None, adapter_registry=registry)
    if not selected_adapter:
        print("Adapter-specific action cancelled.")
        return None

    _print_adapter_selection_hint(selected_adapter)
    return selected_adapter


def _run_interactive_level2_with_shared_foundation(
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    baseline=False,
):
    shared_adapter_name = _shared_foundation_adapter_name(adapter_registry=adapter_registry)
    execution_context = _interactive_execution_context(topology)
    adapter = build_adapter(
        shared_adapter_name,
        adapter_registry=adapter_registry,
        dry_run=False,
        topology=topology,
    )

    infrastructure = getattr(adapter, "infrastructure", None)
    verify_common_services = getattr(infrastructure, "verify_common_services_ready_for_level3", None)
    if callable(verify_common_services):
        common_ready, _root_cause = verify_common_services()
        if common_ready:
            print()
            print("Shared common services are already healthy.")
            print("Level 2 manages the shared foundation used by all adapters in this cluster.")

            if _interactive_confirm(
                f"Reuse shared common services ({execution_context})?",
                default=True,
            ):
                announcer = getattr(infrastructure, "announce_level", None)
                if callable(announcer):
                    announcer(2, "DEPLOY COMMON SERVICES")
                print("Reusing existing shared common services.")
                completer = getattr(infrastructure, "complete_level", None)
                if callable(completer):
                    completer(2)
                payload = {
                    "level": 2,
                    "name": LEVEL_DESCRIPTIONS[2],
                    "status": "completed",
                    "result": {
                        "action": "reuse",
                        "shared_adapter": shared_adapter_name,
                    },
                }
                payload.update(
                    _safe_level_hosts_followup(
                        adapter,
                        2,
                        deployer_name=shared_adapter_name,
                        deployer_registry=deployer_registry,
                        topology=topology,
                    )
                )
                return payload

            if not _interactive_confirm(
                f"Recreate shared common services now ({execution_context})? "
                "This resets common-srvs for all adapters in this cluster.",
                default=False,
            ):
                print("Level 2 cancelled.")
                return None

            resetter = getattr(infrastructure, "reset_local_shared_common_services", None)
            if not callable(resetter):
                resetter = getattr(infrastructure, "reset_common_services_for_level4_repair", None)
            if not callable(resetter):
                raise RuntimeError(
                    "Shared infrastructure does not expose a controlled common-services reset operation."
                )
            if not resetter(reason="Interactive Level 2 recreate requested"):
                raise RuntimeError("Could not reset shared common services safely.")

    return run_level(
        adapter,
        2,
        deployer_name=shared_adapter_name,
        deployer_registry=deployer_registry,
        topology=topology,
        validation_engine_cls=validation_engine_cls,
        metrics_collector_cls=metrics_collector_cls,
        experiment_storage=experiment_storage,
        baseline=baseline,
    )


def _level_supports_hosts_followup(level_id):
    return int(level_id or 0) in {2, 3, 4, 5}


def _safe_level_hosts_followup(
    adapter,
    level_id,
    *,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
    context=None,
):
    if not _level_supports_hosts_followup(level_id):
        return {}
    resolved_deployer_name = deployer_name
    if context is None:
        try:
            resolved_deployer_name, context = _resolve_deployer_context(
                adapter,
                deployer_name=deployer_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
        except Exception:
            return {}

    followup = {
        "hosts_plan": _build_shadow_host_sync_plan(context, levels=[level_id]),
    }

    try:
        followup["hosts_sync"] = _sync_deployer_hosts_if_enabled(context, levels=[level_id])
    except Exception as exc:
        followup["hosts_sync"] = {
            "status": "failed",
            "reason": "followup-error",
            "error": str(exc),
        }

    if not followup["hosts_plan"].get("hosts_file") and "hosts_file" in followup["hosts_sync"]:
        followup["hosts_plan"]["hosts_file"] = followup["hosts_sync"].get("hosts_file")
    if resolved_deployer_name:
        followup["deployer_name"] = resolved_deployer_name
    return followup


def _run_local_repair_interactive(
    current_adapter,
    *,
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
):
    selected_adapter = _interactive_require_adapter_selection(
        current_adapter,
        adapter_registry=adapter_registry,
    )
    if not selected_adapter:
        return None

    apply_hosts = _interactive_confirm(
        "Reconcile framework-managed hosts entries now?",
        default=True,
    )
    recover_connectors = _interactive_confirm(
        "Also restart connector runtimes after local access repair?",
        default=False,
    )
    adapter = build_adapter(
        selected_adapter,
        adapter_registry=adapter_registry,
        topology=topology,
    )
    return run_local_repair(
        adapter,
        deployer_name=selected_adapter,
        deployer_registry=deployer_registry,
        topology=topology,
        apply_hosts=apply_hosts,
        recover_connectors=recover_connectors,
    )


def _run_interactive_full_levels(
    adapter_name,
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    baseline=False,
):
    selected_adapter = str(adapter_name or "").strip()
    if not selected_adapter:
        raise RuntimeError("Full deployment requires selecting an adapter for Levels 3-6.")

    shared_adapter_name = _shared_foundation_adapter_name(adapter_registry=adapter_registry)
    completed = []

    shared_adapter = build_adapter(
        shared_adapter_name,
        adapter_registry=adapter_registry,
        dry_run=False,
        topology=topology,
    )
    completed.append(
        run_level(
            shared_adapter,
            1,
            deployer_name=shared_adapter_name,
            deployer_registry=deployer_registry,
            topology=topology,
            validation_engine_cls=validation_engine_cls,
            metrics_collector_cls=metrics_collector_cls,
            experiment_storage=experiment_storage,
            baseline=baseline,
        )
    )

    level2_result = _run_interactive_level2_with_shared_foundation(
        adapter_registry=adapter_registry,
        deployer_registry=deployer_registry,
        topology=topology,
        validation_engine_cls=validation_engine_cls,
        metrics_collector_cls=metrics_collector_cls,
        experiment_storage=experiment_storage,
        baseline=baseline,
    )
    if level2_result is None:
        return None
    completed.append(level2_result)

    target_adapter = shared_adapter
    if selected_adapter != shared_adapter_name:
        target_adapter = build_adapter(
            selected_adapter,
            adapter_registry=adapter_registry,
            dry_run=False,
            topology=topology,
        )

    for level_id in (3, 4, 5, 6):
        if not _interactive_ensure_hosts_ready_for_levels(
            selected_adapter,
            levels=[level_id],
            adapter_registry=adapter_registry,
            deployer_registry=deployer_registry,
            topology=topology,
        ):
            return None
        completed.append(
            run_level(
                target_adapter,
                level_id,
                deployer_name=selected_adapter,
                deployer_registry=deployer_registry,
                topology=topology,
                validation_engine_cls=validation_engine_cls,
                metrics_collector_cls=metrics_collector_cls,
                experiment_storage=experiment_storage,
                baseline=baseline,
            )
        )

    return {
        "status": "completed",
        "adapter": selected_adapter,
        "topology": topology,
        "levels": completed,
    }


def _print_interactive_menu(adapter_name, adapter_registry=None, topology="local"):
    print()
    print("=" * 50)
    print("DATASPACE VALIDATION ENVIRONMENT")
    print("=" * 50)
    print()
    print(f"Topology: {topology}")
    try:
        cluster_runtime = _resolve_interactive_cluster_runtime(topology)
        print(f"Cluster runtime: {cluster_runtime.get('cluster_type', 'minikube')} (active)")
        if normalize_topology(topology) == "vm-single" and cluster_runtime.get("cluster_type") == "k3s":
            print(f"K3s kubeconfig: {cluster_runtime.get('k3s_kubeconfig')}")
    except ValueError as exc:
        print(f"Cluster runtime: invalid ({exc})")
    if adapter_name:
        print(f"Adapter: {adapter_name}")
    print()
    print("[Full Deployment]")
    print("0 - Run All Levels (1-6) sequentially")
    print()
    print("[Individual Levels]")
    for level_id in sorted(LEVEL_DESCRIPTIONS):
        print(f"{level_id} - Level {level_id}: {LEVEL_DESCRIPTIONS[level_id]}")
    print()
    print("[Operations]")
    print("S - Select adapter")
    print("T - Select topology")
    print("K - Select cluster runtime")
    print("P - Preview deployment plan")
    print("H - Plan/apply hosts entries")
    print("U - Show available access URLs")
    print("G - Validate target")
    print("E - View experiment reports")
    print("M - Run metrics / benchmarks")
    print("X - Recreate dataspace")
    print()
    print("[Developer]")
    print("B - Bootstrap Framework Dependencies")
    print("D - Run Framework Doctor")
    print("R - Repair Local Access / Connectors")
    print("C - Cleanup Workspace")
    print("L - Build and Deploy Local Images")
    print()
    print("[UI Validation]")
    print("I - INESData Tests (Normal/Live/Debug)")
    print("O - Ontology Hub Tests (Normal/Live/Debug)")
    print("A - AI Model Hub Tests (Normal/Live/Debug)")
    print("V - Semantic Virtualization Tests (Normal/Live/Debug)")
    print()
    print("[Control]")
    print("? - Help")
    print("Q - Exit")
    print("=" * 50)


def _print_interactive_help():
    print()
    print("=" * 50)
    print("MENU HELP")
    print("=" * 50)
    print("[Deployment]")
    print("0 - Use for a fresh or full rebuild when you want Levels 1-6 executed in order.")
    print("1 - Use when the local Kubernetes/Minikube cluster is missing or needs to be prepared.")
    print("2 - Use when shared services such as Keycloak, MinIO, PostgreSQL or Vault are missing, outdated, or must be recreated.")
    print("    If shared common services are already healthy, the menu offers reuse or recreate with reuse as the recommended path.")
    print("3 - Use when the dataspace base or registration-service must be deployed or refreshed for the selected adapter.")
    print("4 - Use when connector deployments changed, or when switching/redeploying the selected adapter.")
    print("5 - Use when optional component services changed, for example AI Model Hub or Ontology Hub.")
    print("6 - Use after deployment changes to validate the selected adapter with cleanup, Newman, storage checks and Playwright when enabled.")
    print()
    print("[Operations]")
    print("S - Use when you want to preselect the adapter for upcoming Levels 3-6 or adapter-specific operations.")
    print("    If you skip it, the menu still asks automatically when an action needs an adapter.")
    print("T - Use when you want to change the active topology for this menu session.")
    print("    It switches between local, vm-single and vm-distributed without editing configuration files.")
    print("K - Use when vm-single is active and you want to choose Minikube or k3s for this menu session.")
    print("P - Use before deploying to inspect the plan without changing the environment.")
    print("    If Levels 3-6 need an adapter and none has been chosen yet, the menu asks for one automatically.")
    print("H - Use to inspect or apply local hosts entries needed by the selected adapter.")
    print("    It shows concrete hostnames, the sync result, and in menu mode can offer to apply the plan immediately.")
    print("U - Use to print access URLs derived from the selected adapter config in a readable format.")
    print("    Useful after Levels 2-5 when you want portal, connector, component or MinIO access details without searching files manually.")
    print("G - Use to inspect an external INESData validation target without deploying PIONERA resources.")
    print("    The current runner validates the target YAML and can run enabled read-only Playwright project specs.")
    print("E - Use to open a local, read-only dashboard for previous validation experiments.")
    print("    It lists experiments, summarizes long JSON artifacts, and serves reports only on 127.0.0.1.")
    print(
        "M - Use when you only need metrics or standalone benchmarks. "
        "It does not replace Level 6 validation; Kafka E2E validation runs automatically in Level 6."
    )
    print("X - Use only when you intentionally want to destroy and recreate the selected dataspace.")
    print()
    print("[Developer]")
    print("B - Use on a clean machine or after dependency issues to install/repair framework dependencies.")
    print("D - Use when diagnosing local readiness issues before deploying or validating.")
    print("R - Use when local hostnames, hosts entries or connector runtimes need recovery after a WSL/local restart.")
    print("    It can reconcile framework-managed hosts blocks first, then optionally restart connector runtimes.")
    print("C - Use when generated files, caches or previous results make the workspace hard to reason about.")
    print("L - Use during development after changing local images that must be rebuilt and loaded.")
    print("    In the image submenu, options 1-3 keep the INESData developer redeploy shortcuts.")
    print("    Advanced options use explicit image recipes for the active adapter.")
    print()
    print("[UI Validation]")
    print("I - Use to validate the INESData portal experience and component integrations through INESData.")
    print("O - Use when Ontology Hub UI changed or after deploying ontology-related components.")
    print("    This runs Ontology Hub component suites, not the INESData integration validation.")
    print("A - Use when AI Model Hub UI changed or after deploying AI Model Hub components.")
    print("    This runs AI Model Hub component suites, not the INESData integration validation.")
    print("V - Use when Semantic Virtualization UI/API browser reachability changed or after deploying the virtualizer.")
    print("    This runs Semantic Virtualization component/editor suites, not the INESData integration validation.")
    print()
    print("[Compatibility]")
    print("Levels 1-2 belong to the shared local foundation; the menu asks for an adapter only when an operation needs Levels 3-6, unless you preselect one with S.")
    print("The active topology shown in the header applies to all actions until you change it with T or exit the menu.")
    print("All developer and UI validation shortcuts are available directly from the main menu.")
    print("Q - Exit the menu.")
    print("=" * 50)


def _select_adapter_interactive(current_adapter, adapter_registry=None):
    registry = adapter_registry or ADAPTER_REGISTRY
    print()
    print("Available adapters:")
    for index, adapter_name in enumerate(sorted(registry), start=1):
        marker = " (current)" if current_adapter and adapter_name == current_adapter else ""
        print(f"{index} - {adapter_name}{marker}")
    print("B - Back")

    choice = _interactive_read("\nSelection: ").strip().upper()
    if not choice or choice == "B":
        return current_adapter

    adapters = sorted(registry)
    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid selection.")
        return current_adapter

    if index < 0 or index >= len(adapters):
        print("Invalid selection.")
        return current_adapter
    return adapters[index]


def _select_topology_interactive(
    current_topology="local",
    available_topologies=None,
    include_validation_target=False,
    initial_prompt=False,
):
    topologies = list(available_topologies or SUPPORTED_TOPOLOGIES or (LOCAL_TOPOLOGY,))
    normalized_current = normalize_topology(current_topology)

    print()
    print("Available topologies:")
    for index, topology_name in enumerate(topologies, start=1):
        marker = " (current)" if topology_name == normalized_current else ""
        print(f"{index} - {topology_name}{marker}")
    if include_validation_target:
        print()
        print("[Other actions]")
        print("G - Validate target")
    if initial_prompt:
        print()
        print("[Navigation]")
        print("Q - Exit")
    else:
        print("B - Back")

    choice = _interactive_read("\nSelection: ").strip().upper()
    if not choice:
        return normalized_current
    if initial_prompt and choice in ("Q", "B"):
        return "exit"
    if not initial_prompt and choice == "B":
        return normalized_current
    if include_validation_target and choice == "G":
        return "validation-target"

    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid selection.")
        return normalized_current

    if index < 0 or index >= len(topologies):
        print("Invalid selection.")
        return normalized_current
    return topologies[index]


def _resolve_interactive_cluster_runtime(topology="local"):
    normalized_topology = normalize_topology(topology)
    config = _load_effective_infrastructure_deployer_config(topology=normalized_topology)
    return build_cluster_runtime(config, topology=normalized_topology)


def _interactive_cluster_runtime_label(topology="local"):
    try:
        return _resolve_interactive_cluster_runtime(topology).get("cluster_type", "minikube")
    except ValueError as exc:
        return f"invalid ({exc})"


def _interactive_execution_context(topology="local", adapter_name=None):
    parts = []
    if adapter_name:
        parts.append(f"adapter: {adapter_name}")
    parts.append(f"topology: {normalize_topology(topology)}")
    parts.append(f"cluster: {_interactive_cluster_runtime_label(topology)}")
    return ", ".join(parts)


def _select_cluster_runtime_interactive(current_runtime=None, topology="local"):
    normalized_topology = normalize_topology(topology)
    if normalized_topology != "vm-single":
        runtime = _interactive_cluster_runtime_label(normalized_topology)
        print()
        print(f"Cluster runtime selection is currently only configurable for vm-single. Active runtime: {runtime}")
        return current_runtime or runtime

    current = normalize_cluster_type(
        current_runtime or _resolve_interactive_cluster_runtime(normalized_topology).get("cluster_type"),
        topology=normalized_topology,
    )

    print()
    print("Available cluster runtimes for vm-single:")
    for index, cluster_type in enumerate(SUPPORTED_CLUSTER_TYPES, start=1):
        marker = " (current)" if cluster_type == current else ""
        print(f"{index} - {cluster_type}{marker}")
    print("B - Back")

    choice = _interactive_read("\nSelection: ").strip().upper()
    if not choice or choice == "B":
        return current

    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid selection.")
        return current

    if index < 0 or index >= len(SUPPORTED_CLUSTER_TYPES):
        print("Invalid selection.")
        return current
    return SUPPORTED_CLUSTER_TYPES[index]


def _detect_k3s_kubeconfig_candidate():
    env_kubeconfig = os.environ.get("KUBECONFIG")
    for candidate in (token for token in str(env_kubeconfig or "").split(os.pathsep) if token):
        normalized = os.path.abspath(os.path.expanduser(candidate))
        if normalized.endswith("/k3s.yaml") and os.path.isfile(normalized):
            return normalized
    return "/etc/rancher/k3s/k3s.yaml"


def _k3s_kubeconfig_value(existing_config):
    candidate = str((existing_config or {}).get("K3S_KUBECONFIG") or "").strip()
    normalized = os.path.abspath(os.path.expanduser(candidate)) if candidate else ""
    if normalized.endswith("/.kube/config"):
        return _detect_k3s_kubeconfig_candidate()
    return candidate or _detect_k3s_kubeconfig_candidate()


def _cluster_runtime_config_updates(cluster_runtime, existing_config=None):
    normalized = normalize_cluster_type(cluster_runtime, topology="vm-single")
    existing = dict(existing_config or {})
    updates = {"CLUSTER_TYPE": normalized}
    if normalized == "k3s":
        runtime = build_cluster_runtime({"CLUSTER_TYPE": "k3s"}, topology="vm-single")
        detected_kubeconfig = _detect_k3s_kubeconfig_candidate()
        existing_ingress_service_type = str(existing.get("K3S_INGRESS_SERVICE_TYPE") or "").strip()
        k3s_ingress_service_type = existing_ingress_service_type or runtime["k3s_ingress_service_type"]
        if existing_ingress_service_type == "NodePort":
            k3s_ingress_service_type = runtime["k3s_ingress_service_type"]
        updates.update(
            {
                "K3S_KUBECONFIG": _k3s_kubeconfig_value(existing) or detected_kubeconfig,
                "K3S_INSTALL_EXEC": existing.get("K3S_INSTALL_EXEC") or runtime["k3s_install_exec"],
                "K3S_SERVICE_NAME": existing.get("K3S_SERVICE_NAME") or runtime["k3s_service_name"],
                "K3S_INGRESS_CONTROLLER": existing.get("K3S_INGRESS_CONTROLLER")
                or runtime["k3s_ingress_controller"],
                "K3S_INGRESS_SERVICE_TYPE": k3s_ingress_service_type,
                "K3S_REPAIR_ON_LEVEL1": existing.get("K3S_REPAIR_ON_LEVEL1") or runtime["k3s_repair_on_level1"],
                "K3S_WRITE_KUBECONFIG_MODE": existing.get("K3S_WRITE_KUBECONFIG_MODE")
                or runtime["k3s_write_kubeconfig_mode"],
            }
        )
    return updates


def _write_key_value_config_updates(config_path, updates):
    lines = []
    if os.path.isfile(config_path):
        with open(config_path, encoding="utf-8") as handle:
            lines = handle.readlines()

    pending = dict(updates)
    rendered = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            rendered.append(raw_line)
            continue
        key, _value = raw_line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in pending:
            rendered.append(f"{normalized_key}={pending.pop(normalized_key)}\n")
        else:
            rendered.append(raw_line)

    if rendered and not rendered[-1].endswith("\n"):
        rendered[-1] = f"{rendered[-1]}\n"
    for key, value in pending.items():
        rendered.append(f"{key}={value}\n")

    with open(config_path, "w", encoding="utf-8") as handle:
        handle.writelines(rendered)


def _persist_vm_single_cluster_runtime(cluster_runtime):
    config_path = _seed_infrastructure_topology_config_if_missing("vm-single")
    existing_config = load_raw_deployer_config(config_path)
    updates = _cluster_runtime_config_updates(cluster_runtime, existing_config=existing_config)
    _write_key_value_config_updates(config_path, updates)
    print(f"Saved cluster runtime '{updates['CLUSTER_TYPE']}' in {_framework_relative_path(config_path)}.")
    return config_path


def _offer_persist_vm_single_cluster_runtime(cluster_runtime, previous_runtime=None):
    normalized = normalize_cluster_type(cluster_runtime, topology="vm-single")
    previous = normalize_cluster_type(previous_runtime, topology="vm-single") if previous_runtime else None
    if previous == normalized:
        return None
    if not _interactive_confirm(
        "Save this vm-single cluster runtime in deployers/infrastructure/topologies/vm-single.config?",
        default=True,
    ):
        print("Cluster runtime kept for this menu session only.")
        return None
    return _persist_vm_single_cluster_runtime(normalized)


def _set_session_cluster_runtime_override(cluster_runtime):
    os.environ["PIONERA_CLUSTER_TYPE"] = normalize_cluster_type(cluster_runtime, topology="vm-single")
    print(f"Active cluster runtime set to {os.environ['PIONERA_CLUSTER_TYPE']}.")


def _print_adapter_selection_hint(adapter_name):
    if str(adapter_name or "").strip().lower() not in {"edc", "inesdata"}:
        return
    print()
    print(f"{str(adapter_name).strip().upper()} adapter selected.")


def _interactive_ensure_hosts_ready_for_levels(
    current_adapter,
    levels,
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
):
    normalized_topology = str(topology or "local").strip().lower()
    if not current_adapter or normalized_topology not in {LOCAL_TOPOLOGY, "vm-single"}:
        return True

    selected_levels = {int(level) for level in (levels or [])}
    if not selected_levels.intersection({3, 4, 5, 6}):
        return True

    adapter = build_adapter(current_adapter, adapter_registry=adapter_registry, topology=topology)
    resolved_deployer_name, context = _resolve_deployer_context(
        adapter,
        deployer_name=current_adapter,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    readiness = _build_hosts_readiness_plan(context, levels=selected_levels)
    missing_hostnames = list(readiness.get("missing_hostnames") or [])
    legacy_external_hostnames = list(readiness.get("legacy_external_hostnames") or [])
    if not missing_hostnames:
        return True

    hosts_file = readiness.get("hosts_file") or "(not detected)"
    print()
    print(f"Host entries are missing for adapter '{current_adapter}' in this execution, or existing entries are outdated.")
    print(f"Hosts file: {hosts_file}")
    for hostname in missing_hostnames:
        print(f"- {hostname}")
    print()
    print("The framework will reconcile its managed hosts blocks and will not duplicate hostnames already defined outside those blocks.")
    if legacy_external_hostnames:
        print("Old hostname aliases were found in your hosts file:")
        for item in legacy_external_hostnames:
            print(f"- {item.get('legacy')} -> {item.get('canonical')}")
        print("They are outside the framework-managed hosts blocks, so they are reported but not removed automatically.")

    if not _interactive_confirm("Apply host reconciliation now?", default=False):
        print("Level execution cancelled. Run H first, then retry the selected level.")
        return False

    if not readiness.get("hosts_file"):
        print("Cannot detect a hosts file automatically. Set PIONERA_HOSTS_FILE and run H.")
        return False

    environment_overrides = {
        "PIONERA_SYNC_HOSTS": "true",
        "PIONERA_HOSTS_FILE": readiness["hosts_file"],
        "PIONERA_HOSTS_USE_SUDO": "true",
    }

    try:
        with _temporary_environment(environment_overrides):
            result = run_hosts(
                adapter,
                deployer_name=resolved_deployer_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
        _print_action_result(result)
    except Exception as exc:
        print(f"Could not apply host entries automatically: {exc}")
        print("Run H with the required permissions, then retry the selected level.")
        return False

    refreshed = _build_hosts_readiness_plan(context, levels=selected_levels, hosts_file=readiness["hosts_file"])
    if refreshed.get("missing_hostnames"):
        print(f"Some hostnames for adapter '{current_adapter}' are still missing after applying hosts:")
        for hostname in refreshed["missing_hostnames"]:
            print(f"- {hostname}")
        print("Run H with the required permissions, then retry the selected level.")
        return False

    return True


def _interactive_offer_hosts_plan_apply(
    result,
    adapter,
    deployer_name=None,
    deployer_registry=None,
    topology="local",
):
    if not isinstance(result, dict):
        return result

    hosts_sync = result.get("hosts_sync")
    if not isinstance(hosts_sync, dict):
        return result

    sync_status = str(hosts_sync.get("status") or "").strip().lower()
    sync_reason = str(hosts_sync.get("reason") or "").strip().lower()
    if sync_status != "skipped" or sync_reason != "disabled":
        return result

    hostnames = _hosts_plan_hostnames(result.get("hosts_plan"))
    if not hostnames:
        return result

    hosts_file = _interactive_hosts_file_path()

    print()
    if not hosts_file:
        print("Cannot detect a hosts file automatically. Set PIONERA_HOSTS_FILE and run H again.")
        return result

    print(f"Detected hosts file: {hosts_file}")
    print("The framework can apply this hosts plan now.")

    if not _interactive_confirm("Apply this hosts plan now?", default=False):
        return result

    try:
        with _temporary_environment(
            {
                "PIONERA_SYNC_HOSTS": "true",
                "PIONERA_HOSTS_FILE": hosts_file,
            }
        ):
            applied = run_hosts(
                adapter,
                deployer_name=deployer_name,
                deployer_registry=deployer_registry,
                topology=topology,
            )
    except Exception as exc:
        print(f"Could not apply host entries automatically: {exc}")
        print("Run H again with the required permissions or set PIONERA_SYNC_HOSTS manually.")
        return result

    _print_action_result(applied)
    return applied


def _print_action_result(result):
    def _console_result_label(status):
        normalized = str(status or "").strip().lower()
        if (
            normalized in {
                "completed",
                "updated",
                "unchanged",
                "ready",
                "available",
                "planned",
                "dry-run",
                "prepared",
                "recreated",
                "passed",
            }
            or normalized.endswith("-ok")
        ):
            return "Succeeded"
        if normalized in {"skipped", "not-applicable"}:
            return "Skipped"
        if normalized in {"failed", "unavailable", "error"} or normalized.endswith("-failed"):
            return "Failed"
        return str(status or "Unknown").strip().title() or "Unknown"

    def _append_if_value(lines, label, value):
        if value in (None, "", [], {}):
            return
        lines.append(f"{label}: {value}")

    def _append_config_migration_warning_lines(lines, warnings):
        items = [item for item in list(warnings or []) if isinstance(item, dict)]
        if not items:
            return
        lines.append(f"Configuration migration warnings: {len(items)}")
        for item in items:
            key = str(item.get("key") or "").strip()
            overlay_paths = [
                str(value or "").strip()
                for value in list(item.get("recommended_overlay_paths") or [])
                if str(value or "").strip()
            ]
            if key and overlay_paths:
                lines.append(f"- {key} -> {', '.join(overlay_paths)}")
            elif key:
                lines.append(f"- {key}")

    def _summarize_level_result(level_result):
        if not isinstance(level_result, dict):
            return None
        level_id = level_result.get("level")
        name = level_result.get("name") or LEVEL_DESCRIPTIONS.get(level_id, "Unknown")
        status_label = _console_result_label(level_result.get("status"))
        prefix = f"Level {level_id} - {name}" if level_id is not None else str(name)
        details = level_result.get("result")
        suffix = ""
        if isinstance(details, list) and details:
            suffix = f" ({len(details)} items)"
        return f"{prefix}: {status_label}{suffix}"

    def _format_action_result_lines(payload):
        if isinstance(payload, list):
            if not payload:
                return ["Result: Succeeded"]
            return [f"Result: Succeeded", f"Items: {len(payload)}"]

        if not isinstance(payload, dict):
            return [str(payload)]

        lines = [f"Result: {_console_result_label(payload.get('status'))}"]
        scope = payload.get("scope")
        _append_if_value(lines, "Scope", scope)
        if str(scope or "").strip().lower() != "shared foundation":
            _append_if_value(lines, "Adapter", payload.get("adapter") or payload.get("deployer_name"))
        _append_if_value(lines, "Topology", payload.get("topology"))
        validation_mode = payload.get("validation_mode")
        if isinstance(validation_mode, dict):
            _append_if_value(lines, "Validation mode", validation_mode.get("effective"))
        _append_if_value(lines, "Dataspace", payload.get("dataspace"))

        levels = payload.get("levels")
        if isinstance(levels, list) and levels:
            for level_payload in levels:
                summary = _summarize_level_result(level_payload)
                if summary:
                    lines.append(summary)
                if isinstance(level_payload, dict):
                    level_id = level_payload.get("level")
                    level_urls = level_payload.get("urls")
                    if not level_urls:
                        level_result = level_payload.get("result")
                        if isinstance(level_result, dict):
                            level_urls = level_result.get("urls")
                            if int(level_id or 0) == 5:
                                _append_component_list_lines(
                                    lines,
                                    "Level 5 configured components",
                                    level_result.get("configured"),
                                )
                                _append_component_list_lines(
                                    lines,
                                    "Level 5 deployable now",
                                    level_result.get("deployable"),
                                )
                                _append_component_list_lines(
                                    lines,
                                    "Level 5 pending adapter support",
                                    level_result.get("pending_support"),
                                )
                                _append_component_list_lines(
                                    lines,
                                    "Level 5 unsupported for adapter",
                                    level_result.get("unsupported"),
                                )
                                _append_component_list_lines(
                                    lines,
                                    "Level 5 unknown components",
                                    level_result.get("unknown"),
                                )
                    level_hosts_plan = level_payload.get("hosts_plan")
                    if isinstance(level_hosts_plan, dict):
                        level_prefix = f"Level {level_id} " if level_id is not None else ""
                        for key, label in (
                            ("level_1_2", "Hosts Level 1-2"),
                            ("level_3", "Hosts Level 3"),
                            ("level_4", "Hosts Level 4"),
                            ("level_5", "Hosts Level 5"),
                        ):
                            _append_hosts_level_lines(lines, f"{level_prefix}{label}", level_hosts_plan.get(key))
                        level_legacy_hostnames = list(level_hosts_plan.get("legacy_external_hostnames") or [])
                        if level_legacy_hostnames:
                            lines.append(
                                f"{level_prefix}Hosts legacy aliases detected: {len(level_legacy_hostnames)}"
                            )
                    level_hosts_sync = level_payload.get("hosts_sync")
                    if isinstance(level_hosts_sync, dict):
                        sync_status = str(level_hosts_sync.get("status") or "").strip().lower()
                        sync_reason = str(level_hosts_sync.get("reason") or "").strip().lower()
                        if sync_status and not (sync_status == "skipped" and sync_reason == "disabled"):
                            label = f"Level {level_id} hosts sync" if level_id is not None else "Hosts sync"
                            line = f"{label}: {_console_result_label(sync_status)}"
                            if sync_reason:
                                line += f" ({_humanize_hosts_sync_reason(sync_reason)})"
                            lines.append(line)
                        level_legacy_hostnames = list(level_hosts_sync.get("legacy_external_hostnames") or [])
                        if level_legacy_hostnames:
                            prefix = f"Level {level_id} " if level_id is not None else ""
                            lines.append(
                                f"{prefix}Hosts legacy aliases outside managed blocks: {len(level_legacy_hostnames)}"
                            )
                    if level_urls:
                        heading = f"Level {level_id} URLs"
                        _append_url_lines(lines, level_urls, heading=heading)
        elif payload.get("level") is not None and payload.get("name"):
            summary = _summarize_level_result(payload)
            if summary and summary not in lines:
                lines.append(summary)

        if isinstance(payload.get("connectors"), list):
            lines.append(f"Connectors: {len(payload['connectors'])}")
        elif isinstance(payload.get("result"), list):
            lines.append(f"Items: {len(payload['result'])}")

        validation = payload.get("validation")
        if isinstance(validation, dict) and validation:
            lines.append("Validation: Succeeded")

        playwright = payload.get("playwright")
        if isinstance(playwright, dict) and playwright.get("status") in {"passed", "failed", "skipped"}:
            lines.append(f"Playwright: {_console_result_label(playwright.get('status'))}")

        kafka_results = payload.get("kafka_edc_results")
        if isinstance(kafka_results, list) and kafka_results:
            statuses = {str(item.get("status", "")).strip().lower() for item in kafka_results if isinstance(item, dict)}
            if "failed" in statuses:
                lines.append("Kafka: Failed")
            elif "passed" in statuses:
                lines.append("Kafka: Passed")
            elif "skipped" in statuses:
                lines.append("Kafka: Skipped")

        cleanup = payload.get("test_data_cleanup")
        if isinstance(cleanup, dict) and cleanup.get("status") not in (None, "skipped"):
            lines.append(f"Cleanup: {_console_result_label(cleanup.get('status'))}")

        doctor = payload.get("doctor")
        if isinstance(doctor, dict):
            doctor_status = doctor.get("status")
            if doctor_status not in (None, ""):
                lines.append(f"Doctor: {_doctor_result_label(doctor_status)}")
            doctor_checks = [item for item in list(doctor.get("checks") or []) if isinstance(item, dict)]
            doctor_warning_count = sum(1 for item in doctor_checks if item.get("status") == "warning")
            doctor_missing_count = sum(1 for item in doctor_checks if item.get("status") == "missing")
            if doctor_warning_count:
                lines.append(f"Doctor warnings: {doctor_warning_count}")
            if doctor_missing_count:
                lines.append(f"Doctor missing prerequisites: {doctor_missing_count}")

        hosts_plan = payload.get("hosts_plan")
        if isinstance(hosts_plan, dict):
            for key, label in (
                ("level_1_2", "Hosts Level 1-2"),
                ("level_3", "Hosts Level 3"),
                ("level_4", "Hosts Level 4"),
                ("level_5", "Hosts Level 5"),
            ):
                _append_hosts_level_lines(lines, label, hosts_plan.get(key))
            _append_if_value(lines, "Hosts address", hosts_plan.get("address"))
            legacy_external_hostnames = list(hosts_plan.get("legacy_external_hostnames") or [])
            if legacy_external_hostnames:
                lines.append(f"Hosts legacy aliases detected: {len(legacy_external_hostnames)}")

        missing_hostnames = [str(value or "").strip() for value in (payload.get("missing_hostnames") or []) if str(value or "").strip()]
        if missing_hostnames:
            lines.append(f"Missing hostnames: {len(missing_hostnames)}")
            for value in missing_hostnames:
                lines.append(f"- {value}")

        hosts_sync = payload.get("hosts_sync")
        if isinstance(hosts_sync, dict):
            sync_status = hosts_sync.get("status")
            if sync_status not in (None, ""):
                line = f"Hosts sync: {_console_result_label(sync_status)}"
                sync_reason = hosts_sync.get("reason")
                if sync_reason not in (None, ""):
                    line += f" ({_humanize_hosts_sync_reason(sync_reason)})"
                lines.append(line)
            legacy_external_hostnames = list(hosts_sync.get("legacy_external_hostnames") or [])
            if legacy_external_hostnames:
                lines.append(f"Hosts legacy aliases outside managed blocks: {len(legacy_external_hostnames)}")

        connector_recovery = payload.get("connector_recovery")
        if isinstance(connector_recovery, dict):
            connector_status = connector_recovery.get("status")
            if connector_status not in (None, ""):
                line = f"Connector recovery: {_console_result_label(connector_status)}"
                connector_reason = connector_recovery.get("reason")
                if connector_reason not in (None, ""):
                    line += f" ({str(connector_reason).replace('-', ' ')})"
                lines.append(line)

        public_endpoint_preflight = payload.get("public_endpoint_preflight")
        if isinstance(public_endpoint_preflight, dict):
            preflight_status = public_endpoint_preflight.get("status")
            if preflight_status not in (None, ""):
                line = f"Public endpoints: {_console_result_label(preflight_status)}"
                preflight_reason = _humanize_public_endpoint_reason(public_endpoint_preflight.get("reason"))
                if preflight_reason:
                    line += f" ({preflight_reason})"
                lines.append(line)
            checked = list(public_endpoint_preflight.get("checked") or [])
            failures = list(public_endpoint_preflight.get("failures") or [])
            if checked:
                lines.append(f"Public endpoints checked: {len(checked)}")
            if failures:
                lines.append(f"Public endpoints failures: {len(failures)}")

        local_capacity = payload.get("local_capacity")
        if isinstance(local_capacity, dict):
            capacity_result = local_capacity.get("preflight") or local_capacity.get("install_preflight")
            if isinstance(capacity_result, dict):
                capacity_status = capacity_result.get("status")
                if capacity_status not in (None, "", "skipped"):
                    lines.append(f"Local coexistence capacity: {_console_result_label(capacity_status)}")
                if capacity_result.get("coexistence_detected"):
                    required_memory = capacity_result.get("required_memory_mb")
                    effective_memory = capacity_result.get("effective_memory_mb")
                    if required_memory and effective_memory:
                        lines.append(
                            f"Local coexistence memory: {effective_memory}/{required_memory} MiB"
                        )
                switch_result = capacity_result.get("switch")
                if isinstance(switch_result, dict) and switch_result.get("status") == "completed":
                    removed = ", ".join(switch_result.get("adapters_to_remove") or [])
                    deleted = ", ".join(switch_result.get("deleted_namespaces") or [])
                    if removed:
                        lines.append(f"Local adapter switch: removed {removed}")
                    if deleted:
                        lines.append(f"Local adapter switch namespaces: {deleted}")

        local_stability = payload.get("local_stability")
        if isinstance(local_stability, dict):
            stability_result = local_stability.get("postflight") or local_stability.get("preflight")
            if isinstance(stability_result, dict):
                stability_status = stability_result.get("status")
                if stability_status not in (None, "", "skipped"):
                    lines.append(f"Local stability: {_console_result_label(stability_status)}")
                stability_warnings = list(stability_result.get("warnings") or [])
                stability_blocking = list(stability_result.get("blocking_issues") or [])
                if stability_warnings:
                    lines.append(f"Local stability warnings: {len(stability_warnings)}")
                if stability_blocking:
                    lines.append(f"Local stability blocking issues: {len(stability_blocking)}")

        _append_url_lines(
            lines,
            payload.get("urls"),
            multiline=bool(payload.get("access_urls_view")),
        )
        _append_local_browser_access_lines(lines, payload.get("local_browser_access"))
        _append_config_migration_warning_lines(lines, payload.get("config_migration_warnings"))
        _append_if_value(lines, "Next step", payload.get("next_step"))
        return lines

    if result is None:
        return

    lines = _format_action_result_lines(result)
    if not lines:
        return

    print()
    for line in lines:
        print(line)


def _run_recreate_dataspace_interactive(
    current_adapter="inesdata",
    adapter_registry=None,
    deployer_registry=None,
    topology="local",
):
    adapter = build_adapter(current_adapter, adapter_registry=adapter_registry, topology=topology)
    resolved_deployer_name, context = _resolve_deployer_context(
        adapter,
        deployer_name=current_adapter,
        deployer_registry=deployer_registry,
        topology=topology,
    )
    plan = _build_recreate_dataspace_plan(adapter, context)
    dataspace_name = str(plan.get("dataspace") or "").strip()

    print()
    print("=" * 50)
    print("RECREATE DATASPACE PLAN")
    print("=" * 50)
    print(f"Adapter: {resolved_deployer_name}")
    print(f"Topology: {topology}")
    print(f"Cluster runtime: {_interactive_cluster_runtime_label(topology)}")
    print(f"Dataspace: {dataspace_name}")
    print(f"Namespace: {plan.get('namespace')}")
    print("Shared services: preserved")
    print("Level 4 connectors: invalidated and must be redeployed")
    print("=" * 50)

    confirmation = _interactive_read(
        f"Type the exact dataspace name '{dataspace_name}' to continue: "
    ).strip()
    if confirmation != dataspace_name:
        print("Dataspace recreation cancelled.")
        return None

    with_connectors = _interactive_confirm(
        f"Recreate Level 4 connectors now ({_interactive_execution_context(topology, current_adapter)})?",
        default=False,
    )

    return run_recreate_dataspace(
        adapter,
        deployer_name=current_adapter,
        deployer_registry=deployer_registry,
        topology=topology,
        confirm_dataspace=confirmation,
        with_connectors=with_connectors,
    )


def _print_validation_target_menu(selected_target=None, validation_project="inesdata"):
    print()
    print("=" * 50)
    print("VALIDATION TARGET")
    print("=" * 50)
    print(f"Project: {validation_project}")
    print("Mode: validation-only")
    print("Safety: no cleanup, no writes, no destructive actions")
    if selected_target:
        label = selected_target.get("name") or selected_target.get("filename")
        suffix = " (example)" if selected_target.get("example") else ""
        print(f"Target: {label}{suffix}")
    else:
        print("Target: not selected")
    print()
    print("1 - Select validation target")
    print("2 - Show target validation plan")
    print("3 - Run target validation (read-only)")
    print("B - Back")
    print("=" * 50)


def _select_validation_target_interactive(selected_target=None):
    targets = discover_validation_targets()
    if not targets:
        print("No validation targets found under validation/targets/.")
        return selected_target

    print()
    print("Available validation targets:")
    for index, target in enumerate(targets, start=1):
        marker = " (current)" if selected_target and selected_target.get("path") == target.get("path") else ""
        suffix = " [example]" if target.get("example") else ""
        status = target.get("status") or "available"
        print(f"{index} - {target.get('name')}{suffix} ({status}){marker}")
    print("B - Back")

    choice = _interactive_read("\nSelection: ").strip().upper()
    if not choice or choice == "B":
        return selected_target
    try:
        selected_index = int(choice)
    except ValueError:
        print("Invalid target selection.")
        return selected_target
    if selected_index < 1 or selected_index > len(targets):
        print("Invalid target selection.")
        return selected_target

    target = targets[selected_index - 1]
    if target.get("status") == "invalid":
        print(f"Target cannot be selected because it is invalid: {target.get('error')}")
        return selected_target
    print(f"Validation target selected: {target.get('name')}")
    return target


def _build_selected_validation_target_plan(selected_target, validation_project="inesdata", environ=None):
    if not selected_target:
        raise RuntimeError("Select a validation target first.")
    payload, target_path = load_validation_target(selected_target.get("path") or selected_target.get("name"))
    return build_validation_target_plan(
        payload,
        target_path=target_path,
        adapter=validation_project or "inesdata",
        environ=environ,
    )


def _print_validation_target_plan(plan):
    print()
    for line in format_validation_target_plan(plan):
        print(line)


def _secret_prompt_hidden(env_name):
    normalized = str(env_name or "").upper()
    return any(token in normalized for token in ("PASSWORD", "PASS", "TOKEN", "SECRET", "KEY"))


def _prompt_validation_target_missing_secrets(plan, environ=None):
    runtime_env = dict(os.environ if environ is None else environ)
    missing = [item for item in list(plan.get("secrets") or []) if item.get("status") == "missing"]
    if not missing:
        return runtime_env

    print()
    print("Missing target credentials will be requested for this run only.")
    print("Values are kept in memory and are not written to target files, logs or reports.")
    for item in missing:
        env_name = str(item.get("env") or "").strip()
        if not env_name:
            continue
        prompt = f"{env_name}: "
        if _secret_prompt_hidden(env_name):
            value = getpass.getpass(prompt)
        else:
            value = _interactive_read(prompt)
        if not value:
            print(f"Credential not provided: {env_name}")
            return None
        runtime_env[env_name] = value
    return runtime_env


def _print_validation_target_run_result(result):
    print()
    status = str(result.get("status") or "unknown").strip()
    print(f"Target validation status: {status}")
    reason = str(result.get("reason") or "").strip()
    if reason:
        print(f"Reason: {reason}")
    message = str(result.get("message") or "").strip()
    if message:
        print(message)
    if result.get("experiment_dir"):
        print(f"Artifacts: {result['experiment_dir']}")
    for suite in result.get("suite_results") or []:
        suite_name = suite.get("suite") or "unknown"
        suite_status = suite.get("status") or "unknown"
        specs = suite.get("specs") or []
        print(f"- {suite_name}: {suite_status} ({len(specs)} spec(s))")
        artifacts = suite.get("artifacts") or {}
        if artifacts.get("html_report_dir"):
            print(f"  Report: {artifacts['html_report_dir']}")
        if artifacts.get("output_dir"):
            print(f"  Evidence: {artifacts['output_dir']}")


def _print_report_experiment_list(experiments):
    print()
    print("Available validation experiments:")
    if not experiments:
        print("No experiments found under experiments/.")
        return
    for index, experiment in enumerate(experiments, start=1):
        lines = format_report_experiment_summary(experiment)
        print(f"{index} - {lines[0]}")
        for line in lines[1:]:
            print(line)
        print()
    print("L - Open latest dashboard")
    print("B - Back")


def _select_report_experiment_interactive(experiments):
    _print_report_experiment_list(experiments)
    if not experiments:
        return None
    choice = _interactive_read("\nSelection: ").strip().upper()
    if not choice or choice == "B":
        return None
    if choice == "L":
        latest = dict(experiments[0])
        latest["_open_dashboard"] = True
        return latest
    try:
        selected_index = int(choice)
    except ValueError:
        print("Invalid experiment selection.")
        return None
    if selected_index < 1 or selected_index > len(experiments):
        print("Invalid experiment selection.")
        return None
    return experiments[selected_index - 1]


def _print_report_experiment_menu(experiment):
    reports = ", ".join(experiment.get("reports") or []) or "none detected"
    print()
    print("=" * 50)
    print("VALIDATION REPORTS")
    print("=" * 50)
    print(f"Experiment: {experiment.get('name')}")
    print(f"Adapter: {experiment.get('adapter')}")
    print(f"Topology: {experiment.get('topology')}")
    print(f"Cluster runtime: {experiment.get('cluster_runtime')}")
    print(f"Dashboard status: {experiment.get('result')}")
    print(f"Reports: {reports}")
    print()
    print("1 - Open experiment dashboard")
    print("2 - Open Playwright report")
    print("3 - Show artifact paths")
    print("B - Back")
    print("=" * 50)


def _select_playwright_report_interactive(experiment):
    reports = experiment.get("playwright_reports") or []
    if not reports:
        print("No Playwright HTML reports found for this experiment.")
        return None
    if len(reports) == 1:
        return reports[0]

    print()
    print("Available Playwright reports:")
    for index, report in enumerate(reports, start=1):
        print(f"{index} - {report.get('title')}")
        print(f"    {report.get('path')}")
    print("B - Back")

    choice = _interactive_read("\nSelection: ").strip().upper()
    if not choice or choice == "B":
        return None
    try:
        selected_index = int(choice)
    except ValueError:
        print("Invalid Playwright report selection.")
        return None
    if selected_index < 1 or selected_index > len(reports):
        print("Invalid Playwright report selection.")
        return None
    return reports[selected_index - 1]


def _print_report_artifact_paths(experiment):
    print()
    print("Artifact paths:")
    artifacts = experiment.get("artifacts") or []
    if not artifacts:
        print("No standard artifacts detected for this experiment.")
        return
    for artifact in artifacts:
        print(f"- {artifact.get('path')}")


def _open_experiment_dashboard_interactive(experiment):
    try:
        dashboard_path = build_experiment_dashboard(experiment)
        server = launch_static_report_server(experiment["path"])
    except Exception as exc:
        print(f"Could not open experiment dashboard: {exc}")
        return

    url = f"{server['url']}/framework-report/index.html"
    print()
    print("Experiment dashboard available at:")
    print(url)
    print(f"Dashboard file: {dashboard_path}")
    print("The local server is bound to 127.0.0.1 and stays alive while this framework process is running.")
    if not server.get("ready"):
        print("The dashboard server is still starting. If the browser does not open, use the URL above.")
    if server.get("ready"):
        open_result = open_local_url(url)
        if open_result.get("opened"):
            print(f"Opened in the default browser through {open_result.get('method')}.")
        else:
            print(f"Could not open the browser automatically: {open_result.get('reason')}")


def _open_playwright_report_interactive(experiment):
    report = _select_playwright_report_interactive(experiment)
    if not report:
        return
    report_dir = os.path.join(experiment["path"], report["path"])
    try:
        server = launch_playwright_report(report_dir)
    except Exception as exc:
        print(f"Could not open Playwright report: {exc}")
        return

    print()
    print("Playwright report available at:")
    print(server["url"])
    print(f"Report directory: {report_dir}")
    print("The Playwright report server is bound to 127.0.0.1.")
    if not server.get("ready"):
        print("The Playwright report server is still starting. If the browser does not open, use the URL above.")
    if server.get("ready"):
        open_result = open_local_url(server["url"])
        if open_result.get("opened"):
            print(f"Opened in the default browser through {open_result.get('method')}.")
        else:
            print(f"Could not open the browser automatically: {open_result.get('reason')}")


def _run_validation_reports_menu_interactive():
    experiments = discover_report_experiments()
    selected_experiment = _select_report_experiment_interactive(experiments)
    if not selected_experiment:
        return
    if selected_experiment.pop("_open_dashboard", False):
        _open_experiment_dashboard_interactive(selected_experiment)

    while True:
        _print_report_experiment_menu(selected_experiment)
        choice = _interactive_read("\nSelection: ").strip().upper()
        if not choice or choice == "B":
            return
        if choice == "1":
            _open_experiment_dashboard_interactive(selected_experiment)
            continue
        if choice == "2":
            _open_playwright_report_interactive(selected_experiment)
            continue
        if choice == "3":
            _print_report_artifact_paths(selected_experiment)
            continue
        print("Invalid report action.")


def _run_validation_target_menu_interactive(current_adapter=None, adapter_registry=None):
    registry = adapter_registry or ADAPTER_REGISTRY
    validation_project = "inesdata"
    if validation_project not in registry:
        print("Validation target scaffold currently supports INESData only, but the INESData adapter is not registered.")
        return current_adapter

    selected_target = None
    target_runtime_env = dict(os.environ)
    while True:
        _print_validation_target_menu(
            selected_target=selected_target,
            validation_project=validation_project,
        )
        choice = _interactive_read("\nSelection: ").strip().upper()
        if not choice or choice == "B":
            return current_adapter

        if choice == "1":
            selected_target = _select_validation_target_interactive(selected_target=selected_target)
            continue

        if choice == "2":
            if not selected_target:
                selected_target = _select_validation_target_interactive(selected_target=selected_target)
                if not selected_target:
                    continue
            plan = _build_selected_validation_target_plan(
                selected_target,
                validation_project=validation_project,
                environ=target_runtime_env,
            )
            _print_validation_target_plan(plan)
            continue

        if choice == "3":
            if not selected_target:
                selected_target = _select_validation_target_interactive(selected_target=selected_target)
                if not selected_target:
                    continue
            plan = _build_selected_validation_target_plan(
                selected_target,
                validation_project=validation_project,
                environ=target_runtime_env,
            )
            updated_env = _prompt_validation_target_missing_secrets(plan, environ=target_runtime_env)
            if updated_env is None:
                print("Target validation cancelled because required credentials were not provided.")
                continue
            target_runtime_env = updated_env
            plan = _build_selected_validation_target_plan(
                selected_target,
                validation_project=validation_project,
                environ=target_runtime_env,
            )
            _print_validation_target_plan(plan)
            print()
            print("Running read-only target validation...")
            payload, target_path = load_validation_target(selected_target.get("path") or selected_target.get("name"))
            result = run_validation_target_read_only(
                payload,
                target_path=target_path,
                environ=target_runtime_env,
            )
            _print_validation_target_run_result(result)
            continue

        print("Invalid selection. Please try again.")


def _run_legacy_menu_action(action_name, current_adapter="inesdata"):
    """Run compatibility menu shortcuts through the migrated main.py modules."""
    migrated_actions = {
        "bootstrap": local_menu_tools.run_framework_bootstrap_interactive,
        "doctor": local_menu_tools.run_framework_doctor,
        "recover": local_menu_tools.run_connector_recovery_after_wsl_restart,
        "cleanup": local_menu_tools.run_workspace_cleanup_interactive,
        "inesdata_ui": ui_interactive_menu.run_inesdata_ui_tests_interactive,
        "ontology_hub_ui": ui_interactive_menu.run_ontology_hub_ui_tests_interactive,
        "ai_model_hub_ui": ui_interactive_menu.run_ai_model_hub_ui_tests_interactive,
        "semantic_virtualization_ui": ui_interactive_menu.run_semantic_virtualization_ui_tests_interactive,
    }
    if action_name == "local_images":
        return local_menu_tools.run_local_images_workflow_interactive(active_adapter=current_adapter)

    migrated_action = migrated_actions.get(action_name)
    if callable(migrated_action):
        return migrated_action()

    raise ValueError(f"Unknown legacy menu action: {action_name}")


def run_interactive_menu(
    adapter_registry=None,
    deployer_registry=None,
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    kafka_manager_cls=KafkaManager,
    topology="local",
    prompt_initial_topology=False,
):
    """Run a guided menu equivalent to the legacy numbered-level workflow."""
    registry = adapter_registry or ADAPTER_REGISTRY
    current_adapter = None
    if len(registry) == 1:
        current_adapter = sorted(registry)[0]

    original_cluster_type_env_present = "PIONERA_CLUSTER_TYPE" in os.environ
    original_cluster_type_env = os.environ.get("PIONERA_CLUSTER_TYPE")

    def restore_cluster_type_env():
        if original_cluster_type_env_present:
            os.environ["PIONERA_CLUSTER_TYPE"] = original_cluster_type_env
        else:
            os.environ.pop("PIONERA_CLUSTER_TYPE", None)

    try:
        if prompt_initial_topology:
            selected_topology = _select_topology_interactive(
                topology,
                available_topologies=SUPPORTED_TOPOLOGIES,
                include_validation_target=True,
                initial_prompt=True,
            )
            if selected_topology == "exit":
                print("\nExiting Dataspace Validation Environment\n")
                return {"status": "exited"}
            if selected_topology == "validation-target":
                current_adapter = _run_validation_target_menu_interactive(
                    current_adapter=current_adapter,
                    adapter_registry=registry,
                )
            else:
                topology = selected_topology
                print(f"Active topology set to {topology}.")
                if normalize_topology(topology) == "vm-single":
                    previous_runtime = _interactive_cluster_runtime_label(topology)
                    selected_runtime = _select_cluster_runtime_interactive(topology=topology)
                    _set_session_cluster_runtime_override(selected_runtime)
                    _offer_persist_vm_single_cluster_runtime(selected_runtime, previous_runtime=previous_runtime)
                    _interactive_offer_vm_single_address_configuration(required=False)

        while True:
            _print_interactive_menu(current_adapter, adapter_registry=registry, topology=topology)
            choice = _interactive_read("\nSelection: ").strip().upper()

            if not choice or choice == "Q":
                print("\nExiting Dataspace Validation Environment\n")
                return {"status": "exited", "adapter": current_adapter, "topology": topology}

            try:
                if choice in {"?", "HELP"}:
                    _print_interactive_help()
                    continue

                if choice == "S":
                    selected_adapter = _select_adapter_interactive(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if selected_adapter != current_adapter:
                        current_adapter = selected_adapter
                        _print_adapter_selection_hint(current_adapter)
                    continue

                if choice == "T":
                    selected_topology = _select_topology_interactive(
                        topology,
                        available_topologies=SUPPORTED_TOPOLOGIES,
                    )
                    if selected_topology != topology:
                        topology = selected_topology
                        print(f"Active topology set to {topology}.")
                        if normalize_topology(topology) == "vm-single":
                            previous_runtime = _interactive_cluster_runtime_label(topology)
                            selected_runtime = _select_cluster_runtime_interactive(topology=topology)
                            _set_session_cluster_runtime_override(selected_runtime)
                            _offer_persist_vm_single_cluster_runtime(selected_runtime, previous_runtime=previous_runtime)
                            _interactive_offer_vm_single_address_configuration(required=False)
                    continue

                if choice == "K":
                    previous_runtime = _interactive_cluster_runtime_label(topology)
                    selected_runtime = _select_cluster_runtime_interactive(
                        topology=topology,
                    )
                    if normalize_topology(topology) == "vm-single":
                        _set_session_cluster_runtime_override(selected_runtime)
                        _offer_persist_vm_single_cluster_runtime(selected_runtime, previous_runtime=previous_runtime)
                    continue

                if normalize_topology(topology) == "vm-single" and _menu_action_requires_vm_single_address(choice):
                    if not _interactive_offer_vm_single_address_configuration(required=True):
                        continue

                if choice == "B":
                    _run_legacy_menu_action("bootstrap")
                    continue

                if choice == "D":
                    _run_legacy_menu_action("doctor")
                    continue

                if choice == "R":
                    result = _run_local_repair_interactive(
                        current_adapter,
                        adapter_registry=registry,
                        deployer_registry=deployer_registry,
                        topology=topology,
                    )
                    if result is not None:
                        current_adapter = result.get("adapter") or current_adapter
                        _print_action_result(result)
                    continue

                if choice == "C":
                    _run_legacy_menu_action("cleanup")
                    continue

                if choice == "L":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    _run_legacy_menu_action("local_images", current_adapter=current_adapter)
                    continue

                if choice == "I":
                    _run_legacy_menu_action("inesdata_ui")
                    continue

                if choice == "O":
                    _run_legacy_menu_action("ontology_hub_ui")
                    continue

                if choice == "A":
                    _run_legacy_menu_action("ai_model_hub_ui")
                    continue

                if choice == "V":
                    _run_legacy_menu_action("semantic_virtualization_ui")
                    continue

                if choice == "X":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    _print_action_result(
                        _run_recreate_dataspace_interactive(
                            current_adapter=current_adapter,
                            adapter_registry=registry,
                            deployer_registry=deployer_registry,
                            topology=topology,
                        )
                    )
                    continue

                if choice == "P":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    preview = build_dry_run_preview(
                        adapter_name=current_adapter,
                        command="deploy",
                        adapter_registry=registry,
                        deployer_registry=deployer_registry,
                        validation_engine_cls=validation_engine_cls,
                        metrics_collector_cls=metrics_collector_cls,
                        experiment_storage=experiment_storage,
                        topology=topology,
                        include_deployer_dry_run=True,
                    )
                    _print_action_result(preview)
                    continue

                if choice == "H":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    adapter = build_adapter(current_adapter, adapter_registry=registry, topology=topology)
                    if _should_sync_deployer_hosts() and not _interactive_confirm(
                        "PIONERA_SYNC_HOSTS is enabled. Apply changes to the hosts file?",
                        default=False,
                    ):
                        print("Hosts operation cancelled.")
                        continue
                    result = run_hosts(
                        adapter,
                        deployer_name=current_adapter,
                        deployer_registry=deployer_registry,
                        topology=topology,
                    )
                    _print_action_result(result)
                    result = _interactive_offer_hosts_plan_apply(
                        result,
                        adapter,
                        deployer_name=current_adapter,
                        deployer_registry=deployer_registry,
                        topology=topology,
                    )
                    continue

                if choice == "U":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    adapter = build_adapter(current_adapter, adapter_registry=registry, topology=topology)
                    _print_action_result(
                        run_available_access_urls(
                            adapter,
                            deployer_name=current_adapter,
                            deployer_registry=deployer_registry,
                            topology=topology,
                        )
                    )
                    continue

                if choice == "G":
                    current_adapter = _run_validation_target_menu_interactive(
                        current_adapter=current_adapter,
                        adapter_registry=registry,
                    )
                    continue

                if choice == "E":
                    _run_validation_reports_menu_interactive()
                    continue

                if choice == "M":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    if not _interactive_confirm(
                        f"Run metrics ({_interactive_execution_context(topology, current_adapter)})?",
                        default=False,
                    ):
                        print("Metrics cancelled.")
                        continue
                    kafka_enabled = _interactive_confirm("Enable standalone Kafka broker benchmark?", default=False)
                    adapter = build_adapter(current_adapter, adapter_registry=registry, topology=topology)
                    _print_action_result(
                        run_metrics(
                            adapter,
                            deployer_name=current_adapter,
                            deployer_registry=deployer_registry,
                            topology=topology,
                            metrics_collector_cls=metrics_collector_cls,
                            experiment_storage=experiment_storage,
                            kafka_enabled=kafka_enabled,
                            kafka_manager_cls=kafka_manager_cls,
                        )
                    )
                    continue

                if choice == "0":
                    selected_adapter = _interactive_require_adapter_selection(
                        current_adapter,
                        adapter_registry=registry,
                    )
                    if not selected_adapter:
                        continue
                    current_adapter = selected_adapter
                    if not _interactive_confirm(
                        f"Run all levels 1-6 with adapter {current_adapter} for Levels 3-6 "
                        f"({_interactive_execution_context(topology)})?",
                        default=False,
                    ):
                        print("Full level execution cancelled.")
                        continue
                    result = _run_interactive_full_levels(
                        current_adapter,
                        adapter_registry=registry,
                        deployer_registry=deployer_registry,
                        topology=topology,
                        validation_engine_cls=validation_engine_cls,
                        metrics_collector_cls=metrics_collector_cls,
                        experiment_storage=experiment_storage,
                    )
                    if result is not None:
                        _print_action_result(result)
                    continue

                if choice in {str(level_id) for level_id in LEVEL_DESCRIPTIONS}:
                    level_id = int(choice)
                    level_adapter = current_adapter
                    level_scope = ""
                    if level_id in {1, 2}:
                        level_adapter = _shared_foundation_adapter_name(adapter_registry=registry)
                        level_scope = " (shared foundation)"
                    else:
                        selected_adapter = _interactive_require_adapter_selection(
                            current_adapter,
                            adapter_registry=registry,
                        )
                        if not selected_adapter:
                            continue
                        current_adapter = selected_adapter
                        level_adapter = selected_adapter
                        level_scope = f" for {selected_adapter}"
                    if not _interactive_confirm(
                        f"Run Level {level_id}: {LEVEL_DESCRIPTIONS[level_id]}{level_scope} "
                        f"({_interactive_execution_context(topology)})?",
                        default=False,
                    ):
                        print(f"Level {level_id} cancelled.")
                        continue
                    if level_id >= 3 and not _interactive_ensure_hosts_ready_for_levels(
                        level_adapter,
                        levels=[level_id],
                        adapter_registry=registry,
                        deployer_registry=deployer_registry,
                        topology=topology,
                    ):
                        continue

                    if level_id == 1:
                        shared_adapter_name = _shared_foundation_adapter_name(adapter_registry=registry)
                        shared_adapter = build_adapter(
                            shared_adapter_name,
                            adapter_registry=registry,
                            topology=topology,
                        )
                        _print_action_result(
                            {
                                "status": "completed",
                                "scope": "shared foundation",
                                "adapter": level_adapter,
                                "topology": topology,
                                "levels": [
                                    run_level(
                                        shared_adapter,
                                        1,
                                        deployer_name=shared_adapter_name,
                                        deployer_registry=deployer_registry,
                                        topology=topology,
                                        validation_engine_cls=validation_engine_cls,
                                        metrics_collector_cls=metrics_collector_cls,
                                        experiment_storage=experiment_storage,
                                    )
                                ],
                            }
                        )
                        continue

                    if level_id == 2:
                        result = _run_interactive_level2_with_shared_foundation(
                            adapter_registry=registry,
                            deployer_registry=deployer_registry,
                            topology=topology,
                            validation_engine_cls=validation_engine_cls,
                            metrics_collector_cls=metrics_collector_cls,
                            experiment_storage=experiment_storage,
                        )
                        if result is not None:
                            _print_action_result(
                                {
                                    "status": "completed",
                                    "scope": "shared foundation",
                                    "adapter": level_adapter,
                                    "topology": topology,
                                    "levels": [result],
                                }
                            )
                        continue

                    _print_action_result(
                        run_levels(
                            level_adapter,
                            levels=[level_id],
                            adapter_registry=registry,
                            deployer_registry=deployer_registry,
                            topology=topology,
                            validation_engine_cls=validation_engine_cls,
                            metrics_collector_cls=metrics_collector_cls,
                            experiment_storage=experiment_storage,
                        )
                    )
                    continue

                print("Invalid selection. Please try again.")
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.\n")
            except Exception as exc:
                print(f"\nOperation error: {exc}\n")
    finally:
        restore_cluster_type_env()


def print_available_adapters(adapter_registry=None):
    """Print all available adapters from the registry."""
    registry = adapter_registry or ADAPTER_REGISTRY
    for adapter_name in sorted(registry):
        print(adapter_name)
    return list(sorted(registry))


def create_parser(adapter_registry=None):
    """Create the CLI parser for the experimentation framework."""
    registry = adapter_registry or ADAPTER_REGISTRY
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Dataspace Experimentation Framework CLI",
        usage="python main.py menu | python main.py list | python main.py <adapter> [command] [--topology local|vm-single|vm-distributed] [--dry-run] [--iterations N] [--kafka] [--baseline] | python main.py report <experiment_id> | python main.py compare <experiment_a> <experiment_b>",
        epilog=(
            "Examples:\n"
            "  python main.py menu\n"
            "  python main.py inesdata deploy --topology local\n"
            "  PIONERA_VM_EXTERNAL_IP=192.0.2.10 python main.py edc hosts --topology vm-single\n"
            "  python main.py inesdata local-repair --topology local\n"
            "  python main.py inesdata local-repair --topology local --recover-connectors\n"
            "  python main.py edc validate --topology local\n"
            "  python main.py edc hosts --topology local\n"
            "  python main.py edc recreate-dataspace --topology local --confirm-dataspace pionera-edc\n"
            "  python main.py edc recreate-dataspace --topology local --confirm-dataspace pionera-edc --with-connectors\n"
            "  python main.py inesdata metrics --topology local\n"
            "  python main.py inesdata metrics --topology local --kafka\n"
            "  python main.py inesdata run --topology local\n"
            "  python main.py inesdata run --topology local --iterations 50\n"
            "  python main.py inesdata run --topology local --baseline\n"
            "  python main.py inesdata run --topology local --dry-run\n"
            "  python main.py report experiment_2026-03-10_12-00-00\n"
            "  python main.py compare experiment_A experiment_B\n"
            "  python main.py list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "adapter",
        nargs="?",
        help=f"Adapter name ({', '.join(sorted(registry))}) or 'list'/'menu'",
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="Command to execute. Defaults to 'run'.",
    )
    parser.add_argument("extra", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument(
        "--topology",
        choices=SUPPORTED_TOPOLOGIES,
        default=SUPPORTED_TOPOLOGIES[0],
        help="Deployment topology to target.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview command wiring without executing real deployments or validations.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of repeated experiment runs for the same scenario (default: 1).",
    )
    parser.add_argument(
        "--kafka",
        action="store_true",
        help="Enable the optional Kafka broker benchmark during the metrics phase.",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Mark the generated experiment as a baseline run.",
    )
    parser.add_argument(
        "--validation-mode",
        choices=SUPPORTED_VALIDATION_MODES,
        default=None,
        help="Level 6 orchestration mode. Defaults to stable for local topology and fast elsewhere.",
    )
    parser.add_argument(
        "--confirm-dataspace",
        default=None,
        help="Exact dataspace name required by destructive operations such as recreate-dataspace.",
    )
    parser.add_argument(
        "--with-connectors",
        action="store_true",
        help="After recreate-dataspace, run Level 4 connectors for the same adapter.",
    )
    parser.add_argument(
        "--recover-connectors",
        action="store_true",
        help="With local-repair, restart connector runtimes after repairing local access.",
    )
    return parser


def main(
    argv=None,
    runner_cls=ExperimentRunner,
    adapter_registry=None,
    deployer_registry=None,
    validation_engine_cls=ValidationEngine,
    metrics_collector_cls=MetricsCollector,
    experiment_storage=ExperimentStorage,
    kafka_manager_cls=KafkaManager,
    report_generator_cls=ExperimentReportGenerator,
):
    """Main entry point for the Dataspace Experimentation Framework."""
    parser = create_parser(adapter_registry=adapter_registry)
    args = parser.parse_args(argv)
    registry = adapter_registry or ADAPTER_REGISTRY
    topology_option_provided = _argv_has_topology_option(argv)

    if args.iterations < 1:
        parser.error("--iterations must be greater than or equal to 1")

    if args.recover_connectors and (args.command or "run") != "local-repair":
        parser.error("--recover-connectors can only be used with the local-repair command")

    if not args.adapter:
        if argv is None and sys.stdin.isatty():
            return run_interactive_menu(
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=validation_engine_cls,
                metrics_collector_cls=metrics_collector_cls,
                experiment_storage=experiment_storage,
                kafka_manager_cls=kafka_manager_cls,
                topology=args.topology,
                prompt_initial_topology=not topology_option_provided,
            )
        parser.print_help()
        return 1

    if args.adapter == "menu":
        if args.command is not None or args.extra:
            parser.error("'menu' does not accept additional arguments")
        return run_interactive_menu(
            adapter_registry=registry,
            deployer_registry=deployer_registry,
            validation_engine_cls=validation_engine_cls,
            metrics_collector_cls=metrics_collector_cls,
            experiment_storage=experiment_storage,
            kafka_manager_cls=kafka_manager_cls,
            topology=args.topology,
            prompt_initial_topology=sys.stdin.isatty() and not topology_option_provided,
        )

    if args.adapter == "list":
        if args.command is not None:
            parser.error("'list' does not accept an additional command")
        return print_available_adapters(adapter_registry=registry)

    if args.adapter == "report":
        experiment_id = args.command
        if not experiment_id or args.extra:
            parser.error("'report' expects exactly one experiment identifier")
        generator = report_generator_cls(storage=experiment_storage)
        summary = generator.generate(experiment_id)
        return {
            "experiment_dir": ExperimentLoader.experiment_dir(experiment_id),
            "summary": summary,
        }

    if args.adapter == "compare":
        experiment_a = args.command
        experiment_b = args.extra[0] if args.extra else None
        if not experiment_a or not experiment_b or len(args.extra) != 1:
            parser.error("'compare' expects exactly two experiment identifiers")
        generator = report_generator_cls(storage=experiment_storage)
        return generator.compare(experiment_a, experiment_b)

    if args.adapter not in registry:
        parser.error(
            f"Unsupported adapter '{args.adapter}'. Available adapters: {', '.join(sorted(registry))}"
        )

    command = args.command or "run"
    if command not in SUPPORTED_COMMANDS:
        parser.error(
            f"argument command: invalid choice: '{command}' (choose from {', '.join(SUPPORTED_COMMANDS)})"
        )
    if args.extra:
        parser.error(f"unrecognized arguments: {' '.join(args.extra)}")

    if args.dry_run:
        try:
            preview = build_dry_run_preview(
                adapter_name=args.adapter,
                command=command,
                adapter_registry=registry,
                deployer_registry=deployer_registry,
                validation_engine_cls=validation_engine_cls,
                metrics_collector_cls=metrics_collector_cls,
                experiment_storage=experiment_storage,
                iterations=args.iterations,
                kafka_enabled=args.kafka,
                baseline=args.baseline,
                topology=args.topology,
                with_connectors=args.with_connectors,
                recover_connectors=args.recover_connectors,
                validation_mode=args.validation_mode,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(preview, indent=2, default=str))
        return preview

    try:
        adapter = build_adapter(
            args.adapter,
            adapter_registry=registry,
            dry_run=False,
            topology=args.topology,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if command == "deploy":
        try:
            result = run_deploy(
                adapter,
                deployer_name=args.adapter,
                deployer_registry=deployer_registry,
                topology=args.topology,
            )
        except ValueError as exc:
            parser.error(str(exc))
        if isinstance(result, dict) and result.get("mode") in {"shadow", "execute"}:
            print(json.dumps(result, indent=2, default=str))
        return result

    if command == "validate":
        try:
            return run_validate(
                adapter,
                deployer_name=args.adapter,
                deployer_registry=deployer_registry,
                topology=args.topology,
                validation_engine_cls=validation_engine_cls,
                experiment_storage=experiment_storage,
                baseline=args.baseline,
                validation_mode=args.validation_mode,
            )
        except ValueError as exc:
            parser.error(str(exc))

    if command == "metrics":
        try:
            return run_metrics(
                adapter,
                deployer_name=args.adapter,
                deployer_registry=deployer_registry,
                topology=args.topology,
                metrics_collector_cls=metrics_collector_cls,
                experiment_storage=experiment_storage,
                kafka_enabled=args.kafka,
                kafka_manager_cls=kafka_manager_cls,
                baseline=args.baseline,
            )
        except ValueError as exc:
            parser.error(str(exc))

    if command == "hosts":
        try:
            result = run_hosts(
                adapter,
                deployer_name=args.adapter,
                deployer_registry=deployer_registry,
                topology=args.topology,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2, default=str))
        return result

    if command == "local-repair":
        try:
            result = run_local_repair(
                adapter,
                deployer_name=args.adapter,
                deployer_registry=deployer_registry,
                topology=args.topology,
                apply_hosts=True,
                recover_connectors=args.recover_connectors,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2, default=str))
        return result

    if command == "recreate-dataspace":
        result = run_recreate_dataspace(
            adapter,
            deployer_name=args.adapter,
            deployer_registry=deployer_registry,
            topology=args.topology,
            confirm_dataspace=args.confirm_dataspace,
            with_connectors=args.with_connectors,
        )
        print(json.dumps(result, indent=2, default=str))
        return result

    if _should_use_deployer_run():
        result = run_run(
            adapter,
            deployer_name=args.adapter,
            deployer_registry=deployer_registry,
            topology=args.topology,
            validation_engine_cls=validation_engine_cls,
            metrics_collector_cls=metrics_collector_cls,
            experiment_storage=experiment_storage,
            kafka_enabled=args.kafka,
            kafka_manager_cls=kafka_manager_cls,
            baseline=args.baseline,
            validation_mode=args.validation_mode,
        )
        if isinstance(result, dict) and result.get("mode") in {"shadow", "execute"}:
            print(json.dumps(result, indent=2, default=str))
        return result

    runner = build_runner(
        adapter_name=args.adapter,
        runner_cls=runner_cls,
        adapter_registry=registry,
        validation_engine_cls=validation_engine_cls,
        metrics_collector_cls=metrics_collector_cls,
        experiment_storage=experiment_storage,
        dry_run=False,
        iterations=args.iterations,
        kafka_enabled=args.kafka,
        kafka_manager_cls=kafka_manager_cls,
        baseline=args.baseline,
        topology=args.topology,
    )
    return runner.run()


if __name__ == "__main__":
    main()
